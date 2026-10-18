"""One P01 reset lease across actual migrations/main/server and Chromium."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio
import os
from pathlib import Path
import secrets
import sys
from tests.isolated_database import current_migration_head, migrated_database
from sqlalchemy import text
async def main():
    root = Path(__file__).resolve().parents[2]
    nonce = secrets.token_hex(24)
    async with migrated_database() as engine:
        async with engine.connect() as connection:
            actual = await connection.scalar(text('SELECT version_num FROM alembic_version'))
            assert actual == current_migration_head(), 'Actual Alembic head differs from repository source'
            print(f'Actual migrated Alembic head: {actual}', flush=True)
        server = await asyncio.create_subprocess_exec(sys.executable, '-m', 'tests.channel_hardening_server', nonce,
            cwd=root/'backend', env=dict(os.environ))
        try:
            browser = await asyncio.create_subprocess_exec('node', str(root/'backend/tests/browser/channel_hardening.mjs'),
                cwd=root, env={**os.environ, 'CHANNEL_FIXTURE_NONCE': nonce})
            try:
                result = await asyncio.wait_for(browser.wait(), 180)
            except BaseException:
                if browser.returncode is None:
                    browser.terminate()
                    await browser.wait()
                raise
            if result:
                raise SystemExit(result)
        finally:
            if server.returncode is None:
                server.terminate()
            await server.wait()
if __name__ == '__main__':
    asyncio.run(main())
