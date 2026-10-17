"""Integration-owned registration checks; no broker/provider calls."""
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.database import Base


def test_all_foundation_models_are_registered():
    import app.models
    assert {"businesses", "users", "memberships", "catalogue_skus",
            "catalogue_product_mappings", "instagram_ingress", "user_sessions",
            "business_invitations", "identity_audit_events", "catalogue_store_policies",
            "catalogue_activations", "catalogue_creations", "sku_reservations", "sku_payment_attempts", "channel_operations",
            "channel_connection_states", "channel_oauth_attempts",
            "v1_import_assets", "v1_import_jobs", "v1_import_drafts", "v1_import_audits",
            "import_catalogue_bridges"} <= set(Base.metadata.tables)


def test_versioned_identity_routes_are_mounted_on_actual_application():
    from app.main import app
    paths = {route.path for route in app.routes if "GET" in getattr(route, "methods", set())}
    assert {"/api/v1/me", "/api/v1/businesses", "/api/v1/businesses/{business_id}",
            "/api/v1/businesses/{business_id}/readiness", "/api/v1/auth/session",
            "/api/v1/businesses/{business_id}/onboarding", "/v1",
            "/v1/businesses/{business_id}/catalogue", "/v1/businesses/{business_id}/channels",
            "/api/v1/storefronts/{slug}/products",
            "/api/v1/businesses/{business_id}/catalogue/products",
            "/api/v1/businesses/{business_id}/imports/candidates/{candidate_id}/catalogue-preview"} <= paths


def test_celery_discovers_ingress_and_schedules_recovery():
    from app.workers.celery_app import celery_app
    assert "app.workers.instagram_ingress" in celery_app.conf.include
    celery_app.loader.import_default_modules()
    assert "app.workers.instagram_ingress.process_instagram_ingress" in celery_app.tasks
    assert "app.workers.instagram_ingress.recover_instagram_ingress" in celery_app.tasks
    assert any(item["task"] == "app.workers.instagram_ingress.recover_instagram_ingress"
               and item["schedule"] == 30 for item in celery_app.conf.beat_schedule.values())


def test_foundation_migrations_form_one_actual_revision_chain():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0047_v1_import_catalogue_bridge"]
    assert scripts.get_revision("0047_v1_import_catalogue_bridge").down_revision == "0046_v1_import_jobs"
    assert scripts.get_revision("0046_v1_import_jobs").down_revision == "0045_v1_channel_operator"
    assert scripts.get_revision("0045_v1_channel_operator").down_revision == "0044_v1_checkout"
    assert scripts.get_revision("0044_v1_checkout").down_revision == "0043_v1_auth"
    assert scripts.get_revision("0043_v1_auth").down_revision == "0042_instagram_ingress"
    assert scripts.get_revision("0042_instagram_ingress").down_revision == "0041_v1_catalogue"
    assert scripts.get_revision("0041_v1_catalogue").down_revision == "0040_v1_identity"
    assert scripts.get_revision("0040_v1_identity").down_revision == "0039"
