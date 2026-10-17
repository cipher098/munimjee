"""Single guarded reset path for every database fixture. No admin connection."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.safety import TestSafetyError, sanitized_test_environment, validate_test_database

# Session-scoped advisory lock, held on a dedicated connection through reset,
# migration, the complete yielded fixture, and disposal of its pooled engine.
# Same key across all fixtures/processes: same DB cannot be reset concurrently.
LOCK_ID = 0x4D554E494D


async def acquire_lease(connection, target) -> None:
    actual = await connection.scalar(text("SELECT current_database()"))
    if actual != target.database:
        raise TestSafetyError("Connected database does not match the guarded lane")
    acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID})
    if acquired is not True:
        raise TestSafetyError("Test lane already in use; choose another database/port/lane")


async def migrate() -> None:
    env = sanitized_test_environment(os.environ)
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.migrate_test_database",
        cwd=Path(__file__).resolve().parents[1], env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        raise
    if process.returncode:
        raise RuntimeError("Actual Alembic migration failed:\n" + (stdout + stderr).decode(errors="replace"))


@asynccontextmanager
async def migrated_database():
    target = validate_test_database(os.environ)  # Before engine or connection.
    engine = create_async_engine(target.url, poolclass=NullPool, connect_args={"timeout": 5})
    lease_engine = create_async_engine(
        target.url, poolclass=NullPool, isolation_level="AUTOCOMMIT", connect_args={"timeout": 5}
    )
    try:
        async with lease_engine.connect() as lease:
            await acquire_lease(lease, target)
            # Revalidate immediately before the only destructive SQL path.
            if validate_test_database(os.environ) != target:
                raise TestSafetyError("Test target changed after obtaining the lease")
            await lease.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await lease.execute(text("CREATE SCHEMA public"))
            await migrate()
            try:
                yield engine
            finally:
                await engine.dispose()
            # Closing the dedicated lease connection releases the lock, also on
            # fixture setup/test/migration failure or cancellation.
    finally:
        await engine.dispose()
        await lease_engine.dispose()
