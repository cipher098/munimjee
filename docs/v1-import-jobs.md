# D20 durable import jobs and review

Status: bounded implementation awaiting shared registration and actual migrated
database verification. The package provides real SQLAlchemy models, transactional
services, authenticated-router factory, polling runner, pinned HTTPS transport,
literal website extraction and original-byte upload storage. This is not a
released import flow or a completed V03/V04 feature. The worker makes no publish,
checkout, inventory allocation, Meta consent or source ownership-verification
claim. Tests use synthetic sources and injected transports only.

## Contracts and integration hooks

Base is `7de7cd68ce700e089bcf31e357aeebb08ea08299`; frozen wave2 contracts entered
this branch as `faf2cd0`. Business ID remains legacy Seller UUID. Public input
bodies forbid extra tenant/reviewer/authority fields. Read capability is
`catalogue.read`; every mutation requires current `catalogue.write`. The router
factory has **no mutation-auth fallback**:

```python
from app.api.v1.imports import create_router
from app.api.v1.session import require_v1_mutation
app.include_router(create_router(require_v1_mutation))
```

`current_actor` is the existing shared read dependency. The future shared native
session dependency supplies session validity, cookie Origin/CSRF checks, bearer
handling and current actor identity. This branch neither replaces nor bypasses
that dependency. Import services recheck active user/business/membership/capability
and derive review actors from the authorized context. Staff/viewer do not gain
catalogue.write through an import body. Shared auth dependency must be registered
before these routes are enabled; actual native-session/CSRF composition tests
remain an integrator gate.

After obtaining the tenant lock, and at every subsequent authorization checkpoint,
the owned service selects committed User/Membership/Business/Seller authorization
**scalar columns** with autoflush disabled. It checks active/revoked flags and the
fresh role/account value. This avoids stale ORM identity-map roles, revoked users
or Instagram account IDs without expiring/overwriting unrelated dirty objects.
The shared compatibility check also runs inside a scoped no-autoflush context.
P01-gated two-session lock-wait regressions retain stale ORM instances deliberately
while another session revokes/downgrades/rebinds the account. They are pending
actual DB execution here and do not replace the shared native-session gate.

Register `ImportAsset`, `ImportJob`, `ImportDraft`, `ImportAudit` centrally and
create their additive Alembic migration after the published 0043/0044/0045 chain.
`0046_v1_import_jobs` is a proposal for the integrator, not an assigned/released
revision. This branch creates no competing revision or predecessor. Exact
PostgreSQL table DDL generated from the owned models appears below; create indexes
`ix_v1_import_jobs_business_id`, `ix_v1_import_drafts_business_id` and
`ix_v1_import_audits_business_id`. Upgrade creates assets → jobs → drafts → audits;
downgrade reverses that order only in disposable development schemas. Production
rollback must preserve imported media, review/audit history and new data.

Schedule `app.v1.imports.runner.drain_jobs(sessions)` through an integrator-owned
Celery task/recovery schedule. `sessions.begin()` must yield an AsyncSession and
commit/rollback its short transaction, for example `async_sessionmaker.begin()`.
The HTTP 202 transaction only persists a pending job; **no `.delay()` before
commit**. Until registration/scheduling, a job truthfully remains pending.
Polling recovers missed dispatches and crashed claims without relying on Redis
as the authoritative queue. The runner processes 10 jobs serially by default,
hard maximum 20. A scheduler may invoke `run_job` for one tenant/job directly.

## Seller API

Prefix: `/api/v1/businesses/{business_id}/imports`.

