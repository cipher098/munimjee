# D10 import drafts: first domain slice

Status: proposed draft contract, verified with synthetic fixtures only. This is
not an integrated importer, approved catalogue writer, published product feature
or completed V03/V04 workflow. Base: `e7694ff`. The accepted business seam is
`business_id == Seller.id`; see `go-live-plan.md` and the integration branch's
`docs/v1-contract-decisions.md`.

## Boundary

`backend/app/v1/imports` parses seller-supplied **structured data** for websites,
Instagram media, uploaded media and CSV-derived rows. A CSV row is already
structured input here; this package does not parse CSV files. It does not fetch
URLs, scrape Instagram, inspect images/video, execute imported text, use an LLM,
load application settings, connect to a database or publish anything. Extraction
means validating explicitly supplied fields, not inferring facts from captions.

Future source adapters must establish source ownership, provider authorization,
permitted access, MIME/size restrictions and durable job/retry/cancellation
behavior. URL checks here reject common unsafe references, but do not perform
DNS resolution or redirect checks and are **not a safe-fetch implementation**.
Any future fetcher needs separate SSRF defenses at every redirect and connection.

All application callers must derive `business_id` and reviewer identity from
authorized context and check role/membership. The internal provenance includes
the business UUID to validate imported data against that context. A future API
must not accept tenant identity or review actor identity as client-controlled
authorization. Imported descriptions/evidence remain untrusted text: consumers
must escape them and must never treat them as prompts, HTML or instructions.

## Proposed input

```json
{
  "provenance": {
    "business_id": "00000000-0000-0000-0000-000000000001",
    "import_job_id": "00000000-0000-0000-0000-000000000004",
    "captured_at": "2026-10-17T12:00:00Z",
    "source": {
      "kind": "instagram",
      "media_id": "12345",
      "url": "https://www.instagram.com/reel/example/"
    },
    "source_product_id": "seller-reviewed-item-a",
    "evidence": "Seller supplied fields for the first product in this reel."
  },
  "facts": {
    "title": "Silk dress",
    "description": null,
    "price": null,
    "stock": null,
    "options": null
  },
  "seller_product_ref": "DRESS-01"
}
```

Unknown facts stay `null`. Missing/unknown stock is never zero; unknown options
are never an empty list. Explicit `options: []` means the seller has confirmed
there are no options. Price is `{ "amount": "1200.50", "currency": "INR" }`:
decimal text/integer only, positive, at most two fractional digits and bounded
at `999999999.99`. Floats, booleans, scientific text, NaN and infinity fail.
The proposed draft currency allowlist is INR/USD/EUR/GBP/AED; this does not imply
supported international checkout. Stock is a strict integer from 0 to 1,000,000.

Limits: 200 candidates per JSON batch, 2,000,000 UTF-8 bytes, URL 2,048 characters,
source product/media/reference ID 200, title 200, description 4,000, evidence
8,000, review reason 1,000, at most eight option names and 30 values per option
(80 characters each). Unknown fields, duplicate JSON keys, duplicate option
names/values, invalid timestamps and control characters are rejected. Unicode
text, including instruction-like descriptions, remains data.

## Identity and duplicate review

- Website identity uses its normalized HTTPS URL. Normalization lowercases/IDNA
  encodes host, removes default port and fragment, and supplies `/` for an empty
  path. Paths and query order are preserved because changing them may change
  source meaning. A website with a different URL needs explicit duplicate review.
- Instagram, uploaded-media and CSV-source identity uses source kind plus the
  stable media/document ID. Instagram presentation URL changes do not change ID.
- Candidate UUID is deterministic from business UUID, source identity and
  `source_product_id`. This last key must be stable within the source. The caller
  must supply it rather than deriving it from a mutable list position. A reel
  showing multiple products therefore has distinct candidates under one media ID.
- A repeated identity in one batch is rejected, including identical repeated
  records, so the caller can resolve source collisions. Replaying a candidate
  across imports yields the same UUID and uses explicit `reimport_candidate`.
