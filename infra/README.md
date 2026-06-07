# Deployment — durable webhook ingress + VPS app

Two hosts, each one backend (Alternative A):

| Host | Backend | TLS | Always-up? |
|---|---|---|---|
| `app.munimjee.in` | VPS (Caddy → FastAPI dashboard) | Caddy / Let's Encrypt | only while VPS is up |
| `hooks.munimjee.in` | API Gateway → Lambda → **SQS** | ACM | yes (managed) |

```
Meta ──▶ hooks.munimjee.in ──▶ API Gateway ──▶ Lambda ──▶ SQS FIFO ──▶ sqs_consumer (VPS)
                                (verify + HMAC + enqueue)                    │
                                                                             ▼
                                                  Redis batch ──▶ Celery ──▶ reply
```

If the VPS is down, events queue in SQS (14-day retention) and drain on recovery — nothing is lost.

## Files

- `infra/lambda/handler.py` — ingress: GET challenge, POST HMAC verify, fan out to SQS.
- `infra/*.tf` — ACM, HTTP API + custom domain, SQS FIFO + DLQ + alarm, Lambda, consumer IAM user.
- `backend/app/workers/sqs_consumer.py` — drains SQS → `_handle_messaging_event`.
- `../docker-compose.prod.yml`, `../Caddyfile` — VPS stack.

## 1. Provision AWS

```bash
cd infra
terraform init
terraform apply \
  -var="meta_verify_token=<your META_VERIFY_TOKEN>" \
  -var="meta_webhook_secret=<your META_WEBHOOK_SECRET>"
```

`apply` will **pause** at the ACM cert until you add the DNS validation record. From `terraform output acm_validation`, add that CNAME at your DNS provider. Apply then continues on its own.

## 2. DNS records (at your DNS provider for `munimjee.in`)

| Host | Type | Value | Source |
|---|---|---|---|
| `_xxx.hooks` | CNAME | `…acm-validations.aws` | `terraform output acm_validation` |
| `hooks` | CNAME | `d-xxxx.execute-api.ap-south-1.amazonaws.com` | `terraform output webhook_cname_target` |
| `app` | A | `<VPS public IP>` | your VPS |

## 3. Configure & deploy the VPS

Add to `backend/.env`:

```
DATABASE_URL=postgresql+asyncpg://...@...neon.tech/db?ssl=require
PUBLIC_BASE_URL=https://app.munimjee.in
AWS_REGION=ap-south-1
SQS_QUEUE_URL=<terraform output sqs_queue_url>
AWS_ACCESS_KEY_ID=<terraform output consumer_access_key_id>
AWS_SECRET_ACCESS_KEY=<terraform output consumer_secret_access_key>   # sensitive
```

Open ports 80 and 443 in the VPS firewall, then:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Caddy issues the `app.munimjee.in` cert automatically once DNS resolves to the box.

## 4. Point Meta at the webhook

Only after the Lambda + custom domain are live (step 1–2 done):

- **Callback URL:** `terraform output webhook_url` → `https://hooks.munimjee.in/webhooks/instagram`
- **Verify token:** your `META_VERIFY_TOKEN`
- Click **Verify and Save** — Meta sends the GET; the Lambda echoes `hub.challenge`.

## Order of operations

1. `terraform apply` → add ACM validation CNAME → apply finishes.
2. Add `hooks` and `app` DNS records.
3. Bring up the VPS stack (`docker compose ... up -d`).
4. Configure Meta callback → verify.

## Verify it works

```bash
# Challenge handshake (expect: echoes 1234)
curl "https://hooks.munimjee.in/webhooks/instagram?hub.mode=subscribe&hub.verify_token=<TOKEN>&hub.challenge=1234"

# Send a real DM to the IG account, then watch the consumer pick it up:
docker compose -f docker-compose.prod.yml logs -f sqs_consumer
```

## Notes / gotchas

- The CloudWatch alarm `sellerbot-webhook-backlog-age` fires if anything sits in the queue > 10 min — your signal that the VPS consumer is down. Attach an SNS action to be notified.
- Keep **exactly one** `beat` and (for ordering) the `sqs_consumer` processes sequential — do not scale them. `api`/`worker` can scale freely.
- Local/dev is unchanged: `SQS_QUEUE_URL` is empty there and the FastAPI `/webhooks/instagram` route still handles events inline.
- DLQ messages = poison events that failed 5×. Inspect with the SQS console; redrive after fixing.
