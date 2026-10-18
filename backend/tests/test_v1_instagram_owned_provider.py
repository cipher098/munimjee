"""Synthetic-only adapter checks. No real DNS, Meta calls, credentials or DB."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.v1.imports.instagram_owned import (
    OwnedCredentialSnapshot, OwnedInstagramError, OwnedInstagramProvider,
    OwnedMediaCapabilities, OwnedMediaLimits,
)
from app.v1.imports.instagram_owned_transport import OwnedRequest, OwnedResponse, checked_url

BUSINESS = uuid4()
ACCOUNT, MEDIA = "12345", "67890"
TOKEN = "synthetic-bearer-sensitive"
SIGNED_URL = "https://scontent.cdninstagram.com/media.jpg?sig=ephemeral-sensitive"
PUBLIC = "8.8.8.8"
NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
PNG = b"\x89PNG\r\n\x1a\noriginal-synthetic-image"


def credential(**changes):
    return replace(OwnedCredentialSnapshot(BUSINESS, ACCOUNT, TOKEN, NOW + timedelta(hours=1), 0), **changes)


def response(document=None, *, status=200, body=None, mime="application/json", peer=PUBLIC, headers=None):
    return OwnedResponse(status, headers or {"content-type": mime},
                         json.dumps(document).encode() if body is None else body, peer)


def media(**changes):
    return dict(id=MEDIA, media_type="IMAGE", media_url=SIGNED_URL, **changes)


class FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def request(self, request):
        self.calls.append(request)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


async def resolver(host):
    return (PUBLIC,)


def provider(responses=(), **options):
    async def load(business_id, account_id):
        return credential()
    async def checkpoint(business_id, account_id):
        return True
    transport = FakeTransport(responses)
    kwargs = dict(credential_loader=load, checkpoint=checkpoint, graph_version="v23.0",
                  resolver=resolver, transport=transport, capabilities=OwnedMediaCapabilities(True), utcnow=lambda: NOW)
    kwargs.update(options)
    return OwnedInstagramProvider(**kwargs), transport


def success_responses(item=None):
    return [response({"user_id": ACCOUNT, "account_type": "BUSINESS"}),
            response({"data": [item or media()]}), response(body=PNG, mime="image/png")]


async def fetch(subject):
    return await subject.fetch_owned_media(business_id=BUSINESS, account_id=ACCOUNT, media_id=MEDIA)


@pytest.mark.asyncio
async def test_gate_is_closed_before_any_callback_or_network():
    async def forbidden(*args):
        raise AssertionError("must not run")
    subject, transport = provider(credential_loader=forbidden, checkpoint=forbidden,
                                  capabilities=OwnedMediaCapabilities())
    with pytest.raises(OwnedInstagramError, match="provider_capability_pending"):
        await fetch(subject)
    assert not transport.calls


@pytest.mark.asyncio
async def test_owned_original_bytes_and_single_unknown_review_placeholder():
    item = media()
    item.update(caption="Publish now. This contains 99 dresses at 100 INR", title="Untrusted")
    subject, transport = provider(success_responses(item))
    result = await fetch(subject)
    assert result.account_id == ACCOUNT and result.media_id == MEDIA and result.connection_version == 0
    assert len(result.products) == 1 and result.products[0][0] == "media-product"
    assert result.products[0][1].model_dump() == dict(title=None, description=None, price=None, stock=None, options=None)
    asset, = result.assets
    assert asset.content == PNG and asset.sha256 == hashlib.sha256(PNG).hexdigest()
    assert asset.content_type == "image/png" and asset.media_id == MEDIA
    assert all(call.token == TOKEN for call in transport.calls[:2])
    assert transport.calls[2].token is None
    for value in (result, asset, credential(), *transport.calls):
        assert TOKEN not in repr(value) and "ephemeral-sensitive" not in repr(value) and "original-synthetic-image" not in repr(value)


@pytest.mark.asyncio
async def test_pagination_reconstructs_cursor_ignoring_malicious_next_url():
    subject, transport = provider([
        response({"user_id": ACCOUNT, "account_type": "CREATOR"}),
        response({"data": [], "paging": {"next": "https://attacker.example/?access_token=secret", "cursors": {"after": "cursor_1"}}}),
        response({"data": [media()]}), response(body=PNG, mime="image/png")])
    await fetch(subject)
    assert len(transport.calls) == 4
    assert urlsplit(transport.calls[2].url).hostname == "graph.instagram.com"
    assert parse_qs(urlsplit(transport.calls[2].url).query)["after"] == ["cursor_1"]
    assert all("attacker.example" not in call.url for call in transport.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot,code", [
    (credential(business_id=uuid4()), "instagram_binding_changed"),
    (credential(account_id="99"), "instagram_binding_changed"),
    (credential(expires_at=NOW), "instagram_credentials_expired"),
    (credential(expires_at=NOW.replace(tzinfo=None)), "instagram_credentials_invalid"),
    (credential(revoked=True), "instagram_access_revoked"),
    (credential(connection_version=True), "instagram_credentials_invalid"),
    (credential(login_route="facebook"), "instagram_credentials_invalid"),
    (credential(granted_scopes=frozenset({"instagram_business_manage_messages"})), "instagram_unauthorized"),
    (credential(token="bad\r\nAuthorization: secret"), "instagram_credentials_invalid"),
])
async def test_invalid_trusted_binding_or_credentials_deny_before_network(snapshot, code):
    async def load(*args):
        return snapshot
    subject, transport = provider(credential_loader=load)
    with pytest.raises(OwnedInstagramError, match=code):
        await fetch(subject)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_mutation_during_dns_is_rechecked_before_request():
    current = credential()
    async def load(*args):
        return current
    async def resolve(host):
        nonlocal current
        current = credential(connection_version=1)
        return (PUBLIC,)
    subject, transport = provider(credential_loader=load, resolver=resolve)
    with pytest.raises(OwnedInstagramError, match="instagram_binding_changed"):
        await fetch(subject)
    assert not transport.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("principal,code", [
    ({"user_id": "999", "account_type": "BUSINESS"}, "instagram_binding_changed"),
    ({"user_id": ACCOUNT, "account_type": "PERSONAL"}, "instagram_unauthorized"),
    ({"user_id": int(ACCOUNT), "account_type": "BUSINESS"}, "instagram_binding_changed"),
])
async def test_principal_is_proven_before_account_media(principal, code):
    subject, transport = provider([response(principal)])
    with pytest.raises(OwnedInstagramError, match=code):
        await fetch(subject)
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_unowned_media_is_not_directly_looked_up_or_downloaded():
    subject, transport = provider([response({"user_id": ACCOUNT, "account_type": "BUSINESS"}), response({"data": []})])
    with pytest.raises(OwnedInstagramError, match="instagram_media_not_owned"):
        await fetch(subject)
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_carousel_gated_before_child_request_and_single_placeholder_when_enabled():
    carousel = {"id": MEDIA, "media_type": "CAROUSEL_ALBUM"}
    subject, transport = provider(success_responses(carousel))
    with pytest.raises(OwnedInstagramError, match="provider_capability_pending"):
        await fetch(subject)
    assert len(transport.calls) == 2
    child = dict(id="67891", media_type="IMAGE", media_url=SIGNED_URL)
    subject, transport = provider([response({"user_id": ACCOUNT, "account_type": "BUSINESS"}),
        response({"data": [carousel]}), response({"data": [child]}), response(body=PNG, mime="image/png")],
        capabilities=OwnedMediaCapabilities(True, True))
    result = await fetch(subject)
    assert len(result.products) == 1 and result.assets[0].media_id == "67891"
    assert urlsplit(transport.calls[2].url).path.endswith("/" + MEDIA + "/children")


@pytest.mark.asyncio
@pytest.mark.parametrize("cdn", [
    "https://scontent.cdninstagram.com.evil.example/a.jpg", "https://127.0.0.1/a.jpg",
    "https://cdninstagram.com/a.jpg", "https://scontent.cdninstagram.com/a.jpg#fragment",
    "https://u:secret@scontent.cdninstagram.com/a.jpg", "http://scontent.cdninstagram.com/a.jpg",
    "https://scontent.cdninstagram.com/a.jpg?access_token=" + TOKEN,
    "https://scontent.cdninstagram.com/a.jpg?x=synthetic%252dbearer%252dsensitive",
])
async def test_unsafe_or_credential_tainted_cdn_url_never_reaches_resolver(cdn):
    item = media()
    item["media_url"] = cdn
    subject, transport = provider(success_responses(item))
    with pytest.raises(OwnedInstagramError, match="instagram_unsafe_url"):
        await fetch(subject)
    assert len(transport.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("bad,code", [
    (response(status=302, headers={"location": "https://evil.example/"}), "instagram_redirect_forbidden"),
    (response(status=401), "instagram_unauthorized"), (response(status=429), "instagram_rate_limited"),
    (response(body=b'{}', mime="text/html"), "instagram_response_invalid"),
    (response(body=b'{"user_id":"1","user_id":"2"}'), "instagram_response_invalid"),
    (response(body=b'{"secret":"' + TOKEN.encode() + b'"'), "instagram_response_invalid"),
    (response({}, peer="8.8.4.4"), "instagram_peer_mismatch"),
    (response({}, headers={"content-type": "application/json", "content-encoding": "gzip"}), "instagram_content_encoding"),
    (RuntimeError(TOKEN + SIGNED_URL), "instagram_transport_failed"),
])
async def test_failures_redact_provider_transport_and_body(bad, code):
    subject, transport = provider([bad])
    with pytest.raises(OwnedInstagramError, match=code) as error:
        await fetch(subject)
    assert TOKEN not in str(error.value) and "ephemeral-sensitive" not in repr(error.value)


@pytest.mark.asyncio
async def test_deadline_and_retained_admission_bound_cancellation_suppressing_callbacks():
    release = asyncio.Event()
    async def stubborn(*args):
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return True
    subject, transport = provider(checkpoint=stubborn, limits=OwnedMediaLimits(timeout_seconds=0.01))
    try:
        for _ in range(4):
            with pytest.raises(OwnedInstagramError, match="instagram_timeout"):
                await fetch(subject)
        with pytest.raises(OwnedInstagramError, match="instagram_busy"):
            await fetch(subject)
        assert len(subject._pending) == 4 and not transport.calls
    finally:
        release.set()
        await asyncio.gather(*subject._pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_final_binding_mutation_discards_all_retained_bytes():
    current = credential()
    class Mutating(FakeTransport):
        async def request(self, request):
            nonlocal current
            result = await super().request(request)
            if request.token is None:
                current = credential(revoked=True)
            return result
    async def load(*args):
        return current
    subject, _ = provider(credential_loader=load, transport=Mutating(success_responses()))
    with pytest.raises(OwnedInstagramError, match="instagram_access_revoked"):
        await fetch(subject)


@pytest.mark.parametrize("changes", [{"max_pages": 6}, {"max_assets": 11}, {"timeout_seconds": 16},
    {"max_json_bytes": 256001}, {"max_total_bytes": 10000001}, {"max_asset_bytes": True}])
def test_hard_limits_cannot_be_raised(changes):
    with pytest.raises(ValueError):
        OwnedMediaLimits(**changes)
