# Source-only storefront attribution follow-up

Compared original application `abab30aaf1ab94052344b0ef21d05b3922f260dc` with fetched
`8ae97c2d57c0efda5a03a41a469bf9447739ee72`, whose storefront runtime changes are at
`52fdda8d84f261841a44ef6a84e38e78cd93f237`. The latter runtime and documentary commit
have identical storefront source. Local remote-tracking refs were verified:
`origin/codex/v1-integration` remains `abab30a`; `origin/codex/v1-onboarding-followup`
is `8ae97c2`. The coordinator-reported unpushed `789db95`/0056 source was not inspected.

**The missing-photo overlap cause has not changed in this fetched newer source.**
This is static source attribution, not a new browser observation or latest-source
acceptance. The original `faec01614c27578afd38bef750b9dc2205ee7c98` 69-pass/6-red
browser evidence remains historical evidence on `abab30a`, preserved without edits.

The relevant original/newer Git blobs are identical:

| Shared source | Git blob OID in both revisions |
| --- | --- |
| `components.js` missing-photo `art()` | `6bdb27204303d26182f488d8f0efe77c5493ea27` |
| `styles.css` cart and `.empty-state` rules | `1f77d8ea3b0480440cd3e55bcf96519aa8b47717` |
| `live.css` | `4dd1a233c43d93c9ccf189a8bd58e73afd4fd1a3` |

`live-app.js` changes from blob `281909cf0f6e753f404d9e3fd84d81bdaf060956` to
`36c7271a6c4580075d9b1328e12c8f71d925fccc`, but its entire `renderBag` function is
byte-identical: SHA256 `9f78735283a9915988c245fcd1aebf56f70bf7fdd9d66d2f6827356e1d3d2ff9`.
The adjacent new activity callbacks do not change the cart DOM projection or CSS.
Commerce, theme configuration, published design and the actual renderer/design/schema
blobs are also identical. The companion JSON records exact Git OIDs, SHA256 and byte
sizes for all 15 compared paths, including the newly added `activity-client.js`.

Newer source does change browser behavior outside that layout cause:

- `live-entry` constructs the activity client and supplies it to live API/app.
- Visible-page, product-view and checkout-open hooks can POST to the same-origin
  `/api/v1/storefronts/{slug}/activity/contexts` and `/activity/events` endpoints.
- Checkout intent gains nullable `activity_context_id`; canonical encoding and
  saved-attempt validation accept it, and the API may add an ephemeral
  `X-Activity-Context` Bearer header. The existing uncertain payload remains the
  chosen replay source rather than being replaced by a renewed context.

Those differences prevent treating the old 69 passes as newer runtime acceptance.
The original harness intentionally has no activity HTTP routes: rerunning it
unchanged against this source would record the new requests as unhandled and abort
them. That is the existing fail-closed boundary, not evidence of a new product bug.

Remaining cases for a separately authorized, freshly frozen newer composition:

1. Export fresh actual SSR/metadata and rerun the original 75 experience cases;
   retain the six missing-photo text-overlap assertions until an implementation fix
   is actually observed. Do not replay old fixtures as newer-source evidence.
2. Explicitly intercept the new activity context/event routes with synthetic
   responses. Verify disabled/excluded/expired/capped, malformed, failed, delayed
   and storage-denied measurement still leaves shopping/dialog/stock/error paths usable.
3. Exercise a ready context: visible startup, product_view and checkout_opened,
   nullable frozen checkout context and ephemeral proof header. Check hidden-page,
   GPC/DNT, missing/expired proof and failure paths without creating a measurement
   dependency in shopping or leaking proof to URLs/durable storage.
4. Verify uncertain checkout retry/reload keeps its original financial intent and
   idempotency identity when the measurement context renews, expires or disappears.

No browser, server, provider, credential, DB, production or other runtime action was
needed for this comparison. All 31 files from the original QA checkpoint were checked
against their exact Git blob OIDs and remain unchanged; only this new note and its
companion attribution JSON are added. Physical-device, assistive-technology, media,
migrated persistence and production gates retain their original limits.
