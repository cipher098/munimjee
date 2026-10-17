"""Fixtures for scenario tests: migrated disposable schema and fake clients.

To use these fixtures in a test file, add at module top:

    from tests.conftest_db import db_session, patched_clients, scenario_cassette  # noqa
"""
from __future__ import annotations

import os
import pathlib

import pytest
import pytest_asyncio
import vcr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.isolated_database import migrated_database


CASSETTE_ROOT = pathlib.Path(__file__).parent / "cassettes" / "scenarios"


@pytest_asyncio.fixture
async def migrated_engine():
    """Disposable lane schema built only by actual Alembic migrations."""
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("DB gate pending: set TEST_DATABASE_URL, TEST_LANE and TEST_DB_RESET=1")
    async with migrated_database() as engine:
        yield engine


@pytest_asyncio.fixture
async def db_session(migrated_engine) -> AsyncSession:
    """Fresh migrated schema per test; the reset lease spans the whole session."""
    engine = migrated_engine
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.commit()


@pytest_asyncio.fixture
async def two_sellers(db_session):
    """Independent synthetic tenants for boundary tests; contains no live IDs."""
    from app.models.seller import Seller
    sellers = [
        Seller(email=f"tenant-{index}@example.test", password_hash="unused", business_name=f"Test tenant {index}")
        for index in (1, 2)
    ]
    db_session.add_all(sellers)
    await db_session.flush()
    return tuple(sellers)


@pytest.fixture
def patched_clients(monkeypatch: pytest.MonkeyPatch):
    """Monkeypatch the three external clients to local Fakes.

    Patches BOTH the integration module symbols AND the conversation/responder
    module-local re-imports (since those modules do `from app.integrations.x
    import XClient` inside functions). We replace the underlying class so any
    fresh `XClient(...)` call inside production code returns a fake.

    Returns a dict mapping client name -> the fake instance(s) created.
    Tests can inspect `patched_clients["instagram"][0].calls` after a turn
    to assert the bot tried to send a specific message.
    """
    from tests.fakes import FakeInstagramClient, FakeSarvamFailingClient, FakeWhatsAppClient

    created = {"instagram": [], "whatsapp": [], "sarvam": []}

    def _instagram_factory(*args, **kwargs):
        fake = FakeInstagramClient(*args, **kwargs)
        created["instagram"].append(fake)
        return fake

    def _whatsapp_factory(*args, **kwargs):
        fake = FakeWhatsAppClient(*args, **kwargs)
        created["whatsapp"].append(fake)
        return fake

    def _sarvam_factory(*args, **kwargs):
        fake = FakeSarvamFailingClient(*args, **kwargs)
        created["sarvam"].append(fake)
        return fake

    import app.integrations.instagram as _ig
    import app.integrations.sarvam as _sv
    import app.integrations.whatsapp as _wa

    monkeypatch.setattr(_ig, "InstagramClient", _instagram_factory)
    monkeypatch.setattr(_sv, "SarvamClient", _sarvam_factory)
    monkeypatch.setattr(_wa, "WhatsAppClient", _whatsapp_factory)
    return created


@pytest.fixture
def scenario_cassette():
    """Yields a context-manager builder for per-turn VCR cassettes.

    Usage:
        with scenario_cassette("walkaway_calls_bluff", turn=2):
            await advance_conversation(...)

    Replays tests/cassettes/scenarios/<scenario_id>/turn_<n>.yaml.
    Recording is forbidden; mode is always "none" (strict replay).
    """
    def _open(scenario_id: str, turn: int):
        scenario_dir = CASSETTE_ROOT / scenario_id
        cassette_path = scenario_dir / f"turn_{turn}.yaml"
        return vcr.use_cassette(
            str(cassette_path),
            record_mode="none",
            filter_headers=[
                ("x-api-key", "REDACTED"),
                ("anthropic-api-key", "REDACTED"),
                ("authorization", "REDACTED"),
            ],
            match_on=["method", "scheme", "host", "port", "path", "query", "body"],
            decode_compressed_response=True,
            allow_playback_repeats=True,
        )

    return _open
