"""Tenant-bound owned-media adapter. Default capability is deliberately closed.

The proposed Instagram Login media fields are not yet primary-source verified.
Only a trusted composition root may grant capabilities; no job/request can do so.
The existing collect_claim consumes products and ignores original assets: returning
bytes here does not persist them or attach them to candidates.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote, urlencode
from uuid import UUID

from .contracts import DraftFacts
from .fetching import system_resolver
from .instagram_owned_transport import (
    ERROR_CODES, OwnedInstagramError, OwnedRequest, OwnedResponse, PinnedOwnedTransport,
    checked_ip, checked_url, consume,
)


@dataclass(frozen=True)
class OwnedCredentialSnapshot:
    business_id: UUID
    account_id: str
    token: str = field(repr=False)
    expires_at: datetime
    connection_version: int
    revoked: bool = False
    login_route: str = "instagram"
    granted_scopes: frozenset[str] | None = None


@dataclass(frozen=True)
class OwnedMediaCapabilities:
    ig_login_media: bool = False
    carousel: bool = False

    def __post_init__(self):
        if type(self.ig_login_media) is not bool or type(self.carousel) is not bool:
            raise ValueError("invalid Instagram capability")


@dataclass(frozen=True)
class OwnedMediaLimits:
    timeout_seconds: float = 14
    max_pages: int = 5
    page_size: int = 25
    max_graph_requests: int = 8
    max_assets: int = 10
    max_asset_bytes: int = 5_000_000
    max_total_bytes: int = 10_000_000
    max_json_bytes: int = 256_000

    def __post_init__(self):
        bounds = ((self.max_pages, 5), (self.page_size, 25), (self.max_graph_requests, 8),
                  (self.max_assets, 10), (self.max_asset_bytes, 5_000_000),
                  (self.max_total_bytes, 10_000_000), (self.max_json_bytes, 256_000))
        if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in bounds) or type(self.timeout_seconds) not in (float, int) or not 0 < self.timeout_seconds <= 15:
            raise ValueError("invalid Instagram limits")


@dataclass(frozen=True)
class OriginalMediaAsset:
    media_id: str
    content: bytes = field(repr=False)
    sha256: str
    content_type: str


@dataclass(frozen=True)
class OwnedMediaResult:
    account_id: str
    media_id: str
    products: tuple[tuple[str, DraftFacts], ...]
    assets: tuple[OriginalMediaAsset, ...]
    media_type: str
    connection_version: int


@dataclass
class _Budget:
    deadline: float
    graph_requests: int = 0
    total_bytes: int = 0


class OwnedInstagramProvider:
    def __init__(self, *, credential_loader: Callable[[UUID, str], Awaitable[OwnedCredentialSnapshot]],
                 checkpoint: Callable[[UUID, str], Awaitable[bool]], graph_version: str,
                 resolver=system_resolver, transport=None, limits: OwnedMediaLimits | None = None,
                 capabilities: OwnedMediaCapabilities | None = None, utcnow=None):
        if not isinstance(graph_version, str) or not re.fullmatch(r"v[0-9]{1,2}\.[0-9]{1,2}", graph_version):
            raise ValueError("invalid Instagram API version")
        if not callable(credential_loader) or not callable(checkpoint) or not callable(resolver):
            raise ValueError("trusted Instagram callbacks required")
        self.credential_loader, self.checkpoint = credential_loader, checkpoint
        self.resolver, self.transport = resolver, transport or PinnedOwnedTransport()
        self.limits = limits or OwnedMediaLimits()
        self.capabilities = capabilities or OwnedMediaCapabilities()
        self.graph_version = graph_version
        self.utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        # Cancelled tasks retain admission until they actually finish. This bounds
        # cancellation-suppressing injected callbacks across concurrent fetches.
        self._pending: set[asyncio.Future] = set()

    async def _await(self, factory, budget):
        if time.monotonic() >= budget.deadline:
            raise OwnedInstagramError("instagram_timeout")
        self._pending = {task for task in self._pending if not task.done()}
        if len(self._pending) >= 4:
            raise OwnedInstagramError("instagram_busy")
        task = asyncio.ensure_future(factory())
        self._pending.add(task)
        task.add_done_callback(consume)
        try:
            done, _ = await asyncio.wait({task}, timeout=max(0, budget.deadline - time.monotonic()))
            if not done:
                task.cancel()
                raise OwnedInstagramError("instagram_timeout")
            if time.monotonic() >= budget.deadline:
                raise OwnedInstagramError("instagram_timeout")
            return task.result()
        except asyncio.CancelledError:
            task.cancel()
            raise

    async def _credential(self, business_id, account_id, budget, initial=None):
        try:
            if await self._await(lambda: self.checkpoint(business_id, account_id), budget) is not True:
                raise OwnedInstagramError("instagram_cancelled")
            snapshot = await self._await(lambda: self.credential_loader(business_id, account_id), budget)
        except OwnedInstagramError:
            raise
        except Exception:
            raise OwnedInstagramError("instagram_credentials_unavailable") from None
        if type(snapshot) is not OwnedCredentialSnapshot:
            raise OwnedInstagramError("instagram_credentials_invalid")
        if snapshot.business_id != business_id or snapshot.account_id != account_id:
            raise OwnedInstagramError("instagram_binding_changed")
        if type(snapshot.revoked) is not bool or snapshot.revoked:
            raise OwnedInstagramError("instagram_access_revoked")
        if snapshot.login_route != "instagram" or type(snapshot.connection_version) is not int or snapshot.connection_version < 0 or not isinstance(snapshot.token, str) or not re.fullmatch(r"[\x21-\x7e]{1,4096}", snapshot.token):
            raise OwnedInstagramError("instagram_credentials_invalid")
        scopes = snapshot.granted_scopes
        if scopes is not None and (type(scopes) is not frozenset or not all(type(item) is str for item in scopes)):
            raise OwnedInstagramError("instagram_credentials_invalid")
        if scopes is not None and "instagram_business_basic" not in scopes:
            raise OwnedInstagramError("instagram_unauthorized")
        try:
            now = self.utcnow()
            if not isinstance(now, datetime) or now.utcoffset() is None or not isinstance(snapshot.expires_at, datetime) or snapshot.expires_at.utcoffset() is None:
                raise ValueError()
            expired = snapshot.expires_at <= now
        except Exception:
            raise OwnedInstagramError("instagram_credentials_invalid") from None
        if expired:
            raise OwnedInstagramError("instagram_credentials_expired")
        if initial is not None and (snapshot.token != initial.token or snapshot.connection_version != initial.connection_version or snapshot.expires_at != initial.expires_at or snapshot.granted_scopes != initial.granted_scopes):
            raise OwnedInstagramError("instagram_binding_changed")
        return snapshot

    async def _request(self, url, *, token, business_id, account_id, initial, budget, max_bytes):
        host = checked_url(url, authenticated=token is not None)
        await self._credential(business_id, account_id, budget, initial)
        try:
            addresses = await self._await(lambda: self.resolver(host), budget)
        except OwnedInstagramError:
            raise
        except Exception:
            raise OwnedInstagramError("instagram_transport_failed") from None
        if not isinstance(addresses, (tuple, list)) or not 1 <= len(addresses) <= 32:
            raise OwnedInstagramError("instagram_unsafe_address")
        validated = tuple(checked_ip(address) for address in addresses)
        await self._credential(business_id, account_id, budget, initial)
        remaining_bytes = self.limits.max_total_bytes - budget.total_bytes
        if remaining_bytes <= 0:
            raise OwnedInstagramError("instagram_body_too_large")
        request = OwnedRequest(url, validated[0], token, min(max_bytes, remaining_bytes),
                               max(0.000001, budget.deadline - time.monotonic()))
        try:
            response = await self._await(lambda: self.transport.request(request), budget)
        except OwnedInstagramError:
            raise
        except Exception:
            raise OwnedInstagramError("instagram_transport_failed") from None
        if type(response) is not OwnedResponse or type(response.status) is not int or type(response.body) is not bytes or type(response.headers) is not dict:
            raise OwnedInstagramError("instagram_response_invalid")
        if checked_ip(response.peer_ip) != validated[0]:
            raise OwnedInstagramError("instagram_peer_mismatch")
        if 300 <= response.status < 400:
            raise OwnedInstagramError("instagram_redirect_forbidden")
        if response.status in (401, 403):
            raise OwnedInstagramError("instagram_unauthorized")
        if response.status == 429:
            raise OwnedInstagramError("instagram_rate_limited")
        if response.status != 200:
            raise OwnedInstagramError("instagram_http_error")
        if not all(type(key) is str and type(value) is str for key, value in response.headers.items()) or sum(len(key) + len(value) for key, value in response.headers.items()) > 16384:
            raise OwnedInstagramError("instagram_response_invalid")
        headers = {key.lower(): value for key, value in response.headers.items()}
        if len(headers) != len(response.headers):
            raise OwnedInstagramError("instagram_response_invalid")
        if headers.get("content-encoding", "identity").lower() not in ("identity", ""):
            raise OwnedInstagramError("instagram_content_encoding")
        if len(response.body) > request.max_bytes:
            raise OwnedInstagramError("instagram_body_too_large")
        length = headers.get("content-length")
        if length is not None and (not re.fullmatch(r"[0-9]{1,10}", length) or int(length) != len(response.body)):
            raise OwnedInstagramError("instagram_response_invalid")
        budget.total_bytes += len(response.body)
        return headers.get("content-type", "").split(";", 1)[0].strip().lower(), response.body

    async def _graph(self, path, params, *, initial, budget):
        if budget.graph_requests >= self.limits.max_graph_requests:
            raise OwnedInstagramError("instagram_request_limit")
        budget.graph_requests += 1
        mime, content = await self._request(
            f"https://graph.instagram.com/{self.graph_version}/{path}?{urlencode(params)}",
            token=initial.token, business_id=initial.business_id, account_id=initial.account_id,
            initial=initial, budget=budget, max_bytes=self.limits.max_json_bytes)
        if mime != "application/json":
            raise OwnedInstagramError("instagram_response_invalid")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        try:
            document = json.loads(content.decode("utf-8"), object_pairs_hook=unique,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError, RecursionError):
            raise OwnedInstagramError("instagram_response_invalid") from None
        if type(document) is not dict:
            raise OwnedInstagramError("instagram_response_invalid")
        if "error" in document:
            raise OwnedInstagramError("instagram_unauthorized")
        return document

    @staticmethod
    def _untainted(value, token):
        # A compromised provider response must not launder the active bearer into
        # a CDN URL or a pagination query. Decode bounded layers, never log input.
        for _ in range(8):
            if token in value:
                raise OwnedInstagramError("instagram_unsafe_url")
            decoded = unquote(value)
            if decoded == value:
                return
            value = decoded
        raise OwnedInstagramError("instagram_unsafe_url")

    async def _edge(self, path, *, initial, budget, wanted=None):
        cursor = None
        seen = set()
        collected = []
        for _ in range(self.limits.max_pages):
            params = {"fields": "id,media_type,media_url", "limit": self.limits.page_size}
            if cursor is not None:
                params["after"] = cursor
            document = await self._graph(path, params, initial=initial, budget=budget)
            items = document.get("data")
            if type(items) is not list or len(items) > self.limits.page_size:
                raise OwnedInstagramError("instagram_response_invalid")
            for item in items:
                if type(item) is not dict or not isinstance(item.get("id"), str) or not re.fullmatch(r"[0-9]{1,32}", item["id"]):
                    raise OwnedInstagramError("instagram_response_invalid")
                if wanted is not None and item["id"] == wanted:
                    return (item,)
                if wanted is None:
                    if any(previous["id"] == item["id"] for previous in collected):
                        raise OwnedInstagramError("instagram_response_invalid")
                    collected.append(item)
                    if len(collected) > self.limits.max_assets:
                        raise OwnedInstagramError("instagram_request_limit")
            paging = document.get("paging")
            if paging is None:
                return tuple(collected)
            if type(paging) is not dict:
                raise OwnedInstagramError("instagram_pagination_invalid")
            if "next" not in paging:
                return tuple(collected)
            # next is only a continuation signal. Its URL is never parsed/replayed.
            cursors = paging.get("cursors")
            cursor = cursors.get("after") if type(cursors) is dict else None
            if not isinstance(cursor, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", cursor) or cursor in seen:
                raise OwnedInstagramError("instagram_pagination_invalid")
            self._untainted(cursor, initial.token)
            seen.add(cursor)
        raise OwnedInstagramError("instagram_request_limit")

    async def fetch_owned_media(self, *, business_id: UUID, account_id: str, media_id: str) -> OwnedMediaResult:
        if not self.capabilities.ig_login_media:
            raise OwnedInstagramError("provider_capability_pending")
        if type(business_id) is not UUID or not isinstance(account_id, str) or not re.fullmatch(r"[0-9]{1,32}", account_id) or not isinstance(media_id, str) or not re.fullmatch(r"[0-9]{1,32}", media_id):
            raise OwnedInstagramError("instagram_invalid_request")
        budget = _Budget(time.monotonic() + self.limits.timeout_seconds)
        try:
            initial = await self._credential(business_id, account_id, budget)
            principal = await self._graph("me", {"fields": "user_id,account_type"}, initial=initial, budget=budget)
            if principal.get("user_id") != account_id:
                raise OwnedInstagramError("instagram_binding_changed")
            if principal.get("account_type") not in ("BUSINESS", "CREATOR"):
                raise OwnedInstagramError("instagram_unauthorized")
            matches = await self._edge(account_id + "/media", initial=initial, budget=budget, wanted=media_id)
            if not matches:
                raise OwnedInstagramError("instagram_media_not_owned")
            parent = matches[0]
            kind = parent.get("media_type")
            if kind == "CAROUSEL_ALBUM":
                if not self.capabilities.carousel:
                    raise OwnedInstagramError("provider_capability_pending")
                media = await self._edge(media_id + "/children", initial=initial, budget=budget)
                if not media:
                    raise OwnedInstagramError("instagram_response_invalid")
            elif kind in ("IMAGE", "VIDEO"):
                media = matches
            else:
                raise OwnedInstagramError("instagram_unsupported_media")
            if len(media) > self.limits.max_assets:
                raise OwnedInstagramError("instagram_request_limit")
            assets = []
            for item in media:
                item_kind = item.get("media_type")
                if item_kind not in ("IMAGE", "VIDEO") or not isinstance(item.get("media_url"), str):
                    raise OwnedInstagramError("instagram_unsupported_media")
                self._untainted(item["media_url"], initial.token)
                mime, content = await self._request(item["media_url"], token=None, business_id=business_id,
                    account_id=account_id, initial=initial, budget=budget, max_bytes=self.limits.max_asset_bytes)
                valid = (item_kind == "IMAGE" and mime == "image/jpeg" and content.startswith(b"\xff\xd8\xff")
                         or item_kind == "IMAGE" and mime == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")
                         or item_kind == "VIDEO" and mime == "video/mp4" and len(content) >= 12 and content[4:8] == b"ftyp")
                if not valid:
                    raise OwnedInstagramError("instagram_asset_invalid")
                assets.append(OriginalMediaAsset(item["id"], content, hashlib.sha256(content).hexdigest(), mime))
            await self._credential(business_id, account_id, budget, initial)
            return OwnedMediaResult(account_id, media_id, (("media-product", DraftFacts()),), tuple(assets), kind,
                                   initial.connection_version)
        except OwnedInstagramError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            raise OwnedInstagramError("instagram_transport_failed") from None
