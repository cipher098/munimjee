# sellerbot — common dev commands
# Run `just` to list, `just <name>` to execute.

# Default: list available commands.
default:
    @just --list

# Bring the whole stack up (api, worker, beat, postgres, redis) in the background.
up:
    docker compose up -d --build
    @echo ""
    @echo "API:      http://localhost:8000"
    @echo "Postgres: localhost:5433"
    @echo "Redis:    localhost:6379"

# Stop and remove all containers (keeps volumes/data).
down:
    docker compose down

# Stop + remove containers AND volumes (destroys local data — be sure).
nuke:
    docker compose down -v

# Tail logs from all services (Ctrl-C to exit).
logs:
    docker compose logs -f --tail=100

# Tail just the API service.
logs-api:
    docker compose logs -f --tail=100 api

# Rebuild the image (run after editing requirements.txt or Dockerfile).
rebuild:
    docker compose build --no-cache api

# Run the pytest suite inside the api container (replay mode, no API key needed).
test:
    docker compose run --rm api pytest tests/ -v

# Run the scenario regression tests (YAML-driven, cassette-backed).
# Scenarios without cassettes skip cleanly — record them with `just test-scenarios-record`.
test-scenarios:
    docker compose run --rm api pytest tests/test_scenarios.py -v

# Record / re-record VCR cassettes for every scenario. Needs ANTHROPIC_API_KEY in backend/.env.
# Re-run plain `just test-scenarios` afterward to confirm the recorded cassettes replay green.
test-scenarios-record:
    docker compose run --rm -e VCR_RECORD=1 api pytest tests/test_scenarios.py -v

# Export a real conversation from the DB as a scenario YAML stub.
# Usage: just capture-scenario <conversation_uuid>
capture-scenario CONVO_ID:
    docker compose run --rm api python -m app.scripts.capture_scenario {{CONVO_ID}}

# Run a single test file or pattern, e.g. `just test-one tests/test_claude_decide.py::test_split_decision_prompt_extracts_static_and_dynamic_parts`
test-one TARGET:
    docker compose run --rm api pytest {{TARGET}} -v

# Record VCR cassettes against the real Anthropic API.
# Requires ANTHROPIC_API_KEY in backend/.env (the api container loads it via env_file).
# Cassettes land in backend/tests/cassettes/ (mounted volume — visible on host).
test-record:
    docker compose run --rm -e VCR_RECORD=1 api pytest tests/ -v

# Open a shell inside the api container for ad-hoc poking.
shell:
    docker compose run --rm api bash

# Run alembic migrations against the running postgres.
migrate:
    docker compose run --rm api alembic upgrade head

# Show the cache-hit log lines after running traffic. Useful to verify #6 is working.
# After hitting the bot a few times, run this — look for read=N where N>0.
# Claude calls happen inside celery, so we look at the worker logs (api too,
# in case anything ever calls Claude directly from the request path).
cache-hits:
    @docker compose logs --tail=400 worker api 2>&1 | grep -E "Claude cache" \
      || echo "No cache hits logged yet — send a couple of messages first."
