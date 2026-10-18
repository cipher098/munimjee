"""Frozen V07 command/read allowlists; no provider credential response fields.

Secret-bearing routes must use parse_command after bounded manual JSON parsing.
FastAPI's default validation response may include rejected input values.
"""
from typing import Annotated, Literal, TypeVar
from uuid import UUID

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr,
    ValidationError, field_validator, model_validator,
)

Version = Annotated[StrictInt, Field(ge=0, le=2_000_000_000)]
ProviderID = Annotated[StrictStr, Field(pattern=r"^[0-9]{1,40}$")]
Fingerprint = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
AttemptState = Literal[
    "pending", "exchanging", "exchange_unknown", "awaiting_assets",
    "awaiting_selection", "setting_up", "setup_unknown", "attached", "failed",
    "cancelled", "expired", "stale",
]
StepState = Literal["not_started", "requesting", "unknown", "confirmed", "failed"]
TestState = Literal[
    "awaiting_recipient", "recipient_verified", "queued", "sending", "accepted",
    "sent", "delivered", "read", "failed", "unknown", "expired", "stale_connection",
]
Blocker = Literal[
    "operator_configuration_missing", "configuration_mismatch", "provider_grants_unverified",
    "webhook_not_configured", "signup_disabled", "test_disabled", "unsupported_flow",
    "expired_authorization", "billing_external", "registration_required",
    "subscription_required", "account_not_selected", "test_recipient_required",
    "native_session_changed", "stale_connection", "verification_unknown",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class Command(Contract):
    idempotency_key: UUID


class StartSignup(Command):
    expected_connection_version: Version
    notice_reviewed: Literal[True]

    @field_validator("notice_reviewed", mode="before")
    @classmethod
    def explicit_notice(cls, value):
        if value is not True:
            raise ValueError("Explicit review is required")
        return value


class ExchangeSignup(Command):
    signed_state: Annotated[StrictStr, Field(min_length=32, max_length=4096)] = Field(repr=False)
    code: Annotated[StrictStr, Field(min_length=1, max_length=8192)] = Field(repr=False)

    @field_validator("code", "signed_state")
    @classmethod
    def bounded_ascii(cls, value):
        if any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ValueError("Invalid authorization response")
        return value


class SignupAssets(Command):
    event: Literal["FINISH"]
    waba_id: ProviderID
    phone_number_id: ProviderID
    provider_business_id: ProviderID


class SelectSignup(Command):
    expected_connection_version: Version
    choice_id: UUID
    waba_id: ProviderID
    phone_number_id: ProviderID
    expected_choice_fingerprint: Fingerprint
    owner_confirmed: Literal[True]
    subscription_confirmed: Literal[True]
    request_registration: StrictBool
    registration_pin: Annotated[StrictStr, Field(pattern=r"^[0-9]{6}$")] | None = Field(default=None, repr=False)

    @field_validator("owner_confirmed", "subscription_confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation is required")
        return value

    @model_validator(mode="after")
    def pin_only_for_registration(self):
        if self.request_registration != (self.registration_pin is not None):
            raise ValueError("Registration choice and PIN must agree")
        return self


class StartTest(Command):
    expected_connection_version: Version
    recipient_authorized: Literal[True]

    @field_validator("recipient_authorized", mode="before")
    @classmethod
    def explicit_recipient(cls, value):
        if value is not True:
            raise ValueError("Explicit recipient authorization is required")
        return value


class SendTest(StartTest):
    recipient_contact_id: UUID
    inbound_message_id: UUID
    fixed_text_version: Literal["wa-connection-test.v1"]


class SafeChoice(Contract):
    choice_id: UUID
    display_name: Annotated[StrictStr, Field(max_length=160)]
    phone_hint: Annotated[StrictStr, Field(min_length=1, max_length=50)]


class ReviewedChoice(SafeChoice):
    """Owner-only exact review; these are business assets, not recipient numbers."""
    waba_id: ProviderID
    phone_number_id: ProviderID
    display_phone_number: Annotated[StrictStr, Field(min_length=1, max_length=50)]
    fingerprint: Fingerprint
    registration_status: Literal["unknown", "registered", "unregistered"]


class SetupState(Contract):
    subscription: StepState
    registration: StepState
    billing: Literal["unknown", "external_action_required"]


class SignupView(Contract):
    contract_version: Literal["whatsapp-signup.v1"]
    business_id: UUID
    attempt_id: UUID
    status: AttemptState
    connection_version: Version
    expires_at: AwareDatetime
    choices: Annotated[tuple[SafeChoice, ...], Field(max_length=100)]
    setup: SetupState
    provider_approval: Literal["not_evaluated"]


class SDKConfiguration(Contract):
    app_id: ProviderID
    config_id: ProviderID
    graph_version: Literal["v26.0"]
    sdk_url: Literal["https://connect.facebook.net/en_US/sdk.js"]
    allowed_message_origin: Literal["https://www.facebook.com"]
    auto_log_app_events: StrictBool
    xfbml: StrictBool

    @model_validator(mode="after")
    def no_implicit_sdk_measurement(self):
        if self.auto_log_app_events or self.xfbml:
            raise ValueError("Implicit SDK measurement and markup are disabled")
        return self


class SignupStartView(Contract):
    contract_version: Literal["whatsapp-signup-start.v1"]
    attempt: SignupView
    signed_state: Annotated[StrictStr, Field(min_length=32, max_length=4096)] = Field(repr=False)
    sdk: SDKConfiguration


class TestView(Contract):
    __test__ = False
    contract_version: Literal["whatsapp-test.v1"]
    business_id: UUID
    test_id: UUID
    connection_version: Version
    status: TestState
    recipient_hint: Annotated[StrictStr, Field(max_length=50)] | None
    inbound_observed_at: AwareDatetime | None
    message_id: UUID | None
    provider_delivery_observed_at: AwareDatetime | None
    delivery_confirmed: StrictBool
    is_current_generation: StrictBool
    proof_source: Literal["not_recorded", "signed_provider_webhook", "synthetic_fixture"]
    message: Annotated[StrictStr, Field(max_length=500)]

    @model_validator(mode="after")
    def delivery_requires_bound_observations(self):
        if self.delivery_confirmed and (
            self.status not in {"delivered", "read"} or not self.is_current_generation
            or self.inbound_observed_at is None or self.message_id is None
            or self.provider_delivery_observed_at is None or self.proof_source != "signed_provider_webhook"
        ):
            raise ValueError("Delivery confirmation requires current bound observations")
        return self


class TestChallengeView(Contract):
    __test__ = False
    contract_version: Literal["whatsapp-test-challenge.v1"]
    test: TestView
    command: Annotated[StrictStr, Field(pattern=r"^MUNIMJEE-WA-TEST:[A-Za-z0-9_-]{22}$")] = Field(repr=False)


class ReviewedChoicesView(Contract):
    contract_version: Literal["whatsapp-signup-choices.v1"]
    business_id: UUID
    attempt_id: UUID
    choices: Annotated[tuple[ReviewedChoice, ...], Field(max_length=100)]


class RecipientReview(Contract):
    contract_version: Literal["whatsapp-test-recipient.v1"]
    business_id: UUID
    test_id: UUID
    connection_version: Version
    recipient_contact_id: UUID
    inbound_message_id: UUID
    phone: Annotated[StrictStr, Field(pattern=r"^[1-9][0-9]{7,14}$")] = Field(repr=False)
    inbound_observed_at: AwareDatetime
    reply_window_expires_at: AwareDatetime
    reply_allowed: StrictBool


class ReadinessView(Contract):
    contract_version: Literal["whatsapp-self-service.v1"]
    business_id: UUID
    onboarding_available: StrictBool
    connection_version: Version
    local_status: Literal["not_connected", "paused", "setup_required", "needs_reconnect", "local_access_verified"]
    blockers: Annotated[tuple[Blocker, ...], Field(max_length=20)]
    provider_approval: Literal["not_evaluated"]
    current_generation_test: TestView | None


class InvalidWhatsAppCommand(ValueError):
    def __init__(self):
        super().__init__("Review the connection details and try again")


T = TypeVar("T", bound=Contract)


def parse_command(model: type[T], document: object) -> T:
    """No input value or nested validation details cross this error boundary."""
    try:
        return model.model_validate(document)
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise InvalidWhatsAppCommand() from None
