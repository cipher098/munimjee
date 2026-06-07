# Deployment

Production runbook for SellerBot. Day-to-day ops use the `just prod-*` recipes;
one-time AWS provisioning lives in [`infra/README.md`](infra/README.md).

## Architecture

```
Customer DM
   │
   ▼
Meta ──▶ hooks.munimjee.in ──▶ API Gateway ──▶ Lambda ──▶ SQS FIFO ──┐  (durable ingress,
         (ACM cert)            (HTTP API)     (verify+enqueue)        │   off the app box)
                                                                      ▼
                                              EC2 box ── sqs_consumer ─▶ Redis batch ─▶ Celery worker ─▶ Gemini ─▶ reply
                                                 │
                              app.munimjee.in ──▶ Caddy ──▶ FastAPI (dashboard + /uploads images)
                                                 │
                                                 └──▶ RDS PostgreSQL (data)
```

If the EC2 box is down, webhook events queue in SQS (14-day retention) and drain
when it returns — nothing is lost.

## Production facts

| Thing | Value |
|---|---|
| AWS account / region | `242344399431` / `ap-south-1` |
| EC2 app box | `ubuntu@3.109.60.26` (SSH key `~/.ssh/id_ed25519`) |
| App dir on box | `~/sellerbot`, runs `docker-compose.prod.yml` |
| Dashboard | `https://app.munimjee.in` (Caddy / Let's Encrypt) |
| Webhook URL (Meta callback) | `https://hooks.munimjee.in/webhooks/instagram` (ACM cert) |
| Database | RDS PostgreSQL `munimjee.ctu4qwo0s7s8.ap-south-1.rds.amazonaws.com` (db `postgres`) |
| Webhook queue | SQS FIFO `sellerbot-webhook.fifo` (+ DLQ + backlog CloudWatch alarm) |
| DNS | GoDaddy (`app` A-record, `hooks` CNAME, `_…hooks` ACM-validation CNAME) |
| Deployed branch | `deployment` (alembic head `0027`) — see Caveats |
| Billing alert | AWS Budget `sellerbot-monthly-cost` ($10/mo → saurabhgothi@gmail.com) |

## Containers (on the box)

`api` · `worker` (Celery) · `beat` (scheduler) · `sqs_consumer` · `redis` · `caddy`.
Migrations are **not** run on api startup — they are applied deliberately (see below).

## Day-to-day commands

All run from the repo root (need `just`, `ssh`, `rsync`; AWS CLI for snapshots).

| Command | Purpose |
|---|---|
| `just prod-deploy` | rsync code + rebuild + restart (no migrations) |
| `just prod-ps` | container status |
| `just prod-logs [service]` | tail logs (e.g. `just prod-logs worker`) |
| `just prod-restart [service]` | restart without rebuild |
| `just prod-migrate-plan` | **preview** pending migrations + SQL (read-only) |
| `just prod-migrate [args]` | apply migrations to RDS (`current`, `history`, …) |
| `just prod-snapshot` | timestamped RDS backup |
| `just prod-ssh` | shell onto the box |

`prod-deploy` and `prod-migrate` never sync `.env` (prod secrets live only on the
box) or `uploads/` (product images in the `sellerbot_uploads_data` volume).

## Deploy workflows

### Code-only change (no migration)

```
just prod-deploy
```

### Change that includes a migration

Apply the schema **first** (old app keeps serving on the new schema), then ship code:

```
just prod-snapshot        # 1. backup
just prod-migrate-plan    # 2. preview — review the SQL before touching anything
just prod-migrate         # 3. apply migrations to RDS (one-off container; live app untouched)
just prod-deploy          # 4. ship the new code that uses the new schema
```

`prod-migrate-plan` / `prod-migrate` rsync the latest migration files to the box and
run alembic in a throwaway container, so the schema updates without restarting the
live app. In `prod-migrate-plan`, the **SQL block is the ground truth** — an empty
`BEGIN; … COMMIT;` means nothing pending; otherwise it prints the exact DDL.

This assumes the usual expand-then-contract discipline: migrations the currently
running (old) code can tolerate during the brief window before `prod-deploy`. For a
breaking change, the `prod-snapshot` is your rollback (restore via RDS console or
`aws rds restore-db-instance-from-db-snapshot`).

## Verifying / debugging

```
# webhook ingress (challenge handshake):
curl "https://hooks.munimjee.in/webhooks/instagram?hub.mode=subscribe&hub.verify_token=<META_VERIFY_TOKEN>&hub.challenge=ping"
# dashboard health:
curl -I https://app.munimjee.in/health
# watch a live DM flow through:
just prod-logs            # or: just prod-logs worker
# Lambda ingress logs:
aws logs tail /aws/lambda/sellerbot-webhook-ingress --since 15m --region ap-south-1
```

## Caveats

- **Deployed branch is `deployment` (schema 0027), not the latest `v0` (0029).** `v0`
  adds persistent conversations + multi-product/bundle orders. Deploying `v0` requires
  migrating to `0029` and re-checking data. Only **seller + product data** was migrated
  from local (conversations were intentionally skipped — that's why 0027 was safe).
- **Product images are on the box volume, not S3.** The code has no S3 integration. A
  shared object store (S3) becomes necessary when scaling past one box (the volume isn't
  shared between boxes).
- **Don't deploy the local `agents.yaml` Opus override.** Keep it on Gemini routing
  before `prod-deploy`, or prod will point at Opus.
- **Free tier / credits:** EC2 + RDS are free-tier (12 mo) / covered by ~$100 credits.
  Check **Billing → Credits** occasionally for balance + expiry (no metric exists for it).

## One-time provisioning

The AWS infra (SQS, Lambda, API Gateway, ACM, custom domain) is Terraform in `infra/`.
To rebuild from scratch or onto a new account, follow [`infra/README.md`](infra/README.md):
Terraform apply → DNS records → EC2 (Docker + swap + clone) → `.env` → `docker compose up`.
