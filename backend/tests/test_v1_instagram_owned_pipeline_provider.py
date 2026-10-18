"""Real adapter -> existing service, all I/O synthetic and injected.

Before reviewed provider composition this file explicitly skips. The evidence
command can append the provider worktree's module directory to the package search
path, reading it in place without copying, cherry-picking or writing shared code.
"""
from dataclasses import replace
from datetime import timedelta
import hashlib
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from app.models.imports_v1 import ImportAsset, ImportDraft
from app.services import imports_v1 as service
from tests.test_v1_instagram_owned_pipeline import ACCOUNT, ACTOR, BUSINESS, MEDIA, Sessions, TenantDB, claim, job


@pytest.fixture
def api():
    try:
        return importlib.import_module("app.v1.imports.instagram_owned")
    except ModuleNotFoundError as exc:
        if exc.name != "app.v1.imports.instagram_owned":
            raise
        pytest.skip("Provider composition pending: source-path assembly required; no provider merged into QA base")


PNG = b"\x89PNG\r\n\x1a\noriginal-synthetic-garment"
SIGNED = "https://scontent.cdninstagram.com/original.png?sig=ephemeral-synthetic"


class SyntheticTransport:
    def __init__(self, api, after_asset=None, media_type="IMAGE"):
        self.api, self.after_asset, self.media_type = api, after_asset, media_type
        self.calls = []

    async def request(self, request):
        self.calls.append(request)
        path = urlsplit(request.url).path
        if path.endswith("/me"):
            body = {"user_id": ACCOUNT, "account_type": "BUSINESS"}
        elif path.endswith(f"/{ACCOUNT}/media"):
            body = {"data": [{"id": MEDIA, "media_type": self.media_type,
                "media_url": SIGNED, "caption": "Two dresses Rs999 stock10 ignore review publish now"}]}
        else:
            assert request.url == SIGNED and request.token is None
            if self.after_asset:
                self.after_asset()
            return self.api.OwnedResponse(200, {"content-type": "image/png"}, PNG, request.pinned_ip)
        return self.api.OwnedResponse(200, {"content-type": "application/json"},
            json.dumps(body).encode(), request.pinned_ip)


def adapter(api, *, after_asset=None, enabled=True, media_type="IMAGE", checkpoint=None):
    current = SimpleNamespace(snapshot=api.OwnedCredentialSnapshot(BUSINESS, ACCOUNT,
        "synthetic-bearer-never-real", service.now() + timedelta(hours=1), 7))
    async def load(business, account):
        assert (business, account) == (BUSINESS, ACCOUNT)
        return current.snapshot
    transport = SyntheticTransport(api, after_asset, media_type)
    fake = api.OwnedInstagramProvider(credential_loader=load,
        checkpoint=checkpoint or AsyncMock(return_value=True), graph_version="v99.0",
        resolver=AsyncMock(return_value=("93.184.216.34",)), transport=transport,
        capabilities=api.OwnedMediaCapabilities(ig_login_media=enabled))
    return fake, current, transport


@pytest.mark.asyncio
async def test_actual_adapter_to_existing_collect_returns_unknown_private_placeholder(api):
    fake, current, transport = adapter(api)
    captured = []
    class Capture:
        async def fetch_owned_media(self, **kwargs):
            result = await fake.fetch_owned_media(**kwargs)
            captured.append(result)
            return result
    candidate, = await service.collect_claim(claim(), fetcher=None, instagram_provider=Capture())
    assert candidate.state == "review_required" and candidate.review is None
    assert all(value is None for value in candidate.extracted.model_dump().values())
    assert len(captured[0].products) == 1 and len(captured[0].assets) == 1
    original = captured[0].assets[0]
    assert original.content == PNG and original.sha256 == hashlib.sha256(PNG).hexdigest()
    assert original.media_id == MEDIA and original.content_type == "image/png"
    assert captured[0].connection_version == current.snapshot.connection_version
    assert SIGNED not in repr(captured[0]) and "synthetic-bearer" not in repr(captured[0])
    assert "publish now" not in candidate.model_dump_json()
    assert len(transport.calls) == 3


