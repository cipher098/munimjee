# Bounded comment binding repair

Status: bounded real0055/signed-hook/worker candidate tested on the exclusive NEWparcel_w6 PostgreSQL16 lane; **not enabled or accepted for launch**. The five original unsafe send conditions are now covered by passing current-worker tests. Central shared0055 composition and the integrator final evidence verdict remain separate. Native comment management and visible inferred-WA follow-up handoff remain separate unimplemented product work.

## Ownership and real dependencies

New isolated `codex/v1-comment-binding` worktree starts at central `b608f6f`. Real activity foundation `00ed382` supplies `0054_v1_activity`; real owned-media module chain through `b2c0f36` supplies the generation types; `b5a3bb7`, `d69dadb`, `c4794bb` supply the independently reviewed shared credential helper/fixes. Local dependency-only head is `5a0e5af`; none of those upstream changes are claimed as this feature's work. Shared main/config/native auth/package files remain untouched by the feature.

Owned changes: existing comment models/service/worker; new private claim schema and scalar policy helper; migration `0055_v1_comment_binding` → `0054_v1_activity`; tests/docs; one internal trusted-source keyword in the existing verified webhook and typed private-SQS comment branch. No new sender, native comment API/page, buffering change or live provider call.

## Accepted binding and persistence

Signature-verified ingress resolves the receiving account to exactly one Seller. A caller cannot supply tenant or private proof fields. The local generation is observed at acceptance; a provider webhook does not sign our credential version. Duplicate events keep their original source/rule/actions and never rebind to current credentials.

Event source columns are complete-or-null: account ID, exact shared helper proof (account/version/HMAC credential fingerprint/expiry), verification time and signed-webhook/provider-metadata provenance. JSON keys/types/size are constrained. Historical NULL remains NULL, including after reconnect. Event source/identity/rule/text/time is immutable. Invalid/unmanaged/ambiguous account ownership sends nothing; no tenant is guessed.

Actions freeze accepted event/body/configuration fingerprints and private proof, not duplicated raw body/token. A once-only claim token and attempt time cannot be cleared/replaced, receipts cannot be overwritten, and terminal work cannot return pending. Source-bound runtime state is constrained. Existing history is retained; the historical action/event tenant FK is NOT VALID only to preserve possible old mismatches while enforcing future writes. New append-only audit references are strictly tenant/event/action constrained. Claim/outcome/withholding/recovery audit rows contain no token, raw body, provider URL or exception text.

The migration does not send, bind or reinterpret legacy work. Legacy pending work is lazily marked review-required. Historical foreign action/event inconsistencies are held without exposing/mutating the other tenant's event; they cannot produce an invalid new audit association. No review/replay endpoint is introduced here.

## Producer and dispatcher

The producer reads current active Business/Seller, account/credential generation, expiry and control. It additionally requires explicit sending permission plus local `check_status=verified` and checked_at; this is account-access evidence only. A refresh invalidates that check and old pending proofs. Provider permission/window approval is not inferred. Missing metadata is retrieved read-only using the accepted generation; after the await, source/control/config are rechecked. A transient read returns a sanitized503 for ingress retry, never a token-bearing provider exception.

Every action requires one explicit matching rule/media/product context. Wildcard/unbound media, multiple matching products, inactive/foreign/missing product, unpublished store and **every activated-product context** are held. Arbitrary static text is not a certified current-SKU renderer; no price parser or automatic variant/product selection is added. At most100 rule scopes are evaluated; excessive/malformed configuration holds. Source creation time is verified; entry delivery time never opens a new window. The inherited seven-day age cutoff is a conservative local bound, not official entitlement certification. Own/nested/live/malformed comments are ineligible.

One existing dispatcher claims never-attempted accepted actions, commits before provider IO, then takes a fresh scalar projection including active claim token/state, current Business/Seller/binding/expiry/control/local verification, immutable event/rule/body/config and product/store/activation. It does not reuse retained Seller credentials. Current rule/legacy public facts/media/config changes withhold old copy. Recovery or cancellation can fence a worker before the call. Local throughput accounting is serialized by a per-seller advisory transaction lock; it is not a provider quota.

No new SKU/Storefront/catalogue sweep row locks span provider HTTP. Facts are observations; a revoke committed after the final projection cannot recall an already-started request. The post-provider check preserves the original receipt/claim and makes changed-authority outcomes review-required. A provider receipt means accepted, not delivered. Missing/malformed/credential-bearing receipt, unclassified HTTP errors, timeout, cancellation or process interruption stays unknown; no blind retry/reconnect-key reuse. Public/private actions retain independent once-only state. Recovery records stale sending as unknown, never pending.

## Trusted producer boundary and pending proof

The webhook passes the internal trusted-source marker only after signature validation. The second production path assumes the existing signature-verifying Lambda and private SQS/IAM boundary; the marker is not read from its payload. A direct untrusted service call defaults to denied. This does not certify a deployed queue policy or provider connection.

Pure tests exercise real dispatcher/producer phases with injected rows and synthetic provider methods; they do **not** prove PostgreSQL visibility, row locks, triggers, migration execution or live messaging. The actual-PG test file and required incumbent DB scenarios now pass. The bounded proof includes the original five negatives, post-claim pause, generation/metadata races, duplicate/concurrent workers, tenant/source/audit mutations, legacy holds, unknown/cancellation/recovery, and writer progress during synthetic send. Incumbent DB fixtures explicitly create valid current binding/access checks and trusted-domain calls. The main run passed92 tests; five focused follow-ups passed, with one immutable case repeated and expanded. Raw commands/results distinguish pure and actual-PG evidence; no broad full-suite or browser run was added. The slot was released after completion.

No production services, provider permissions, customer messages, physical camera, live approval/window, deployment or native operator workflow are certified by this candidate. Exact source/result hashes and commands are in `artifacts/v1/comment-binding/`.
