"""Loopback-only actual app for independent wave3 QA; synthetic import transport.

Run only through run_v1_wave3_browser, which holds the guarded P01 DB lease.
These test-only routes are never included in app.main or runtime packaging.
"""
from tests.safety import install_test_safety
install_test_safety()

from uuid import UUID
from fastapi import Depends
from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_IMPORTS_ENABLED = False
settings.V1_STOREFRONT_ENABLED = True
settings.PUBLIC_BASE_URL = 'http://127.0.0.1:4322'

from app.main import app
from app.api.v1.session import require_v1_mutation
from app.database import AsyncSessionLocal, get_db
from app.services.identity import require_business_access
from app.services.imports_v1 import get_job, run_job
from app.v1.imports.fetching import FetchedSource


class SyntheticWebsite:
    async def fetch(self, *args, **kwargs):
        return FetchedSource('https://shop.example.com/dress', 'application/ld+json',
            b'{"@type":"Product","sku":"qa-dress","name":"Synthetic QA dress","description":"Literal synthetic source","offers":{"price":"1299","priceCurrency":"INR","availability":"https://schema.org/InStock"}}')


@app.post('/__qa/imports/{business_id}/{job_id}/run', include_in_schema=False)
async def run_synthetic_import(business_id: UUID, job_id: UUID,
                               actor=Depends(require_v1_mutation), db=Depends(get_db)):
    await require_business_access(db, actor, business_id, 'catalogue.write')
    await get_job(db, actor, business_id, job_id)
    completed = await run_job(AsyncSessionLocal, business_id, job_id, fetcher=SyntheticWebsite())
    return {'completed': completed}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=4322, log_level='warning')
