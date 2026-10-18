"""Export actual formatter/capability output with synthetic authorization/counts.

No DB, credential, provider, environment-file or application-server operation.
The shared P01 safety policy loads before application imports.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from tests.safety import install_test_safety
install_test_safety()

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import AsyncMock

from app.api.v1.identity import business_view
from app.services.identity import Actor, BusinessAccess
from app.services import onboarding

OUT = ROOT / "artifacts/v1/independent-onboarding-experience"
IDS = [UUID("10000000-0000-4000-8000-000000000081"), UUID("10000000-0000-4000-8000-000000000082")]
UID = UUID("20000000-0000-4000-8000-000000000081")
SOURCES = ["backend/app/services/onboarding.py", "backend/app/services/identity.py",
    "backend/app/api/v1/identity.py", "backend/app/api/v1/auth.py", "backend/tests/safety.py"]


async def main():
    fixtures = {}
    original = onboarding.require_business_access
    try:
        for role in ("owner", "manager", "staff", "viewer"):
            businesses, records = [], {}
            for index, bid in enumerate(IDS):
                business = SimpleNamespace(id=bid, name=["Synthetic QA Atelier", "Second QA Atelier"][index],
                    profile={"support_email": "qa@example.com", "phone": "", "website": ""},
                    profile_version=3, profile_confirmed_at=datetime(2026, 10, 18, tzinfo=timezone.utc))
                access = BusinessAccess(business, SimpleNamespace(role=role), SimpleNamespace())
                onboarding.require_business_access = AsyncMock(return_value=access)
                db = SimpleNamespace(scalar=AsyncMock(side_effect=[0, 0]))
                available = frozenset(f"/v1/businesses/{bid}/{suffix}" for suffix in ("catalogue", "channels"))
                record = await onboarding.onboarding_view(db, Actor(UID, "v1_user"), bid, available_actions=available)
                assert db.scalar.await_count == 2
                records[str(bid)] = record
                businesses.append(business_view(access).model_dump(mode="json"))
            fixtures[role] = {"session": {"user_id": str(UID), "auth_method": "v1_user",
                "csrf_token": "synthetic-browser-csrf-never-real", "businesses": businesses,
                "features": {"support_grants": False, "assisted_operator": False, "customer_links": False}},
                "records": records}
    finally:
        onboarding.require_business_access = original
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"mode": "actual-onboarding-formatter-with-fake-access-and-counts-no-database",
        "source_sha256": {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES},
        "roles": fixtures, "database_connections": 0, "provider_calls": 0}
    (OUT / "fixtures.json").write_text(json.dumps(result, default=str, indent=2) + "\n")
    print("Exported four actual capability/formatter roles for two synthetic businesses; no DB/provider calls.")


if __name__ == "__main__":
    asyncio.run(main())
