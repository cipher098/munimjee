# V08 material repair: independent scoped review

Review base `e7edea1613b9902c726ce571e3d16c169c8cf190`, branch `codex/v1-v08-material-review`. Ownership is this document and `artifacts/v1/v08-material-review/` only; runtime and tests are read-only. The prior 21-case packet and its reproduced material red are retained as historical evidence.

## Minimal repair contract

The approved runtime owner may change only `backend/app/services/sku_fact_replies.py`: remove `material` and `materials` from both `_FACT_WORDS` and the `requested` set. This is a category-based change, rather than a special case for “What material is this?”. The all-word allowlist also rejects a mixed price/material request, even though price alone remains supported.

Both existing caller seams already route an unsupported factual request through `HANDOFF`: `whatsapp_context.reel_reply_decision` and the Instagram final writer `conversation._send_and_tag`. No caller transfer is required. `read_facts`, `render`, schemas, `HANDOFF`, provider/financial logic and other callers must remain unchanged. Existing final authority reads still precede the handoff decision; the repair does not create new send authority.

The result is deliberately conservative human handling. It does not add approved material facts, claim that a real product lacks material, infer composition, or add multilingual answer generation. Supported English/Hinglish price, option and stock behavior should remain exact; unsupported Devanagari behavior remains a safe handoff rather than language-quality proof.

## Review criteria fixed before evidence

Check the exact one-file diff and runtime hashes, preserve original21 test bytes and prior red artifact bytes, review the peer's finite ordinary/mixed-question regressions, and verify literal expectations, actual functions and injected raw-row boundary. New tests must not replace context/classifier/decision/render with expected outputs or treat synthetic row results as SQL authority/persistence. No DB, server, provider, model, credentials, sends, Docker or ambient service operation is authorized here.

The original P2 finding concerns missing-fact uncertainty/actionability; it was not an invented-fact or financial-safety failure. A passing repair check closes that bounded classifier/caller symptom only. Actual migrated/mounted behavior, reconnect/durable queue/resume, supported provider policy and full V08/X01 remain separate gates. No redundant test scenario is added by this review lane.

## Checkpoints

Baseline hashes for source, safety, original tests and prior red evidence are saved in `base-inventory.json`. Exact source and independent-QA checkpoints are reviewed below.

## Final independent disposition

No scoped source, harness or assertion-fidelity blocker found. Exact runtime `3b91a3a96a6c3f104e0666bb19dfbd97d1bc96e9` changes only the two approved vocabulary lines. The candidate SHA256 is `884bdbdd3df66658a9c1f295494931c87fed17a2777c65757642e5140cb8b953`. An independent byte transform confirms all other source bytes match the base; all other function ASTs match. No third file, caller seam or permission change is needed.

Owner evidence checkpoint: `aea4effd148810f63f079369adcf2dc87822290d`. QA baseline checkpoint: `68441ddf0c8f6f3abf07cb76b0c672ff29c61761`. QA final checkpoint: `5faa15255c085a16f50954ec2ae5ca7baa78a569`, with runtime composed as `fb8e9276a60053d472109203a350d58f122b349a`. New harness SHA256: `8bb6bc7877828fefc1f8d03bc0ce692393627cfe0f802aa061187b41cd2bbdb9`.

The six added assertions were fixed before baseline execution. Baseline M01 plural, M02 mixed price/material and M03 mixed sizes/stock/materials fail the same actionability requirement; the three supported-facts/authority cases pass. Candidate XML records **48 passed, 0 failed/errors/skips**: unchanged original21, new6 and existing pure-SKU21. The author separately records 65 passing focused checks; these overlap and are not added together. No redundant test run was performed by this review lane.

The actual XML properties show the original singular material case and M01–M03 now return the existing exact `HANDOFF`. M04 still returns the independent exact catalogue reply with approved ₹0.00, recorded zero stock and untracked/null stock. M05 empty rows and M06 null required price remain withheld before unsupported-intent handling; the repair does not acquire authority to answer from invalid facts.

The new QA module reuses only the unchanged strict raw projection adapter, independently owns its observations/invocation/literal reply and checks the full five-call application composition. Context, classifier, validation, decision and rendering functions are not replaced. The material oracle allows human handoff or specific uncertainty rather than only the original question or one required uncertainty phrase. It is a bounded English clarity criterion, not a complete hallucination or language-safety oracle.

Independently checked all 219 prior tracked test files, including original21 and shared safety, against immutable base bytes; all 16 prior V08 artifact files are byte-preserved. The added harness is identical before/after repair; the six-case baseline raw red files are unchanged. All owner/QA raw artifact hashes, 11 owner function hashes, source hashes and new-case XML properties match their manifests. The verification artifacts here record those checks. Historical red evidence is retained and its status remains historical; no failure was erased, skipped or weakened.

This closes the bounded missing-material response symptom through conservative human handling, including mixed supported/unsupported questions. It does not introduce material facts, assert that every product lacks them, improve Hindi generation, or prove a durable operator takeover. Actual SQL tenant/publication/activation/current-state authority, sender/queue/resume/reconnect, migrated/mounted journeys and authorized provider/model delivery remain unrun here and require their own acceptance. Full V08/X01 completion and a green release are not inferred.
