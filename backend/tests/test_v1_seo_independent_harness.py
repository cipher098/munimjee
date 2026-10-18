"""Pure environment/spawn proofs; no DB, server, Node or socket is executed."""
from contextlib import asynccontextmanager

import pytest

from tests import run_v1_seo_independent_mounted as runner


def synthetic_environment():
    return {"PATH": "/synthetic/bin", "HOME": "/synthetic/home", "TMPDIR": "/synthetic/tmp",
            "TEMP": "/synthetic/temp", "TMP": "/synthetic/tmp", "LANG": "C.UTF-8",
            "LC_ALL": "C", "LC_CTYPE": "C", "MUNIMJEE_SEO_QA_PORT": "4399",
            "TEST_DATABASE_URL": "postgresql+asyncpg://fake:fake@127.0.0.1:1/munimjee_test_fake",
            "DATABASE_URL": "synthetic-db-secret", "TEST_LANE": "fake", "TEST_DB_RESET": "1",
            "SECRET_KEY": "synthetic-secret", "META_VERIFY_TOKEN": "synthetic-meta-secret",
            "ANTHROPIC_API_KEY": "synthetic-provider-secret", "AWS_SECRET_ACCESS_KEY": "synthetic-aws-secret",
            "NODE_OPTIONS": "--require=/synthetic/injected.js", "NODE_PATH": "/synthetic/injected",
            "LD_PRELOAD": "/synthetic/injected.so", "DYLD_INSERT_LIBRARIES": "/synthetic/injected.dylib",
            "HTTP_PROXY": "https://proxy.example.test"}


def expected_environment():
    return {key: value for key, value in synthetic_environment().items() if key in (
        "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE", "MUNIMJEE_SEO_QA_PORT")}


def test_probe_environment_discards_credentials_and_node_injection_without_mutating_source():
    source = synthetic_environment()
    original = dict(source)
    result = runner.probe_environment(source)
    assert result == expected_environment()
    assert source == original
    assert result is not source


@pytest.mark.asyncio
async def test_actual_runner_spawn_boundary_passes_only_filtered_environment_to_node(monkeypatch, tmp_path):
    events = []
    spawned = []
    monkeypatch.setattr(runner, "_port", "4399")
    monkeypatch.setattr(runner.os, "environ", synthetic_environment())
    monkeypatch.setattr(runner, "__file__", str(tmp_path / "backend/tests/runner.py"))
    monkeypatch.setattr(runner, "source_manifest", lambda root: {"synthetic": "pure fake manifest"})
    monkeypatch.setattr(runner, "validate_test_database", lambda source: events.append("validated"))

    @asynccontextmanager
    async def fake_lease():
        events.append("lease-open")
        yield
        events.append("lease-close")
    monkeypatch.setattr(runner, "migrated_database", fake_lease)

    class FakeOutput:
        async def readline(self):
            events.append("owned-bind-marker")
            return b"SEO_QA_BOUND\n"

    class FakeProcess:
        def __init__(self, name):
            self.name = name
            self.returncode = None
            self.stdout = FakeOutput()
        async def wait(self):
            events.append(self.name + "-wait")
            self.returncode = 0
            return 0
        def terminate(self):
            events.append(self.name + "-terminate")
            self.returncode = 0

    async def fake_spawn(*args, **kwargs):
        name = "node" if args[0] == "node" else "server"
        events.append(name + "-spawn")
        spawned.append((name, dict(kwargs["env"])))
        return FakeProcess(name)
    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_spawn)

    await runner.main()

    assert events == ["validated", "lease-open", "server-spawn", "owned-bind-marker",
                      "node-spawn", "node-wait", "server-terminate", "server-wait", "lease-close"]
    server_env, node_env = spawned[0][1], spawned[1][1]
    assert server_env["TEST_DATABASE_URL"] == synthetic_environment()["TEST_DATABASE_URL"]
    assert node_env == expected_environment()
