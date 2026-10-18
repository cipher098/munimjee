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
            "import_catalogue_bridges", "v1_parcel_connectors", "v1_order_parcel_links",
            "v1_parcel_observations", "v1_parcel_notifications", "v1_parcel_audits",
            "storefront_theme_settings_v1", "storefront_theme_commands_v1",
            "v1_onboarding_assignments", "v1_assistance_commands",
            "v1_support_grants", "v1_support_commands", "v1_customers", "v1_customer_link_challenges",
            "v1_customer_link_proofs", "v1_customer_associations", "v1_customer_link_audits",
            "v1_activity_policies", "v1_activity_contexts", "v1_activity_events", "v1_order_activity"} <= set(Base.metadata.tables)


def test_versioned_identity_routes_are_mounted_on_actual_application():
    from app.main import app
    paths = {route.path for route in app.routes if "GET" in getattr(route, "methods", set())}
    assert {"/api/v1/me", "/api/v1/businesses", "/api/v1/businesses/{business_id}",
            "/api/v1/businesses/{business_id}/readiness", "/api/v1/auth/session",
            "/api/v1/businesses/{business_id}/onboarding", "/v1",
            "/v1/businesses/{business_id}/catalogue", "/v1/businesses/{business_id}/channels",
            "/v1/businesses/{business_id}/imports", "/v1/businesses/{business_id}/themes",
            "/v1/businesses/{business_id}/payments", "/v1/assistance",
            "/v1/businesses/{business_id}/assistance", "/api/v1/assistance/businesses",
            "/api/v1/businesses/{business_id}/theme-settings",
            "/api/v1/businesses/{business_id}/theme-settings/preview",
            "/api/v1/storefronts/{slug}/products",
            "/api/v1/businesses/{business_id}/catalogue/products",
            "/v1/support", "/api/v1/support/grants",
            "/api/v1/businesses/{business_id}/support/grants",
            "/v1/businesses/{business_id}/analytics", "/api/v1/businesses/{business_id}/analytics",
            "/api/v1/businesses/{business_id}/analytics/activity",
            "/api/v1/businesses/{business_id}/analytics/measurement-policy",
            "/v1/businesses/{business_id}/customers", "/api/v1/businesses/{business_id}/customer-links",
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
    assert scripts.get_heads() == ["0054_v1_activity"]
    assert scripts.get_revision("0054_v1_activity").down_revision == "0053_v1_csv_import"
    assert scripts.get_revision("0053_v1_csv_import").down_revision == "0052_v1_customer_links"
    assert scripts.get_revision("0052_v1_customer_links").down_revision == "0051_v1_support_grants"
    assert scripts.get_revision("0051_v1_support_grants").down_revision == "0050_v1_assistance"
    assert scripts.get_revision("0050_v1_assistance").down_revision == "0049_v1_storefront_settings"
    assert scripts.get_revision("0049_v1_storefront_settings").down_revision == "0048_v1_parcel_tracking"
    assert scripts.get_revision("0048_v1_parcel_tracking").down_revision == "0047_v1_import_catalogue_bridge"
    assert scripts.get_revision("0047_v1_import_catalogue_bridge").down_revision == "0046_v1_import_jobs"
    assert scripts.get_revision("0046_v1_import_jobs").down_revision == "0045_v1_channel_operator"
    assert scripts.get_revision("0045_v1_channel_operator").down_revision == "0044_v1_checkout"
    assert scripts.get_revision("0044_v1_checkout").down_revision == "0043_v1_auth"
    assert scripts.get_revision("0043_v1_auth").down_revision == "0042_instagram_ingress"
    assert scripts.get_revision("0042_instagram_ingress").down_revision == "0041_v1_catalogue"
    assert scripts.get_revision("0041_v1_catalogue").down_revision == "0040_v1_identity"
    assert scripts.get_revision("0040_v1_identity").down_revision == "0039"


def test_parcel_recovery_is_registered_and_default_off():
    from app.workers.celery_app import celery_app
    from app.workers.v1_parcels import recover_parcels
    from app.config import settings
    assert not settings.V1_PARCEL_ENABLED
    assert recover_parcels() == 0
    assert 'app.workers.v1_parcels' in celery_app.conf.include
    assert any(item['task'] == 'app.workers.v1_parcels.recover_parcels'
               and item['schedule'] == 30 for item in celery_app.conf.beat_schedule.values())


def test_raw_activity_cleanup_remains_scheduled_with_collection_off():
    from app.workers.celery_app import celery_app
    from app.config import settings
    assert not settings.V1_ACTIVITY_ENABLED and not settings.V1_ACTIVITY_RETENTION_READY
    assert 'app.workers.v1_activity' in celery_app.conf.include
    celery_app.loader.import_default_modules()
    assert 'app.workers.v1_activity.cleanup_activity' in celery_app.tasks
    assert any(item['task']=='app.workers.v1_activity.cleanup_activity' and item['schedule']==300
               for item in celery_app.conf.beat_schedule.values())
