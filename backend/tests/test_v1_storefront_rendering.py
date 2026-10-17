"""Pure rendering/router tests with an injected synthetic public provider; no DB."""
from dataclasses import replace
import json
import re
from uuid import UUID
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.storefront import create_router
from app.v1.storefront.rendering import PublicStorefront, render_storefront, canonical_origin, safe_json, public_image, public_product

PRODUCT='22222222-2222-4222-8222-222222222201'
SKU='33333333-3333-4333-8333-333333333301'
CATEGORY='44444444-4444-4444-8444-444444444401'


def snapshot(**changes):
    product={'product_id':PRODUCT,'name':'Rose <set>','description':'A "special" set </script><script>bad()</script>','category_id':CATEGORY,'photo_urls':['javascript:bad()','https://media.example.test/rose.jpg'],'floor_price':1,'credentials':'secret','source_evidence':'private','skus':[{'sku_id':SKU,'product_id':PRODUCT,'options':{'Size':'S'},'price_minor':129950,'currency':'INR','stock_available':2,'active':True,'floor_price':2,'private_note':'hidden'}]}
    values=dict(slug='tara',name='Tara "Studio"',theme='editorial',products=(product,),categories=({'category_id':CATEGORY,'name':'Occasion <wear>','private':'secret'},),description='Thoughtful pieces',publication_verified=True,checkout_enabled=True,payment_methods=('cod',))
    values.update(changes)
    return PublicStorefront(**values)


def extract(html,script_id):
    return json.loads(re.search(fr'<script id="{script_id}" type="application/json">(.*?)</script>',html,re.S)[1])


def test_public_projection_escapes_html_json_and_excludes_every_private_extra():
    html=render_storefront(snapshot(),'https://store.example.test',product_id=UUID(PRODUCT))
    assert '<script>bad()' not in html
    assert '&lt;set&gt;' in html
    assert '\\u003c/script' in html
    assert 'floor_price' not in html and 'credentials' not in html and 'source_evidence' not in html and 'private_note' not in html
    data=extract(html,'storefront-data')
    assert set(data['products'][0])=={'product_id','name','description','category_id','photo_urls','skus'}
    assert data['products'][0]['photo_urls']==['https://media.example.test/rose.jpg']
    assert data['store']['payment_methods']==['cod']
    assert not any(key in data for key in ['customer','order','token'])
    assert f'https://store.example.test/stores/tara/products/{PRODUCT}' in html


@pytest.mark.parametrize('theme',['editorial','catalogue','video'])
def test_stable_product_category_links_and_readable_without_javascript(theme):
    html=render_storefront(snapshot(theme=theme),'https://store.example.test')
    assert f'href="/stores/tara/products/{PRODUCT}"' in html
    assert f'href="/stores/tara/categories/{CATEGORY}"' in html
    assert 'Rose &lt;set&gt;' in html and '₹1,299.50' in html
    category=render_storefront(snapshot(theme=theme),'https://store.example.test',category_id=UUID(CATEGORY))
    assert f'rel="canonical" href="https://store.example.test/stores/tara/categories/{CATEGORY}"' in category


@pytest.mark.parametrize('origin',['https://good.test/evil','https://user:pass@good.test','https://good.test?host=x','http://public.test','//evil.test'])
def test_canonical_origin_requires_configured_safe_https_origin(origin):
    with pytest.raises(ValueError):canonical_origin(origin)


def test_unpublished_unknown_product_and_category_fail_closed():
    with pytest.raises(LookupError):render_storefront(snapshot(publication_verified=False),'https://good.test')
    with pytest.raises(LookupError):render_storefront(snapshot(),'https://good.test',product_id=UUID(int=1))
    with pytest.raises(LookupError):render_storefront(snapshot(),'https://good.test',category_id=UUID(int=2))


def test_default_unregistered_provider_cannot_expose_a_store():
    app=FastAPI();app.include_router(create_router(canonical_base='https://canonical.example.test'))
    with TestClient(app) as client:
        response=client.get('/stores/tara')
    assert response.status_code==503 and response.headers['x-robots-tag']=='noindex, nofollow'


def test_router_ignores_host_headers_and_denies_nonpublic_provider_results():
    class Provider:
        async def public_store(self,slug):return snapshot(publication_verified=slug!='hidden',slug=slug)
    async def dependency():return Provider()
    app=FastAPI();app.include_router(create_router(canonical_base='https://canonical.example.test',provider_dependency=dependency))
    with TestClient(app) as client:
        response=client.get('/stores/tara',headers={'Host':'attacker.test','X-Forwarded-Host':'attacker.test'})
        assert response.status_code==200
        assert 'https://canonical.example.test/stores/tara' in response.text
        assert 'attacker.test' not in response.text
        assert "connect-src 'self'" in response.headers['content-security-policy']
        hidden=client.get('/stores/hidden')
        assert hidden.status_code==404 and hidden.headers['x-robots-tag']=='noindex, nofollow'
        foreign=client.get('/stores/tara/products/00000000-0000-4000-8000-000000000001')
        assert foreign.status_code==404 and 'noindex' in foreign.headers['x-robots-tag']


def test_safe_json_roundtrips_without_literal_script_breakout():
    value={'name':'</script><script>& \u2028 \u2029 "Rose"'}
    encoded=safe_json(value)
    assert '<' not in encoded and '&' not in encoded
    assert json.loads(encoded)==value


@pytest.mark.parametrize('url',['/\\evil.test/image','//evil.test/image','https://user:pass@evil.test/image','https://good.test/image?token=secret','https://good.test/image#fragment','https://good.test/white space','/image\n.svg'])
def test_media_rejects_ambiguous_credentials_query_and_control_urls(url):
    assert public_image(url) is None


@pytest.mark.parametrize('field,value',[('name',{'floor_price':1}),('description',{'credentials':'secret'}),('skus',{})])
def test_malformed_product_types_fail_instead_of_stringifying_private_objects(field,value):
    product=dict(snapshot().products[0]);product[field]=value
    with pytest.raises(ValueError):public_product(product)


def test_duplicate_product_and_sku_identities_fail_closed():
    product=snapshot().products[0]
    with pytest.raises(ValueError):render_storefront(snapshot(products=(product,product)),'https://good.test')
    other={**product,'product_id':'22222222-2222-4222-8222-222222222202','skus':[{**product['skus'][0],'product_id':'22222222-2222-4222-8222-222222222202'}]}
    with pytest.raises(ValueError):render_storefront(snapshot(products=(product,other)),'https://good.test')


def test_sku_product_identity_mismatch_and_duplicate_categories_fail_closed():
    product=snapshot().products[0]
    mismatched={**product,'skus':[{**product['skus'][0],'product_id':'22222222-2222-4222-8222-222222222202'}]}
    with pytest.raises(ValueError):public_product(mismatched)
    category={'category_id':CATEGORY,'name':'Duplicate'}
    with pytest.raises(ValueError):render_storefront(snapshot(categories=(category,category)),'https://good.test')
