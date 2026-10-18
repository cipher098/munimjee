"""Local channel controls shared with automatic Instagram reply paths."""
from app.models.channel_operator import ChannelConnectionState


async def instagram_automation_enabled(db, seller_id) -> bool:
    control = await db.get(ChannelConnectionState, (seller_id, "instagram"))
    # Existing connected accounts retain their prior policy until operated here.
    return control is None or control.automation_enabled


class CatalogueAuthorityHandoff(RuntimeError):
    """A legacy bot must not read frozen price/stock facts for an activated SKU."""


class InstagramSendUncertain(RuntimeError):
    """A customer send failed without a safely persisted outcome."""


async def guard_legacy_product(db, seller_id, product_id, *, nowait=False) -> None:
    if not product_id:
        return
    from sqlalchemy import select
    from app.models.product import Product
    from app.services.checkout_v1 import is_product_activated
    # Readers share this lock; activation takes FOR UPDATE on the same Product.
    # Hold until commit so activation cannot race a legacy fact read/send, while
    # chats focused on different products cannot deadlock each other as readers.
    query = select(Product.id).where(Product.id == product_id, Product.seller_id == seller_id).with_for_update(read=True, nowait=nowait)
    if nowait:
        from sqlalchemy.exc import DBAPIError
        try:
            # WA holds Account before this read, while checkout can hold Product
            # before Account. Never wait in that inverted order; the savepoint
            # leaves the caller's claimed outbox transaction usable on contention.
            async with db.begin_nested():
                product = await db.scalar(query)
        except DBAPIError as exc:
            if getattr(exc.orig, 'sqlstate', None) != '55P03':
                raise
            raise CatalogueAuthorityHandoff('Catalogue is changing; current facts need review') from None
    else:
        product = await db.scalar(query)
    if product is None:
        raise CatalogueAuthorityHandoff("Product context does not belong to this business")
    if await is_product_activated(db, seller_id, product):
        raise CatalogueAuthorityHandoff("Current SKU facts need a human response")


async def legacy_fact_products(db, seller_id, products):
    eligible = []
    for product in sorted(products, key=lambda item: str(item.id)):
        try:
            await guard_legacy_product(db, seller_id, product.id)
        except CatalogueAuthorityHandoff:
            continue
        eligible.append(product)
    if products and not eligible:
        raise CatalogueAuthorityHandoff("This catalogue now requires authoritative SKU replies")
    return eligible


async def identity_product_data(db, seller_id, products):
    """Identification may use names/descriptions; activated legacy prices stay out."""
    data = []
    for product in sorted(products, key=lambda item: str(item.id)):
        try:
            await guard_legacy_product(db, seller_id, product.id)
            price = product.listed_price
        except CatalogueAuthorityHandoff:
            price = None
        data.append({"id": str(product.id), "name": product.name, "description": product.description or "", "listed_price_paise": price})
    return data


def current_provider_window(occurred_at) -> bool:
    """Conservative 24-hour automation limit; never infer time from DB receipt age."""
    from datetime import datetime, timedelta, timezone
    if occurred_at is None:
        return False
    current = datetime.now(timezone.utc)
    return current - timedelta(hours=24) <= occurred_at <= current + timedelta(minutes=5)


async def resume_messages_after_review(db, seller_id, customer_id, messages):
    """A close-without-retry decision also fences older autonomous follow-ups.

    Keep the transcript unchanged. A new customer turn after the decision can
    resume ordinary processing; old/missing-time entries cannot re-trigger it.
    """
    from datetime import datetime, timezone
    from sqlalchemy import func, select
    from app.models.instagram_ingress import InstagramIngress
    cutoff = await db.scalar(select(func.max(InstagramIngress.finished_at)).where(
        InstagramIngress.seller_id == seller_id, InstagramIngress.customer_id == customer_id,
        InstagramIngress.status == "resolved", InstagramIngress.error_code == "reviewed_without_replay"))
    if cutoff is None:
        return messages
    eligible = []
    for message in messages:
        try:
            timestamp = datetime.fromisoformat(message.get("timestamp", ""))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp > cutoff:
                eligible.append(message)
        except (TypeError, ValueError):
            continue
    return eligible
