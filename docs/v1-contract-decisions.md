# V1 initial contract decisions

Status: accepted for first foundation slices, 17 October 2026. These decisions do not turn fixture-backed features into completed product flows.

- Keep legacy routes and login tokens working. New APIs use `/api/v1`; native principals use a distinct role and purpose that legacy dependencies reject. No staff or sales user receives a legacy seller token.
- `Business.id == Seller.id` is the compatibility bridge. Add Users and Memberships; backfill deterministically and idempotently, never on each request. Revoked membership must not be resurrected.
- Roles: owner, manager, staff, viewer. Owner manages memberships and channel authorization. Manager operates catalogue/orders/inbox/automation and business settings. Staff reads catalogue and operates orders/inbox. Viewer is read-only. Sales support will require a separate explicit expiring grant with audit; legacy admin impersonation is denied by new APIs until that exists.
- Customer identities are tenant scoped. An entered phone number is not proof to merge Instagram and WhatsApp identities. Full Customer/ChannelAccount migration is a subsequent slice.
- Keep `commerce_orders` as the canonical new-order writer. Preserve legacy Instagram orders as a labelled read projection until reconciliation. No third independent order writer.
- SKU `stock_available` means available quantity, not on-hand. Null means untracked. Copy stock once only for unambiguous nonvariant products; legacy variant stock needs a seller-reviewed allocation. SKU snapshots do not activate checkout until writer cutover and reservation reconciliation pass.
- Catalogue first contract version is `catalogue.v1`, with `mode=preview_foundation` and `checkout_enabled=false` until integrated. Public serializers explicitly omit floor prices and private fields. Tenant comes from authorized context, not write payload.
- Imported facts remain drafts with source evidence and seller corrections; no automatic publication. Import and storefront workers use catalogue fixtures while the API is integrated.
- Instagram ingress uses existing trusted Seller.instagram_page_id ownership until ChannelAccount exists. Persist accepted message work before acknowledgement. Redis is a wakeup mechanism, not sole durable storage. Do not automatically retry unknown external-send outcomes.
- Migration sequence reserved: 0040_v1_identity → 0041_v1_catalogue → 0042_instagram_ingress. The integrator registers models/routes/workers and owns migration ordering.

All domain workers commit on owned branches. Test reset fixtures must target explicitly disposable, independently isolated databases before execution. This phase does not migrate production data or send live customer messages.
