"""Bounded durable-queue recovery entry point; the integrator schedules it."""
from sqlalchemy import and_, or_, select

from app.models.imports_v1 import ImportJob
from app.services.imports_v1 import now, run_job


async def drain_jobs(sessions, *, limit=10, fetcher=None, instagram_provider=None):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Drain limit must be 1 through 20")
    timestamp = now()
    async with sessions.begin() as db:
        rows = (await db.execute(select(ImportJob.business_id, ImportJob.id).where(or_(
            and_(ImportJob.state == "pending", ImportJob.available_at <= timestamp),
            and_(ImportJob.state == "running", ImportJob.lease_expires_at <= timestamp),
        )).order_by(ImportJob.available_at, ImportJob.id).limit(limit))).all()
    completed = 0
    # Dispatch is deliberately serial and bounded. Each job rechecks membership,
    # source binding and lease, and performs fetch outside its DB transactions.
    for business_id, job_id in rows:
        completed += bool(await run_job(sessions, business_id, job_id,
            fetcher=fetcher, instagram_provider=instagram_provider))
    return completed