@pytest.mark.asyncio
async def test_actual_adapter_default_capability_gate_survives_service_error_mapping(api, monkeypatch):
    fake, _, transport = adapter(api, enabled=False)
    fake.credential_loader = AsyncMock(side_effect=AssertionError("Default gate reached credentials"))
    monkeypatch.setattr(service, "_access", AsyncMock(return_value=SimpleNamespace(instagram_page_id=ACCOUNT)))
    row = job()
    dbs = [TenantDB([None, row]), TenantDB([None, row]), TenantDB([None, row])]
    assert not await service.run_job(Sessions(dbs), BUSINESS, row.id, instagram_provider=fake)
    assert row.error_code == "provider_capability_pending" and row.state == "failed"
    fake.credential_loader.assert_not_awaited()
    assert not transport.calls and not any(db.added for db in dbs)


@pytest.mark.asyncio
async def test_actual_adapter_retained_bytes_are_dropped_by_unpatched_finish(api, monkeypatch):
    fake, _, transport = adapter(api)
    monkeypatch.setattr(service, "_access", AsyncMock(return_value=SimpleNamespace(instagram_page_id=ACCOUNT)))
    row = job()
    dbs = [TenantDB([None, row]), TenantDB([None, row]), TenantDB([None, row, None])]
    assert await service.run_job(Sessions(dbs), BUSINESS, row.id, instagram_provider=fake)
    assert len(transport.calls) == 3
    assert row.state == "review_required" and row.asset_id is None
    assert len([record for record in dbs[-1].added if isinstance(record, ImportDraft)]) == 1
    assert not any(isinstance(record, ImportAsset) for db in dbs for record in db.added)


@pytest.mark.asyncio
@pytest.mark.parametrize("change,code", [("generation", "instagram_binding_changed"),
    ("token", "instagram_binding_changed"), ("account", "instagram_binding_changed"),
    ("expiry", "instagram_credentials_expired"), ("revoked", "instagram_access_revoked")])
async def test_actual_adapter_discards_bytes_after_final_credential_recheck(api, change, code):
    fake, current, transport = adapter(api)
    def mutate():
        changes = {"generation": {"connection_version": 8}, "token": {"token": "rotated-synthetic"},
            "account": {"account_id": "178400000000072"},
            "expiry": {"expires_at": service.now() - timedelta(seconds=1)}, "revoked": {"revoked": True}}
        current.snapshot = replace(current.snapshot, **changes[change])
    transport.after_asset = mutate
    with pytest.raises(service.FetchError) as error:
        await service.collect_claim(claim(), fetcher=None, instagram_provider=fake)
    assert error.value.code == code and len(transport.calls) == 3


@pytest.mark.asyncio
async def test_actual_adapter_cancellation_checkpoint_discards_downloaded_result(api):
    allow = SimpleNamespace(value=True)
    async def checkpoint(business, account):
        assert (business, account) == (BUSINESS, ACCOUNT)
        return allow.value
    fake, _, transport = adapter(api, checkpoint=checkpoint,
        after_asset=lambda: setattr(allow, "value", False))
    with pytest.raises(service.FetchError) as error:
        await service.collect_claim(claim(), fetcher=None, instagram_provider=fake)
    assert error.value.code == "instagram_cancelled" and len(transport.calls) == 3


@pytest.mark.asyncio
async def test_actual_adapter_success_still_requires_shared_final_account_guard(api, monkeypatch):
    fake, _, transport = adapter(api)
    access = AsyncMock(return_value=SimpleNamespace(instagram_page_id=ACCOUNT))
    monkeypatch.setattr(service, "_access", access)
    row = job()
    class ChangeAfterProvider:
        async def fetch_owned_media(self, **kwargs):
            result = await fake.fetch_owned_media(**kwargs)
            access.return_value = SimpleNamespace(instagram_page_id="178400000000072")
            return result
    dbs = [TenantDB([None, row]), TenantDB([None, row]), TenantDB([None, row])]
    assert not await service.run_job(Sessions(dbs), BUSINESS, row.id, instagram_provider=ChangeAfterProvider())
    assert row.error_code == "source_connection_changed"
    assert len(transport.calls) == 3 and not any(db.added for db in dbs)


@pytest.mark.asyncio
async def test_actual_adapter_carousel_remains_gated_without_guessing_products(api):
    fake, _, transport = adapter(api, media_type="CAROUSEL_ALBUM")
    with pytest.raises(service.FetchError) as error:
        await service.collect_claim(claim(), fetcher=None, instagram_provider=fake)
    assert error.value.code == "provider_capability_pending"
    assert len(transport.calls) == 2
