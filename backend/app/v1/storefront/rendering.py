"""Escaped, allowlisted SSR projection. No database or publication writer exists here."""
from dataclasses import dataclass
from html import escape
import json
import re
from urllib.parse import urlsplit
from uuid import UUID
from app.v1.storefront.design import public_design, design_text, DEFAULTS


THEMES = frozenset({'editorial', 'catalogue', 'video'})


@dataclass(frozen=True)
class PublicStorefront:
    """Internal provider result, not a write/API DTO.

    The canonical provider MUST verify publication, activation, current mapping,
    ownership and public product visibility before setting publication_verified.
    A reviewed snapshot alone is insufficient. Default provider is unavailable.
    """
    slug: str
    name: str
    theme: str
    products: tuple[dict, ...]
    categories: tuple[dict, ...] = ()
    description: str = ''
    shipping_policy: str = ''
    return_policy: str = ''
    currency: str = 'INR'
    publication_verified: bool = False
    checkout_enabled: bool = False
    payment_methods: tuple[str, ...] = ()
    design: dict | None = None


def canonical_origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
        raise ValueError('A configured absolute canonical origin is required')
    if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('Public canonical origin must use HTTPS')
    return value.rstrip('/')


def public_image(value: str) -> str | None:
    """No data/javascript URLs, credentials or protocol-relative assets."""
    if not isinstance(value,str) or not value or len(value)>2048 or any(char.isspace() or ord(char)<32 for char in value) or '\\' in value:
        return None
    parsed = urlsplit(value)
    if parsed.query or parsed.fragment:
        return None
    if value.startswith('/') and not value.startswith('//') and not parsed.scheme and not parsed.netloc:
        return value
    if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password:
        return value
    return None


def public_product(source: dict) -> dict:
    """Project exact browser fields; seller mapping/private extras never serialize."""
    if not isinstance(source,dict) or not isinstance(source.get('name'),str) or not 1<=len(source['name'])<=200 or not isinstance(source.get('description',''),str):
        raise ValueError('Invalid public product text')
    product_id = str(UUID(str(source['product_id'])))
    raw_skus=source.get('skus',[])
    if not isinstance(raw_skus,list) or len(raw_skus)>500:
        raise ValueError('Invalid public SKU list')
    skus = []
    for source_sku in raw_skus:
        if not isinstance(source_sku,dict):
            raise ValueError('Invalid public SKU')
        if source_sku.get('product_id') is not None and str(UUID(str(source_sku['product_id'])))!=product_id:
            raise ValueError('SKU product identity mismatch')
        price = source_sku['price_minor']
        stock = source_sku['stock_available']
        if type(price) is not int or not 0 <= price <= 2_000_000_000 or (stock is not None and (type(stock) is not int or not 0 <= stock <= 2_000_000_000)) or source_sku['currency'] != 'INR' or type(source_sku['active']) is not bool:
            raise ValueError('Invalid public SKU')
        options = source_sku.get('options', {})
        if not isinstance(options, dict) or len(options)>10 or any(not isinstance(k, str) or not isinstance(v, str) or not 1<=len(k)<=64 or not 1<=len(v)<=200 for k, v in options.items()):
            raise ValueError('Invalid public options')
        skus.append({'sku_id': str(UUID(str(source_sku['sku_id']))), 'product_id': product_id, 'options': dict(options), 'price_minor': price, 'currency': 'INR', 'stock_available': stock, 'active': source_sku['active']})
    raw_photos=source.get('photo_urls',[])
    if not isinstance(raw_photos,list) or len(raw_photos)>50:
        raise ValueError('Invalid public media list')
    return {'product_id': product_id, 'name': source['name'], 'description': source.get('description',''), 'category_id': str(UUID(str(source['category_id']))) if source.get('category_id') else None, 'photo_urls': [url for raw in raw_photos if isinstance(raw, str) and (url := public_image(raw))], 'skus': skus}


def safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def render_storefront(store: PublicStorefront, origin: str, *, product_id: UUID | None = None, category_id: UUID | None = None) -> str:
    if store.publication_verified is not True:
        raise LookupError('Storefront unavailable')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', store.slug) or store.theme not in THEMES or store.currency != 'INR':
        raise ValueError('Invalid store presentation')
    for field in ('name','description','shipping_policy','return_policy'):
        value=getattr(store,field)
        if not isinstance(value,str) or len(value)>6000 or (field=='name' and not value.strip()):
            raise ValueError('Invalid public store text')
    design = public_design(store.design, store.theme)
    origin = canonical_origin(origin)
    base = f'/stores/{store.slug}'
    products = [public_product(item) for item in store.products]
    product_ids=[item['product_id'] for item in products]
    sku_ids=[sku['sku_id'] for item in products for sku in item['skus']]
    if len(set(product_ids))!=len(product_ids) or len(set(sku_ids))!=len(sku_ids):
        raise ValueError('Duplicate public catalogue identity')
    categories = []
    for item in store.categories:
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not 1<=len(item['name'])<=200:
            raise ValueError('Invalid public category text')
        categories.append({'category_id':str(UUID(str(item['category_id']))),'name':item['name']})
    if len({item['category_id'] for item in categories})!=len(categories):
        raise ValueError('Duplicate public category identity')
    selected = None
    if product_id:
        selected = next((item for item in products if item['product_id'] == str(product_id)), None)
        if selected is None:
            raise LookupError('Product unavailable')
        path = f'{base}/products/{product_id}'
        title = f"{selected['name']} | {store.name}"
        description = selected['description']
    elif category_id:
        category = next((item for item in categories if item['category_id'] == str(category_id)), None)
        if category is None:
            raise LookupError('Category unavailable')
        path = f'{base}/categories/{category_id}'
        title = f"{category['name']} | {store.name}"
        description = store.description
    else:
        path, title, description = base, store.name, store.description
    visible = [item for item in products if not category_id or item['category_id'] == str(category_id)]
    payload = {'contract_version': 'storefront.page.v1', 'store': {'slug': store.slug, 'name': store.name, 'theme': store.theme, 'design': design, 'currency': store.currency, 'description': store.description, 'shipping_policy': store.shipping_policy, 'return_policy': store.return_policy, 'payment_methods': [method for method in store.payment_methods if method in {'cod', 'razorpay'}]}, 'capabilities': {'public_catalogue': True, 'sku_checkout': store.checkout_enabled is True}, 'products': products, 'categories': categories, 'selected_product_id': str(product_id) if product_id else None, 'selected_category_id': str(category_id) if category_id else None}
    cards = []
    for item in visible:
        image = f'<img src="{escape(item["photo_urls"][0], quote=True)}" alt="{escape(item["name"], quote=True)}" width="600" height="760" loading="lazy">' if item['photo_urls'] else '<div class="empty-state">Image unavailable</div>'
        prices = [sku['price_minor'] for sku in item['skus'] if sku['active']]
        price = f'₹{min(prices)/100:,.2f}' if prices else 'Unavailable'
        availability = 'In stock' if any(sku['active'] and sku['stock_available'] is not None and sku['stock_available'] > 0 for sku in item['skus']) else 'Availability checked at checkout' if any(sku['active'] and sku['stock_available'] is None for sku in item['skus']) else 'Sold out'
        cards.append(f'<article class="product-card"><a class="product-image" href="{base}/products/{item["product_id"]}">{image}</a><div class="product-meta"><h3><a href="{base}/products/{item["product_id"]}">{escape(item["name"])}</a></h3><p>{price} INR</p><p>{availability}</p></div></article>')
    links = ''.join(f'<a href="{base}/categories/{item["category_id"]}">{escape(item["name"])}</a>' for item in categories)
    detail = f'<section class="brand-story"><h1>{escape(selected["name"])}</h1><p>{escape(selected["description"])}</p></section>' if selected else ''
    text = lambda key, fallback='': escape(design_text(design, key, fallback))
    # Presentation toggles leave categories and products in the public contract,
    # and every canonical category/PDP route retains its existing authority.
    navigation = f'<nav aria-label="Categories">{links}</nav>' if design['show_categories'] else ''
    tagline = f'<p class="brand-tagline">{text("brand_tagline")}</p>' if design['brand_tagline'] else ''
    hero_media = next((item['photo_urls'][0] for item in products if item['photo_urls']), None)
    art = f'<img class="hero-image" src="{escape(hero_media, quote=True)}" alt="{escape(store.name, quote=True)}" width="600" height="760">' if hero_media else '<div class="empty-state">New pieces are on their way.</div>'
    hero = f'<section class="hero"><div class="hero-copy"><span class="eyebrow">{text("hero_eyebrow")}</span><h1>{text("hero_headline")}</h1><p>{text("hero_intro")}</p><a class="primary-button" href="#collection">{escape(DEFAULTS[store.theme]["cta"])}</a></div><div class="hero-art">{art}</div></section>'
    story = f'<section id="our-story" class="brand-story published-story"><h2>{text("story_heading", "Our story")}</h2><p>{text("story_body", store.description)}</p></section>' if design['show_story'] else ''
    schema = {'@context': 'https://schema.org', '@type': 'Product' if selected else 'CollectionPage', 'name': selected['name'] if selected else title, 'description': description, 'url': origin + path}
    if selected and selected['photo_urls']:
        schema['image'] = selected['photo_urls']
    # No Offer is asserted: shipping/tax/availability and payment authority stay server-side.
    return f'''<!doctype html><html lang="en" data-theme="{store.theme}" class="palette-{design['palette']}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><meta name="description" content="{escape(description[:300], quote=True)}"><meta name="robots" content="index,follow"><link rel="canonical" href="{escape(origin+path, quote=True)}"><meta property="og:title" content="{escape(title, quote=True)}"><meta property="og:url" content="{escape(origin+path, quote=True)}"><link rel="stylesheet" href="/storefront-assets/src/styles.css"><link rel="stylesheet" href="/storefront-assets/src/live.css"><script type="application/ld+json">{safe_json(schema)}</script><script id="storefront-data" type="application/json">{safe_json(payload)}</script><script type="module" src="/storefront-assets/src/live-entry.js"></script></head><body><a class="skip-link" href="#collection">Skip to collection</a><main id="live-app"><header class="shop-header"><div><a class="wordmark" href="{base}">{escape(store.name)}</a>{tagline}</div>{navigation}</header>{detail or hero}<section class="collection" id="collection"><h2>{text('collection_heading')}</h2><p>{escape(description)}</p><div class="product-grid">{''.join(cards) or '<p>No published pieces available.</p>'}</div></section>{story}</main><noscript>Browse the collection using the links above. JavaScript is required for the bag and checkout.</noscript></body></html>'''
