# Comment binding source candidate

The source-only run below used the P01 disabled DB target. Subsequent bounded actual0054→0055 runs on the newly allocated exclusive PostgreSQL16 parcel_w6 lane are recorded separately below. No browser/live-provider run was made.

```sh
PYTHONPATH=backend ../munimjee-v1/.venv/bin/python -m pytest \
  backend/tests/test_comment_binding_pure.py backend/tests/test_comment_automation.py \
  -k 'binding_pure or wholeword or meta_private_reply_payload or production_lambda or malformed_unicode' \
  -q --tb=short --junitxml=artifacts/v1/comment-binding/pure.xml
```

Result: **60 passed, 20 deselected**; no DB fixtures executed. The selected incumbent tests cover keyword matching, exact synthetic provider payload, signed-Lambda forged-source denial and malformed Unicode signature. New tests cover private proof types/secret repr, source/body tamper, real dispatcher pre/postclaim schedules, recovery fencing, activation/static-copy withholding, current local access check, unbound/ambiguous media, metadata races, redacted retry503, cancellation/unknown/intermediary409 and actual task cancellation after provider entry, original receipt preservation, UTC timestamp round-trip identity and unencodable comment rejection. One offline Alembic operation render passes; this is SQL generation, not PostgreSQL execution.

`initial-producer-row-key-harness.txt` preserves a fake query-row mapping mistake (4 failures/35 passes), fixed before the final run. It is not a product regression. No credentials or real customer/provider data were used. The new actual-PG tests and20 incumbent DB scenarios subsequently ran after the coordinator allocated NEWparcel_w6; see the actual results below.

Runtime dependencies and limits: `docs/v1-comment-binding.md`. Deployment/enablement remains closed; native comment management and inferred-WA manual-handoff visibility are still pending. Earlier V08 raw actual failures remain preserved in the separate audit branch `14b3d3c`.


## Actual migrated and signed-hook proof

Tested application source: `efc3ad3` (runtime byteidentical to reviewed `c90b3af`; efc only added cancellation proof). Real migrations0054→0055, P01 exact-lane validation and reset lease; isolated disk-backed PostgreSQL16 `parcel_w6` at the explicitly allocated numeric loopback endpoint. No old parcel_w3 or integrator lane access, no create_all/fake predecessor, no actual provider call.

```sh
TEST_DATABASE_URL=<exact coordinator-allocated parcel_w6 URL> TEST_LANE=parcel_w6 TEST_DB_RESET=1 PYTHONPATH=backend \
  ../munimjee-v1/.venv/bin/python -m pytest \
  backend/tests/test_comment_binding_pure.py backend/tests/test_comment_binding_db.py \
  backend/tests/test_comment_automation.py -q --tb=short \
  --junitxml=artifacts/v1/comment-binding/backend.xml
```

**92 passed,0 failures/skips,32.45s**:60 pure/source checks plus32 actual owned/incumbent DB cases. The actual app.main signature-verified hook commits bound receipts/actions; actual worker/SQL sees committed pauses/deactivation/account/token changes, postclaim pause and activated static-copy restrictions before any synthetic provider invocation. Concurrent signed duplicates/workers produce one attempt. Metadata refresh CAS never promotes the original proof. Legacy NULL remains unbound/review-required. Mid-provider pause preserves the original provider receipt/claim and marks review; direct Product/Storefront NOWAIT writer probes progress during synthetic IO. Required legacy public/private, source age, rate, signature and interruption behavior remains covered with explicit trusted fixtures.

Then a narrowly targeted proof closed requested coverage details, without runtime edits or broad suite repetition:

```sh
TEST_DATABASE_URL=<same allocated parcel_w6 URL> TEST_LANE=parcel_w6 TEST_DB_RESET=1 PYTHONPATH=backend \
  ../munimjee-v1/.venv/bin/python -m pytest backend/tests/test_comment_binding_db.py \
  -k 'offset_timestamp or exact_types or never_reset or real_task_cancellation or accepted_source_body' \
  -q --tb=short --junitxml=artifacts/v1/comment-binding/focused-tail.xml
```

**5 passed,11 deselected,5.67s**. One earlier immutable case was repeated/expanded; these are not97 distinct cases. Real PG validates offset→UTC accepted-claim stability, exact source proof/complete-or-null CHECKs, immutable source/body/accepted hashes/audits, strict tenant FKs, one-way claim token/attempt time/provider receipt/finalization, and actual task.cancel→durable unknown with no second attempt. Four test cases are additional to the main run. Both runs passed on first actual execution; only the earlier pure fake-row harness mistake is retained as a failure artifact.

The exclusive DB slot was released after the focused run; no DB/browser process or server port remains. No new runtime source after the reviewed/tested application bytes. New DB test additions and evidence are a follow-up commit. Independent source review was by the integrator; actual execution here is author evidence, not relabelled independent QA. No native comment UI, invisible-WA handoff fix, official permission/window canary, production enablement or deployment is claimed.