| Method/path | Behavior |
| --- | --- |
| POST `/uploads?idempotency_key=<uuid>&source_authorized=true` | Raw image/jpeg, image/png or video/mp4 request. Authorize before reading; stream at most 5 MB with a 30-second deadline; preserve exact bytes and SHA256. Returns tenant asset ID, type, size and hash. |
| POST `/jobs` | `idempotency_key`, `source_authorized: true`, `source_kind` plus website `source_url`, Instagram `media_id`/optional URL, or uploaded-media `asset_id`. Returns 202 and pending job; never publishes. |
| GET `/jobs` and `/jobs/{job_id}` | Authorized status/revision, attempt count, last stable error code, source and result count. List accepts UUID `after` and `limit` 1–100. |
| POST `/jobs/{job_id}/cancel` | `expected_revision` and `idempotency_key`; pending/running/failed → cancelled. A claim token no longer authorizes late results. |
| POST `/jobs/{job_id}/retry` | Same body; failed jobs below three attempts become pending after persisted backoff of min(5×2^attempts,60) seconds. Revoked authorization/changed account failures require a new valid job. |
| GET `/candidates` | Tenant-wide candidate page with UUID cursor and limit 1–100. Exact source identities dedupe across jobs. |
| POST `/candidates/{candidate_id}/review` | `expected_revision`, `idempotency_key`, `action` edit/approve/reject. Edits carry typed `overrides`; approval explicitly confirms every factual field; rejection requires reason. Actor identity is server supplied. |

Seller `source_authorized: true` is an explicit permission attestation, not DNS
domain-ownership verification or proof of provider account consent. Job provenance
stores authorizing actor/time; current membership is rechecked at claim, after
committed claim before retrieval, and before committing results. Website jobs
fetch **one authorized URL**, including at most three same-host redirects; they
do not crawl a whole domain or automatically follow product/media links.

Uploads validate size, declared MIME and basic signatures. This does not claim
full media decoding, antivirus, thumbnails, transcription or visual extraction.
The exact original bytes remain in tenant-scoped storage; no image enhancement
or garment modification occurs. Media candidates start with unknown facts.
Upload SHA, scoped by business UUID, is the stable media identity: reuploading
identical content with a new asset UUID/key preserves candidate identity and
seller corrections. An asset from another tenant is never an import source.

## Retrieval and source facts

HTTPS/443 only; no supplied cookies, credentials, proxies or caller headers.
Source URL credentials and sensitive query aliases (token, secret, sig, key,
auth, session, code and related names) are rejected before durable persistence.
Query keys left percent-encoded after parsing and more than 32 query fields fail
closed. Errors return stable codes, not raw URLs, HTTP bodies or provider errors.

Each hop resolves a bounded DNS answer set and rejects the entire answer if any
address is private, loopback, link-local, reserved, multicast or ambiguous IPv6
transition/NAT64/scoped addressing. The transport connects directly to the chosen
numeric sockaddr, checks the actual peer, and uses the original hostname for
TLS certificate verification/SNI/Host. It does not resolve that hostname again
while connecting. Every redirect must remain on the seller-authorized hostname
and pass the URL/DNS/address checks afresh. Instagram hosts are refused by the
website path; there is no scraping fallback.

Total async retrieval deadline is 15 seconds. Bodies are capped at 2 MB; only
HTML/application JSON/JSON-LD and identity content encoding are accepted. Gzip and
other encodings are rejected rather than decompressed without an expansion cap.
Blocking body reads enforce a remaining deadline and bounded chunks. A timed-out
blocking operation may finish in its thread, but its result is ignored; global
DNS and HTTP pools each cap four unfinished operations without an unbounded
executor queue, and late exceptions are consumed without logging secrets.
OS DNS calls cannot be forcibly interrupted; their unfinished work retains the
global slot until it really completes.

Website extraction reads only literal schema.org Product JSON/JSON-LD (including
bounded @graph blocks). It validates title/description and exact unambiguous offer
price/currency. Availability strings, captions, images and videos never invent
stock/options. Duplicate JSON keys, normalized duplicate product IDs, missing
stable keys in multi-product blocks and excessive products/complexity fail closed.
A lone Product can use the stable page-product key. Reels/photos may describe
multiple products; caller/provider keys must identify each without list positions.
Imported instruction-like text remains untrusted data and must be escaped by
future UI consumers; nothing executes it as HTML, code, prompt or workflow.

## Connected Instagram gate

