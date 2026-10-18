"""Actual renderer/router export using literal synthetic public-provider DTOs.

This does not exercise persisted settings or the database publication provider.
Source hashes accompany the files so the browser evidence can identify them.
"""
from tests.safety import install_test_safety
install_test_safety()

import hashlib
import json
from pathlib import Path
import subprocess
from uuid import UUID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.storefront import create_router
from app.schemas.storefront_theme_v1 import ThemeConfig
from app.v1.storefront.rendering import PublicStorefront, render_storefront

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'artifacts/v1/qa-product/wave4-public-theme-synthetic/fixtures'
PRODUCT = '22222222-2222-4222-8222-222222222201'
SKU = '33333333-3333-4333-8333-333333333301'
ORDER = '55555555-5555-4555-8555-555555555501'
CATEGORY = '44444444-4444-4444-8444-444444444401'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    product = {'product_id': PRODUCT, 'name': 'Independent public dress', 'description': 'Literal published dress',
        'category_id': CATEGORY, 'photo_urls': [], 'source_evidence': 'NEVER_PUBLIC_SOURCE_EVIDENCE',
        'credentials': 'NEVER_PUBLIC_CREDENTIALS', 'skus': [{'sku_id': SKU, 'product_id': PRODUCT,
            'options': {'Size': 'M'}, 'price_minor': 1250, 'currency': 'INR', 'stock_available': 5,
            'active': True, 'private_note': 'NEVER_PUBLIC_SKU_NOTE'}]}
    for theme, palette in [('editorial', 'rose'), ('catalogue', 'forest'), ('video', 'indigo')]:
        config = ThemeConfig(theme=theme, palette=palette, brand_tagline='Published & boutique',
            hero_headline=f'Published & {theme}', hero_intro='Literal published introduction',
            collection_heading='Published collection', story_heading='Published story',
            story_body='Published story body', show_categories=False).model_dump()
        store = PublicStorefront(slug='tara', name='Independent QA boutique', theme=theme, design=config,
            products=(product,), categories=({'category_id': CATEGORY, 'name': 'Published category'},),
            description='Published boutique description', publication_verified=True, checkout_enabled=True,
            payment_methods=('cod', 'razorpay'))
        html = render_storefront(store, 'https://independent-public.example.test')
        assert f'Published &amp; {theme}' in html
        assert 'NEVER_PUBLIC_' not in html
        (OUT/f'{theme}.html').write_text(html)
        blank = PublicStorefront(**{**store.__dict__, 'design': ThemeConfig(theme=theme, palette=palette).model_dump()})
        (OUT/f'{theme}-defaults.html').write_text(render_storefront(blank, 'https://independent-public.example.test'))
    app = FastAPI()
    app.include_router(create_router(canonical_base='https://independent-public.example.test'))
    with TestClient(app) as client:
        result = client.get(f'/stores/tara/orders/{ORDER}')
        assert result.status_code == 200 and 'no-store' in result.headers['cache-control']
        (OUT/'private-order-shell.html').write_text(result.text)
    sources = ['backend/app/v1/storefront/rendering.py', 'backend/app/v1/storefront/design.py',
        'backend/app/schemas/storefront_theme_v1.py', 'backend/app/api/v1/storefront.py',
        'backend/tests/export_wave4_public_theme_fixtures.py']
    metadata = {'mode': 'actual-renderer-and-order-shell-with-synthetic-public-provider-dto-no-database',
        'source_head': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'source_hashes': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources},
        'fixture_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.html')},
        'product_id': PRODUCT, 'sku_id': SKU, 'order_id': ORDER}
    (OUT/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
