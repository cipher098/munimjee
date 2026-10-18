"""Serial P01 lease for actual native/PG report rendering; no providers."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio,os,secrets,sys
from pathlib import Path
from tests.isolated_database import migrated_database


async def main():
    root=Path(__file__).resolve().parents[2];nonce=secrets.token_hex(24)
    async with migrated_database():
        server=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.activity_channel_server',nonce,
            cwd=root/'backend',env=dict(os.environ))
        try:
            child=await asyncio.create_subprocess_exec('node',str(root/'backend/tests/browser/activity-channel.mjs'),
                cwd=root,env={**os.environ,'ACTIVITY_FIXTURE_NONCE':nonce})
            try:code=await asyncio.wait_for(child.wait(),180)
            except TimeoutError:child.terminate();await child.wait();raise
            if code:raise SystemExit(code)
        finally:
            if server.returncode is None:server.terminate()
            await server.wait()


if __name__=='__main__':asyncio.run(main())
