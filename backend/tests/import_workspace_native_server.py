"""Actual application browser target with one protected synthetic worker hook.

Only launched under the held P01 reset/migration lease. No provider sockets.
"""
from tests.safety import install_test_safety
install_test_safety()
from uuid import UUID
from fastapi import Depends
from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_IMPORT_BRIDGE_ENABLED = True
settings.V1_IMPORTS_ENABLED = False  # Manual synthetic worker hook only.
settings.PUBLIC_BASE_URL = "http://127.0.0.1:4320"
from app.main import app
from app.api.v1.import_workspace import router
from app.api.v1.session import require_v1_mutation
from app.database import AsyncSessionLocal, get_db
from app.services.identity import require_business_access
from app.services.imports_v1 import run_job
from app.v1.imports.fetching import FetchedSource

# Support both the feature checkout and the final coordinator-mounted app.
if not any(getattr(route, "path", "") == "/v1/businesses/{business_id}/imports" for route in app.routes):
    app.include_router(router)


class SyntheticFetcher:
    async def fetch(self, url, **kwargs):
        return FetchedSource(url, "application/ld+json",
            b'{"@type":"Product","sku":"synthetic-dress","name":"Indigo cotton dress",'
            b'"description":"Source text <strong>is data</strong>",'
            b'"offers":{"price":"1299","priceCurrency":"INR"}}')


@app.post("/__import_workspace_fixture/businesses/{business_id}/jobs/{job_id}/run")
async def process_synthetic_job(business_id: UUID, job_id: UUID,
                                actor=Depends(require_v1_mutation), db=Depends(get_db)):
    await require_business_access(db, actor, business_id, "catalogue.write")
    return {"processed": await run_job(AsyncSessionLocal, business_id, job_id,
                                       fetcher=SyntheticFetcher())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=4320, log_level="warning")
