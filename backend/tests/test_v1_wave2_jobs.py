"""Independent durable-import authority tests; fake DB is not migration proof."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from app.schemas.imports_v1 import CandidateReviewWrite, ImportJobCreate, JobMutation, UploadCreate
from app.services import imports_v1 as service
from app.services.identity import Actor


@pytest.mark.parametrize("field", ["business_id", "reviewer_id", "actor_id", "user_id", "published"])
def test_review_body_cannot_supply_authority_or_publication(field):
    body = {"idempotency_key": str(uuid4()), "expected_revision": 1, "action": "approve", field: str(uuid4())}
    with pytest.raises(ValidationError):
        CandidateReviewWrite.model_validate(body)


def test_nested_override_cannot_forge_the_review_actor():
    with pytest.raises(ValidationError):
        CandidateReviewWrite.model_validate({"idempotency_key": str(uuid4()), "expected_revision": 1,
            "action": "edit", "overrides": [{"field": "stock", "value": 1, "reviewer_id": str(uuid4())}]})


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "upload", "retry", "cancel", "review", "get", "list_jobs", "list_candidates"])
async def test_revoked_actor_cannot_replay_a_prior_authorized_import_action(monkeypatch, action):
    actor = Actor(uuid4(), "v1_user")
    business, resource, key = uuid4(), uuid4(), uuid4()
    denied = AsyncMock(side_effect=HTTPException(404, "Business not found"))
    monkeypatch.setattr(service, "require_business_access", denied)
    class NoReadsAfterRevocation:
        @property
        def no_autoflush(self):
            return nullcontext()
        async def execute(self, query):
            pytest.fail("A revoked actor reached a database query")
        async def scalar(self, query):
            pytest.fail("A revoked actor reached an idempotency/resource lookup")
        async def scalars(self, query):
            pytest.fail("A revoked actor reached an import listing")
        def add(self, row):
            pytest.fail("A revoked actor wrote import state")
    db = NoReadsAfterRevocation()
    mutation = JobMutation(idempotency_key=key, expected_revision=1)
    calls = {
        "create": lambda: service.create_job(db, actor, business, ImportJobCreate(idempotency_key=key, source_authorized=True, source_kind="website", source_url="https://boutique.example.com/dress")),
        "upload": lambda: service.put_upload(db, actor, business, UploadCreate(idempotency_key=key, source_authorized=True, content_type="image/png"), content=b"\x89PNG\r\n\x1a\nsynthetic"),
        "retry": lambda: service.mutate_job(db, actor, business, resource, mutation, action="retry"),
        "cancel": lambda: service.mutate_job(db, actor, business, resource, mutation, action="cancel"),
        "review": lambda: service.review_candidate(db, actor, business, resource, CandidateReviewWrite(idempotency_key=key, expected_revision=1, action="approve")),
        "get": lambda: service.get_job(db, actor, business, resource),
        "list_jobs": lambda: service.list_jobs(db, actor, business),
        "list_candidates": lambda: service.list_candidates(db, actor, business),
    }
    with pytest.raises(HTTPException) as error:
        await calls[action]()
    assert error.value.status_code == 404
    denied.assert_awaited_once()


@pytest.mark.asyncio
async def test_instagram_adapter_foreign_account_never_becomes_candidate_provenance():
    business, actor = uuid4(), uuid4()
    claim = service.JobClaim(uuid4(), business, actor, uuid4(),
        {"kind": "instagram", "media_id": "source-media", "account_id": "authorized-account"}, service.now())
    provider = SimpleNamespace(fetch_owned_media=AsyncMock(return_value=SimpleNamespace(
        account_id="foreign-account", media_id="source-media", products=[])))
    with pytest.raises(service.FetchError, match="provider_ownership_mismatch"):
        await service.collect_claim(claim, fetcher=None, instagram_provider=provider)
    assert provider.fetch_owned_media.await_args.kwargs["business_id"] == business
