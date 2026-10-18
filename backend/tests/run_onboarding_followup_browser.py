"""Exclusive P01 lease across actual app.main server and Chromium lifecycle."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio
import os
from pathlib import Path
import secrets
import sys
from tests.isolated_database import migrated_database


async def main():
    root = Path(__file__).resolve().parents[2]
    nonce = secrets.token_hex(24)
    async with migrated_database():
        server = await asyncio.create_subprocess_exec(sys.executable, '-m',
            'tests.onboarding_followup_server', nonce, cwd=root / 'backend', env=dict(os.environ))
        try:
            browser = await asyncio.create_subprocess_exec('node',
                str(root / 'backend/tests/browser/onboarding-followup.mjs'), cwd=root,
                env={**os.environ, 'ONBOARDING_FIXTURE_NONCE': nonce})
            try:
                code = await asyncio.wait_for(browser.wait(), 180)
            except TimeoutError:
                browser.terminate()
                await browser.wait()
                raise
            if code:
                raise SystemExit(code)
        finally:
            if server.returncode is None:
                server.terminate()
            await server.wait()


if __name__ == '__main__':
    asyncio.run(main())
