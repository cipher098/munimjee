"""Guarded actual-main HTTP acceptance; requires independently allocated P01 lane.

No listener, schema reset or subprocess exists before exact P01 validation. This
is mounted HTTP evidence, not browser/device or real seller migration evidence.
"""
import os
_port = os.environ.get("MUNIMJEE_SEO_QA_PORT", "")
from tests.safety import install_test_safety
install_test_safety()

import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
from tests.isolated_database import migrated_database
from tests.safety import TestSafetyError, validate_test_database


def source_manifest(root):
    paths = sorted([*root.glob("backend/app/**/*.py"), *root.glob("frontend/storefront/src/*"),
        root / "backend/tests/run_v1_seo_independent_mounted.py",
        root / "backend/tests/v1_seo_independent_server.py", root / "backend/tests/v1_seo_independent_mounted.mjs"])
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def probe_environment(source):
    """Keep local process essentials; never pass DB/provider/Node injection keys."""
    return {key: value for key, value in source.items()
            if key in {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE", "MUNIMJEE_SEO_QA_PORT"}}


async def main():
    if not re.fullmatch(r"[1-9][0-9]{3,4}", _port) or not 1024 <= int(_port) <= 65535:
        raise TestSafetyError("Explicit allocated MUNIMJEE_SEO_QA_PORT 1024..65535 required")
    validate_test_database(os.environ)
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "MUNIMJEE_SEO_QA_PORT": _port}
    before = source_manifest(root)
    artifact = root / "artifacts/v1/seo-independent-qa"
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "mounted-source-before.json").write_text(json.dumps(before, sort_keys=True, indent=2) + "\n")
    async with migrated_database():  # Exact name, numeric loopback, reset opt-in, held lease.
        server = await asyncio.create_subprocess_exec(sys.executable, "-m", "tests.v1_seo_independent_server",
            cwd=root / "backend", env=env, stdout=asyncio.subprocess.PIPE)
        probe = None
        try:
            # Never probe a port owned by an unrelated listener. The child emits
            # this only after its own Uvicorn server bound the allocated port.
            ready = await asyncio.wait_for(server.stdout.readline(), 20)
            if ready != b"SEO_QA_BOUND\n" or server.returncode is not None:
                raise RuntimeError("Owned QA listener did not bind; no HTTP requests sent")
            probe_env = probe_environment(env)
            probe = await asyncio.create_subprocess_exec("node", str(root / "backend/tests/v1_seo_independent_mounted.mjs"),
                cwd=root, env=probe_env)
            if await asyncio.wait_for(probe.wait(), 90):
                raise RuntimeError("Mounted SEO probe failed; inspect sanitized result JSON")
        finally:
            for child in (probe, server):
                if child and child.returncode is None:
                    child.terminate()
                    try:
                        await asyncio.wait_for(child.wait(), 5)
                    except asyncio.TimeoutError:
                        child.kill()
                        await child.wait()
            after = source_manifest(root)
            (artifact / "mounted-source-after.json").write_text(json.dumps(after, sort_keys=True, indent=2) + "\n")
            if before != after:
                raise RuntimeError("Mounted source changed during execution; evidence invalid")


if __name__ == "__main__":
    asyncio.run(main())
