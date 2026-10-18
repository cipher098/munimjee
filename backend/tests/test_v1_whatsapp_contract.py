"""Pure DTO/sanitized-error tests only; no provider or database acceptance."""
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.schemas.whatsapp_self_service import (
    ExchangeSignup, InvalidWhatsAppCommand, ReadinessView, SelectSignup,
    SDKConfiguration, SendTest, SignupAssets, SignupView, StartSignup, StartTest, TestView,
    parse_command,
)

FIXTURE = Path(__file__).resolve().parents[2] / "docs/contracts/whatsapp-self-service/proposal.v1.json"


def start(**changes):
    return {"idempotency_key": str(uuid4()), "expected_connection_version": 0, "notice_reviewed": True, **changes}


@pytest.mark.parametrize("value", [True, False, "0", 1.0, -1, 2_000_000_001, None])
def test_version_rejects_bool_string_fraction_and_out_of_bounds(value):
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(StartSignup, start(expected_connection_version=value))


@pytest.mark.parametrize("value", [1, 0, "true", False, None])
def test_notice_requires_literal_true(value):
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(StartSignup, start(notice_reviewed=value))


def test_commands_forbid_authority_or_provider_secret_fields():
    for extra in ({"business_id": str(uuid4())}, {"actor_user_id": str(uuid4())},
                  {"is_test": False}, {"access_token": "synthetic-never-real-token"}):
        with pytest.raises(InvalidWhatsAppCommand):
            parse_command(StartSignup, start(**extra))


@pytest.mark.parametrize("event", ["FINISH_ONLY_WABA", "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING", "CANCEL", "ERROR"])
def test_unsupported_sdk_variants_are_not_standard_cloud_success(event):
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(SignupAssets, {"idempotency_key": str(uuid4()), "event": event,
            "waba_id": "123", "phone_number_id": "456", "provider_business_id": "789"})


@pytest.mark.parametrize("identifier", [123, True, "1/phone_numbers", "١٢٣", "1" * 41])
def test_sdk_ids_are_bounded_decimal_strings(identifier):
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(SignupAssets, {"idempotency_key": str(uuid4()), "event": "FINISH",
            "waba_id": identifier, "phone_number_id": "456", "provider_business_id": "789"})


def test_secret_command_repr_and_safe_failure_do_not_echo_rejected_input():
    secret = "synthetic-secret-code-never-real"
    command = parse_command(ExchangeSignup, {"idempotency_key": str(uuid4()), "signed_state": "x" * 32, "code": secret})
    assert secret not in repr(command)
    for document in ({"idempotency_key": str(uuid4()), "signed_state": "x" * 32, "code": secret + "\n"},
                     {"idempotency_key": str(uuid4()), "signed_state": "x" * 32, "code": [secret]}):
        with pytest.raises(InvalidWhatsAppCommand) as caught:
            parse_command(ExchangeSignup, document)
        assert secret not in str(caught.value) and caught.value.__cause__ is None
        assert caught.value.__suppress_context__ is True


def test_selection_binds_exact_asset_and_fingerprint_and_never_repr_pin():
    body = {"idempotency_key": str(uuid4()), "expected_connection_version": 3, "choice_id": str(uuid4()),
        "waba_id": "123", "phone_number_id": "456", "expected_choice_fingerprint": "a" * 64,
        "owner_confirmed": True, "subscription_confirmed": True,
        "request_registration": True, "registration_pin": "123456"}
    command = parse_command(SelectSignup, body)
    assert "123456" not in repr(command)
    for change in ({"request_registration": False}, {"registration_pin": None},
                   {"registration_pin": 123456}, {"registration_pin": "12345"},
                   {"owner_confirmed": 1}, {"subscription_confirmed": "true"},
                   {"expected_choice_fingerprint": "A" * 64}, {"choice_id": "123"}):
        with pytest.raises(InvalidWhatsAppCommand):
            parse_command(SelectSignup, {**body, **change})


