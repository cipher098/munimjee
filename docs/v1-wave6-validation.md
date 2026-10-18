# Wave6 bounded validation

18 October 2026. Complete gate invocation `b608f6f`; tested runtime `0e658fc`.
Later status-only commits do not change runtime or test source. CSV0053, reviewed
SEO/legacy redirects and default-off authoritative SKU fact replies are composed.
This is local synthetic acceptance of these slices, not full V1 or a release.

## Completed gates

| Gate | Actual result and evidence |
| --- | --- |
| Complete backend, real migration0053 | **1950 passed,8 skipped,0 failed in852.31s**; `artifacts/v1/integration/wave6/full-disk-pg16.{txt,xml}`. Dedicated disk-backed PG16/P01, serialized. |
| Native imports, actual app.main | **47 passed**; `native-import-mounted/` and log. Queried0053; application and harness pre/post SHA256 maps equal; both capture hashes recorded. Invocation `a3f98ec`. |
| SKU/channel mounted | **5 journeys passed**; `sku-mounted/` and log. Actual native catalogue UI, signed synthetic IG/WA ingress and existing durable/outbox single writers; current price/out-of-stock and conflicting batch withholding. Actual0053 separately queried; inherited owner runner0052 label explicitly corrected in composition.json. |
| CSV mounted | **74 passed**, actual central app.main; `csv-mounted/` and log. Owner159 focused evidence remains separate. |
| SEO mounted HTTP | **28 passed**, actual current native/SKU setup and app.main endpoints; `seo-mounted/`. This is HTTP composition, not physical-device or search-engine indexing proof. |
| Focused composition | **372 passed**; `focused-final.{txt,xml}`. Overlaps complete gate. |
| JavaScript | **77** storefront/shared checks plus **3** analytics checks; separate logs. |
| WA legacy lock inversion | **2 migrated regressions passed**; savepoint NOWAIT retains transaction usability and hands off instead of waiting under Account locks. No new SKU/catalogue locks across provider HTTP. |
| Current locked runtime | Image `sha256:1faf4b5089cccf93d15cd8ed91584aca547ff82298bc13eb6c2295b9a1fb689a`, source `b608f6f`,315 files,arm64,nonroot10001:10001,133942125 bytes. All3 actual offline startup/asset modes pass with context/image/per-file hash equality, no network/DB attempts and verified CID-only container removal. |
| Fresh0053 restore pair | **53 passed,0 skipped** at source1281372; `artifacts/v1/release-rehearsal/local-pg16-w6/`. Real dump/restore, retained exact CSV bytes and pending job, full rows/schema/protections and newer target-only order preserved. This pair has no package-switch proof. |

Counts overlap and are not summed. Eight complete-suite skips are five missing
historical LLM cassettes and three real-Redis cases without an allocated
TEST_REDIS_URL. No provider request was made to fill a cassette.

## Failure and recovery matrix

| Observed failure | Disposition |
| --- | --- |
| Focused361 passed/11 fixture errors | Native import fixture retained an installed middleware stack across shared app reuse. Fixture teardown/bootstrap repaired; focused372 then complete1950 green. Initial logs retained. |
| First WA test fixture lacked required WABA field | Synthetic fixture corrected; both actual lock regressions green. Initial log retained. |
| Old PG16 cgroup signal9/recovery during complete run | Original runtime0e658fc interrupted at1278 passed/8 skipped/72 migration-fixture errors. Not product acceptance. Old1GiB cgroup/tmpfs data exceeded safe capacity; old container/data/archives untouched. New bounded2GiB disk-backed dedicated container/volume on55443, new guarded lanes, serialized DB-heavy tests. Complete fresh1950 gate passes. Incident evidence and interrupted log/XML retained. |
| Failed log exposed synthetic test DB password | Public failed log/XML copies redact only the dedicated synthetic credential. Byte-identical originals remain in private0700 archive; original/public SHA256 and private location are recorded in redacted-failure-evidence.json. No failed run is relabelled success. |
| Conflicting SKU reel/reply-to batch chose first/last product in initial owner repro | Whole-batch references and eligibility frozen before state/media handling; every explicit reel revalidated at final scalar sender projection. Owner failed-before log retained; final owner227/3Redis skips and central5 mounted/complete1950 pass. |

Exact evidence hashes are in `artifacts/v1/integration/wave6/manifest.json`.
Historical proof directories are preserved; final mounted outputs are exported
under wave6 rather than overwriting prior evidence. The image remains local;
no existing resource was pruned, production service restarted or app deployed.

## Open scope and release boundaries

Activity0054 owner final74 Python/19 mounted/28 Node now passes on newpayment_w6,
but shared public shell, financial writer, retention scheduler and channel
producer installation remain next integration work. Missing producer metrics
remain null. Owned Instagram adapter/shared retention is isolated; final
optimized-integrity/legacy-authority/current-reader fixes require their own new
race and mounted rerun. Official Meta documentation identifies principal-wrapper,
account-type and unavailable-original compatibility questions. Both retrieval and
carousel gates stay false; docs and fake transports are not live approval.

Five reproduced queued-comment safety failures block broader V08 acceptance.
Reserved0055 source repair, native comment controls and durable visibility for
withheld inferred WA enquiries remain code work. Current minimal support consent
scope does not become implicit membership or discovery/write access.

Native amd64 image proof, hosted CI billing, old-package writers/browser routing,
full populated-domain backup/restore fixtures, provider approvals/canaries,
physical cameras and real utility-template delivery remain open. Historical0052
current-create/old-read/current-read ASGI compatibility is read-only proof, not
production rollback approval. No live payment/customer send, provider permission
change, original ParcelDesk change or deployment occurred.
