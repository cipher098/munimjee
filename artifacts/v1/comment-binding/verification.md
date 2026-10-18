# Comment binding source candidate

No DB/browser run. Tests used the P01 no-outbound harness with its disabled DB target. This is not evidence that0055 migrates or that the five original actual-PG failures are fixed in the mounted system.

```sh
PYTHONPATH=backend ../munimjee-v1/.venv/bin/python -m pytest \
  backend/tests/test_comment_binding_pure.py backend/tests/test_comment_automation.py \
  -k 'binding_pure or wholeword or meta_private_reply_payload or production_lambda or malformed_unicode' \
  -q --tb=short --junitxml=artifacts/v1/comment-binding/pure.xml
```

Result: **60 passed, 20 deselected**; no DB fixtures executed. The selected incumbent tests cover keyword matching, exact synthetic provider payload, signed-Lambda forged-source denial and malformed Unicode signature. New tests cover private proof types/secret repr, source/body tamper, real dispatcher pre/postclaim schedules, recovery fencing, activation/static-copy withholding, current local access check, unbound/ambiguous media, metadata races, redacted retry503, cancellation/unknown/intermediary409 and actual task cancellation after provider entry, original receipt preservation, UTC timestamp round-trip identity and unencodable comment rejection. One offline Alembic operation render passes; this is SQL generation, not PostgreSQL execution.

`initial-producer-row-key-harness.txt` preserves a fake query-row mapping mistake (4 failures/35 passes), fixed before the final run. It is not a product regression. No credentials or real customer/provider data were used. New actual-PG tests and20 incumbent DB scenarios are **not run/pending** until the coordinator allocates/releases NEWparcel_w6.

Runtime dependencies and limits: `docs/v1-comment-binding.md`. Deployment/enablement remains closed; native comment management and inferred-WA manual-handoff visibility are still pending. Earlier V08 raw actual failures remain preserved in the separate audit branch `14b3d3c`.
