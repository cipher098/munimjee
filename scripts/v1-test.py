#!/usr/bin/env python3
"""Run an independently named disposable DB lane without loading any .env file."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from tests.safety import TestSafetyError, sanitized_test_environment, validate_test_database


def local_docker_endpoint(env):
    """Read context metadata only, then pin Compose to that local socket."""
    try:
        result = subprocess.run(
            ["docker", "context", "inspect"], env=env, capture_output=True, text=True, timeout=5,
        )
        if result.returncode:
            raise TestSafetyError("Cannot inspect the local Docker context")
        contexts = json.loads(result.stdout)
        if len(contexts) != 1:
            raise TestSafetyError("Expected exactly one Docker context")
        endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "unix" or parsed.netloc or not parsed.path.startswith("/")
                or parsed.query or parsed.fragment or "%" in endpoint
                or endpoint != "unix://" + parsed.path):
            raise TestSafetyError("Docker context must use a local Unix socket; refusing remote Docker action")
        return endpoint
    except (KeyError, TypeError, ValueError, subprocess.TimeoutExpired) as error:
        raise TestSafetyError("Cannot verify a local Unix-socket Docker context") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", required=True, help="Unique lane, e.g. qa or catalogue")
    parser.add_argument("--pg-port", type=int, required=True, help="Unique numeric loopback port")
    parser.add_argument("--allow-reset", action="store_true", help="Explicitly permit disposable schema resets")
    parser.add_argument("action", choices=["up", "test", "down"])
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == "test" and not args.allow_reset:
        parser.error("test requires --allow-reset; it drops only the validated lane's public schema")
    if os.environ.get("VCR_RECORD", "0") not in ("", "0"):
        parser.error("VCR_RECORD is forbidden; this harness only replays cassettes")
    env = sanitized_test_environment({
        **os.environ,
        "TEST_LANE": args.lane,
        "TEST_DATABASE_URL": f"postgresql+asyncpg://munimjee_test:local_test_only@127.0.0.1:{args.pg_port}/munimjee_test_{args.lane}",
        "TEST_DB_RESET": "1",
    })
    validate_test_database(env)
    env["TEST_PG_PORT"] = str(args.pg_port)
    if args.action == "test":
        extra = args.pytest_args
        if extra and extra[0] == "--":
            extra = extra[1:]
        command = [sys.executable, "-m", "pytest"] + (extra or ["tests", "-q", "-ra"])
    else:
        endpoint = local_docker_endpoint(env)
        compose = [
            "docker", "--host", endpoint, "compose", "--env-file", os.devnull,
            "--project-name", "munimjee-test-" + args.lane.replace("_", "-"),
            "-f", str(ROOT / "docker-compose.v1-test.yml"),
        ]
        command = compose + (["up", "-d", "--wait", "--wait-timeout", "45"] if args.action == "up"
                             else ["down", "--timeout", "5"])
    try:
        result = subprocess.run(command, cwd=ROOT / "backend", env=env, timeout=60 if args.action != "test" else None)
    except subprocess.TimeoutExpired:
        print("Disposable Docker lane operation timed out; no shared services were restarted.", file=sys.stderr)
        return 1
    return result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TestSafetyError as error:
        raise SystemExit(str(error))
