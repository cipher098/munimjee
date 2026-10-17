"""Bounded HTTPS retrieval. Every hop resolves, validates, then pins its peer IP.

No proxies, cookies, caller headers, decompression, authentication or IP fallback.
Transport/resolver injection is for deterministic tests, not request payloads.
"""
from __future__ import annotations

import asyncio
import http.client
import ipaddress
import socket
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlsplit

from .contracts import normalize_url


class FetchError(ValueError):
    """Only stable, credential-free codes cross the transport boundary."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FetchLimits:
    max_bytes: int = 2_000_000
    timeout_seconds: float = 15
    max_redirects: int = 3

    def __post_init__(self):
        if not 1 <= self.max_bytes <= 5_000_000 or not 0 < self.timeout_seconds <= 30 or not 0 <= self.max_redirects <= 5:
            raise ValueError("invalid fetch limits")


@dataclass(frozen=True)
class FetchResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    peer_ip: str


@dataclass(frozen=True)
class FetchedSource:
    final_url: str
    content_type: str
    body: bytes


def source_url(value: str) -> str:
    try:
        normalized = normalize_url(value)
    except ValueError as exc:
        raise FetchError("invalid_url") from exc
    # Tokens must not enter durable source references, logs, redirects or errors.
    for key, _ in parse_qsl(urlsplit(normalized).query, keep_blank_values=True):
        lowered = key.casefold().replace("-", "_")
        if any(secret in lowered for secret in ("token", "secret", "password", "credential", "authorization", "api_key", "signature")):
            raise FetchError("credential_url_forbidden")
    return normalized


def public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise FetchError("invalid_dns_address") from exc
    if not address.is_global or address.is_multicast or address.is_unspecified or address.is_reserved:
        raise FetchError("non_public_address")
    # IPv4-mapped/transition addresses add ambiguity to routing and policy.
    if address.version == 6 and (address.ipv4_mapped or address.sixtofour or address.teredo):
        raise FetchError("transition_address_forbidden")
    return address.compressed


async def system_resolver(host: str) -> tuple[str, ...]:
    records = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if len(records) > 32:
        raise FetchError("too_many_dns_addresses")
    return tuple(record[4][0] for record in records)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, timeout: float):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = public_ip(ip)

    def connect(self):
        # Numeric sockaddr connects directly: there is no second hostname lookup.
        family = socket.AF_INET6 if ":" in self._pinned_ip else socket.AF_INET
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(self.timeout)
        try:
            address = (self._pinned_ip, 443, 0, 0) if family == socket.AF_INET6 else (self._pinned_ip, 443)
            raw.connect(address)
            if public_ip(raw.getpeername()[0]) != self._pinned_ip:
                raise FetchError("peer_address_mismatch")
            # TLS verifies the original hostname and sends that hostname as SNI.
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class PinnedHTTPTransport:
    """At most four blocking transport threads, with no unbounded work queue.

    OS DNS is handled separately; cancelling a timed-out resolver cannot stop an
    OS resolver thread. The fetch deadline still rejects its late result.
    """

    def __init__(self):
        self._inflight: set[asyncio.Task] = set()

    async def request(self, url: str, pinned_ip: str, limits: FetchLimits) -> FetchResponse:
        self._inflight = {task for task in self._inflight if not task.done()}
        if len(self._inflight) >= 4:
            raise FetchError("transport_busy")
        task = asyncio.create_task(asyncio.to_thread(self._request, url, pinned_ip, limits))
        self._inflight.add(task)
        return await asyncio.shield(task)

    @staticmethod
    def _request(url: str, pinned_ip: str, limits: FetchLimits) -> FetchResponse:
        parts = urlsplit(source_url(url))
        connection = PinnedHTTPSConnection(parts.hostname, pinned_ip, limits.timeout_seconds)
        deadline = time.monotonic() + limits.timeout_seconds
        try:
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            connection.request("GET", target, headers={
                "Accept": "text/html, application/ld+json, application/json",
                "Accept-Encoding": "identity", "User-Agent": "Munimjee-Catalogue-Import/1",
                "Connection": "close",
            })
            response = connection.getresponse()
            headers = {key.lower(): value for key, value in response.getheaders()}
            peer = connection.sock.getpeername()[0] if connection.sock else pinned_ip
            # Redirect bodies need not be downloaded.
            if response.status in (301, 302, 303, 307, 308):
                return FetchResponse(response.status, headers, b"", peer)
            length = headers.get("content-length")
            if length is not None and (not length.isascii() or not length.isdecimal() or int(length) > limits.max_bytes):
                raise FetchError("body_too_large")
            if headers.get("content-encoding", "identity").lower() not in ("identity", ""):
                raise FetchError("encoded_body_forbidden")
            body = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("fetch_timeout")
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, limits.max_bytes - len(body) + 1))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > limits.max_bytes:
                    raise FetchError("body_too_large")
            return FetchResponse(response.status, headers, bytes(body), peer)
        finally:
            connection.close()


class SafeFetcher:
    def __init__(self, *, resolver: Callable[[str], Awaitable[tuple[str, ...]]] = system_resolver,
                 transport=None, limits: FetchLimits | None = None):
        self.resolver = resolver
        self.transport = transport or PinnedHTTPTransport()
        self.limits = limits or FetchLimits()
        self._active_resolutions: set[asyncio.Task] = set()

    async def fetch(self, url: str, *, authorized_origin: str) -> FetchedSource:
        try:
            return await asyncio.wait_for(self._fetch(url, authorized_origin), timeout=self.limits.timeout_seconds)
        except FetchError:
            raise
        except TimeoutError as exc:
            raise FetchError("fetch_timeout") from exc
        except (OSError, http.client.HTTPException, ValueError, UnicodeError) as exc:
            raise FetchError("fetch_failed") from exc

    async def _fetch(self, url: str, origin: str) -> FetchedSource:
        current = source_url(url)
        allowed_host = urlsplit(source_url(origin)).hostname
        for hop in range(self.limits.max_redirects + 1):
            host = urlsplit(current).hostname
            if host != allowed_host:
                raise FetchError("unauthorized_redirect_origin")
            # No arbitrary Instagram scraping through the website source path.
            if host == "instagram.com" or host.endswith(".instagram.com"):
                raise FetchError("instagram_requires_connected_provider")
            self._active_resolutions = {task for task in self._active_resolutions if not task.done()}
            if len(self._active_resolutions) >= 4:
                raise FetchError("resolver_busy")
            resolution = asyncio.create_task(self.resolver(host))
            self._active_resolutions.add(resolution)
            addresses = await asyncio.shield(resolution)
            if not addresses or len(addresses) > 32:
                raise FetchError("invalid_dns_response")
            validated = tuple(public_ip(address) for address in addresses)
            response = await self.transport.request(current, validated[0], self.limits)
            if public_ip(response.peer_ip) != validated[0]:
                raise FetchError("peer_address_mismatch")
            if response.status in (301, 302, 303, 307, 308):
                if hop == self.limits.max_redirects:
                    raise FetchError("too_many_redirects")
                location = response.headers.get("location")
                if not location:
                    raise FetchError("invalid_redirect")
                current = source_url(urljoin(current, location))
                continue
            if response.status != 200:
                raise FetchError("source_http_error")
            if response.headers.get("content-encoding", "identity").lower() not in ("identity", ""):
                raise FetchError("encoded_body_forbidden")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
            if content_type not in ("text/html", "application/ld+json", "application/json"):
                raise FetchError("unsupported_content_type")
            if len(response.body) > self.limits.max_bytes:
                raise FetchError("body_too_large")
            return FetchedSource(current, content_type, response.body)
        raise FetchError("too_many_redirects")
