"""Native private page access on the actual P01 migration schema."""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.v1.auth import router as auth
from app.api.v1.import_workspace import router as workspace
from app.api.v1.imports import create_router
from app.api.v1.session import require_v1_mutation
from app.config import settings
from app.database import get_db


@pytest.fixture
async def client(migrated_engine, monkeypatch):
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "V1_IMPORTS_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://test")
    app = FastAPI()
    for router in (auth, workspace, create_router(require_v1_mutation)):
        app.include_router(router)
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async def database():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    app.dependency_overrides[get_db] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"Origin": "http://test"}) as c:
        yield c


async def signup(client):
    response = await client.post("/api/v1/auth/signup", json={"email": f"{uuid4().hex}@example.com",
        "password": "synthetic-workspace-password", "business_name": "Import Boutique"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_import_workspace_native_page_scope_and_feature_gate(client, monkeypatch):
    bid = (await signup(client))["businesses"][0]["id"]
    path = f"/v1/businesses/{bid}/imports"
    response = await client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "/static/v1_client.js" in response.text
    assert "/static/import_workspace.js" in response.text
    assert "Import Boutique" not in response.text
    assert (await client.get(f"/v1/businesses/{uuid4()}/imports")).status_code == 404
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", False)
    assert (await client.get(path)).status_code == 404
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", True)
    client.cookies.clear()
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "staff"])
async def test_import_workspace_read_only_roles_and_mutation_csrf(client, role):
    bid = (await signup(client))["businesses"][0]["id"]
    path = f"/api/v1/businesses/{bid}/imports"
    body = {"idempotency_key": str(uuid4()), "source_kind": "website",
            "source_url": "https://example.com/catalogue", "source_authorized": True}
    assert (await client.post(path+"/jobs", json=body)).status_code == 403
    invitation = await client.post(f"/api/v1/businesses/{bid}/invitations", headers={"X-CSRF-Token": client.cookies["v1_csrf"]},
        json={"email": f"{uuid4().hex}@example.com", "role": role})
    assert invitation.status_code == 201
    data = invitation.json()
    accepted = await client.post("/api/v1/auth/invitations/accept", json={"email": data["email"],
        "password": "synthetic-workspace-password", "token": data["invitation_url"].split("=", 1)[1]})
    assert accepted.status_code == 200
    assert (await client.get(f"/v1/businesses/{bid}/imports")).status_code == 200
    assert (await client.get(path+"/jobs")).status_code == 200
    assert (await client.get(path+"/candidates")).status_code == 200
    assert (await client.post(path+"/jobs", json=body, headers={"X-CSRF-Token": client.cookies["v1_csrf"]})).status_code == 403
