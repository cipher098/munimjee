"""P01 lease for actual native app + Worker/SQLite service + Chromium lifetime."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio,os,sys,tempfile
from pathlib import Path
from tests.isolated_database import migrated_database
async def main():
    root=Path(__file__).resolve().parents[2]
    async with migrated_database():
        with tempfile.TemporaryDirectory(prefix='parcel-browser-sqlite-') as temporary:
            config=Path(temporary)/'connector.json'
            # Worker fixture waits until native owner provisioning writes config.
            connector=await asyncio.create_subprocess_exec('node','tests/server.mjs',cwd=root.parent/'parcel-desk-v1-connector',env={**os.environ,'PARCEL_FIXTURE_CONFIG':str(config),'PARCEL_FIXTURE_DATABASE':str(Path(temporary)/'parcel.sqlite')})
            server=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.parcel_browser_server',str(config),cwd=root/'backend',env=dict(os.environ))
            try:
                node=await asyncio.create_subprocess_exec('node',str(root/'backend/tests/browser/parcel-tracking.mjs'),cwd=root)
                code=await node.wait()
                if code:raise SystemExit(code)
            finally:
                for process in (server,connector):
                    if process.returncode is None:process.terminate()
                    await process.wait()
                config.unlink(missing_ok=True)
if __name__=='__main__':asyncio.run(main())
