"""Feature-gated durable import recovery; pending rows commit before polling."""
from app.config import settings
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.v1_imports.recover_import_jobs")
def recover_import_jobs():
    if not settings.V1_IMPORTS_ENABLED:
        return 0
    # Import retrieval can leave bounded shielded DNS tasks after its deadline.
    # Cancel those tasks on loop shutdown; the legacy helper gathers them and
    # would extend this task beyond the retrieval deadline.
    import asyncio
    return asyncio.run(_drain())


async def _drain():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.v1.imports.runner import drain_jobs
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        return await drain_jobs(async_sessionmaker(engine, expire_on_commit=False), limit=10)
    finally:
        await engine.dispose()
