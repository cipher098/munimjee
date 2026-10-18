"""Validated public presentation and fixed defaults shared by SSR projections."""
from app.schemas.storefront_theme_v1 import ThemeConfig

DEFAULTS = {
    "editorial": {"hero_eyebrow": "THE CELEBRATION EDIT", "hero_headline": "For moments\nthat stay.", "hero_intro": "Occasionwear, considered. A softer kind of statement.", "collection_heading": "Pieces to make memories in.", "cta": "Explore the edit"},
    "catalogue": {"hero_eyebrow": "EVERYDAY, ELEVATED", "hero_headline": "Good pieces.\nGreat repeats.", "hero_intro": "Considered staples, easy layers, and a daily rotation that feels like you.", "collection_heading": "Your next everyday favourite.", "cta": "Find your everyday"},
    "video": {"hero_eyebrow": "A CLOSER LOOK", "hero_headline": "Made to move\nwith you.", "hero_intro": "Discover the pieces behind the story. Explore our illustrated studio study.", "collection_heading": "From the story to your wardrobe.", "cta": "Explore the pieces"},
}


def public_design(value, theme):
    config = ThemeConfig.model_validate(value if value is not None else {"theme": theme}).model_dump()
    if config["theme"] != theme:
        raise ValueError("Public design theme mismatch")
    return config


def design_text(config, key, fallback=""):
    return config[key] or DEFAULTS[config["theme"]].get(key, fallback)
