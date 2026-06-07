"""Fixtures for scenario tests: per-test DB schema + integration-client patches.

Separated from the top-level conftest.py because the existing pure-unit tests
(test_claude_decide, test_interventions, etc.) don't need any of this and we
want to keep their boot time at ~0.1s.

To use these fixtures in a test file, add at module top:

    from tests.conftest_db import db_session, patched_clients, scenario_cassette  # noqa
"""
from __future__ import annotations

import os
import pathlib

import pytest
import pytest_asyncio
import vcr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Touching this module registers every ORM table on Base.metadata.
import app.models  # noqa: F401
from app.database import Base


CASSETTE_ROOT = pathlib.Path(__file__).parent / "cassettes" / "scenarios"


def _test_db_url() -> str:
    """Test DB URL — same Postgres instance, dedicated `sellerbot_test` database.

    Honours an explicit TEST_DATABASE_URL override (useful for CI). Otherwise
    swaps the database name on the configured DATABASE_URL so we never write
    test rows into the dev/prod DB by accident.
    """
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override
    from app.config import settings
    base = settings.DATABASE_URL
    # postgresql+asyncpg://user:pass@host:port/sellerbot → .../sellerbot_test
    if "/" in base:
        head, _, _name = base.rpartition("/")
        return f"{head}/sellerbot_test"
    return base


async def _ensure_test_db_exists() -> None:
    """CREATE DATABASE sellerbot_test if missing. Idempotent.

    We connect to the default `postgres` admin DB to issue the CREATE.
    """
    from app.config import settings
    admin_url = settings.DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_async_engine(admin_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            result = await conn.exec_driver_sql(
                "SELECT 1 FROM pg_database WHERE datname='sellerbot_test'"
            )
            if result.fetchone() is None:
                await conn.exec_driver_sql("CREATE DATABASE sellerbot_test")
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Fresh schema per test, yielded as a single AsyncSession.

    We drop + recreate all tables on every test rather than truncating to keep
    the fixture trivially correct as the schema evolves — no fixture edits
    needed when a new column lands.

    Cost: ~80ms per test on the dev box. Fine for the dozen-or-so scenarios
    we expect short-term.
    """
    await _ensure_test_db_exists()
    engine = create_async_engine(_test_db_url(), poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session
            await session.commit()
    finally:
        await engine.dispose()


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

    Records under tests/cassettes/scenarios/<scenario_id>/turn_<n>.yaml.
    Recording is gated on VCR_RECORD=1; default mode is "none" (strict replay).
    """
    record_mode = "all" if os.environ.get("VCR_RECORD") == "1" else "none"

    def _open(scenario_id: str, turn: int):
        scenario_dir = CASSETTE_ROOT / scenario_id
        scenario_dir.mkdir(parents=True, exist_ok=True)
        cassette_path = scenario_dir / f"turn_{turn}.yaml"
        return vcr.use_cassette(
            str(cassette_path),
            record_mode=record_mode,
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
