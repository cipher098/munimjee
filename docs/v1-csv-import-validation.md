# CSV import v1 validation

Reviewed bounded slice, 2026-10-18. Contract: [v1-csv-import-contract.md](v1-csv-import-contract.md). Template and transport fixture: docs/contracts/csv-import-v1/. Base256bfa1 has real0052; new revision0053_v1_csv_import follows0052_v1_customer_links. No main, config, navigation, packaging, shared-client or production changes were made in this branch.

## Behavior and integration

The existing native upload and job endpoints now accept bounded text/csv originals and an explicitly named document UUID. The same durable worker and reviewed private-draft bridge process literal facts. Product identity is business + document + case-sensitive trimmed product_ref, independent of row order, filename, file hash or title. Original bytes and source evidence are retained. Blank remains unknown; 0 is known zero; price requires recognized explicit currency; options are never inferred. The entire file is validated before any candidates are persisted.

Reimports preserve seller overrides, do not remove absent products, and do not change an already bridged catalogue product. CSV captured_at uses server job acceptance time so a delayed older worker cannot rewind a newer document version. Existing website/media request hashes exclude the newly added optional document fields, preserving old exact-key retries. Original-media upload remains separate and was exercised by the browser gate.

Native catalogue.write/CSRF/origin checks and the existing final transaction guard remain authoritative. The owned importer client also now orders every session response, including digest waits: an older owner response cannot re-enable controls after a newer viewer downgrade. Unknown upload/job results retain exact commands through reload; reselecting exact original bytes is required for an uncertain upload. No file bytes are stored in the browser. Wrong-document acknowledgements, malformed recovery state and unavailable browser storage fail closed.

No new application registration is needed: the existing import router and workspace are already mounted by actual app.main. The browser harness asserts each route is present exactly once and adds no fallback router. Shared package requirements already include the changed three import assets. The integrator owns central0053 composition and the next-slice milestone.

## Recorded evidence

- 159 backend tests passed, 0 skipped, in102.25s. Includes34 new pure CSV cases and12 new actual PostgreSQL16/0053 CSV cases, plus existing job, native mutation boundary, native completion, workspace and private-bridge/schema regressions. Raw output: artifacts/v1/csv-import/backend-run.txt; JUnit: backend-results.xml.
- 74 actual mounted Chromium checks passed on the same dedicated P01 payment_w3 lane and actual0053 chain. Raw output: browser-run.txt; machine result: browser-results.json. Actual native signup/session/CSRF and API writers were used. A protected local test trigger runs the actual CSV parser/worker; there is no provider extraction or fake parsed-facts adapter.
- Browser checks cover upload and job commit-then-drop, reload without automatic POST, exact-key retries and one job, wrong-document valid-shaped ACK recovery, changed-file rejection, unavailable storage zeroPOST, malformed journal blocking, literal unknown/zero review, stable same-document reimport and seller override, one inactive private draft, complete-file error, incumbent original-media upload, current viewer downgrade and held-old-session race, and physical ended-session DOM clearing.
- Actual database checks cover retained bytes/author, size bounds, exact replay/conflict and concurrent job creation, CSV/media type binding, tenant asset isolation, atomic whole-file failure, cancel/retry/result fencing, private zero-stock bridge/exact receipt after reimport, missing-row preservation, stale captures and late-old-claim ordering, native session/role lock-wait rollback, and session revocation while upload bytes stream.
- JavaScript syntax and git diff whitespace checks passed. Provider calls and external browser requests:0. Tests use synthetic seller/file fixtures; no production data, provider credentials, paid transactions, messages or deployment.

## Source and render review

Independent integrator review returned **SHIP** at this bounded scope after inspecting parser/API/schema/tenant/hash/provenance/session boundaries and the final six captures. No substantive blocker was found. Central composition/full release readiness is not implied. Initial confirmed session-order failure is retained in browser-pre-session-fix.txt; the same actual browser case passes after the fix.

A fresh Impeccable finish-reviewer spawn was attempted and failed with agent thread limit reached. Independent integrator source/render review substituted; documentation comparison was performed inline. All six final captures were opened and checked: desktop-empty, desktop-reviewed-private, mobile-csv-source, mobile-file-error, mobile-viewer and mobile-session-ended. The initial error capture was replaced with a settled visible error state. Mobile width390 has no horizontal overflow in the browser assertion.

The detector ran once. It reported inherited workspace/shared-CSS accent borders, eyebrows, 10–11px text and a linked-CSS contrast warning. The new CSV explanatory hints were increased to13px and final captures regenerated. This is not a zero-warning claim, nor an accessibility audit of unchanged workspace styles.

Documentation comparison: **No design-system changes**. Checked commerce.css, import_workspace.html/css and the final captures. Palette remains ink/paper/green; body remains the existing14px system stack; controls retain incumbent shapes/focus/44px targets; source layout uses two desktop columns and one mobile column; review/list architecture remains unchanged. Inherited tiny labels/eyebrows/accent-border drift was neither canonized nor expanded into new system rules. No DESIGN.md or token sidecar was written.

## Explicit limits

CSV v1 accepts only the seven frozen headers,256,000 bytes and200 records. It is not a variant-row mapper, XLSX importer, formula evaluator, currency converter, network extractor, global source registry or operational inventory feed. Existing-source choices come from loaded activity pages with a bounded in-memory cache. Variants require existing human option review and explicit allocation. Publication, stock reconciliation, activation, checkout and provider canaries remain separate gates. Production worker/deployment readiness is unchanged.

0053 downgrade cannot reinstate the old CHECK while retained CSV originals exist; it must fail rather than erase evidence. Upgrade was exercised by the actual migration gate; downgrade with retained originals was not independently rehearsed in this slice. Use a forward repair for accepted CSV data.
