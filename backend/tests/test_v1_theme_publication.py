"""Published design rendering and actual migrated composition; no provider sends."""
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4
import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.api.v1.storefront import create_router
from app.schemas.storefront_theme_v1 import ThemeConfig
from app.v1.storefront.rendering import render_storefront
from app.v1.storefront.design import DEFAULTS
from tests.test_v1_storefront_rendering import snapshot, PRODUCT, CATEGORY
from tests.test_storefront_publication import public_api, setup, checkout  # noqa: F401


def payload(html):
    return json.loads(re.search(r'<script id="storefront-data" type="application/json">(.*?)</script>',html,re.S)[1])


@pytest.mark.parametrize('theme',['editorial','catalogue','video'])
@pytest.mark.parametrize('palette',['rose','forest','indigo'])
def test_actual_ssr_uses_strict_published_allowlist_and_defaults(theme,palette):
    design=ThemeConfig(theme=theme,palette=palette,brand_tagline='A & B',hero_headline='A "published" collection',story_heading='A thoughtful story',story_body='Only published story').model_dump()
    html=render_storefront(snapshot(theme=theme,design=design),'https://store.example.test')
    assert f'data-theme="{theme}" class="palette-{palette}"' in html
    assert 'A &amp; B' in html and 'A & B' not in html
    assert 'A &quot;published&quot; collection' in html
    assert DEFAULTS[theme]['hero_eyebrow'] in html
    assert DEFAULTS[theme]['hero_intro'] in html
    assert 'Only published story' in html and 'A thoughtful story' in html
    data=payload(html)
    assert data['store']['design']==design
    assert data['store']['payment_methods']==['cod'] and data['capabilities']['sku_checkout'] is True
    assert set(data['store']['design'])==set(ThemeConfig.model_fields)
    for secret in ('draft_config','published_config','business_id','actor_id','request_hash','result','idempotency_key'):
        assert secret not in html


@pytest.mark.parametrize('theme',['editorial','catalogue','video'])
def test_theme_presentation_toggles_preserve_public_category_pdp_routes_and_commerce(theme):
    design=ThemeConfig(theme=theme,show_story=False,show_categories=False).model_dump()
    store=snapshot(theme=theme,design=design,payment_methods=('cod','razorpay'))
    class Provider:
        async def public_store(self,slug):return store
    async def dependency():return Provider()
    app=FastAPI();app.include_router(create_router(canonical_base='https://store.example.test',provider_dependency=dependency))
    with TestClient(app) as client:
        home=client.get('/stores/tara?theme=video&preview=true&checkout=true')
        category=client.get(f'/stores/tara/categories/{CATEGORY}')
        pdp=client.get(f'/stores/tara/products/{PRODUCT}')
    assert home.status_code==category.status_code==pdp.status_code==200
    assert '<nav aria-label="Categories">' not in home.text and 'id="our-story"' not in home.text
    assert f'/stores/tara/products/{PRODUCT}' in home.text
    data=payload(home.text)
    assert data['categories'] and data['store']['theme']==theme
    assert data['store']['payment_methods']==['cod','razorpay'] and data['capabilities']['sku_checkout'] is True
    assert payload(category.text)['selected_category_id']==CATEGORY
    assert payload(pdp.text)['selected_product_id']==PRODUCT


@pytest.mark.parametrize('change',[{'css':'body{}'},{'palette':'rose onload=alert(1)'},{'hero_headline':'<img>'},{'story_body':{'token':'private'}},{'theme':'video'}])
def test_unvalidated_published_config_fails_closed(change):
    design={**ThemeConfig(theme='editorial').model_dump(),**change}
    with pytest.raises((ValueError,ValidationError)):
        render_storefront(snapshot(design=design),'https://store.example.test')


def test_exact_registered_theme_migration_chain_and_guard_hooks():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.api.v1.theme_settings import router
    config=Config();config.set_main_option('script_location',str(Path(__file__).parents[1]/'alembic'))
    script=ScriptDirectory.from_config(config)
    assert script.get_revision('0052_v1_customer_links').down_revision=='0051_v1_support_grants'
    assert script.get_revision('0050_v1_assistance').down_revision=='0049_v1_storefront_settings'
    assert script.get_revision('0049_v1_storefront_settings').down_revision=='0048_v1_parcel_tracking'
    for route in router.routes:
        if route.methods.intersection({'PUT','POST'}):
            actor=next(dependency for dependency in route.dependant.dependencies if dependency.name=='actor')
            assert actor.call.__name__=='guarded'
            assert 'business.write' in [cell.cell_contents for cell in actor.call.__closure__]


@pytest.mark.asyncio
async def test_mounted_draft_isolation_design_publish_and_canonical_cod_status_all_themes(public_api):
    from app.models.catalogue_v1 import CatalogueSKU
    from app.models.commerce import Storefront
    client,factory=public_api;data=await setup(client,stock=6)
    url=f"/api/v1/businesses/{data['bid']}/theme-settings";path=f"/stores/{data['slug']}";version=0
    for theme in ('editorial','catalogue','video'):
        previous=(await client.get(path)).text
        config={'theme':theme,'hero_headline':f'Published {theme}','palette':'indigo','story_body':'Published seller story'}
        saved=await client.put(url,headers=data['headers'],json={'expected_version':version,'idempotency_key':str(uuid4()),'config':config})
        assert saved.status_code==200,saved.text
        assert (await client.get(path)).text==previous
        preview=await client.get(url+'/preview?checkout=true&theme=unknown')
        assert preview.status_code==200 and f'Published {theme}' in preview.text and '<script' not in preview.text
        published=await client.post(url+'/publish',headers=data['headers'],json={'expected_version':version+1,'idempotency_key':str(uuid4())})
        assert published.status_code==200,published.text
        version+=2
        public=await client.get(path);assert public.status_code==200
        assert payload(public.text)['store']['design']==published.json()['published']
        assert payload(public.text)['store']['theme']==theme
        order=await client.post(f"/api/v1/storefronts/{data['slug']}/checkout",json=checkout(data['sku']))
        assert order.status_code==201,order.text
        status=f"/api/v1/storefronts/{data['slug']}/orders/{order.json()['id']}"
        assert (await client.get(status)).status_code==404
        assert (await client.get(status,params={'token':order.json()['access_token']})).status_code==404
        assert (await client.get(status,headers={'Authorization':'Bearer '+order.json()['access_token']})).status_code==200
        assert order.json()['access_token'] not in public.text
    async with factory() as db:
        assert (await db.get(Storefront,data['bid'])).published is True
        assert (await db.get(CatalogueSKU,data['sku'])).stock_available==3
