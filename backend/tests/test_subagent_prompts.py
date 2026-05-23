"""Tests that the extracted sub-agent prompts format without errors.

These prompts moved out of inline f-strings in claude.py into module-level
constants in app/subagent_prompts.py. Goal of these tests: catch typos in
placeholders (missing/extra {} pairs) before they hit production.
"""
from app import subagent_prompts as p


def test_generate_product_description_formats():
    out = p.GENERATE_PRODUCT_DESCRIPTION_PROMPT.format(product_name="wooden clock")
    assert "wooden clock" in out
    assert "{" not in out  # no unresolved placeholders


def test_suggest_category_formats_with_description():
    out = p.SUGGEST_CATEGORY_PROMPT.format(
        product_name="led clock",
        description_line="Description: LED-lit wall clock\n",
    )
    assert "led clock" in out
    assert "LED-lit wall clock" in out
    # JSON schema braces are intentional literals — they appear as {...} in output.
    assert '{"category_name"' in out


def test_suggest_category_formats_without_description():
    out = p.SUGGEST_CATEGORY_PROMPT.format(product_name="hat", description_line="")
    assert "hat" in out
    assert "Description:" not in out


def test_suggest_tags_for_category_formats():
    out = p.SUGGEST_TAGS_FOR_CATEGORY_PROMPT.format(category_name="Wall Clock")
    assert "Wall Clock" in out


def test_extract_feature_query_formats():
    out = p.EXTRACT_FEATURE_QUERY_PROMPT.format(
        customer_message="kaise chalega",
        tags_json='[{"name": "power_source"}]',
    )
    assert "kaise chalega" in out
    assert "power_source" in out


def test_extract_persona_formats():
    out = p.EXTRACT_PERSONA_PROMPT.format(
        conversation_history="customer: hi\nbot: haan ji",
    )
    assert "customer: hi" in out


def test_intent_classifier_replace_substitution():
    """Intent classifier prompt is consumed by .replace() not .format() to
    avoid having to double-brace the JSON schema. Verify both substitutions land."""
    out = p.INTENT_CLASSIFIER_PROMPT.replace("{history}", "HIST").replace("{message}", "MSG")
    assert "HIST" in out
    assert "MSG" in out
    assert "{history}" not in out
    assert "{message}" not in out
    # Schema braces stay literal — model needs to see them as JSON delimiters.
    assert '"sentiment"' in out
