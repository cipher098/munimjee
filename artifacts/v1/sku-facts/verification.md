# Current SKU facts in automated replies

Runtime candidate: `741a45b3b7c1fa72925c51712613c0e8ee666947`. Separate `codex/v1-sku-replies` worktree from central `7a5974f`, accepted customer privacy dependency `a7e6ce7`, and real shared default-off configuration `8a9de4d9`. No DDL or new sender.

Final exact source: **227 passed, 3 existing Redis skips, 0 failures**, including **75 owned checks (21 pure +54 actual PostgreSQL)**. **Five mounted Chromium journeys passed** on this same source. Browser source hashes and every listed source byte match the committed candidate. The integrator independently accepted the bounded batch/crossover source fixes; final proof was supplied before local integration.

The three skips require a separately allocated TEST_REDIS_URL and are incumbent Redis transfer/trim checks. No owned check skipped. Raw JUnit/output, controlled before/after failure evidence, final browser results, observed synthetic message text and capture/source hashes are in this directory. Earlier candidates remain clearly named before-fix files; they are not acceptance evidence for fixed batch behavior.

## Behavior and boundaries

Active tenant, published storefront, explicit activation, reviewed mapping and active authoritative SKUs are required. Responses contain only bounded product name/options/public INR price/recorded availability. Unknown quantity stays untracked. Availability is an observation, never a reservation. Price/variant selection, negotiation, order/payment/stock mutation and joined customer history remain outside this slice.

The existing durable Instagram thread/MID ledger and WhatsApp auto:reel outbox retain the only senders. Final scalar reads bypass retained ORM values and do not autoflush unrelated dirty fields. Instagram preserves current account/window, takeover, disengagement, manual/payment holds and quarantine. WhatsApp regenerates the queued intent at its existing delivery boundary and preserves opt-out/window/account/automation checks. Unknown provider effects keep the existing quarantine/unknown outcomes and do not retry automatically.

Every explicit reel and reply-to reference in a buffered SKU turn must agree before media or state processing. Unknown/conflicting references withhold instead of choosing first or last. Every frozen reel and every processing source window/account binding is checked in the final statement. Existing cycle/variant/negotiation values stay unchanged, including a previous legacy feature wait when a new exact SKU reel becomes focus.

## Reproduced review finding

At `a34404f`, actual durable-worker cases reproduced three failures: two reel products selected the last; two reply-to products selected the first; two embedded URLs produced an automatic response. The mixed reel/reply case already withheld. `batch-ambiguity-before-fix.txt` preserves the real three-fail/one-pass result. `batch-ambiguity-after-fix.txt` records the immediate 11-case targeted rerun; the final suite includes those and further frozen-reference/window/cycle cases.

## Lock scope

The adapter takes no new explicit SKU, Storefront or catalogue sweep row locks across provider awaits. Actual probes show direct SKU and Storefront row locks progress during an exact-reel send; these are row-lock probes, not a claim that the full domain inventory writer bypasses its Product lock. Incumbent focus persistence can hold a single-Product foreign-key KEY SHARE lock until commit; Product FOR UPDATE can wait, including a domain inventory operation that also locks Product. This is not a claim that every catalogue writer is unblocked. The existing legacy WhatsApp Account→Product lock inversion remains a separately owned integrator follow-up.

## Verification setup

Only the allocated `parcel_w3` PostgreSQL16 lane was used, through the P01 validated reset lease and actual Alembic0052 chain. No runtime.env, fake predecessor, create_all, Redis connection, production database, customer record or live provider was used.

The mounted browser imports actual app.main. It uses real native signup/session/CSRF and catalogue draft/activation/inventory forms, actual HMAC-verified webhook handlers, actual durable workers and the existing outbox. Test-only fixtures bind synthetic accounts/reel mappings; only Instagram.send_message and WhatsApp provider.send are replaced with in-process synthetic transports. The captured provider text is fixture evidence, not a new production inbox UI or live Meta proof. External browser assets are blocked and asserted absent.

The two PNGs show the existing native catalogue at desktop1365 and mobile390. No product UI, layout or style was changed. The mobile page is checked for horizontal overflow. All names, messages, account IDs and observations are synthetic; no native session/challenge secret is captured.

## Reproduction

Use the explicitly allocated disposable lane with `TEST_DATABASE_URL`, `TEST_LANE=parcel_w3`, `TEST_DB_RESET=1` and `PYTHONPATH=backend`. Run pytest for `test_sku_fact_replies{,_db}.py`, `test_whatsapp.py`, `test_commerce_whatsapp.py`, `test_instagram_ingress{,_db,_worker}.py` and `test_channel_operator{,_db}.py`. The browser runner is `python -m tests.run_sku_fact_browser`; its exclusive P01 lease covers actual migration, app.main server, Chromium and server cleanup on8156.

## Integration seams

Owned runtime commits: `35b6e4f`, `66a6169`, `a34404f`, `79687f9`, `741a45b`, plus contract `248b3c4`. Real shared flag dependency `8a9de4d9` was cherry-picked locally as `9d98a86`; do not duplicate it if centrally integrated. No new model/router/worker startup registration or migration is needed. Existing app directory packaging includes the new schema/service. No shared main/nav/client/package/import/customer/support files were edited.

The final source marker freezes SKU eligibility before cycle handling. Controlled activation, rollout and inferred-vision crossover cases withhold and roll back cycle changes. This prevents a turn that had no explicit eligible product from acquiring fact authority later.

## Remaining gates

The real rollout flag defaults off. Central integrated migration/source composition, release packaging and independent acceptance remain separate gates. No deployment or provider/customer send is authorized by this packet. Approved Meta/provider consent/window/template/live delivery canaries remain external. Strict English/Hinglish factual phrasing, bounded option lists and explicit context are the supported slice; other cases hand off or withhold.
