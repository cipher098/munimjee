"""Test-only actual main app; launch exclusively through held-lease QA runner."""
import os
_port = os.environ.get("MUNIMJEE_SEO_QA_PORT", "")
from tests.safety import install_test_safety
install_test_safety()

import json
import re
from tests.safety import TestSafetyError, validate_test_database

validate_test_database(os.environ)
if not re.fullmatch(r"[1-9][0-9]{3,4}", _port) or not 1024 <= int(_port) <= 65535:
    raise TestSafetyError("Explicit allocated SEO listener port required")

from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_STOREFRONT_ENABLED = True
settings.PUBLIC_BASE_URL = f"http://127.0.0.1:{_port}"
settings.V1_STOREFRONT_LEGACY_REDIRECTS = json.dumps([{
    "source_origin": settings.PUBLIC_BASE_URL, "source_path": "/legacy-qa-tara",
    "target_path": "/stores/qa-seo-tara", "store_slug": "qa-seo-tara",
    "owner_reference": "synthetic-fixture-only", "reviewed_by": "independent-qa",
    "reviewed_at": "2026-10-18",
}])

from app.main import app

if __name__ == "__main__":
    import asyncio
    import uvicorn
    class OwnedListener(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started and not self.should_exit:
                print("SEO_QA_BOUND", flush=True)
    asyncio.run(OwnedListener(uvicorn.Config(app, host="127.0.0.1", port=int(_port),
        log_level="warning", access_log=False)).serve())
