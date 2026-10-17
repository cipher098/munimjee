"""P01 lease plus nonce-bound dedicated local real-app browser process."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio
import os
from pathlib import Path
import secrets
import sys
from tests.isolated_database import migrated_database


async def main():
    root=Path(__file__).resolve().parents[2];nonce=secrets.token_hex(24)
    async with migrated_database():
        server=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.public_payment_browser_server',nonce,
            cwd=root/'backend',env=dict(os.environ))
        try:
            node=await asyncio.create_subprocess_exec('node',str(root/'backend/tests/browser/public-payment.mjs'),cwd=root,
                env={**os.environ,'PUBLIC_PAYMENT_FIXTURE_NONCE':nonce})
            try:code=await asyncio.wait_for(node.wait(),150)
            except TimeoutError:
                node.terminate();await node.wait();raise
            if code:raise SystemExit(code)
        finally:
            if server.returncode is None:server.terminate()
            await server.wait()


if __name__=='__main__':asyncio.run(main())
