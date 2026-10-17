"""Adversarial harness checks run without a database or provider credentials."""
from contextlib import asynccontextmanager
import os
import socket
from unittest.mock import patch

import pytest

from tests.safety import (
    TestSafetyError, require_allowed_socket, sanitized_test_environment, validate_test_database,
)
from tests.conftest_db import db_session, two_sellers  # noqa: F401


def safe_env(**updates):
    return {
        "TEST_DATABASE_URL": "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_qa",
        "TEST_LANE": "qa", "TEST_DB_RESET": "1", **updates,
    }


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@[::1]:55461/munimjee_test_qa",
])
def test_accepts_only_explicit_literal_lane_target(url):
    target = validate_test_database(safe_env(TEST_DATABASE_URL=url))
    assert target.database == "munimjee_test_qa"
    assert target.port == 55461


@pytest.mark.parametrize("url", [
    "", "postgresql://test:test@127.0.0.1:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@prod.example:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@localhost:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@localhost.evil:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@127.1:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@2130706433:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@0x7f000001:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@127.0.0.2:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@[::ffff:127.0.0.1]:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@[::1%lo0]:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@[0:0:0:0:0:0:0:1]:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@%31%32%37.0.0.1:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test%40evil@127.0.0.1:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@evil@127.0.0.1:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@127.0.0.1:55461@evil/munimjee_test_qa",
    "postgresql+asyncpg://test:test@127.0.0.1:55461,evil:5432/munimjee_test_qa",
    "postgresql+asyncpg://test:test@/munimjee_test_qa?host=/tmp",
    "postgresql+asyncpg://test:test@127.0.0.1:0/munimjee_test_qa",
    "postgresql+asyncpg://test:test@127.0.0.1:65536/munimjee_test_qa",
    "postgresql+asyncpg://test:test@127.0.0.1:055461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_%71a",
    "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_qa%2f..%2fpostgres",
    "postgresql+asyncpg://test:test@127.0.0.1:55461/postgres/munimjee_test_qa",
    "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_qa/",
    "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_qa#ignored",
    " postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_qa",
    "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_qa\n",
])
def test_rejects_ambiguous_or_nondisposable_urls(url):
    with pytest.raises(TestSafetyError):
        validate_test_database(safe_env(TEST_DATABASE_URL=url))


@pytest.mark.parametrize("options", [
    "?host=prod.example", "?host=127.0.0.1", "?port=5432", "?database=postgres",
    "?user=admin", "?sslmode=disable", "?host=prod&host=127.0.0.1", "?options=-csearch_path=private",
])
def test_rejects_all_driver_query_overrides(options):
    with pytest.raises(TestSafetyError):
        validate_test_database(safe_env(TEST_DATABASE_URL=safe_env()["TEST_DATABASE_URL"] + options))


@pytest.mark.parametrize("changes", [
    {"TEST_DB_RESET": ""}, {"TEST_DB_RESET": "true"}, {"TEST_DB_RESET": "0"},
    {"TEST_LANE": ""}, {"TEST_LANE": "QA"}, {"TEST_LANE": "qa_other"},
    {"TEST_LANE": "qa;DROP"}, {"TEST_LANE": "qa-test"}, {"TEST_LANE": "qa\n"},
    {"TEST_LANE": "a" * 25}, {"PYTEST_XDIST_WORKER": "gw0"}, {"PYTEST_XDIST_WORKER": "gw1"},
])
def test_optin_lane_exact_match_and_xdist_are_mandatory(changes):
    with pytest.raises(TestSafetyError):
        validate_test_database(safe_env(**changes))


def test_no_runtime_or_admin_fallback():
    with pytest.raises(TestSafetyError):
        validate_test_database({"DATABASE_URL": safe_env()["TEST_DATABASE_URL"], "TEST_DB_RESET": "1", "TEST_LANE": "qa"})
    env = sanitized_test_environment({
        "DATABASE_URL": "postgresql://live:secret@production/live",
        "REDIS_URL": "redis://production/0", "META_APP_SECRET": "live-secret",
        "ANTHROPIC_API_KEY": "live-key", "AWS_SECRET_ACCESS_KEY": "live-key",
        "GOOGLE_APPLICATION_CREDENTIALS": "/private/live.json", "HTTP_PROXY": "http://live-proxy",
    })
    assert env["DATABASE_URL"].endswith(":1/munimjee_test_disabled")
    assert "TEST_DATABASE_URL" not in env
    assert "META_APP_SECRET" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env
    assert "HTTP_PROXY" not in env
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-replay-only-not-a-real-key"
    assert env["REDIS_URL"] == "redis://127.0.0.1:1/0"


def test_runtime_url_is_only_explicit_validated_test_url():
    env = sanitized_test_environment({**safe_env(), "DATABASE_URL": "live-value"})
    assert env["DATABASE_URL"] == safe_env()["TEST_DATABASE_URL"]
    with pytest.raises(TestSafetyError):
        sanitized_test_environment({**safe_env(TEST_DB_RESET="0"), "DATABASE_URL": "live-value"})