Current `InstagramClient` supports oEmbed resolution and shortcode lookup, but no
owned-media retrieval with verifiable owner/account metadata. Jobs require a
currently linked Seller.instagram_page_id and persist that account binding. The
default runner fails safely with `provider_capability_pending`, and account
changes fail with `source_connection_changed`. This is not a successful Instagram
import or a provider-permissions canary.

A future injected adapter must expose async
`fetch_owned_media(business_id, account_id, media_id)`, use the authorized existing
provider credentials internally, and return `account_id`, `media_id`, and a
bounded sequence of `(stable_product_key, DraftFacts)`. The runner bounds that
await to 15 seconds and checks exact account/media ownership. Arbitrary public
URL fetches, unsupported private-media downloads and claimed ownership based only
on a user-entered media ID are forbidden. Official provider field/edge support,
token ownership, actual permissions and current connection transport remain
explicit P03/social integration gates; no production adapter is invented here.

## Durability, review and catalogue boundary

Tenant Business row locks serialize job idempotency and candidate upserts; each
job/draft lookup also includes authorized tenant identity. Lease claims commit
before retrieval; no long database transaction holds network I/O. A claim has a
fresh token, 60-second expiry and bounded attempt count. Cancellation, expiry or
a newer claim fences late results. Lost workers are reclaimed by polling; three
attempts is a hard ceiling. Fetch failures are visible failed jobs with explicit
manual retry/backoff, not infinite provider retry. Cancellation checkpoints stop
new work and drop late results; an already-started bounded HTTPS socket need not
be forcibly interrupted before its deadline.

Draft review and job mutation idempotency are durable, request-hash checked audit
records. Stale revisions return 409; replay of the identical operation returns
its recorded result without another mutation/audit. Exact source/product identity
is checked independently of candidate UUID. Changed extractions invalidate prior
review while preserving seller overrides. Identical extraction preserves prior
approval; a slower older capture is ignored/audited rather than overwriting newer
facts. Extracted before/incoming facts, prior provenance and reviewer actions stay
in append-only application audits. Rejected drafts remain rejected on reimport.

Import approval is a reviewed **import record only** with
`catalogue_bridge_status=pending_reviewed_allocation`. No Product/SKU row is written
or published; no checkout flag changes. The catalogue owner's approved-write seam
is not yet present on this base. Integration must supply reviewed SKU allocation,
canonical draft creation and product/media matching before claiming an approved
import-to-catalogue journey. In particular, draft stock null means unknown;
canonical SKU stock_available null means explicitly untracked. Aggregate stock
cannot be duplicated across variants. This branch never guesses that bridge.

## Verification and remaining gates

Owned synthetic tests exercise actual router dependency enforcement, streamed
upload bounds, SQL tenant/lock shape, strict DTOs, job/review idempotency, leases,
attempt recovery/backoff, authorization cancellation checkpoints, preserved
overrides and fetch/extraction adversarial cases. The existing 110 draft-domain
cases remain covered. Three P01 `migrated_engine` tests exercise real concurrent
job/review behavior and composite tenant constraints **once** the integrator
registers the migration; six further cases exercise cached-authorization races
against the existing identity tables. They skip explicitly without an allocated test DB;
they do not call create_all or replace actual Alembic DDL with mock persistence.

```sh
PYTHONPATH=backend .venv-imports/bin/python -m pytest \
  backend/tests/test_v1_import_jobs.py backend/tests/test_v1_import_jobs_fetch.py \
  backend/tests/test_v1_import_jobs_db.py backend/tests/test_v1_import_drafts.py \
  -q -ra -p no:cacheprovider
```

Current remote environment: Python 3.12.14, Pydantic 2.7.1, SQLAlchemy 2.0.30,
pytest 8.2.0; test harness strips dotenv/provider settings and blocks live sockets.
Docker remains unavailable; no service restart or database fallback was attempted.
Exact tested source/counts/skips are recorded under `artifacts/v1/D20/` after the
implementation commit. Missing gates: actual migrated schema/full-chain evidence,
shared native-session/CSRF integration, worker registration, live provider/source
acceptance, seller UI/browser journey, canonical reviewed allocation/draft bridge,
media decoder/storage operational quotas and rollout. No production action.

