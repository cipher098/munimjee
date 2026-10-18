"""Explicit public storefront installation with a narrow packaged runtime mount."""
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app.config import settings

_RUNTIME = (
    "styles.css", "live.css", "live-entry.js", "live-app.js", "live-api.js",
    "canonical-contract.js", "checkout-attempt.js", "order-status.js",
    "components.js", "commerce.js", "theme-config.js", "payment-handoff.js", "published-design.js", "activity-client.js",
)


def install_storefront(app):
    if not settings.V1_STOREFRONT_ENABLED:
        return
    from app.api.v1.storefront import create_router
    from app.v1.storefront.seo import (create_seo_router, parse_legacy_redirects,
                                       strict_origin, validate_route_collisions, install_seo_request_fence)

    # Configuration is authoritative; an incoming Host header never publishes a
    # new origin. An enabled deployment must actually package the runtime files.
    origin = strict_origin(settings.PUBLIC_BASE_URL)
    inventory = parse_legacy_redirects(settings.V1_STOREFRONT_LEGACY_REDIRECTS, origin)
    directory = (Path(settings.V1_STOREFRONT_ASSETS_DIR) if settings.V1_STOREFRONT_ASSETS_DIR
                 else Path(__file__).resolve().parents[4] / "frontend/storefront/src")
    if not directory.is_dir() or any(not (directory / name).is_file() for name in _RUNTIME):
        raise RuntimeError("V1 storefront runtime assets are missing; package the JS/CSS directory before enabling publication")

    from app.services.storefront_publication import published_storefront_provider
    seo = create_seo_router(canonical_base=origin, provider_dependency=published_storefront_provider,
                            legacy_redirects=inventory)
    validate_route_collisions(app, seo)
    install_seo_request_fence(app, canonical_base=origin, legacy_redirects=inventory)
    app.include_router(seo)
    app.include_router(create_router(canonical_base=origin, provider_dependency=published_storefront_provider))
    # Do not serve test results, node_modules, package metadata or design files.
    app.mount("/storefront-assets/src", StaticFiles(directory=directory), name="v1-storefront-runtime")
    # main.py declares additional legacy/customer routes after this installer.
    # Validate the completed routing table before the server accepts traffic.
    def validate_installed_seo_routes():
        validate_route_collisions(app, seo)
    app.add_event_handler("startup", validate_installed_seo_routes)