@pytest.mark.parametrize("record", ["1", "all", "once", "true"])
def test_recording_requires_separate_authorization_and_is_forbidden(record):
    with pytest.raises(TestSafetyError, match="recording is forbidden"):
        sanitized_test_environment({"VCR_RECORD": record})


def test_dotenv_is_not_read_even_with_explicit_env_file(tmp_path):
    from app.config import Settings
    from pydantic_settings import sources
    sentinel = tmp_path / ".env"
    sentinel.write_text("SECRET_KEY=live-secret\nDATABASE_URL=live-value\n")
    # This is the lower-level reader that DotEnvSettingsSource normally calls
    # *during construction*, before __call__. Any read fails the test.
    with patch.object(sources, "read_env_file", side_effect=AssertionError("dotenv was read")):
        settings = Settings(_env_file=sentinel)
    assert settings.SECRET_KEY != "live-secret"
    assert settings.DATABASE_URL == os.environ["DATABASE_URL"]


@pytest.mark.parametrize("address", [
    ("graph.facebook.com", 443), ("127.0.0.1", 443), ("127.0.0.1", 6379),
    ("localhost", 55461), ("::ffff:127.0.0.1", 55461), "/var/run/docker.sock",
])
def test_outbound_and_shared_local_service_addresses_blocked(address):
    with pytest.raises(TestSafetyError):
        require_allowed_socket(address, validate_test_database(safe_env()))


def test_only_guarded_db_endpoint_is_allowed():
    target = validate_test_database(safe_env())
    require_allowed_socket(("127.0.0.1", 55461), target)
    with pytest.raises(TestSafetyError):
        require_allowed_socket(("127.0.0.1", 55461), None)


def test_actual_socket_and_dns_entrypoints_are_guarded():
    # Fail before touching the network. Tests work with or without a DB target.
    with socket.socket() as client:
        with pytest.raises(TestSafetyError):
            client.connect(("203.0.113.10", 443))
        with pytest.raises(TestSafetyError):
            client.connect_ex(("203.0.113.10", 443))
    with pytest.raises(TestSafetyError):
        socket.getaddrinfo("provider.invalid", 443)


def test_strict_cassette_replay_works_with_network_guard(tmp_path, monkeypatch, claude_cassette):
    import httpx
    import yaml
    import vcr
    from tests import conftest

    monkeypatch.setattr(conftest, "CASSETTE_DIR", tmp_path)
    cassette = tmp_path / "synthetic_replay.yaml"
    cassette.write_text(yaml.safe_dump({
        "version": 1,
        "interactions": [{
            "request": {"method": "GET", "uri": "https://provider.invalid/answer", "body": "", "headers": {}},
            "response": {"status": {"code": 200, "message": "OK"}, "body": {"string": "replayed"}, "headers": {}},
        }],
    }))
    original = cassette.read_bytes()
    # Even a late environment mutation cannot turn the fixture into a recorder.
    monkeypatch.setenv("VCR_RECORD", "1")
    with claude_cassette("synthetic_replay"):
        assert httpx.get("https://provider.invalid/answer").text == "replayed"
        with pytest.raises(vcr.errors.CannotOverwriteExistingCassetteException):
            httpx.get("https://provider.invalid/unrecorded")
    assert cassette.read_bytes() == original


