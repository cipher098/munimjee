"""Actual mounted browser acceptance; no lane, reset or credentials fallback."""
import os
_browser_module = os.environ.get('MUNIMJEE_PLAYWRIGHT_MODULE')
_browser_binary = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE')
from tests.safety import install_test_safety
install_test_safety()

import asyncio
from pathlib import Path
import sys
from tests.isolated_database import migrated_database


async def main():
    root = Path(__file__).resolve().parents[2]
    async with migrated_database():  # Validates exact assigned P01 URL and holds its lease.
        server = await asyncio.create_subprocess_exec(sys.executable, '-m', 'tests.wave4_native_browser_server',
            cwd=root/'backend', env=dict(os.environ))
        try:
            browser_env = dict(os.environ)
            if _browser_module:
                browser_env['MUNIMJEE_PLAYWRIGHT_MODULE'] = _browser_module
            if _browser_binary:
                browser_env['PLAYWRIGHT_CHROMIUM_EXECUTABLE'] = _browser_binary
            node = await asyncio.create_subprocess_exec('node', str(root/'backend/tests/wave4_native_browser.mjs'),
                cwd=root, env=browser_env)
            result = await node.wait()
            if result:
                raise SystemExit(result)
        finally:
            if server.returncode is None:
                server.terminate()
            await server.wait()


if __name__ == '__main__':
    asyncio.run(main())
