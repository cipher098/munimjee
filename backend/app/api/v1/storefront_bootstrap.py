"""Explicit public storefront installation with a narrow packaged runtime mount."""
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app.config import settings

_RUNTIME = (
    "styles.css", "live.css", "live-entry.js", "live-app.js", "live-api.js",
    "canonical-contract.js", "checkout-attempt.js", "order-status.js",
    "components.js", "commerce.js", "theme-config.js", "payment-handoff.js",
)


def install_storefront(app):
    if not settings.V1_STOREFRONT_ENABLED:
        return
    from app.api.v1.storefront import create_router
    from app.v1.storefront.rendering import canonical_origin

    # Configuration is authoritative; an incoming Host header never publishes a
    # new origin. An enabled deployment must actually package the runtime files.
    origin = canonical_origin(settings.PUBLIC_BASE_URL)
    directory = (Path(settings.V1_STOREFRONT_ASSETS_DIR) if settings.V1_STOREFRONT_ASSETS_DIR
                 else Path(__file__).resolve().parents[4] / "frontend/storefront/src")
    if not directory.is_dir() or any(not (directory / name).is_file() for name in _RUNTIME):
        raise RuntimeError("V1 storefront runtime assets are missing; package the JS/CSS directory before enabling publication")

    from app.services.storefront_publication import published_storefront_provider
    app.include_router(create_router(canonical_base=origin, provider_dependency=published_storefront_provider))
    # Do not serve test results, node_modules, package metadata or design files.
    app.mount("/storefront-assets/src", StaticFiles(directory=directory), name="v1-storefront-runtime")
