"""Exported SSR routes. Integrator supplies canonical provider and registers router.

Never query legacy products or infer publication from catalogue readiness here.
The default dependency returns 503 until the canonical publication seam is wired.
"""
from typing import Protocol
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from app.v1.storefront.rendering import PublicStorefront, render_storefront, canonical_origin


class StorefrontProvider(Protocol):
    async def public_store(self, slug: str) -> PublicStorefront:
        """404 unpublished/foreign/inactive state; verify canonical activation first."""
        ...


async def unavailable_provider() -> StorefrontProvider:
    raise HTTPException(503, 'Public catalogue integration is not configured', headers={'X-Robots-Tag': 'noindex, nofollow'})


def create_router(*, canonical_base: str, provider_dependency=unavailable_provider) -> APIRouter:
    origin = canonical_origin(canonical_base)  # Fail at configuration, not from Host headers.
    routes = APIRouter(prefix='/stores', tags=['public-storefront-pages'])

    async def page(slug, provider, product_id=None, category_id=None):
        try:
            store = await provider.public_store(slug)
            if store.slug != slug:
                raise LookupError('Storefront unavailable')
            html = render_storefront(store, origin, product_id=product_id, category_id=category_id)
        except HTTPException as error:
            error.headers={**(error.headers or {}),'X-Robots-Tag':'noindex, nofollow','Cache-Control':'no-store'}
            raise
        except LookupError:
            raise HTTPException(404, 'Page unavailable', headers={'X-Robots-Tag': 'noindex, nofollow'})
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Catalogue temporarily unavailable', headers={'X-Robots-Tag': 'noindex, nofollow'})
        return HTMLResponse(html, headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'", 'Referrer-Policy': 'same-origin'})

    @routes.get('/{slug}', response_class=HTMLResponse)
    async def store_page(slug: str, provider: StorefrontProvider = Depends(provider_dependency)):
        return await page(slug, provider)

    @routes.get('/{slug}/products/{product_id}', response_class=HTMLResponse)
    async def product_page(slug: str, product_id: UUID, provider: StorefrontProvider = Depends(provider_dependency)):
        return await page(slug, provider, product_id=product_id)

    @routes.get('/{slug}/categories/{category_id}', response_class=HTMLResponse)
    async def category_page(slug: str, category_id: UUID, provider: StorefrontProvider = Depends(provider_dependency)):
        return await page(slug, provider, category_id=category_id)

    @routes.get('/{slug}/orders/{order_id}', response_class=HTMLResponse)
    async def private_order_page(slug: str, order_id: UUID):
        # A shell only: no store publication dependency, customer data or token
        # enters public HTML. The session-held capability authorizes a later GET.
        import json
        import re
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', slug):
            raise HTTPException(404, 'Order page unavailable')
        context = json.dumps({"slug":slug,"orderId":str(order_id)})
        html = f'''<!doctype html><html lang="en" data-theme="catalogue"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Your order</title><link rel="stylesheet" href="/storefront-assets/src/styles.css"><link rel="stylesheet" href="/storefront-assets/src/live.css"><script type="application/json" id="order-context">{context}</script><script type="module" src="/storefront-assets/src/order-status.js"></script></head><body><main class="collection" id="order-status"><h1>Your order</h1><p role="status">Checking order access in this browser session…</p></main><noscript>Order status requires JavaScript and access from the browser session that placed the order.</noscript></body></html>'''
        return HTMLResponse(html, headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow',
            'Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"})

    return routes
