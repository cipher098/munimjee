"""Native workspace access and API boundaries on the real migration schema."""
from uuid import uuid4
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.v1.auth import router as auth
from app.api.v1.catalogue import router as catalogue
from app.api.v1.catalogue_workspace import router as workspace
from app.config import settings
from app.database import get_db


@pytest.fixture
async def client(migrated_engine, monkeypatch):
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "V1_ENFORCE_LEGACY_ACCESS", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://test")
    app = FastAPI()
    for router in (auth, catalogue, workspace):
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Origin": "http://test"}) as c:
        yield c


async def signup(client):
    response = await client.post("/api/v1/auth/signup", json={"email": f"{uuid4().hex}@example.com",
        "password": "synthetic-workspace-password", "business_name": "Reviewed Boutique"})
    assert response.status_code == 201, response.text
    return response.json()


def mutation(client):
    return {"X-CSRF-Token": client.cookies["v1_csrf"]}


@pytest.mark.asyncio
async def test_workspace_requires_native_access_and_stays_dark_when_auth_disabled(client, monkeypatch):
    bid = (await signup(client))["businesses"][0]["id"]
    path = f"/v1/businesses/{bid}/catalogue"
    response = await client.get(path)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert "/static/v1_client.js" in response.text and "/static/catalogue_workspace.js" in response.text
    assert "Reviewed Boutique" not in response.text  # Shell never serializes private business data.
    assert (await client.get(f"/v1/businesses/{uuid4()}/catalogue")).status_code == 404
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", False)
    assert (await client.get(path)).status_code == 404
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", True)
    client.cookies.clear()
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "staff"])
async def test_read_only_workspace_roles_cannot_publish_or_activate(client, role):
    bid = (await signup(client))["businesses"][0]["id"]
    store = {"name": "Reviewed Boutique", "slug": "workspace-" + uuid4().hex[:12], "cod_enabled": True}
    path = f"/api/v1/businesses/{bid}/catalogue"
    assert (await client.put(path + "/storefront", json=store)).status_code == 403
    assert (await client.put(path + "/storefront", json=store, headers=mutation(client))).status_code == 200
    assert (await client.get(path + "/checkout-policy")).json() == {"checkout_enabled": False}
    invitation = await client.post(f"/api/v1/businesses/{bid}/invitations", headers=mutation(client),
        json={"email": f"{uuid4().hex}@example.com", "role": role})
    assert invitation.status_code == 201
    data = invitation.json()
    accepted = await client.post("/api/v1/auth/invitations/accept", json={"email": data["email"],
        "password": "synthetic-workspace-password", "token": data["invitation_url"].split("=", 1)[1]})
    assert accepted.status_code == 200
    assert (await client.get(f"/v1/businesses/{bid}/catalogue")).status_code == 200
    assert (await client.get(path + "/products")).status_code == 200
    assert (await client.put(path + "/storefront", json=store, headers=mutation(client))).status_code == 403
    assert (await client.put(path + "/checkout-policy", json={"checkout_enabled": True}, headers=mutation(client))).status_code == 403
    assert (await client.post(path + f"/products/{uuid4()}/activate", json={"seller_reviewed": True,
        "expected_mapping_revision": 1, "expected_legacy_fingerprint": "a" * 64}, headers=mutation(client))).status_code == 403