- Same seller product reference or case-insensitive title creates only a review
  suggestion. Neither is authority to merge. Separate businesses never match.
  Matching examines at most 200 supplied existing candidates; a persistence
  adapter must perform tenant-scoped lookup/windowing rather than passing a
  truncated global list and assuming deduplication is exhaustive.

## Review and reimport

The only domain states are `pending`, `review_required`, `approved`, `rejected`.
`parse_candidate` creates pending drafts; `begin_review` queues them for review.
`confirm_facts` requires one explicit seller confirmation covering title,
description, price, stock and options. `approve` additionally requires resolved
title, price, stock and options. Description may remain unknown when explicitly
reviewed. No transition publishes, activates checkout, creates SKUs or approves
source authorization. Caller transactions/locking must prevent stale concurrent
reviews when this domain is integrated with persistence.

`apply_overrides` records typed field values and reviewer UUID separately from
extracted values. Editing approved data returns it to review and invalidates
prior confirmation. Rejection requires a reviewer and reason. Rejected candidates
cannot be edited, approved or reopened through this slice; a later explicit
reopen workflow needs its own authorization/audit decision.

`reimport_candidate` accepts only exact tenant/source/product identity and a
capture no older than the stored capture. It retains seller overrides and stable
seller product reference, updates extracted draft values/provenance, and returns
per-field before/incoming values, the **previous effective value**, whether an
override was preserved, and previous provenance. Any extracted factual change
invalidates approval/confirmation and requires review, even if masked by a seller
override. An identical reimport preserves review and approval. Rejected items
stay rejected while still returning proposed differences.

The current immutable input candidate and `ReimportResult.previous_provenance`
allow the future persistence adapter to store an append-only revision and audit
trail. This package does not retain durable revision history itself. A changed
extraction is a new unapproved draft; it cannot update a live catalogue through
this package. The adapter must persist diffs/history and expose review explicitly.

## Catalogue bridge remains pending

The accepted read contract is `catalogue.v1`, `mode=preview_foundation`,
`checkout_enabled=false`, with product/SKU IDs, SKU `options`, `price_minor`,
`currency`, `stock_available` and `active`. D10 deliberately has no dependency on
shared catalogue models, readers, writers, migrations or startup registration.

These draft fields are a proposal for seller review, not canonical catalogue
allocation. In particular:

- Draft scalar `stock: null` means **unknown extraction**. Canonical SKU
  `stock_available: null` means **explicitly untracked inventory**. They must
  never be mapped directly. This slice can approve only explicitly tracked
  scalar stock; reviewed untracked stock needs a future explicit draft flag or
  allocation adapter, rather than a fake zero.
- Aggregate stock must never be copied into multiple option combinations. Draft
  options do not define SKU combinations, per-SKU prices, identifiers or stock.
  Variant allocation and existing SKU matching require seller review.
- Decimal draft prices need explicit currency-aware minor-unit conversion and
  canonical currency validation at that adapter. This two-decimal draft format
  is intentionally narrower than arbitrary currency support.
- Name/title mapping, category/media ownership, original image preservation,
  product/SKU matching, durable approval history, public allowlists and catalogue
  write authorization remain integration work. No media asset is downloaded or
  transformed by this slice.

## Verification

Verified on CPython 3.12.14 with isolated pytest 8.2.0 / Pydantic 2.7.1. The
following command excludes legacy conftest, pytest configuration/plugin loading
and cache writes; it does not need production `.env`, Docker, PostgreSQL or Redis:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend .venv-imports/bin/python -m pytest \
  -c /dev/null --noconftest -p no:cacheprovider backend/tests/test_v1_import_drafts.py -q
```

93 synthetic cases pass. They cover invalid/adversarial references and fields,
bounded batches, exact/source duplicate handling, multi-product reels, cross-tenant
matching/reimport denial, unknown facts, explicit review, terminal rejection,
changed approved data, preserved seller corrections and stale reimports.
No database, API, provider retrieval, UI or live seller acceptance is claimed.
