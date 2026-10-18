"""Bounded raw measurement retention, including while collection is disabled."""
import asyncio
from app.workers.celery_app import celery_app


async def cleanup_once(session_factory=None):
    from app.database import worker_session
    from app.services.activity_v1 import delete_expired
    async with (session_factory or worker_session)() as db:
        return await delete_expired(db, batch_size=500)


@celery_app.task(name="app.workers.v1_activity.cleanup_activity")
def cleanup_activity():
    # Turning collection off cannot turn retention off. A fresh worker_session
    # owns a NullPool engine for this loop and commits only this bounded batch.
    return asyncio.run(cleanup_once())
