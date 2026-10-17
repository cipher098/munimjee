from datetime import datetime,timezone
from uuid import UUID
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.schemas.checkout_sessions import CheckoutSessionRead,CheckoutStateRead

ORDER="11111111-1111-4111-8111-111111111111"
BASE=f"/api/v1/storefronts/synthetic-boutique/orders/{ORDER}"


def session():
    return dict(contract_version="checkout-session.v1",order_id=ORDER,provider="razorpay",provider_order_id="order_synthetic",key_id="rzp_test_synthetic",mode="test",
        amount_minor=129900,currency="INR",session_token="eyJzeW50aGV0aWMiOiJvbmx5In0.eyJub3RfYXV0aG9yaXR5Ijp0cnVlfQ.c3ludGhldGlj",
        expires_at="2030-01-01T00:15:00Z",merchant_name="Synthetic boutique",prefill={"name":"Synthetic buyer","contact":"+919876543210","email":""},
        verify_url=BASE+"/checkout-session/verify",status_url=BASE+"/checkout-session",order_status_url=BASE)


@pytest.mark.parametrize("field,value",[("key_secret","private"),("webhook_secret","private"),("gateway_credentials",{}),("amount_minor",True),("amount_minor",0),("currency","USD"),("mode","live"),("verify_url","https://evil.invalid/verify"),("status_url",BASE+"/checkout-session?cap=secret"),("status_url","/api/v1/storefronts/../../evil/orders/"+ORDER+"/checkout-session")])
def test_public_handoff_rejects_secrets_ambiguous_values_or_foreign_paths(field,value):
    body=session();body[field]=value
    with pytest.raises(ValidationError):CheckoutSessionRead.model_validate(body)


def test_public_frozen_handoff_fixtures_round_trip():
    root=Path(__file__).resolve().parents[2]/"docs/contracts/checkout-session"
    for name,model in (("session-read",CheckoutSessionRead),("state-read",CheckoutStateRead)):
        body=json.loads((root/(name+".json")).read_text())
        assert model.model_validate(body).model_dump(mode="json")==body
        assert model.model_json_schema()==json.loads((root/(name+".schema.json")).read_text())
