# CSV import v1 — frozen bounded contract

Status: frozen with the integrator on 2026-10-18 before parser/API implementation. Base256bfa1 contains the real0051/0052 chain. Reserved migration0053_v1_csv_import follows0052_v1_customer_links; implementation and acceptance evidence follow separately. This is a separate slice after the Wave5 milestone. No provider fetch, publication, inventory update or activation follows an upload.

## Reuse and ownership

Reuse tenant-owned v1_import_assets, durable ImportJob leases/retries, ImportDraft candidates/overrides, ImportAudit and the exact-key ImportCatalogueBridge. Domain SourceKind already permitscsv; the HTTP upload/job schemas and asset content_type CHECK currently reject it. The narrow migration widens that CHECK to text/csv; the existing maximum5MB remains, while CSV HTTP/parsing is limited to256,000 bytes. No new customer/order/catalogue writer or CSV-specific table is proposed.

CSV owns new parser/tests/fixtures and narrow import schema/service/API/asset-CHECK changes. Main/config/nav/package/shared client stay with the integrator. Existing import-workspace UI changes require coordination before edits. Native catalogue.write+CSRF/origin/final transaction guard precede upload buffering and all mutations; tenant-owned assets are mandatory. Reads retain existing tenant/capability rules. CSV bytes and cells are untrusted data, never instructions or executable formulas.

## Transport and retained provenance

Use existing raw upload endpoint with Content-Type:text/csv and explicit source_authorized=true, then existing job creation with source_kind:csv, asset_id, document_id, document_label and idempotency_key. Website/media fields must be absent. The UI generates a fresh document UUID once for a new named source, or chooses an existing document explicitly; sellers never type UUIDs/code fields. Filename and content hash do not identify a product or document.

Original exact bytes, byte length, SHA256, actor and authorization time stay in ImportAsset. ImportJob.source stores only source metadata: kind, stable document identity/label and captured asset evidence. CSV content is never embedded in job DTOs, logs or error responses. The candidate SourceReference is kindcsv with media_id `csv-document:{document_id}`. source_product_id is the exact trimmed product_ref. Existing uuid5(business_id,[source.identity(),source_product_id]) gives tenant-bound stable candidate identity. Evidence records the upload SHA and source record/line without echoing arbitrary cells.

Same key+same bytes/body replays the same upload/job; changed bytes/body with that key conflict. A lost response must retain exact command identity, require reselecting identical local bytes after reload when needed, and never silently create a replacement key/job. No raw file is stored in browser storage. New file bytes with the same explicit document UUID reimport the same product_ref candidates; a different document UUID is a deliberately different source. Absent rows do not delete/archive products or alter stock.

## Columns and parsing

UTF8 only, optional single initial UTF8 BOM; reject invalid encoding, UTF16/32, embedded BOM/NUL/control characters and bare CR. Accept comma-separated LF/CRLF CSV, double-quoted fields/doubled quotes and quoted multiline descriptions; normalize CRLF to LF in parsed text while retaining original bytes. No dialect sniffing, delimiter guessing, formula evaluation, HTML execution, network extraction or asset URL fetch.

At most200 nonblank records, at most7 distinct exact case-sensitive headers. product_ref is required; all other supported headers may be omitted. Unknown/duplicate/blank headers, wrong column counts, stray/unclosed quotes, duplicate trimmed product_ref, overlong fields or invalid factual values fail closed for the complete job before any candidates are written. Wholly empty physical lines may be ignored; a record with cells but no product_ref is invalid. Report bounded error codes with source line/column names, not raw cell values. No partial success or silent truncation.

| Column | Bound and meaning |
| --- | --- |
| product_ref | Required nonempty stable text≤200 chars. Preserve case; never derive from row number, title or filename. |
| title | Optional text≤200 chars; blank/absent→unknown. |
| description | Optional text≤4000 chars; blank/absent→unknown, not a claim of no description. |
| price | Optional fixed decimal major-unit text, at most2 decimals, positive and within existing DraftPrice range. No float/exponent/comma/currency-symbol/sign/rounding. |
| currency | Required when price exists; both price/currency blank→unknown price. Existing draft pilot codes INR/USD/EUR/GBP/AED; non-INR remains a reviewed source fact and cannot bridge to the INR catalogue without explicit seller correction. No conversion is inferred. Unpaired price/currency fails. |
| stock | Optional explicit integer0–1,000,000; blank/absent→unknown.0 means known zero. Reject signs, decimals, bool words and guessed availability. This is source total available stock, not per-variant allocation or an operational stock adjustment. |
| options_state | blank/unknown→unknown options; literalnone→explicit empty options list. No inferred single default SKU. Other values fail with a supported-format message. Variant matrices are resolved in existing human review/allocation; this first CSV format is not a variant-row/variant-price mapper. |

Text uses existing clean_text constraints. Numeric and option-state cells have small bounded lexical lengths before conversion. Parsed fields obey DraftFacts/DraftPrice limits. Values that cannot fit the current draft contract are rejected, never replaced by invented defaults. Formula-like text remains literal text and is never executed; numeric fields reject such syntax. CSV export and spreadsheet formula escaping are outside this upload slice.

## Review, reimport and private draft bridge

Candidates enter pending/review_required with unknown facts intact. Every factual field still requires current seller review; CSV authorization is not factual approval. Existing source-version reconciliation and seller overrides are preserved on reimport, including stale-capture rejection. For immutable CSV originals, candidate captured_at is the server job-acceptance created_at, so an older queued file cannot become a newer source version merely by starting its worker later. Never replace corrected catalogue facts or operational inventory from new file contents.

Unknown title/price/stock/options prevents the current catalogue bridge. options_state:none permits the existing explicit one-SKU review; a known zero stock creates a reviewed zero-availability draft only. Variants require each confirmed Cartesian combination allocated exactly once and allocations summing to the confirmed source total. An aggregate stock count is never copied into every SKU. This allocation does not reconcile pending reservations or enable checkout.

The existing bridge requires current candidate revision, five explicit factual confirmations, exact idempotency key/body and private draft receipt. Its immutable source/review snapshots and tenant locks stay authoritative. Replaying the same bridge command after reimport returns its original receipt; a new command cannot duplicate an already bridged candidate. Product activation, storefront publication and checkout policy remain separate explicit operations.

## Required acceptance evidence

Pure parsing: quoted commas/newlines/doubled quotes/BOM; every size/header/row/field limit; duplicate refs, malformed quoting/UTF8/control data; fixed decimals and blank-vs0; no inferred options, stock or currencies. Reordering rows preserves identities; changing document/business does not merge; reimport retains manual corrections.

Actual0053 chain: upload/job retry/cancel and tenant isolation, exact-key replay/conflict, native CSRF/current role/session loss during body/lock waits, CSV job claim/lease and atomic candidate persistence, stale capture handling, unknown facts and exact reviewed private bridge with no activation. Browser: human-named document selection, upload/parse errors, progress, review, variant handoff, source reimport and lost response/reload/reselection. No provider/network call, customer send, real credential or production database operation.

## Migration rollback boundary

0053 changes only v1_import_asset_content in the actual migration chain and its matching ORM CHECK; the original byte-size/hash/tenant constraints remain. Downgrade reinstates the old content-type CHECK and fails atomically while retained CSV originals exist. It never deletes originals, jobs, evidence or drafts to force a rollback. A forward repair is required for an installation that has accepted CSV files.
