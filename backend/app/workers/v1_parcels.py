"""Default-off recovery for committed parcel intents and cached tracking reads."""
import asyncio
from app.config import settings
from app.workers.celery_app import celery_app


@celery_app.task(name='app.workers.v1_parcels.recover_parcels')
def recover_parcels():
    if not settings.V1_PARCEL_ENABLED:
        return 0
    from app.workers.parcel_tracking import poll_due
    return asyncio.run(poll_due(limit=20))