## Proposed PostgreSQL DDL

The following is model-generated DDL, not a migration applied to any database.

```sql
CREATE TABLE v1_import_assets (
	id UUID NOT NULL,
	business_id UUID NOT NULL,
	creator_id UUID NOT NULL,
	idempotency_key UUID NOT NULL,
	content_type VARCHAR(32) NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	size_bytes INTEGER NOT NULL,
	content BYTEA NOT NULL,
	authorized_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT v1_import_asset_tenant UNIQUE (business_id, id),
	CONSTRAINT v1_import_asset_idempotency UNIQUE (business_id, idempotency_key),
	CONSTRAINT v1_import_asset_size CHECK (size_bytes > 0 AND size_bytes <= 5000000 AND octet_length(content) = size_bytes),
	CONSTRAINT v1_import_asset_content CHECK (content_type IN ('image/jpeg','image/png','video/mp4') AND sha256 ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE RESTRICT,
	FOREIGN KEY(creator_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE TABLE v1_import_jobs (
	id UUID NOT NULL,
	business_id UUID NOT NULL,
	creator_id UUID NOT NULL,
	idempotency_key UUID NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	source JSONB NOT NULL,
	asset_id UUID,
	state VARCHAR(24) DEFAULT 'pending' NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	attempts INTEGER DEFAULT '0' NOT NULL,
	lease_token UUID,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	candidate_count INTEGER DEFAULT '0' NOT NULL,
	error_code VARCHAR(64),
	authorized_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT v1_import_job_tenant UNIQUE (business_id, id),
	CONSTRAINT v1_import_job_idempotency UNIQUE (business_id, idempotency_key),
	CONSTRAINT v1_import_job_tenant_asset FOREIGN KEY(business_id, asset_id) REFERENCES v1_import_assets (business_id, id),
	CONSTRAINT v1_import_job_state CHECK (state IN ('pending','running','review_required','failed','cancelled')),
	CONSTRAINT v1_import_job_counters CHECK (revision >= 1 AND attempts >= 0 AND attempts <= 3 AND candidate_count >= 0 AND candidate_count <= 200),
	CONSTRAINT v1_import_job_lease CHECK ((state = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (state <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)),
	CONSTRAINT v1_import_job_source CHECK (jsonb_typeof(source) = 'object' AND request_hash ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE RESTRICT,
	FOREIGN KEY(creator_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE TABLE v1_import_drafts (
	id UUID NOT NULL,
	business_id UUID NOT NULL,
	last_job_id UUID NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	document JSONB NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT v1_import_draft_tenant UNIQUE (business_id, id),
	CONSTRAINT v1_import_draft_tenant_job FOREIGN KEY(business_id, last_job_id) REFERENCES v1_import_jobs (business_id, id),
	CONSTRAINT v1_import_draft_document CHECK (revision >= 1 AND jsonb_typeof(document) = 'object'),
	FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE RESTRICT
);

CREATE TABLE v1_import_audits (
	id UUID NOT NULL,
	business_id UUID NOT NULL,
	job_id UUID,
	candidate_id UUID,
	actor_id UUID NOT NULL,
	idempotency_key UUID NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	action VARCHAR(32) NOT NULL,
	details JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT v1_import_audit_idempotency UNIQUE (business_id, idempotency_key),
	CONSTRAINT v1_import_audit_tenant_job FOREIGN KEY(business_id, job_id) REFERENCES v1_import_jobs (business_id, id),
	CONSTRAINT v1_import_audit_tenant_candidate FOREIGN KEY(business_id, candidate_id) REFERENCES v1_import_drafts (business_id, id),
	CONSTRAINT v1_import_audit_details CHECK (jsonb_typeof(details) = 'object' AND request_hash ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE RESTRICT,
	FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE RESTRICT
);

```
