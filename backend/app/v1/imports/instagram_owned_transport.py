"""Isolated authenticated Graph / unauthenticated signed-CDN transport.

No proxy discovery, redirects, cookies, decompression, retry or credential lookup.
Request URLs and credentials and response headers/bodies are intentionally absent
from repr. TLS uses the original authority while the socket uses a validated IP.
"""
from __future__ import annotations

import asyncio
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from urllib.parse import urlsplit

from .fetching import FetchError, PinnedHTTPSConnection, public_ip


ERROR_CODES = frozenset({
    "provider_capability_pending", "instagram_invalid_request", "instagram_credentials_unavailable",
    "instagram_credentials_invalid", "instagram_credentials_expired", "instagram_binding_changed",
    "instagram_access_revoked", "instagram_cancelled", "instagram_timeout", "instagram_busy",
    "instagram_request_limit", "instagram_media_not_owned", "instagram_pagination_invalid",
    "instagram_response_invalid", "instagram_unsupported_media", "instagram_asset_invalid",
    "instagram_body_too_large", "instagram_unauthorized", "instagram_rate_limited",
    "instagram_http_error", "instagram_transport_failed", "instagram_unsafe_address",
    "instagram_peer_mismatch", "instagram_redirect_forbidden", "instagram_unsafe_url",
    "instagram_content_encoding",
})


class OwnedInstagramError(FetchError):
    def __init__(self, code: str):
        super().__init__(code if code in ERROR_CODES else "instagram_transport_failed")


@dataclass(frozen=True)
class OwnedRequest:
    url: str = field(repr=False)
    pinned_ip: str
    token: str | None = field(repr=False)
    max_bytes: int
    timeout_seconds: float


@dataclass(frozen=True)
class OwnedResponse:
    status: int
    headers: dict[str, str] = field(repr=False)
    body: bytes = field(repr=False)
    peer_ip: str


def checked_url(url: str, *, authenticated: bool) -> str:
    """Only the fixed Graph authority may receive a token; CDN URLs are ephemeral."""
    try:
        if not isinstance(url, str) or not 1 <= len(url) <= 8192 or any(
            ord(char) <= 32 or ord(char) >= 127 for char in url
        ) or "\\" in url:
            raise ValueError()
        parts = urlsplit(url)
        host = parts.hostname
        if parts.scheme != "https" or parts.port not in (None, 443) or parts.username is not None or parts.password is not None or parts.fragment or not host:
            raise ValueError()
        # Canonical ASCII DNS authorities only; no encoded hosts, literal IPs or dots.
        if parts.netloc not in (host, host + ":443") or len(host) > 253 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")
        ):
            raise ValueError()
        if authenticated:
            if host != "graph.instagram.com" or not re.fullmatch(r"/v[0-9]{1,2}\.[0-9]{1,2}/(?:me|[0-9]{1,32}/(?:media|children))", parts.path):
                raise ValueError()
            # Graph queries are built internally; URL auth is categorically forbidden.
            if any(word in parts.query.casefold() for word in ("token", "secret", "authorization")):
                raise ValueError()
        elif not any(host.endswith("." + suffix) for suffix in ("cdninstagram.com", "fbcdn.net")):
            raise ValueError()
        return host
    except (ValueError, TypeError, UnicodeError):
        raise OwnedInstagramError("instagram_unsafe_url") from None


def checked_ip(value: str) -> str:
    try:
        return public_ip(value)
    except (ValueError, TypeError):
        raise OwnedInstagramError("instagram_unsafe_address") from None


def consume(future):
    if not future.cancelled():
        future.exception()


class PinnedOwnedTransport:
    _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="instagram-owned")
    _lock = Lock()
    _inflight = set()

    async def request(self, request: OwnedRequest) -> OwnedResponse:
        checked_url(request.url, authenticated=request.token is not None)
        checked_ip(request.pinned_ip)
        if type(request.max_bytes) is not int or not 1 <= request.max_bytes <= 5_000_000 or not 0 < request.timeout_seconds <= 15:
            raise OwnedInstagramError("instagram_invalid_request")
        if request.token is not None and (not isinstance(request.token, str) or not re.fullmatch(r"[\x21-\x7e]{1,4096}", request.token)):
            raise OwnedInstagramError("instagram_credentials_invalid")
        with self._lock:
            type(self)._inflight = {item for item in self._inflight if not item.done()}
            if len(self._inflight) >= 4:
                raise OwnedInstagramError("instagram_busy")
            future = self._pool.submit(self._request, request)
            self._inflight.add(future)
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(consume)
        try:
            return await asyncio.shield(wrapped)
        except OwnedInstagramError:
            raise
        except Exception:
            raise OwnedInstagramError("instagram_transport_failed") from None

    @staticmethod
    def _request(request: OwnedRequest) -> OwnedResponse:
        host = checked_url(request.url, authenticated=request.token is not None)
        parts = urlsplit(request.url)
        connection = PinnedHTTPSConnection(host, checked_ip(request.pinned_ip), request.timeout_seconds)
        deadline = time.monotonic() + request.timeout_seconds
        try:
            headers = {"Accept": "application/json" if request.token else "image/jpeg,image/png,video/mp4",
                       "Accept-Encoding": "identity", "Connection": "close",
                       "User-Agent": "Munimjee-Owned-Media/1"}
            if request.token is not None:
                headers["Authorization"] = "Bearer " + request.token
            # Finish TLS before preparing an authenticated HTTP send. A slow
            # connect may outlive the async caller but must not send afterwards.
            connection.connect()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OwnedInstagramError("instagram_timeout")
            if connection.sock:
                connection.sock.settimeout(remaining)
            connection.request("GET", parts.path + ("?" + parts.query if parts.query else ""), headers=headers)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OwnedInstagramError("instagram_timeout")
            if connection.sock:
                connection.sock.settimeout(remaining)
            response = connection.getresponse()
            raw_headers = response.getheaders()
            if sum(len(key) + len(value) for key, value in raw_headers) > 16384:
                raise OwnedInstagramError("instagram_response_invalid")
            normalized = {}
            for key, value in raw_headers:
                key = key.lower()
                if key in normalized:
                    raise OwnedInstagramError("instagram_response_invalid")
                normalized[key] = value
            peer = connection.sock.getpeername()[0] if connection.sock else request.pinned_ip
            if response.status != 200:
                # Error and redirect bodies may contain credentials; do not download.
                return OwnedResponse(response.status, normalized, b"", peer)
            if normalized.get("content-encoding", "identity").lower() not in ("identity", ""):
                raise OwnedInstagramError("instagram_content_encoding")
            length = normalized.get("content-length")
            if length is not None and (not re.fullmatch(r"[0-9]{1,10}", length) or int(length) > request.max_bytes):
                raise OwnedInstagramError("instagram_body_too_large")
            body = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OwnedInstagramError("instagram_timeout")
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, request.max_bytes - len(body) + 1))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > request.max_bytes:
                    raise OwnedInstagramError("instagram_body_too_large")
            return OwnedResponse(response.status, normalized, bytes(body), peer)
        except OwnedInstagramError:
            raise
        except Exception:
            raise OwnedInstagramError("instagram_transport_failed") from None
        finally:
            connection.close()
