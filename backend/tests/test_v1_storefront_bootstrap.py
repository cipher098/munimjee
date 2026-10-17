"""Rollout cannot expose an unconfigured origin or an incomplete asset package."""
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.storefront_bootstrap import install_storefront
from app.config import settings


def test_disabled_storefront_needs_no_origin_or_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", False)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "V1_STOREFRONT_ASSETS_DIR", str(tmp_path / "absent"))
    app = FastAPI()
    install_storefront(app)
    assert not any(route.path.startswith(("/stores", "/storefront-assets")) for route in app.routes)


@pytest.mark.parametrize("origin", ["", "http://untrusted.example", "https://shop.example/path", "https://shop.example/?token=secret"])
def test_enabled_publication_requires_explicit_origin(monkeypatch, origin):
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", origin)
    with pytest.raises(ValueError):
        install_storefront(FastAPI())


def test_incomplete_package_refuses_enabled_startup(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://configured.example")
    monkeypatch.setattr(settings, "V1_STOREFRONT_ASSETS_DIR", str(tmp_path))
    (tmp_path / "live-entry.js").write_text("// an incomplete deployment")
    with pytest.raises(RuntimeError, match="runtime assets are missing"):
        install_storefront(FastAPI())


@pytest.mark.asyncio
async def test_packaged_runtime_mount_excludes_project_files(monkeypatch):
    monkeypatch.setattr(settings, "V1_STOREFRONT_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://configured.example")
    monkeypatch.setattr(settings, "V1_STOREFRONT_ASSETS_DIR", "")
    app = FastAPI()
    install_storefront(app)
    paths = {route.path for route in app.routes}
    assert {"/stores/{slug}", "/stores/{slug}/orders/{order_id}"} <= paths
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/storefront-assets/src/live-entry.js")
        assert response.status_code == 200 and "mountLiveStorefront" in response.text
        for path in ("/storefront-assets/tests/example.js", "/storefront-assets/node_modules/package.json",
                     "/storefront-assets/package.json", "/storefront-assets/src/../package.json"):
            assert (await client.get(path)).status_code == 404
