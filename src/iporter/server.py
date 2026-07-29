# IPorter - A local DNS server with source IP group based rewrite rules.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from __future__ import annotations

import asyncio
from dataclasses import replace
import logging
import socket
from pathlib import Path

from dnslib import DNSHeader, DNSLabel, DNSQuestion, DNSRecord, QTYPE, RCODE

from .config import ServerConfig
from .policy_db import load_policy, resolve_policy_db_path
from .rules import Decision, decide

LOG = logging.getLogger(__name__)
ACTION_LOG = logging.getLogger("iporter.action")


class DnsUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, config: ServerConfig, config_path: str | None = None) -> None:
        self.config = config
        self._config_path = Path(config_path).resolve() if config_path else None
        self._policy_db_path = (
            resolve_policy_db_path(self._config_path) if self._config_path is not None else None
        )
        self._policy_db_mtime_ns = self._policy_db_stat_mtime_ns()
        self.transport: asyncio.DatagramTransport | None = None
        self._inflight: set[asyncio.Task[None]] = set()

    def _policy_db_stat_mtime_ns(self) -> int | None:
        if self._policy_db_path is None or not self._policy_db_path.exists():
            return None
        try:
            return self._policy_db_path.stat().st_mtime_ns
        except OSError:
            return None

    def _refresh_policy_if_needed(self) -> None:
        if self._policy_db_path is None:
            return

        current_mtime_ns = self._policy_db_stat_mtime_ns()
        if current_mtime_ns is None or current_mtime_ns == self._policy_db_mtime_ns:
            return

        try:
            group_map, rules = load_policy(self._policy_db_path)
            self.config = replace(self.config, ip_groups=group_map, rules=rules)
            self._policy_db_mtime_ns = current_mtime_ns
            LOG.info("Reloaded policy from %s", self._policy_db_path)
        except Exception as exc:
            LOG.warning("Failed to reload policy from %s: %s", self._policy_db_path, exc)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        LOG.info(
            "DNS server listening on %s:%s",
            self.config.listen_host,
            self.config.listen_port,
        )

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        task = asyncio.create_task(self._handle_request(data, addr))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _handle_request(self, data: bytes, addr: tuple[str, int]) -> None:
        client_ip, client_port = addr
        try:
            self._refresh_policy_if_needed()
            request = DNSRecord.parse(data)
            if not request.questions:
                return

            question = request.questions[0]
            query_name = str(question.qname).rstrip(".").lower()
            decision = decide(self.config, client_ip, query_name)

            if decision.action == "block":
                response = self._blocked_response(request)
                self._send_response(response.pack(), addr)
                self._log_policy_action(client_ip, query_name, decision)
                LOG.info("Blocked %s for %s", query_name, client_ip)
                return

            if decision.action == "rewrite" and decision.target:
                forward_packet = self._build_rewrite_query(request, question, decision)
                upstream_reply_bytes = await self._query_upstream_parallel(forward_packet)
                upstream_reply = DNSRecord.parse(upstream_reply_bytes)
                upstream_reply.questions = [request.q]
                self._send_response(upstream_reply.pack(), addr)
                self._log_policy_action(client_ip, query_name, decision)
                LOG.info(
                    "Rewrote %s -> %s for %s",
                    query_name,
                    decision.target,
                    client_ip,
                )
                return

            upstream_reply = await self._query_upstream_parallel(data)
            self._send_response(upstream_reply, addr)
        except Exception as exc:
            LOG.exception("Failed to handle DNS request from %s:%s: %s", client_ip, client_port, exc)

    def _blocked_response(self, request: DNSRecord) -> DNSRecord:
        return DNSRecord(
            DNSHeader(
                id=request.header.id,
                qr=1,
                aa=1,
                ra=1,
                rcode=RCODE.NXDOMAIN,
            ),
            q=request.q,
        )

    def _build_rewrite_query(
        self,
        request: DNSRecord,
        question: DNSQuestion,
        decision: Decision,
    ) -> bytes:
        rewritten = DNSRecord(DNSHeader(id=request.header.id, rd=request.header.rd))
        rewritten.add_question(DNSQuestion(DNSLabel(decision.target), qtype=question.qtype))
        return rewritten.pack()

    def _query_single_upstream(self, packet: bytes, host: str, port: int) -> bytes:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3.0)
        try:
            sock.sendto(packet, (host, port))
            response, _ = sock.recvfrom(4096)
            return response
        finally:
            sock.close()

    async def _query_upstream_parallel(self, packet: bytes) -> bytes:
        tasks = [
            asyncio.create_task(
                asyncio.to_thread(
                    self._query_single_upstream,
                    packet,
                    upstream.host,
                    upstream.port,
                )
            )
            for upstream in self.config.upstream_servers
        ]

        pending: set[asyncio.Task[bytes]] = set(tasks)
        errors: list[str] = []

        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    try:
                        response = task.result()
                        for other in pending:
                            other.cancel()
                        return response
                    except Exception as exc:
                        errors.append(str(exc))

            raise RuntimeError(
                "All upstream DNS servers failed: " + ", ".join(errors)
            )
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    def _send_response(self, packet: bytes, addr: tuple[str, int]) -> None:
        if self.transport is not None:
            self.transport.sendto(packet, addr)

    def _log_policy_action(self, client_ip: str, query_name: str, decision: Decision) -> None:
        if not self.config.verbose_logging:
            return
        if decision.action == "block":
            ACTION_LOG.info("action=block ip=%s domain=%s", client_ip, query_name)
            return
        if decision.action == "rewrite" and decision.target:
            ACTION_LOG.info(
                "action=rewrite ip=%s domain=%s target=%s",
                client_ip,
                query_name,
                decision.target,
            )


async def run_server(config: ServerConfig, config_path: str | None = None) -> None:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: DnsUdpProtocol(config, config_path=config_path),
        local_addr=(config.listen_host, config.listen_port),
    )
    try:
        await asyncio.Future()
    finally:
        transport.close()
