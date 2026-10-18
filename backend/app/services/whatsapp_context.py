"""Resolve explicit Instagram references without fetching customer-supplied URLs.

Context is evidence for a reply, not permission to send one. Product matches are
exact, active and seller-scoped; unknown or ambiguous references stay unresolved.
"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import select

from app.models.product import Product
from app.models.whatsapp import WhatsAppMessage


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
IG_PATH = re.compile(r"^/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)/?$")


def instagram_references(text):
    refs = {}
    for raw in URL_RE.findall(text or ''):
        try:
            url = urlsplit(raw.rstrip('.,!?;:)]}'))
            if url.hostname not in {'instagram.com', 'www.instagram.com', 'm.instagram.com'} or url.username or url.password or url.port:
                continue
        except ValueError:
            continue
        match = IG_PATH.fullmatch(url.path)
        if match:
            code = match.group(1)
            kind = url.path.split('/')[1]
            kind = 'reel' if kind == 'reels' else kind
            refs[code] = {'shortcode': code, 'url': f'https://www.instagram.com/{kind}/{code}/'}
    return list(refs.values())[:10]


async def inbound_context(db, account, contact, event, text):
    result = {}
    quoted = event.get('context')
    if isinstance(quoted, dict) and isinstance(quoted.get('id'), str):
        result['reply_to_message_id'] = quoted['id'][:255]
    referral = event.get('referral')
    if isinstance(referral, dict):
        result['referral'] = {k: referral[k][:2048] for k in ('source_url', 'source_id', 'source_type', 'headline', 'body') if isinstance(referral.get(k), str)}

    timestamp = datetime.fromtimestamp(int(event['timestamp']), timezone.utc)
    shared_at = timestamp.isoformat()
    refs = instagram_references(text)
    source = 'message_link'
    if not refs and not URL_RE.search(text) and result.get('referral'):
        refs = instagram_references(result['referral'].get('source_url', ''))
        source = 'referral_link'
    if not refs and not URL_RE.search(text) and result.get('reply_to_message_id'):
        original = await db.scalar(select(WhatsAppMessage).where(
            WhatsAppMessage.seller_id == account.seller_id,
            WhatsAppMessage.contact_id == contact.id,
            WhatsAppMessage.provider_message_id == result['reply_to_message_id'],
        ))
        if original:
            # Re-resolve against the current catalogue; never inherit stale prices
            # or a product belonging to a different seller/contact.
            old_refs = (original.payload or {}).get('reel_context', {}).get('references', [])
            refs = instagram_references(' '.join(r.get('url', '') for r in old_refs)) or instagram_references(original.text)
            source = 'quoted_message'
    # A link followed by "price?" is usually two separate WhatsApp messages.
    # Keep a bounded conversational reference, explicitly labelled as inferred.
    # A new URL, referral, quote or attachment must never inherit an older reel.
    if not refs and event.get('type') == 'text' and not URL_RE.search(text) and not quoted and not referral:
        previous = await db.scalar(select(WhatsAppMessage).where(
            WhatsAppMessage.seller_id == account.seller_id,
            WhatsAppMessage.contact_id == contact.id,
            WhatsAppMessage.direction == 'inbound',
            WhatsAppMessage.provider_message_id != event.get('id'),
            WhatsAppMessage.created_at <= timestamp,
            WhatsAppMessage.created_at >= timestamp - timedelta(minutes=30),
        ).order_by(WhatsAppMessage.created_at.desc(), WhatsAppMessage.updated_at.desc()).limit(1))
        if previous:
            prior = (previous.payload or {}).get('reel_context', {})
            origin = datetime.fromisoformat(prior['shared_at']) if prior.get('shared_at') else previous.created_at
            if timestamp - timedelta(minutes=30) <= origin <= timestamp:
                old_refs = prior.get('references', [])
                refs = instagram_references(' '.join(r.get('url', '') for r in old_refs)) or instagram_references(previous.text)
                source, shared_at = 'recent_message', origin.isoformat()
    if not refs:
        return result

    from app.services import sku_fact_replies as facts
    if facts.enabled():
        for ref in refs:
            ids = await facts.exact_reel_products(db, account.seller_id, reel_url=ref['url'])
            if ids is None:
                ref['products'], ref['status'] = [], 'ambiguous'
                continue
            with db.no_autoflush:
                matches = (await db.execute(select(Product.id, Product.name).where(
                    Product.seller_id == account.seller_id, Product.active.is_(True), Product.id.in_(ids))
                    .order_by(Product.id))).all() if ids else []
            ref['products'] = [{'id':str(product_id), 'name':name} for product_id, name in matches]
            ref['status'] = 'matched' if len(matches) == 1 else 'ambiguous' if matches else 'unlinked'
        result['reel_context'] = {'source':source, 'shared_at':shared_at, 'references':refs}
        return result

    products = (await db.scalars(select(Product).where(
        Product.seller_id == account.seller_id,
        Product.active.is_(True), Product.reel_urls.isnot(None),
    ))).all()
    for ref in refs:
        matches = []
        for product in products:
            linked = instagram_references(' '.join(u for u in product.reel_urls or [] if isinstance(u, str)))
            if any(r['shortcode'] == ref['shortcode'] for r in linked):
                matches.append({'id': str(product.id), 'name': product.name})
        ref['products'] = matches
        ref['status'] = 'matched' if len(matches) == 1 else 'ambiguous' if matches else 'unlinked'
    result['reel_context'] = {'source': source, 'shared_at': shared_at, 'references': refs}
    return result


async def reel_catalogue_reply(db, seller_id, context, customer_text):
    """A bounded catalogue response, not an open-ended AI sales conversation.

    Require one unambiguous product and recheck its reel mapping. Include only
    public catalogue facts; no discounts, invented delivery promises or floors.
    """
    refs = context.get('references', [])
    if len(refs) != 1 or refs[0].get('status') != 'matched':
        return None
    ref = refs[0]
    from app.services import sku_fact_replies as facts
    if facts.enabled():
        matches = await facts.exact_reel_products(db, seller_id, reel_url=ref.get('url', ''))
        if matches is None or len(matches) != 1 or [str(matches[0])] != [p.get('id') for p in ref.get('products', [])]:
            return None
        if await facts.is_activated(db, seller_id, matches[0]):
            if context.get('source') not in {'message_link', 'referral_link', 'quoted_message'}:
                return None
            observed = await facts.read_facts(db, seller_id, matches[0], reel=dict(reel_url=ref.get('url', '')))
            if observed is None:
                return None
            question = facts.reel_question(customer_text)
            return facts.render(observed) if question == "[customer sent media]" or facts.factual_request(question) else facts.HANDOFF
    products = (await db.scalars(select(Product).where(
        Product.seller_id == seller_id, Product.active.is_(True),
        Product.reel_urls.isnot(None),
    ))).all()
    matches = [p for p in products if any(r['shortcode'] == ref.get('shortcode')
        for r in instagram_references(' '.join(u for u in p.reel_urls or [] if isinstance(u, str))))]
    if len(matches) != 1 or [str(matches[0].id)] != [p.get('id') for p in ref.get('products', [])]:
        return None
    product = matches[0]
    from app.services.channel_readiness import guard_legacy_product, CatalogueAuthorityHandoff
    try:
        await guard_legacy_product(db, seller_id, product.id, nowait=True)
    except CatalogueAuthorityHandoff:
        return "Our team will confirm the current options, price and availability for this product."
    price = f'₹{product.listed_price / 100:,.2f}'
    reply = f'You’re asking about {product.name}.\nListed price: {price}.'
    question = customer_text.casefold()
    if re.search(r'\b(warranty|guarantee)\b', question):
        reply += f'\nWarranty: {product.warranty_months} months.' if product.warranty_months else '\nNo warranty is listed; please confirm with our team.'
    elif re.search(r'\b(stock|available|availability)\b', question):
        reply += '\nCurrently out of stock.' if product.stock_quantity == 0 else '\nIn stock.' if product.stock_quantity and product.stock_quantity > 0 else '\nStock availability needs confirmation from our team.'
    elif re.search(r'\b(delivery|shipping|deliver|kab)\b', question):
        reply += '\nPlease share your delivery postcode so our team can confirm shipping and timing.'
    elif re.search(r'\b(discount|bargain|negotiable|best price|last price)\b', question):
        reply += '\nOur team can confirm whether an offer is available.'
    elif product.description:
        reply += '\n' + product.description[:1800]
    return reply[:4096]