def test_test_message_cannot_be_a_client_composer_or_privilege_bypass():
    body = {"idempotency_key": str(uuid4()), "expected_connection_version": 1, "recipient_authorized": True,
        "recipient_contact_id": str(uuid4()), "inbound_message_id": str(uuid4()), "fixed_text_version": "wa-connection-test.v1"}
    parse_command(SendTest, body)
    for change in ({"text": "arbitrary reply"}, {"is_test": True}, {"recipient_authorized": 1},
                   {"phone": "919999999999"}, {"fixed_text_version": "other"}):
        with pytest.raises(InvalidWhatsAppCommand):
            parse_command(SendTest, {**body, **change})
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(StartTest, {"idempotency_key": str(uuid4()), "expected_connection_version": 0,
            "recipient_authorized": 1})


def test_frozen_safe_fixtures_validate_and_unknown_outputs_are_rejected():
    fixtures = json.loads(FIXTURE.read_text())
    for model, key in ((ReadinessView, "gated_readiness_example"), (SignupView, "safe_attempt_example"),
                       (TestView, "safe_test_example")):
        value = fixtures[key]
        result = model.model_validate(value)
        assert set(result.model_dump()) == set(value)
        with pytest.raises(InvalidWhatsAppCommand):
            parse_command(model, {**value, "access_token": "synthetic-never-real"})


def test_accepted_or_historical_status_never_claims_current_delivered_proof():
    value = json.loads(FIXTURE.read_text())["safe_test_example"]
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(TestView, {**value, "delivery_confirmed": True})
    delivered = {**value, "status": "delivered", "delivery_confirmed": True, "proof_source": "signed_provider_webhook",
        "provider_delivery_observed_at": "2026-10-18T12:00:01Z"}
    parse_command(TestView, delivered)
    for change in ({"inbound_observed_at": None}, {"message_id": None},
                   {"is_current_generation": False}, {"proof_source": "not_recorded"},
                   {"proof_source": "synthetic_fixture"}):
        with pytest.raises(InvalidWhatsAppCommand):
            parse_command(TestView, {**delivered, **change})


def test_synthetic_delivery_can_only_be_illustrative_never_confirmed():
    value = json.loads(FIXTURE.read_text())["safe_test_example"]
    simulated = {**value, "status": "delivered", "provider_delivery_observed_at": "2026-10-18T12:00:01Z"}
    assert parse_command(TestView, simulated).delivery_confirmed is False
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(TestView, {**simulated, "delivery_confirmed": True})


@pytest.mark.parametrize('effect', ['queued','sending','unknown'])
def test_recorded_pending_effect_cannot_authorize_new_test_even_if_stale(effect):
    value = json.loads(FIXTURE.read_text())["safe_test_example"]
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(TestView, {**value, "status":"stale_connection", "is_current_generation":False,
            "recorded_effect_status":effect, "can_prepare_new_test":True})


def test_read_timestamps_need_explicit_timezone():
    value = json.loads(FIXTURE.read_text())["safe_attempt_example"]
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(SignupView, {**value, "expires_at": "2026-10-18T12:10:00"})


def test_sdk_configuration_is_narrow_current_and_has_no_implicit_measurement():
    body = {"app_id": "123", "config_id": "456", "graph_version": "v26.0",
        "sdk_url": "https://connect.facebook.net/en_US/sdk.js",
        "allowed_message_origin": "https://www.facebook.com", "auto_log_app_events": False, "xfbml": False}
    parse_command(SDKConfiguration, body)
    for change in ({"graph_version": "v23.0"}, {"sdk_url": "https://facebook.com/sdk.js"},
                   {"allowed_message_origin": "https://evilfacebook.com"},
                   {"auto_log_app_events": True}, {"xfbml": True}, {"auto_log_app_events": 0}):
        with pytest.raises(InvalidWhatsAppCommand):
            parse_command(SDKConfiguration, {**body, **change})


def test_readiness_blockers_cannot_be_raw_provider_error_text():
    value = json.loads(FIXTURE.read_text())["gated_readiness_example"]
    with pytest.raises(InvalidWhatsAppCommand):
        parse_command(ReadinessView, {**value, "blockers": ["raw response with a provider secret"]})
