"""Release-only safety tests. No provider, Docker or real DB calls by default."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import v1_release_rehearsal as rehearsal


def env(**updates):
    return {"REHEARSAL_SOURCE_URL": "postgresql+asyncpg://test:secret_synthetic@127.0.0.1:55461/munimjee_test_release_src",
            "REHEARSAL_TARGET_URL": "postgresql+asyncpg://test:secret_synthetic@127.0.0.1:55461/munimjee_test_release_dst", **updates}


def ownership(tmp_path):
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({"format": "munimjee.release-ownership.v1", "source_lane": "release_src",
        "target_lane": "release_dst", "synthetic_only": True, "allocated": True, "owner": "synthetic-ci-job"}))
    path.chmod(0o600)
    return path


def test_default_plan_does_not_import_db_or_call_process_or_network(monkeypatch, capsys):
    monkeypatch.setattr(rehearsal, "p01", lambda: pytest.fail("plan imported DB harness"))
    monkeypatch.setattr(rehearsal.subprocess, "run", lambda *a, **k: pytest.fail("plan launched a subprocess"))
    monkeypatch.setattr(rehearsal.os, "mkdir", lambda *a, **k: pytest.fail("plan created a directory"))
    assert rehearsal.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "plan"
    assert result["database_effects"] is False
    assert result["container_effects"] is False
    assert result["alembic_head"] == "0050_v1_assistance"


@pytest.mark.parametrize("url", ["", "postgresql://test:test@127.0.0.1:55461/munimjee_test_release_src",
    "postgresql+asyncpg://test:test@localhost:55461/munimjee_test_release_src",
    "postgresql+asyncpg://test:test@production.example:55461/munimjee_test_release_src",
    "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_release_src?host=production.example",
    "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_release_dst",
    "postgresql+asyncpg://test:test@127.0.0.1:55461/munimjee_test_release_src\n"])
def test_p01_source_policy_rejects_before_any_connection(url):
    with pytest.raises(Exception):
        rehearsal.targets("release_src", "release_dst", env(REHEARSAL_SOURCE_URL=url))


def test_both_targets_distinct_and_never_use_runtime_fallback():
    with pytest.raises(Exception):
        rehearsal.targets("release_src", "release_dst", {"DATABASE_URL": env()["REHEARSAL_SOURCE_URL"]})
    with pytest.raises(Exception):
        rehearsal.targets("release_src", "release_src", env(REHEARSAL_TARGET_URL=env()["REHEARSAL_SOURCE_URL"]))
    source, target = rehearsal.targets("release_src", "release_dst", env())
    assert source.database != target.database


@pytest.mark.parametrize("mutation", ["mode", "lane", "allocated", "synthetic", "extra", "symlink"])
def test_attestation_is_private_owned_explicit_and_lane_bound(tmp_path, mutation):
    path = ownership(tmp_path)
    if mutation == "mode":
        path.chmod(0o644)
    elif mutation == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    else:
        value = json.loads(path.read_text())
        value[{"lane": "target_lane", "allocated": "allocated", "synthetic": "synthetic_only", "extra": "unknown"}[mutation]] = False
        path.write_text(json.dumps(value))
    with pytest.raises(Exception):
        rehearsal.ownership(path, *rehearsal.targets("release_src", "release_dst", env()))


def test_private_archive_refuses_symlink_overwrite_and_repository(tmp_path):
    target = tmp_path / "new"
    rehearsal.archive_location(target)
    target.mkdir(mode=0o700)
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.archive_location(target)
    with rehearsal.private_file(target, "synthetic.dump") as stream:
        stream.write(b"synthetic")
    assert (target / "synthetic.dump").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        rehearsal.private_file(target, "synthetic.dump")
    (target / "alias.dump").symlink_to(target / "synthetic.dump")
    with pytest.raises(FileExistsError):
        rehearsal.private_file(target, "alias.dump")
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.archive_location(rehearsal.ROOT / "new-private-output")


def test_child_secrets_are_only_private_environment():
    source, _ = rehearsal.targets("release_src", "release_dst", env())
    child = rehearsal.child_env(source, {"PATH": "/usr/bin", "DATABASE_URL": "production", "PGSERVICE": "production",
                                        "META_APP_SECRET": "provider", "LD_PRELOAD": "/bad"})
    assert child["PGPASSWORD"] == "secret_synthetic"
    assert child["PGHOST"] == "127.0.0.1"
    assert child["PGPASSFILE"] == os.devnull
    assert not {"DATABASE_URL", "PGSERVICE", "META_APP_SECRET", "LD_PRELOAD"} & child.keys()


@pytest.mark.parametrize("version", [b"pg_dump (PostgreSQL) 15.9\n", b"pg_dump (PostgreSQL) 17.0\n", b"anything\n"])
def test_pg16_tools_fail_closed(tmp_path, monkeypatch, version):
    for name in ("pg_dump", "pg_restore"):
        (tmp_path / name).write_text("fixture")
        (tmp_path / name).chmod(0o700)
    monkeypatch.setattr(rehearsal, "command", lambda *a, **k: version)
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.pg_tools(tmp_path, {})


def test_subprocess_is_bounded_and_failure_text_withheld(monkeypatch):
    calls = []
    def failed(argv, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=1, stdout=b"secret rows", stderr=b"postgresql://secret")
    monkeypatch.setattr(rehearsal.subprocess, "run", failed)
    with pytest.raises(rehearsal.RehearsalError) as error:
        rehearsal.command(["pg_dump"], {})
    assert "secret" not in str(error.value)
    assert calls[0]["timeout"] == rehearsal.TIMEOUT
    assert calls[0]["preexec_fn"] is rehearsal.file_limit


def test_cli_refusal_redacts_driver_and_environment_exceptions(monkeypatch, capsys):
    monkeypatch.setattr(rehearsal, "repo_head", lambda: rehearsal.SUPPORTED_HEAD)
    async def failed(*args):
        raise RuntimeError("postgresql://secret:password@production/private rowdata")
    monkeypatch.setattr(rehearsal, "run", failed)
    assert rehearsal.main(["execute", "--source-lane", "release_src", "--target-lane", "release_dst",
        "--attestation", "/private/ownership.json", "--archive-dir", "/private/archive", "--pg-bin", "/tools"]) == 1
    output = capsys.readouterr()
    assert "password" not in output.err and "rowdata" not in output.err and "postgresql" not in output.err


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 10])
async def test_nonempty_target_refused(count, monkeypatch):
    async def result(*args):
        return SimpleNamespace(scalar_one=lambda: count)
    monkeypatch.setattr(rehearsal, "query", result)
    with pytest.raises(rehearsal.RehearsalError, match="empty"):
        await rehearsal.empty_database(object())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["target_busy", "migration", "restore"])
async def test_both_p01_leases_span_mutations_and_failure_unwinds_owned_connections(tmp_path, monkeypatch, failure):
    import v1_release_synthetic as synthetic
    events, held = [], set()
    class Connection:
        def __init__(self, lane): self.lane = lane
        async def commit(self): pass
        @asynccontextmanager
        async def begin(self): yield self
    class Engine:
        def __init__(self, lane): self.lane = lane
        @asynccontextmanager
        async def connect(self):
            try: yield Connection(self.lane)
            finally:
                held.discard(self.lane)
                events.append("close:" + self.lane)
        async def dispose(self): events.append("dispose:" + self.lane)
    async def lease(connection, database):
        if failure == "target_busy" and database.lane == "release_dst":
            raise rehearsal.RehearsalError("busy")
        held.add(database.lane)
    validate, _ = rehearsal.p01()
    monkeypatch.setattr(rehearsal, "p01", lambda: (validate, lease))
    from sqlalchemy.ext import asyncio as sa
    monkeypatch.setattr(sa, "create_async_engine", lambda url, **k: Engine("release_src" if "release_src" in url else "release_dst"))
    async def noop(*a): pass
    monkeypatch.setattr(rehearsal, "pg16", noop)
    monkeypatch.setattr(rehearsal, "empty_database", noop)
    async def query(*a): return SimpleNamespace(scalar_one=lambda: "00000001-00000002-1")
    monkeypatch.setattr(rehearsal, "query", query)
    async def baseline(*a): return {"totals": {"orders": 2}}
    monkeypatch.setattr(rehearsal, "snapshot", baseline)
    monkeypatch.setattr(synthetic, "seed", noop)
    monkeypatch.setattr(synthetic, "validate_fixture", noop)
    monkeypatch.setattr(rehearsal, "pg_tools", lambda *a: {"pg_dump": "pg_dump", "pg_restore": "pg_restore"})
    def command(argv, *a, **kwargs):
        assert held == {"release_src", "release_dst"}
        events.append(argv[0] if "tests.migrate_test_database" not in argv else "migration")
        if failure == "migration": raise rehearsal.RehearsalError("migration")
        if argv[0] == "pg_dump":
            kwargs["stdout"].write(b"synthetic dump")
        if argv[0] == "pg_restore":
            assert "--create" not in argv and "--clean" not in argv
            assert not any("secret" in item or "://" in item for item in argv)
            raise rehearsal.RehearsalError("restore")
    monkeypatch.setattr(rehearsal, "command", command)
    args = SimpleNamespace(source_lane="release_src", target_lane="release_dst", attestation=ownership(tmp_path),
                           archive_dir=tmp_path / "archive", pg_bin=tmp_path)
    with pytest.raises(rehearsal.RehearsalError):
        await rehearsal.run(args, env())
    assert not held
    assert "close:release_src" in events and "close:release_dst" in events
    if failure == "target_busy": assert "migration" not in events
    if failure == "restore": assert events.index("pg_dump") < events.index("pg_restore") < events.index("close:release_src")


@pytest.mark.skipif(os.environ.get("REHEARSAL_ACCEPTANCE") != "1", reason="Actual PG16 restore acceptance requires two explicitly allocated empty lanes")
def test_actual_pg16_backup_restore_and_newer_order_preservation():
    """No mocks: caller provisions the two empty DBs; never creates or cleans DBs."""
    source_lane = os.environ["REHEARSAL_SOURCE_LANE"]
    target_lane = os.environ["REHEARSAL_TARGET_LANE"]
    args = SimpleNamespace(source_lane=source_lane, target_lane=target_lane,
        attestation=Path(os.environ["REHEARSAL_ATTESTATION"]), archive_dir=Path(os.environ["REHEARSAL_ARCHIVE_DIR"]),
        pg_bin=Path(os.environ["REHEARSAL_PG_BIN"]))
    result = __import__("asyncio").run(rehearsal.run(args, dict(os.environ)))
    assert result["restore"] == "passed"
    assert result["reconciliation"]["totals"]["orders"] == 2
    assert result["post_cutover_reconciliation"]["totals"]["orders"] == 3
    assert result["application_switch"].startswith("pending")
