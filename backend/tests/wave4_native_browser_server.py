"""Test-only actual main app. Run only under the held P01 migration/reset lease.

The sole extra route inserts literal synthetic source facts, scoped by current
native catalogue.write. All review, preview, receipt and theme endpoints are the
actual mounted application. No production runtime imports this module.
"""
from tests.safety import install_test_safety
install_test_safety()

from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import Depends
from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_IMPORTS_ENABLED = False
settings.V1_IMPORT_BRIDGE_ENABLED = True
settings.V1_STOREFRONT_ENABLED = True
settings.PUBLIC_BASE_URL = 'http://127.0.0.1:4322'

from app.main import app
from app.api.v1.session import business_mutation
from app.database import get_db
from app.models.imports_v1 import ImportDraft, ImportJob
from app.v1.imports import parse_candidate


@app.post('/__qa/completion/{business_id}/source-fixture', include_in_schema=False)
async def seed_source(business_id: UUID, actor=Depends(business_mutation('catalogue.write')), db=Depends(get_db)):
    jid = uuid4()
    candidate = parse_candidate({'provenance': dict(business_id=business_id, import_job_id=jid,
        captured_at=datetime.now(timezone.utc), source={'kind': 'website', 'url': 'https://shop.example.com/qa'},
        source_product_id=uuid4().hex), 'facts': dict(title='Independent mounted QA dress',
        description='Literal synthetic fixture facts', price={'amount': '12.50', 'currency': 'INR'},
        stock=5, options=[{'name': 'Size', 'values': ['S', 'M']}, {'name': 'Colour', 'values': ['Red', 'Blue']}])}, business_id=business_id)
    db.add(ImportJob(id=jid, business_id=business_id, creator_id=actor.user_id, idempotency_key=uuid4(),
        request_hash='a'*64, source={'kind': 'website'}))
    await db.flush()
    db.add(ImportDraft(id=candidate.id, business_id=business_id, last_job_id=jid,
        document=candidate.model_dump(mode='json')))
    await db.flush()
    return {'candidate_id': str(candidate.id)}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=4322, log_level='warning')
