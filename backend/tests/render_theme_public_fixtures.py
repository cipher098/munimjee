"""Capture real SSR routes with a synthetic published provider, without a DB.

Artifacts are synthetic provider fixtures for controlled HTTP browser checks, not
persistence or production evidence. No application main/settings or real I/O.
Run from repository root with PYTHONPATH=backend.
"""
from tests.safety import install_test_safety
install_test_safety()
import json
from pathlib import Path
from uuid import UUID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.storefront import create_router
from app.api.v1.theme_settings import preview_html, PRIVATE_HEADERS
from app.schemas.storefront_theme_v1 import ThemeConfig
from app.v1.storefront.rendering import PublicStorefront

OUTPUT=Path(__file__).resolve().parents[2]/'artifacts/v1/theme-settings/public-provider'
PRODUCT='22222222-2222-4222-8222-222222222201'
CATEGORY='44444444-4444-4444-8444-444444444401'
ORDER='55555555-5555-4555-8555-555555555501'
PALETTES={'editorial':'rose','catalogue':'forest','video':'indigo'}
products=tuple({'product_id':str(UUID(int=UUID(PRODUCT).int+n)),'name':name,'description':'Synthetic published product illustration for local browser verification.','category_id':CATEGORY,'photo_urls':[f'/theme-assets/{asset}.svg'],'skus':[{'sku_id':str(UUID(int=UUID('33333333-3333-4333-8333-333333333301').int+n)),'product_id':str(UUID(int=UUID(PRODUCT).int+n)),'options':{'Size':'M'},'price_minor':129950+n*10000,'currency':'INR','stock_available':6,'active':True}]} for n,(name,asset) in enumerate([('Synthetic Rose Set','rose'),('Synthetic Indigo Dress','indigo'),('Synthetic Linen Layer','sage'),('Synthetic Ivory Co-ord','ivory')]))
class SyntheticPublishedProvider:
    async def public_store(self,slug):
        theme=slug.removeprefix('synthetic-')
        config=ThemeConfig(theme=theme,palette=PALETTES[theme],brand_tagline='A thoughtful collection',hero_headline=f'Your {theme}\ncollection.',hero_intro='Synthetic published design served through the actual storefront renderer.',story_heading='Pieces with a story',story_body='This is a synthetic provider fixture. Products and artwork are local illustrations; no seller data or seller footage is connected.').model_dump()
        return PublicStorefront(slug=slug,name='Synthetic Boutique',theme=theme,design=config,products=products,categories=({'category_id':CATEGORY,'name':'The edit'},),description='Synthetic published provider. No database, real seller, real order or provider.',shipping_policy='Synthetic delivery policy.',return_policy='Synthetic returns policy.',publication_verified=True,checkout_enabled=True,payment_methods=('cod','razorpay'))
async def provider():return SyntheticPublishedProvider()
app=FastAPI();app.include_router(create_router(canonical_base='http://127.0.0.1:4321',provider_dependency=provider))
OUTPUT.mkdir(parents=True,exist_ok=True)
headers={}
with TestClient(app) as client:
    for theme in PALETTES:
        base=f'/stores/synthetic-{theme}'
        for name,route in [('home',base),('pdp',f'{base}/products/{PRODUCT}'),('category',f'{base}/categories/{CATEGORY}'),('status',f'{base}/orders/{ORDER}')]:
            response=client.get(route);assert response.status_code==200,response.text
            filename=f'{theme}-{name}.html';(OUTPUT/filename).write_text(response.text)
            headers[filename]={key:value for key,value in response.headers.items() if key.lower() not in {'content-length','content-type'}}
        config=ThemeConfig(theme=theme,palette=PALETTES[theme],hero_headline=f'Private {theme} draft',story_body='Private synthetic draft study.').model_dump()
        filename=f'{theme}-preview.html';(OUTPUT/filename).write_text(preview_html(config,'Synthetic Private Boutique'))
        headers[filename]={**PRIVATE_HEADERS,'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"}
(OUTPUT/'headers.json').write_text(json.dumps(headers,indent=2)+'\n')
print('Rendered 12 actual SSR route fixtures using a synthetic published provider + 3 private preview fixtures. No DB/provider/network proof.')
