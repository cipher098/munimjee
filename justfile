# sellerbot — common dev commands
# Run `just` to list, `just <name>` to execute.

# --- Production (AWS EC2, ap-south-1) ---
prod_host    := "ubuntu@3.109.60.26"
prod_key     := "~/.ssh/id_ed25519"
prod_dir     := "~/sellerbot"
prod_compose := "docker-compose.prod.yml"
prod_db      := "munimjee"
prod_region  := "ap-south-1"

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

# Bring the stack up AND start the Cloudflare tunnel so app.vouchrs.in is reachable.
# Tunnel runs in the background; logs at ~/cloudflared.log. Ctrl-C does NOT stop it —
# use `just tunnel-down` to kill it.
serve:
    docker compose up -d --build
    @pkill -f "cloudflared tunnel.*sellerbot" 2>/dev/null || true
    @nohup cloudflared tunnel --config ~/.cloudflared/config.yml run sellerbot \
      > ~/cloudflared.log 2>&1 &
    @sleep 1
    @echo ""
    @echo "API:    http://localhost:8000"
    @echo "Public: https://app.vouchrs.in"
    @echo "Tunnel log: ~/cloudflared.log  (tail -f to watch)"

# Stop the Cloudflare tunnel (leaves docker containers running).
tunnel-down:
    @pkill -f "cloudflared tunnel.*sellerbot" && echo "tunnel stopped" \
      || echo "no tunnel process found"

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

# ---------------------------------------------------------------------------
# Production deploy / ops (AWS EC2)
# ---------------------------------------------------------------------------

# Deploy local code to the production box and restart the stack.
# rsyncs backend + prod compose + Caddyfile, then rebuilds & restarts.
# Does NOT apply migrations. If this change includes a migration, run
# `just prod-migrate` FIRST (updates the schema while the old app keeps serving),
# THEN prod-deploy. NEVER syncs .env (prod secrets) or uploads/ (product images).
prod-deploy:
    rsync -az \
      --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
      --exclude '.pytest_cache' --exclude '.env' --exclude 'uploads/' \
      --exclude 'celerybeat-schedule' --exclude 'tests/' \
      -e "ssh -i {{prod_key}}" \
      backend docker-compose.prod.yml Caddyfile \
      {{prod_host}}:{{prod_dir}}/
    ssh -i {{prod_key}} {{prod_host}} \
      'cd {{prod_dir}} && sudo docker compose -f {{prod_compose}} up -d --build'
    @echo ""
    @echo "deployed → https://app.munimjee.in"

# Show prod container status.
prod-ps:
    @ssh -i {{prod_key}} {{prod_host}} \
      'cd {{prod_dir}} && sudo docker compose -f {{prod_compose}} ps'

# Tail prod logs. Optional service, e.g. `just prod-logs worker` (default: all).
prod-logs SERVICE='':
    ssh -i {{prod_key}} {{prod_host}} \
      'cd {{prod_dir}} && sudo docker compose -f {{prod_compose}} logs -f --tail=100 {{SERVICE}}'

# Restart prod services without rebuilding. Optional service, e.g. `just prod-restart api`.
prod-restart SERVICE='':
    ssh -i {{prod_key}} {{prod_host}} \
      'cd {{prod_dir}} && sudo docker compose -f {{prod_compose}} restart {{SERVICE}}'

# Apply migrations to the PROD (RDS) database — run this BEFORE `just prod-deploy`.
# rsyncs code so new migration files reach the box, then runs alembic in a one-off
# container built from the latest code, WITHOUT disturbing the running app (the old
# app keeps serving on the migrated schema until you prod-deploy the new code).
# Safe flow:  just prod-snapshot → just prod-migrate → just prod-deploy
# Pass any alembic args, e.g.
#   just prod-migrate current        (show current revision)
#   just prod-migrate history        (list migrations)
#   just prod-migrate "downgrade -1" (roll back one — quote multi-word args)
prod-migrate ARGS='upgrade head':
    rsync -az \
      --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
      --exclude '.pytest_cache' --exclude '.env' --exclude 'uploads/' \
      --exclude 'celerybeat-schedule' --exclude 'tests/' \
      -e "ssh -i {{prod_key}}" \
      backend docker-compose.prod.yml Caddyfile \
      {{prod_host}}:{{prod_dir}}/
    ssh -i {{prod_key}} {{prod_host}} \
      'cd {{prod_dir}} && sudo docker compose -f {{prod_compose}} run --rm --no-deps --build api alembic {{ARGS}}'

# Preview what `just prod-migrate` WOULD apply — read-only, changes nothing.
# Shows the DB's current revision, the pending migrations (with descriptions),
# and the exact SQL that would run. Run this to be sure BEFORE prod-migrate.
prod-migrate-plan:
    rsync -az \
      --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
      --exclude '.pytest_cache' --exclude '.env' --exclude 'uploads/' \
      --exclude 'celerybeat-schedule' --exclude 'tests/' \
      -e "ssh -i {{prod_key}}" \
      backend docker-compose.prod.yml Caddyfile \
      {{prod_host}}:{{prod_dir}}/
    ssh -i {{prod_key}} {{prod_host}} \
      'cd {{prod_dir}} && \
       cur=$(sudo docker compose -f {{prod_compose}} run --rm --no-deps --build api alembic current 2>/dev/null | grep -oE "^[0-9a-zA-Z_]+" | head -1) && \
       echo "=== current DB revision: $cur ===" && \
       echo "" && echo "=== pending migrations (current -> head) ===" && \
       sudo docker compose -f {{prod_compose}} run --rm --no-deps api alembic history -r "$cur:head" --verbose && \
       echo "" && echo "=== SQL that would be applied ===" && \
       sudo docker compose -f {{prod_compose}} run --rm --no-deps api alembic upgrade "$cur:head" --sql'

# Take a manual RDS snapshot of the prod DB. Run this BEFORE risky migrations.
# Runs from your Mac (AWS CLI admin creds). The snapshot is point-in-time; restore
# later via the RDS console or `aws rds restore-db-instance-from-db-snapshot`.
# Snapshots of this small DB are tiny and fit free-tier backup storage.
prod-snapshot:
    aws rds create-db-snapshot \
      --region {{prod_region}} \
      --db-instance-identifier {{prod_db}} \
      --db-snapshot-identifier "{{prod_db}}-manual-$(date +%Y%m%d-%H%M%S)" \
      --query 'DBSnapshot.{Snapshot:DBSnapshotIdentifier,Status:Status,Engine:Engine}' \
      --output table
    @echo ""
    @echo "Snapshot started (status 'creating' → 'available' in a few min)."
    @echo "List:    aws rds describe-db-snapshots --db-instance-identifier {{prod_db}} --snapshot-type manual --region {{prod_region}} --query 'DBSnapshots[].DBSnapshotIdentifier'"

# Open a shell on the production box.
prod-ssh:
    ssh -i {{prod_key}} {{prod_host}}
