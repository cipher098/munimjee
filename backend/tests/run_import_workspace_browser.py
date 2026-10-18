"""Dedicated import browser runner; native mode holds a P01 migrated DB lease."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def source_manifest():
    def hashes(paths):
        return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(paths)}
    application = list((ROOT/'backend/app').rglob('*.py'))
    application += list((ROOT/'backend/alembic').rglob('*.py'))
    application += [ROOT/'backend/static'/name for name in
                    ('import_workspace.html','import_workspace.js','import_workspace.css','v1_client.js')]
    harness = [Path(__file__), ROOT/'backend/tests/import_workspace_native_server.py',
               ROOT/'backend/tests/browser/import_workspace_native.mjs']
    return {'commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'application':hashes(application),'harness':hashes(harness)}


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
        async with migrated_database() as engine:
            from sqlalchemy import text
            async with engine.connect() as connection:
                head = await connection.scalar(text('SELECT version_num FROM alembic_version'))
            before, passed = source_manifest(), False
            try:
                await run(True)
                passed = True
            finally:
                after = source_manifest()
                output = ROOT/'artifacts/v1/import-workspace'
                captures = {path.name:hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in sorted(output.glob('native-*.png'))}
                evidence = {'actual_alembic_head':head,'before':before,'after':after,
                            'source_unchanged':before==after,'captures':captures,
                            'browser_exit_success':passed,'physical_device':False,
                            'provider_scope':'Synthetic worker retrieval; no provider send or fetch.'}
                output.mkdir(parents=True,exist_ok=True)
                (output/'native-source-manifest.json').write_text(json.dumps(evidence,indent=2)+'\n')
                if before != after:
                    raise RuntimeError('Native import application or harness changed during acceptance')
    else:
        await run(False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.native))
