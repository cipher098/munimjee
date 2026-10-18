# Source-only operator candidate

Base: approved central `3820d14`, separate `codex/v1-comment-operator` worktree. Contract and exact0056 table/FK proposal were approved before DDL authoring. No shared registration, authentication, main, package or configuration file was edited. No DB/browser/provider run was made for this candidate. PostgreSQL resources remain reserved by the integrator.

Executed:

```sh
PYTHONPATH=backend ../munimjee-v1/.venv/bin/python -m pytest backend/tests/test_comment_operator_pure.py -q --tb=short --junitxml=artifacts/v1/comment-operator/pure.xml
node --test backend/tests/comment_operator_contract.test.mjs
```

Results: **27 Python source/pure checks and 6 Node contract checks passed**. Python covers strict confirmation/encoding, conservative legacy/unknown delivery labels, tenant/kind/filter cursor isolation, active-send close refusal with no Action lock, exact receipt before stale snapshot, unknown review preserving original effect, specific activated inferred-WA classification, static Alembic/model constraints and legacy DELETE-as-disable. Node covers cross-language canonical command hashes (Hindi, emoji and case-sensitive keywords), stale/wrong acknowledgement rejection, exact replay distinct from delivery, route/business/body recovery restrictions, explicit rule scope, and inspectable legacy wildcard rules that cannot become new native scopes.

One earlier Python test-harness failure included the `@router.delete` decorator when checking that the delete handler body never physically deletes history; the assertion was narrowed to its body. One initial Node harness failure attempted to assign Node26's read-only global crypto getter; the harness now installs WebCrypto only when absent. Neither was a product finding. The final captured outputs are `pure.txt`, `pure.xml`, and `node.txt`; these do not claim actual API or mounted browser behavior.

Prepared `test_comment_operator_db.py` is **not executed**: real0056 constraints, native HTTP/current authority waits and postflush rollback, close concurrency, exact lost-response replay, tenant/CSRF/role negatives, and signed exact-inbound WA visibility are still pending allocation. Browser mounted owner/viewer/unknown recovery/session replacement/mobile flows and independent rendered review are pending. UI source has not been visually certified.

Integration seams: include `app.api.v1.comment_operator.router`, import `app.models.comment_operator` (four immutable tables plus exact historical-message source uniqueness), and allowlist four assets `comment_operator.html`, `comment_operator.js`, `comment_operator_contract.js`, `comment_operator.css`. Shared native cleanup must add prefix `munimjee.v1.comment-command:` before release. Native route `/v1/businesses/{business_id}/comment-automation` and API routes are documented in `docs/v1-comment-operator-contract.md`. There is no new worker/sender, review replay, source rebind, provider approval claim, actual customer send or deployment.

## Source review follow-up

Integrator review of `e6978b6` found two UI lifecycle gaps and a bad back link. The follow-up clears only the current page's owned journal, removes stale list/detail/editor facts on read failure and blocks fresh actions until a successful current read, preserves exact pending intent, and uses the mounted native business picker URL. **Six additional exact-production-JS VM checks pass** (`lifecycle.txt`), using a controlled DOM substitute. This is source behavior proof, not a real browser/API/DB run. Together with the unchanged six contract checks there are twelve Node cases. Eleven actual-DB cases collect successfully (`prepared-collection.txt`); collection is not execution.

The independent invite-tail review found an internal commit before final inviter reauthorization in another owned worktree. Its author fixed `start_session(commit=False)` specifically for invitation acceptance, preserving the default signup/login commit behavior. `reviews/invite_tail_order.py` extracts the exact helper/route AST with synthetic session staging and confirms zero commits before the denied final guard (`invite-tail-fixed.json`). The first probe invocation overlapped that fix and expected the historical one-commit result, so its assertion failed because the source was already fixed; no old runtime proof is fabricated. This probe proves source call ordering, not PostgreSQL rollback. The original source finding and final bounded source verdict were sent to the integrator. No other worktree source was modified.
