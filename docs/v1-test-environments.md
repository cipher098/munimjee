# V1 isolated test harness

P01/F10 harness implementation, based on application baseline `e7694ff`.
This is test infrastructure, not evidence that all V1 acceptance flows pass.

## Pure tests

Use Python 3.12 and install `backend/requirements.txt` in a worktree-local
`.venv`. No application `.env`, DB credentials, Docker or provider keys are
required to collect the suite or execute pure tests:

```sh
cd backend
../.venv/bin/python -m pytest tests/test_test_safety.py -q -ra
../.venv/bin/python -m pytest tests -q -ra
```

With no `TEST_DATABASE_URL`, DB fixtures explicitly skip and remain pending.
An explicit unsafe URL or missing reset opt-in fails before any connection.
The full suite includes cassette cases that can skip when replay data is absent.
Skips do not satisfy DB/provider release gates.

## Disposable PostgreSQL lane

Assign a different lane name **and port** for every concurrent worktree. Lane
names match `[a-z][a-z0-9_]{0,23}`. Do not reuse another owner's database, even
on the same host. Examples from the repository root:

```sh
.venv/bin/python scripts/v1-test.py --lane qa --pg-port 55461 up
.venv/bin/python scripts/v1-test.py --lane qa --pg-port 55461 --allow-reset test
.venv/bin/python scripts/v1-test.py --lane qa --pg-port 55461 down
```

`up` creates only a project-scoped PostgreSQL 16 container/network with temporary
storage and a loopback port. `down` removes that named project; it does not use
the development Compose files. Containers have a 512 MiB memory and 1 CPU limit.
There is no persistent volume, production network or application bind mount.
The runner passes `--env-file /dev/null` and a sanitized environment to Compose.
Before `up` or `down`, it inspects Docker context metadata with a five-second
timeout, refuses TCP/SSH/ambiguous endpoints, and pins Compose to the verified
local Unix socket. It does not query the daemon during that safety check.
It never restarts Docker or any shared service. Disposable data disappears when
the container is stopped/recreated.

For an already provisioned independently disposable Postgres instance, set only
explicit test configuration before invoking pytest:

```sh
cd backend
TEST_LANE=qa TEST_DB_RESET=1 \
TEST_DATABASE_URL=postgresql+asyncpg://munimjee_test:local_test_only@127.0.0.1:55461/munimjee_test_qa \
../.venv/bin/python -m pytest tests -q -ra
```

The database must already exist. No fixture creates a database or connects to
an admin database. Only `postgresql+asyncpg`, literal `127.0.0.1` or `[::1]`, an
explicit port, simple disposable credentials, and exactly
`munimjee_test_<TEST_LANE>` are accepted. DNS names (including `localhost`),
query parameters, fragments, escapes in authority/path and multi-host URLs are
rejected. This narrow URL grammar is intentional; do not loosen it to reuse a
development database. Runtime `DATABASE_URL` is never a source for a test target.

Every DB fixture uses the same guarded path. Before the only destructive SQL,
it validates the URL/opt-in, checks `current_database()`, and acquires a
nonblocking PostgreSQL advisory lease. The lease connection stays open through
schema reset, actual `alembic upgrade head` in a sanitized subprocess, every
yielded test session, and engine disposal. A second invocation targeting the same
DB fails without reset. Xdist DB workers are rejected; use separate lane
processes instead. The migration entry module is private to the leased harness;
invoking it directly only upgrades a validated disposable DB and is not a reset
or test command. All migrations run unchanged; migration failures are real
failures to report to their owners, not permission to recreate ORM tables.

## Side effects and isolation boundaries

- Pytest sanitizes inherited settings before collection imports the app, supplies
  only test placeholders, and disables both reading and applying dotenv files.
  A missing test URL gives runtime DB access a closed-port sentinel, never the
  developer's configured database.
- Real TCP/DNS and Unix-socket connections are blocked, except the one explicitly
  validated PostgreSQL endpoint. Provider transports must be faked or replayed;
  socketpair creation for asyncio internals is unaffected.
- VCR remains strict replay (`record_mode=none`). `VCR_RECORD=1` (or any recording
  mode) is rejected. Recording requires separate explicit owner authorization
  and an intentionally separate workflow; this harness has no recording switch.
- App modules importing `app.paths.UPLOAD_DIR` receive a per-pytest-invocation
  temporary upload directory. It is cleaned up at session finish.
- Redis is deliberately unreachable (`127.0.0.1:1`), and real worker enqueueing
  cannot reach a shared broker. Redis instances/namespaces, live worker queues,
  app HTTP ports, browser sessions, and standalone application upload paths are
  **not** provisioned or exercised by this pytest harness. Their independent
  runtime isolation remains a P01 gate before starting those processes.
- The socket guard is a cooperative Python test guard, not an OS sandbox for
  arbitrary subprocess binaries. Do not run real worker/provider CLIs from tests.

## Verification status

The owning Mac mini has Python 3.12 but Docker daemon queries time out. No Docker
restart, shared-service change or local DB reset is authorized by this document.
Pure adversarial safety tests and the suite without DB credentials can run here;
actual PostgreSQL migration/fixture checks remain a separate host/CI gate. The
coordinator's existing isolated PostgreSQL 15 can verify compatibility; CI runs
PostgreSQL 16. Record exact SHA, commands, counts, skips and failures in
`artifacts/v1/P01/<run-id>/` before claiming a DB gate passes.

Local verification on 17 October 2026, branch `codex/v1-test-isolation`, Python
3.12.14, with no DB credentials:

- `python -m pytest tests/test_test_safety.py -q -ra`: 78 passed, 2 DB gates skipped.
- `python -m pytest tests -q`: 361 passed, 173 skipped (172 DB-dependent and one
  missing historical cassette). Two existing deprecation warnings; no failures.
- The safety checks include synthetic VCR replay with a real HTTP client under
  the socket guard, adversarial URLs, disabled dotenv file reads, reset lease
  lifetime/failure cleanup, and refusal of remote Docker contexts before mutation.
