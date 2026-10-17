"""Fail-closed test policy. This module deliberately has no application imports.

Test credentials must be simple disposable credentials, not URL-encoded secrets.
Only a numeric loopback address and an exact per-lane database name are accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import socket
from typing import Mapping


class TestSafetyError(RuntimeError):
    __test__ = False


@dataclass(frozen=True)
class TestDatabase:
    __test__ = False
    url: str
    lane: str
    database: str
    host: str
    port: int


_LANE = re.compile(r"[a-z][a-z0-9_]{0,23}", re.ASCII)
_URL = re.compile(
    r"postgresql\+asyncpg://[A-Za-z0-9_-]+:[A-Za-z0-9_-]+@"
    r"(?P<host>127\.0\.0\.1|\[::1\]):(?P<port>[1-9][0-9]{0,4})/"
    r"(?P<database>[a-z][a-z0-9_]{0,62})",
    re.ASCII,
)


def validate_test_database(env: Mapping[str, str]) -> TestDatabase:
    """Validate before *connecting*, and again immediately before resetting.

    No URL parsing normalization is allowed: queries (including asyncpg host
    overrides), escapes, fragments, Unix sockets, multi-host URLs and DNS names
    all fail the literal grammar. Error messages never echo credentials.
    """
    if env.get("TEST_DB_RESET") != "1":
        raise TestSafetyError("Destructive tests require explicit TEST_DB_RESET=1")
    lane = env.get("TEST_LANE", "")
    if not _LANE.fullmatch(lane):
        raise TestSafetyError("TEST_LANE must match [a-z][a-z0-9_]{0,23}")
    if env.get("PYTEST_XDIST_WORKER", "master") != "master":
        raise TestSafetyError("DB fixtures forbid xdist workers; use separate lane processes")
    match = _URL.fullmatch(env.get("TEST_DATABASE_URL", ""))
    if not match or int(match["port"]) > 65535:
        raise TestSafetyError("TEST_DATABASE_URL requires a literal loopback asyncpg URL without escapes/options")
    database = "munimjee_test_" + lane
    if match["database"] != database:
        raise TestSafetyError("Test database must be exactly munimjee_test_<TEST_LANE>")
    return TestDatabase(
        env["TEST_DATABASE_URL"], lane, database, match["host"].strip("[]"), int(match["port"])
    )


def sanitized_test_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Allowlist the process environment; never inherit app/provider settings."""
    if source.get("VCR_RECORD", "0") not in ("", "0"):
        raise TestSafetyError("Cassette recording is forbidden in the isolated harness")
    allowed = {
        "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE",
        "SYSTEMROOT", "VIRTUAL_ENV", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER",
        "TEST_DATABASE_URL", "TEST_DB_RESET", "TEST_LANE",
    }
    env = {key: value for key, value in source.items() if key in allowed}
    target = validate_test_database(env) if env.get("TEST_DATABASE_URL") else None
    env.update({
        "APP_ENV": "test",
        "DATABASE_URL": target.url if target else
            "postgresql+asyncpg://unused:unused@127.0.0.1:1/munimjee_test_disabled",
        "SECRET_KEY": "isolated-tests-only-never-a-production-secret",
        "META_VERIFY_TOKEN": "isolated-tests-only",
        "ANTHROPIC_API_KEY": "sk-ant-replay-only-not-a-real-key",
        # No Redis connections or shared worker queues in the pytest harness.
        "REDIS_URL": "redis://127.0.0.1:1/0",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "AWS_CONFIG_FILE": os.devnull,
        "VCR_RECORD": "0",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    })
    return env


def require_allowed_socket(address, target: TestDatabase | None) -> None:
    """The only permitted TCP endpoint is the explicitly validated test DB."""
    if isinstance(address, tuple) and target and len(address) >= 2 and address[0] == target.host and address[1] == target.port:
        return
    raise TestSafetyError("Real outbound networking is blocked; use a fake transport or cassette replay")


_installed = False


def install_test_safety() -> None:
    """Call before importing app.config, app.database or any provider client."""
    global _installed
    if _installed:
        return
    import sys
    if "app.config" in sys.modules or "app.database" in sys.modules:
        raise TestSafetyError("Test safety must load before application configuration")
    safe_env = sanitized_test_environment(os.environ)
    target = validate_test_database(safe_env) if safe_env.get("TEST_DATABASE_URL") else None
    os.environ.clear()
    os.environ.update(safe_env)

    # Settings.Config.env_file is '.env'. Disable that source before Settings()
    # is constructed, including later Settings(_env_file=...) calls in tests.
    from pydantic_settings.sources import DotEnvSettingsSource
    DotEnvSettingsSource._read_env_files = lambda self: {}
    DotEnvSettingsSource.__call__ = lambda self: {}

    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo

    def guarded_connect(sock, address):
        require_allowed_socket(address, target)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        require_allowed_socket(address, target)
        return connect_ex(sock, address)

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        require_allowed_socket((host, int(port) if str(port).isdigit() else port), target)
        return getaddrinfo(host, port, *args, **kwargs)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.getaddrinfo = guarded_getaddrinfo
    _installed = True
