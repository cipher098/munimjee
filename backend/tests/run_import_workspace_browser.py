"""Dedicated import browser runner; native mode holds a P01 migrated DB lease."""
import argparse
import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


async def run(native):
    server = await asyncio.create_subprocess_exec(sys.executable, "-m",
        "tests.import_workspace_native_server" if native else "tests.import_workspace_server",
        cwd=ROOT / "backend", env=dict(os.environ))
    try:
        browser = await asyncio.create_subprocess_exec("node", str(ROOT / "backend/tests/browser" /
            ("import_workspace_native.mjs" if native else "import_workspace.mjs")),
            cwd=ROOT, env=dict(os.environ))
        if await browser.wait():
            raise SystemExit(browser.returncode)
    finally:
        if server.returncode is None:
            server.terminate()
        await server.wait()


async def main(native):
    if native:
        # Read only explicit disposable TEST_DATABASE_URL; never .env/fallback.
        from tests.safety import install_test_safety
        # Preserve only explicit browser-tool paths through the safety scrub.
        browser_env = {k: os.environ[k] for k in
            ("PLAYWRIGHT_MODULE", "PLAYWRIGHT_CHROMIUM_EXECUTABLE") if k in os.environ}
        install_test_safety()
        os.environ.update(browser_env)
        from tests.isolated_database import migrated_database
        async with migrated_database():
            await run(True)
    else:
        await run(False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.native))