def load_runner():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("v1_test_runner", Path(__file__).resolve().parents[2] / "scripts" / "v1-test.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


@pytest.mark.parametrize("endpoint", [
    "tcp://production.example:2376", "ssh://production.example", "unix://remote/path",
    "unix:///tmp/docker.sock?host=production", "unix:///%2ftmp/docker.sock", "unix:///tmp/docker.sock\n",
])
def test_runner_refuses_remote_or_ambiguous_docker_context_before_mutation(monkeypatch, endpoint):
    import json
    import sys
    from types import SimpleNamespace
    runner = load_runner()
    calls = []
    def inspect(command, **kwargs):
        calls.append(command)
        assert command == ["docker", "context", "inspect"]
        assert kwargs["timeout"] == 5
        return SimpleNamespace(returncode=0, stdout=json.dumps([{"Endpoints": {"docker": {"Host": endpoint}}}]))
    monkeypatch.setattr(runner.subprocess, "run", inspect)
    monkeypatch.setattr(sys, "argv", ["v1-test.py", "--lane", "qa", "--pg-port", "55461", "down"])
    with pytest.raises(TestSafetyError):
        runner.main()
    assert len(calls) == 1


def test_runner_pins_compose_to_verified_local_context_and_disables_dotenv(monkeypatch):
    import json
    import sys
    from types import SimpleNamespace
    runner = load_runner()
    endpoint = "unix:///tmp/isolated-docker.sock"
    calls = []
    def execute(command, **kwargs):
        calls.append(command)
        assert "DOCKER_HOST" not in kwargs["env"]
        assert "META_APP_SECRET" not in kwargs["env"]
        if command == ["docker", "context", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps([{"Endpoints": {"docker": {"Host": endpoint}}}]))
        assert command[:6] == ["docker", "--host", endpoint, "compose", "--env-file", os.devnull]
        assert kwargs["env"]["TEST_LANE"] == "qa"
        return SimpleNamespace(returncode=0)
    monkeypatch.setenv("DOCKER_HOST", "tcp://production.example:2376")
    monkeypatch.setenv("META_APP_SECRET", "live-secret")
    monkeypatch.setattr(runner.subprocess, "run", execute)
    monkeypatch.setattr(sys, "argv", ["v1-test.py", "--lane", "qa", "--pg-port", "55461", "up"])
    assert runner.main() == 0
    assert len(calls) == 2


class LeaseConnection:
    def __init__(self, shared, database="munimjee_test_qa"):
        self.shared, self.database, self.owned = shared, database, False

    async def scalar(self, query, params=None):
        if "current_database" in str(query):
            return self.database
        if self.shared["locked"]:
            return False
        self.shared["locked"] = self.owned = True
        return True

    async def execute(self, query):
        assert self.owned and self.shared["locked"]
        self.shared["events"].append(str(query))


@pytest.mark.asyncio
async def test_same_database_lease_rejects_second_invocation_and_wrong_database():
    from tests.isolated_database import acquire_lease
    shared = {"locked": False}
    await acquire_lease(LeaseConnection(shared), validate_test_database(safe_env()))
    with pytest.raises(TestSafetyError, match="already in use"):
        await acquire_lease(LeaseConnection(shared), validate_test_database(safe_env()))
    with pytest.raises(TestSafetyError, match="does not match"):
        await acquire_lease(LeaseConnection({"locked": False}, "postgres"), validate_test_database(safe_env()))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "migration", "test"])
async def test_lease_spans_reset_migration_yield_and_failure_cleanup(monkeypatch, failure):
    from tests import isolated_database as harness
    for key, value in safe_env().items():
        monkeypatch.setenv(key, value)
    shared = {"locked": False, "events": []}

    class Engine:
        def __init__(self, lease):
            self.lease = lease

        @asynccontextmanager
        async def connect(self):
            connection = LeaseConnection(shared)
            try:
                yield connection
            finally:
                if connection.owned:
                    shared["locked"] = False
                    shared["events"].append("lease_closed")

        async def dispose(self):
            shared["events"].append("lease_disposed" if self.lease else "engine_disposed")

    def engine_factory(*args, **kwargs):
        return Engine("isolation_level" in kwargs)

    async def migration():
        assert shared["locked"]
        shared["events"].append("migration")
        if failure == "migration":
            raise RuntimeError("migration failed")

    monkeypatch.setattr(harness, "create_async_engine", engine_factory)
    monkeypatch.setattr(harness, "migrate", migration)

    async def run():
        async with harness.migrated_database():
            assert shared["locked"]
            shared["events"].append("yield")
            if failure == "test":
                raise RuntimeError("test failed")
    if failure:
        with pytest.raises(RuntimeError):
            await run()
    else:
        await run()
    assert shared["events"][:3] == ["DROP SCHEMA public CASCADE", "CREATE SCHEMA public", "migration"]
    if failure != "migration":
        assert shared["events"].index("yield") < shared["events"].index("engine_disposed") < shared["events"].index("lease_closed")
    assert shared["locked"] is False


@pytest.mark.asyncio
async def test_unsafe_target_never_creates_an_engine(monkeypatch):
    from tests import isolated_database as harness
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(harness, "create_async_engine", lambda *a, **kw: pytest.fail("unsafe engine created"))
    with pytest.raises(TestSafetyError):
        async with harness.migrated_database():
            pytest.fail("unsafe fixture yielded")


@pytest.mark.asyncio
async def test_actual_migrated_schema_and_database_lease(migrated_engine):
    """Real DB gate: alembic version and concurrent lease, never metadata.create_all."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from pathlib import Path
    from sqlalchemy import text
    from tests.isolated_database import acquire_lease

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    heads = set(ScriptDirectory.from_config(config).get_heads())
    async with migrated_engine.connect() as connection:
        versions = set((await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars())
        assert versions == heads
        # The fixture's dedicated PostgreSQL connection holds the real lock.
        with pytest.raises(TestSafetyError, match="already in use"):
            await acquire_lease(connection, validate_test_database(os.environ))


@pytest.mark.asyncio
async def test_reusable_synthetic_tenants_have_distinct_persisted_ids(db_session, two_sellers):
    from sqlalchemy import select
    from app.models.seller import Seller

    first, second = two_sellers
    assert first.id != second.id
    await db_session.commit()
    assert set((await db_session.execute(select(Seller.id))).scalars()) == {first.id, second.id}
