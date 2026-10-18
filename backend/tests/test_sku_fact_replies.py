"""Public observation contract and deliberately bounded request classifier."""
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.schemas.sku_fact_replies import ProductFacts, SKUFact
from app.services import sku_fact_replies as service


def fact(stock=None, **updates):
    return SKUFact(sku_id=uuid4(), options={"Size":"M", "Color":"Red"}, price_minor=12345,
        currency="INR", stock_available=stock, **updates)


def test_observation_has_no_legacy_floor_description_or_default_variant():
    facts = ProductFacts(business_id=uuid4(), product_id=uuid4(), product_name="Synthetic dress",
        mapping_revision=2, observed_at=datetime.now(timezone.utc), skus=(fact(), fact(0)), fact_hash="a"*64)
    rendered = service.render(facts)
    assert "₹123.45" in rendered and "availability untracked" in rendered and "recorded out of stock" in rendered
    assert "not a reservation" in rendered and rendered.count("Color: Red; Size: M") == 2
    assert set(facts.model_dump()) == {"business_id","product_id","product_name","mapping_revision","observed_at","skus","fact_hash"}


@pytest.mark.parametrize("text", ["price?", "Is this available?", "what sizes and colors?", "kitna rate hai?"])
def test_factual_question(text):
    assert service.factual_request(text)


@pytest.mark.parametrize("text", ["buy this", "discount?", "best price", "M size please", "2 available?", "refund", "payment sent", "https://instagram.com/reel/x/", "", None])
def test_transactional_variant_selection_or_ambiguous_question_hands_off(text):
    assert not service.factual_request(text)


@pytest.mark.parametrize("updates", [dict(price_minor=True),dict(stock_available=True),dict(stock_available=-1),dict(currency="USD"),dict(options={"Size":"M\nIn stock"})])
def test_malformed_public_facts_rejected(updates):
    values=dict(sku_id=uuid4(),options={},price_minor=100,currency="INR",stock_available=None)
    with pytest.raises(ValidationError):SKUFact(**(values|updates))


def test_other_url_or_transactional_text_does_not_disappear_behind_reel_reference():
    assert service.reel_question('https://instagram.com/reel/x/')=='[customer sent media]'
    assert service.factual_request(service.reel_question('https://instagram.com/reel/x/ price?'))
    assert not service.factual_request(service.reel_question('https://instagram.com/reel/x/ https://foreign.example/new-product'))
    assert not service.factual_request(service.reel_question('https://instagram.com/reel/x/ discount please'))
