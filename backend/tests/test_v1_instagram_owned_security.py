"""Independent adversarial owned-Instagram tests; synthetic credentials/network only.

Media capability enabled here tests a proposed contract, not live Meta support.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from app.v1.imports.fetching import FetchError
from app.v1.imports.instagram_owned import (
    OwnedCredentialSnapshot, OwnedInstagramProvider, OwnedMediaCapabilities,
    OwnedMediaLimits,
)
from app.v1.imports.instagram_owned_transport import OwnedResponse

BUSINESS = UUID("00000000-0000-0000-0000-000000000041")
OTHER = UUID("00000000-0000-0000-0000-000000000042")
ACCOUNT, MEDIA = "178414000000001", "180000000000001"
PUBLIC = "93.184.216.34"
TOKEN = "SYNTHETIC-INDEPENDENT-SECRET-DO-NOT-LOG"
SIGNED = "https://scontent.cdninstagram.com/original.jpg?oe=ABC123&sig=SYNTHETIC-SIGNED-URL"
NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
JPEG = b"\xff\xd8\xff\xe0" + b"synthetic-original"


def credential(**changes):
    values = dict(business_id=BUSINESS, account_id=ACCOUNT, token=TOKEN,
                  expires_at=NOW + timedelta(hours=1), connection_version=3,
                  granted_scopes=frozenset({"instagram_business_basic"}))
    values.update(changes)
    return OwnedCredentialSnapshot(**values)


def wire(value, *, status=200, mime="application/json", peer=PUBLIC, headers=None):
    body = value if isinstance(value, bytes) else json.dumps(value).encode()
    return OwnedResponse(status=status, headers={"content-type": mime, **(headers or {})}, body=body, peer_ip=peer)


def me(**changes):
    return {"user_id": ACCOUNT, "account_type": "BUSINESS", **changes}


def item(**changes):
    return {"id": MEDIA, "media_type": "IMAGE", "media_url": SIGNED, **changes}


class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def request(self, request):
        self.calls.append(request)
        reply = self.replies.pop(0)
        return await reply(request) if callable(reply) else reply


class Harness:
    def __init__(self, *, replies=None, snapshot=None, addresses=(PUBLIC,), capabilities=None, limits=None):
        self.snapshot = snapshot or credential()
        self.loads = []
        self.checks = []
        self.dns = []
        self.allowed = True
        self.addresses = addresses
        self.transport = FakeTransport(replies if replies is not None else [
            wire(me()), wire({"data": [item()]}), wire(JPEG, mime="image/jpeg")])
        self.provider = OwnedInstagramProvider(
            credential_loader=self.load, checkpoint=self.check,
            graph_version="v25.0", resolver=self.resolve, transport=self.transport,
            capabilities=capabilities if capabilities is not None else OwnedMediaCapabilities(ig_login_media=True),
            limits=limits, utcnow=lambda: NOW)

    async def load(self, business_id, account_id):
        self.loads.append((business_id, account_id))
        return self.snapshot

    async def check(self, business_id, account_id):
        self.checks.append((business_id, account_id))
        return self.allowed

    async def resolve(self, host):
        self.dns.append(host)
        return self.addresses

    async def fetch(self, **changes):
        return await self.provider.fetch_owned_media(business_id=BUSINESS, account_id=ACCOUNT, media_id=MEDIA, **changes)


def assert_redacted(error):
    assert TOKEN not in str(error) + repr(error)
    assert SIGNED not in str(error) + repr(error)
    assert "SYNTHETIC-SIGNED-URL" not in str(error) + repr(error)
    assert error.__cause__ is None


@pytest.mark.asyncio
async def test_security_default_capability_rejects_before_any_callback_or_network():
    h = Harness(capabilities=OwnedMediaCapabilities())
    with pytest.raises(FetchError, match="provider_capability_pending"):
        await h.fetch()
    assert h.loads == h.checks == h.dns == h.transport.calls == []


@pytest.mark.asyncio
async def test_security_success_header_only_graph_and_original_bytes_never_become_facts(caplog):
    h = Harness()
    result = await h.fetch()
    assert result.account_id == ACCOUNT and result.media_id == MEDIA
    assert len(result.products) == 1
    assert result.products[0][1].model_dump() == {"title": None, "description": None, "price": None, "stock": None, "options": None}
    assert len(h.transport.calls) == 3
    for request in h.transport.calls[:2]:
        assert urlsplit(request.url).hostname == "graph.instagram.com"
        assert request.token == TOKEN
        assert TOKEN not in request.url and "access_token" not in parse_qs(urlsplit(request.url).query)
    assert h.transport.calls[-1].token is None
    assert TOKEN not in repr(h.snapshot) + repr(result) + repr(h.transport.calls) + caplog.text
    assert SIGNED not in repr(result) + repr(h.transport.calls) + caplog.text
    assert all(pair == (BUSINESS, ACCOUNT) for pair in h.loads + h.checks)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"business_id": OTHER}, {"account_id": "178414999999999"}, {"revoked": True},
    {"expires_at": NOW}, {"expires_at": NOW - timedelta(seconds=1)},
    {"login_route": "facebook"}, {"granted_scopes": frozenset()},
])
async def test_security_untrusted_or_expired_snapshot_never_reaches_dns(changes):
    h = Harness(snapshot=credential(**changes))
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert h.dns == h.transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [me(user_id="178414999999999"), me(account_type="PERSONAL"), {"id": ACCOUNT, "account_type": "BUSINESS"}])
async def test_security_me_proves_current_account_before_account_edge(profile):
    h = Harness(replies=[wire(profile)])
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert len(h.transport.calls) == 1
    assert urlsplit(h.transport.calls[0].url).path.endswith("/me")


@pytest.mark.asyncio
async def test_security_unknown_scope_storage_does_not_invent_a_missing_permission():
    h = Harness(snapshot=credential(granted_scopes=None))
    assert (await h.fetch()).media_id == MEDIA


@pytest.mark.asyncio
async def test_security_unowned_media_never_gets_direct_lookup_or_cdn():
    h = Harness(replies=[wire(me()), wire({"data": [item(id="180000000000099")]})])
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) == 2
    assert h.dns == ["graph.instagram.com", "graph.instagram.com"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b'{"data":[],"data":[{"id":"180000000000001"}]}', b'{"data": NaN}', b'{"data":', b'\xff\xfe', b'[]'])
async def test_security_malformed_or_ambiguous_json_fails_without_cdn(raw):
    h = Harness(replies=[wire(me()), wire(raw)])
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert len(h.transport.calls) == 2


@pytest.mark.asyncio
async def test_security_raw_paging_next_cannot_change_authority_or_carry_token():
    h = Harness(replies=[wire(me()), wire({"data": [], "paging": {
        "next": "https://127.0.0.1/metadata?access_token=" + TOKEN,
        "cursors": {"after": "SAFE_cursor-2"}}}), wire({"data": [item()]}), wire(JPEG, mime="image/jpeg")])
    try:
        await h.fetch()
    except FetchError as error:
        assert_redacted(error)  # Rejecting hostile next entirely is also safe.
    for request in h.transport.calls:
        assert urlsplit(request.url).hostname in {"graph.instagram.com", "scontent.cdninstagram.com"}
        assert TOKEN not in request.url
    assert "127.0.0.1" not in h.dns


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", [TOKEN + "?access_token=x", "x/y", "x%2fy", "x\r\nHeader", "x" * 257])
async def test_security_invalid_cursor_cannot_start_another_graph_request(cursor):
    h = Harness(replies=[wire(me()), wire({"data": [], "paging": {"next": "https://graph.instagram.com/next", "cursors": {"after": cursor}}})])
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert len(h.transport.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://cdninstagram.com.attacker.example/a.jpg", "https://attackerfbcdn.net/a.jpg",
    "https://169.254.169.254/a.jpg", "https://user:pass@scontent.cdninstagram.com/a.jpg",
    "https://scontent.cdninstagram.com:8443/a.jpg", "http://scontent.cdninstagram.com/a.jpg",
    "https://scontent.cdninstagram.com/a.jpg#fragment",
])
async def test_security_cdn_authority_rejected_before_dns(url):
    h = Harness(replies=[wire(me()), wire({"data": [item(media_url=url)]})])
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert h.dns == ["graph.instagram.com", "graph.instagram.com"]


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [(PUBLIC, "127.0.0.1"), ("169.254.169.254",), ("::ffff:93.184.216.34",), (), (PUBLIC,) * 33])
async def test_security_all_dns_addresses_are_public_and_bounded(addresses):
    h = Harness(addresses=addresses)
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert h.transport.calls == []


@pytest.mark.asyncio
async def test_security_connection_changes_during_dns_prevent_first_request():
    h = Harness()
    async def mutate(host):
        h.snapshot = replace(h.snapshot, connection_version=4)
        return (PUBLIC,)
    h.provider.resolver = mutate
    with pytest.raises(FetchError):
        await h.fetch()
    assert h.transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    wire(me(), status=302, headers={"location": "https://attacker.example/?token=" + TOKEN}),
    wire(me(), headers={"content-encoding": "gzip"}), wire(me(), peer="1.1.1.1"),
    wire({"error": {"message": TOKEN, "code": 190}}, status=401),
])
async def test_security_response_redirect_encoding_peer_and_error_do_not_leak(response, caplog):
    h = Harness(replies=[response])
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert TOKEN not in caplog.text
    assert len(h.transport.calls) == 1


@pytest.mark.asyncio
async def test_security_graph_cannot_echo_live_bearer_to_cdn_query():
    h = Harness(replies=[wire(me()), wire({"data": [item(media_url=
        "https://scontent.cdninstagram.com/a.jpg?access_token=" + TOKEN)]})])
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert len(h.transport.calls) == 2


@pytest.mark.asyncio
async def test_security_carousel_disabled_before_children_or_download():
    h = Harness(replies=[wire(me()), wire({"data": [item(media_type="CAROUSEL_ALBUM")]})])
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) == 2


@pytest.mark.asyncio
async def test_security_cancellation_suppressed_by_late_graph_does_not_start_children():
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def late(request):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return wire({"data": [item(media_type="CAROUSEL_ALBUM")]})
    h = Harness(replies=[wire(me()), late], capabilities=OwnedMediaCapabilities(ig_login_media=True, carousel=True))
    task = asyncio.create_task(h.fetch())
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        await asyncio.wait_for(cancelled.wait(), 1)
        release.set()
        await asyncio.sleep(0.01)
        assert len(h.transport.calls) == 2
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_security_timeout_suppressed_by_callback_returns_promptly_without_network():
    entered, release = asyncio.Event(), asyncio.Event()
    h = Harness(limits=OwnedMediaLimits(timeout_seconds=0.02))
    async def stalled(business_id, account_id):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return credential()
    h.provider.credential_loader = stalled
    task = asyncio.create_task(h.fetch())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        done, _ = await asyncio.wait({task}, timeout=0.25)
        assert done, "Cancelled callback must not hold the fetch deadline open"
        with pytest.raises(FetchError) as error:
            task.result()
        assert_redacted(error.value)
        assert h.transport.calls == []
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_security_resolver_failure_message_is_not_exception_cause_or_log(caplog):
    h = Harness()
    async def broken(host):
        raise RuntimeError(TOKEN + " " + SIGNED)
    h.provider.resolver = broken
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert TOKEN not in caplog.text and SIGNED not in caplog.text
    assert h.transport.calls == []


@pytest.mark.asyncio
async def test_security_graph_request_budget_bounds_cursor_walk():
    page = {"data": [], "paging": {"next": "https://graph.instagram.com/ignored", "cursors": {"after": "next"}}}
    h = Harness(replies=[wire(me()), wire(page), wire(page)], limits=OwnedMediaLimits(max_graph_requests=2))
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) <= 2


@pytest.mark.asyncio
async def test_security_oversized_graph_body_does_not_enter_parser_or_cdn():
    h = Harness(replies=[wire(me()), wire(b"x" * 257)], limits=OwnedMediaLimits(max_json_bytes=256))
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) == 2


@pytest.mark.asyncio
async def test_security_timeout_late_resolvers_keep_bounded_admission():
    release = asyncio.Event()
    entered = []
    h = Harness(limits=OwnedMediaLimits(timeout_seconds=0.01))
    async def stuck(host):
        entered.append(host)
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return (PUBLIC,)
    h.provider.resolver = stuck
    try:
        for _ in range(4):
            with pytest.raises(FetchError):
                await h.fetch()
        with pytest.raises(FetchError, match="instagram_busy"):
            await h.fetch()
        assert len(entered) == 4
        assert h.transport.calls == []
    finally:
        release.set()
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_security_generation_change_during_cdn_prevents_result_return():
    h = Harness()
    async def mutate(request):
        h.snapshot = replace(h.snapshot, connection_version=4)
        return wire(JPEG, mime="image/jpeg")
    h.transport.replies[-1] = mutate
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"revoked": True}, {"token": TOKEN + "-ROTATED"}, {"granted_scopes": frozenset()}])
async def test_security_revocation_rotation_and_scope_loss_block_final_result(change):
    h = Harness()
    async def mutate(request):
        h.snapshot = replace(h.snapshot, **change)
        return wire(JPEG, mime="image/jpeg")
    h.transport.replies[-1] = mutate
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)


@pytest.mark.asyncio
async def test_security_aggregate_bytes_include_graph_and_asset_payloads():
    h = Harness(limits=OwnedMediaLimits(max_total_bytes=len(json.dumps(me()).encode()) + 1))
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) <= 2


@pytest.mark.asyncio
async def test_security_original_asset_size_is_enforced_at_fake_transport_boundary():
    h = Harness(limits=OwnedMediaLimits(max_asset_bytes=len(JPEG) - 1))
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) == 3


@pytest.mark.asyncio
async def test_security_carousel_duplicate_children_cannot_create_duplicate_originals():
    h = Harness(replies=[wire(me()), wire({"data": [item(media_type="CAROUSEL_ALBUM")]}),
                         wire({"data": [item(id="1001"), item(id="1001")]})],
                capabilities=OwnedMediaCapabilities(ig_login_media=True, carousel=True))
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) == 3


@pytest.mark.asyncio
async def test_security_carousel_children_are_bounded_before_any_download():
    h = Harness(replies=[wire(me()), wire({"data": [item(media_type="CAROUSEL_ALBUM")]}),
                         wire({"data": [item(id="1001"), item(id="1002")]})],
                capabilities=OwnedMediaCapabilities(ig_login_media=True, carousel=True),
                limits=OwnedMediaLimits(max_assets=1))
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    b'{"user_id":"178414000000001","account_type":"BUSINESS","account_type":"PERSONAL"}',
    b'{"user_id":"178414000000001","user_id":"999","account_type":"BUSINESS"}',
])
async def test_security_principal_duplicate_keys_rejected_before_media_edge(raw):
    h = Harness(replies=[wire(raw)])
    with pytest.raises(FetchError):
        await h.fetch()
    assert len(h.transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("account_id", "../me"), ("account_id", "123?access_token=bad"),
    ("media_id", "https://www.instagram.com/reel/example/"), ("media_id", "123/children"),
    ("media_id", "1" * 33), ("media_id", "१२३"), ("business_id", str(BUSINESS))])
async def test_security_caller_identifiers_cannot_inject_graph_path(field, value):
    h = Harness()
    params = dict(business_id=BUSINESS, account_id=ACCOUNT, media_id=MEDIA)
    params[field] = value
    with pytest.raises(FetchError):
        await h.provider.fetch_owned_media(**params)
    assert h.loads == h.checks == h.dns == h.transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"connection_version": True}, {"connection_version": -1}, {"connection_version": 1.0},
    {"expires_at": NOW.replace(tzinfo=None)}, {"revoked": "false"},
    {"token": "credential\r\nAuthorization: injected"}, {"granted_scopes": {"instagram_business_basic"}},
])
async def test_security_malformed_credential_snapshot_rejected_before_network(changes):
    h = Harness(snapshot=credential(**changes))
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert h.transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mime,body", [("image/jpeg", b"<svg>active</svg>"), ("image/svg+xml", JPEG),
    ("text/html", b"<html>wrong</html>"), ("image/jpeg", b"")])
async def test_security_original_mime_and_signature_must_agree(mime, body):
    h = Harness(replies=[wire(me()), wire({"data": [item()]}), wire(body, mime=mime)])
    with pytest.raises(FetchError):
        await h.fetch()


@pytest.mark.asyncio
async def test_security_success_retains_exact_original_hash_and_no_source_url():
    import hashlib
    h = Harness()
    result = await h.fetch()
    original, = result.assets
    assert original.content == JPEG
    assert original.sha256 == hashlib.sha256(JPEG).hexdigest()
    assert original.content_type == "image/jpeg" and original.media_id == MEDIA
    assert not hasattr(original, "url") and not hasattr(original, "media_url")


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["cursor", "cdn"])
async def test_security_encoded_live_bearer_cannot_be_replayed_as_opaque_data(target):
    encoded = "".join(f"%{ord(character):02x}" for character in TOKEN)
    if target == "cursor":
        payload = {"data": [], "paging": {"next": "https://graph.instagram.com/ignored", "cursors": {"after": encoded}}}
    else:
        payload = {"data": [item(media_url="https://scontent.cdninstagram.com/a.jpg?opaque=" + encoded)]}
    h = Harness(replies=[wire(me()), wire(payload)])
    with pytest.raises(FetchError) as error:
        await h.fetch()
    assert_redacted(error.value)
    assert len(h.transport.calls) == 2


@pytest.mark.asyncio
async def test_security_cancelled_late_children_cannot_resume_original_downloads():
    entered, release = asyncio.Event(), asyncio.Event()
    async def late_children(request):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return wire({"data": [item(id="1001")]})
    h = Harness(replies=[wire(me()), wire({"data": [item(media_type="CAROUSEL_ALBUM")]}), late_children],
                capabilities=OwnedMediaCapabilities(ig_login_media=True, carousel=True))
    task = asyncio.create_task(h.fetch())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert urlsplit(h.transport.calls[-1].url).path.endswith("/" + MEDIA + "/children")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        release.set()
        await asyncio.sleep(0.01)
        assert len(h.transport.calls) == 3
        assert all(urlsplit(call.url).hostname == "graph.instagram.com" for call in h.transport.calls)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
