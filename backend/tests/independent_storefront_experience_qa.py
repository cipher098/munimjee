"""Export fresh actual SSR for independent experience checks; no DB or network.

Reuses the existing export_wave4_public_theme_fixtures pattern, with the missing
stock/empty/long-text inputs. Only the owned evidence directory is written.
"""
from tests.safety import install_test_safety
install_test_safety()

import hashlib
import json
from pathlib import Path
import subprocess

from app.schemas.storefront_theme_v1 import ThemeConfig
from app.v1.storefront.rendering import PublicStorefront, render_storefront

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/v1/independent-storefront-experience/fixtures"
ORIGIN = "https://storefront-experience.example.test"
PRODUCT = "22222222-2222-4222-8222-222222222201"
SKU = "33333333-3333-4333-8333-333333333301"
CATEGORY = "44444444-4444-4444-8444-444444444401"
BUSINESS = "11111111-1111-4111-8111-111111111101"


def product():
    def sku(suffix, size, stock, active=True):
        return {"sku_id": SKU[:-1] + str(suffix), "product_id": PRODUCT,
                "options": {"Size": size}, "price_minor": 129950, "currency": "INR",
                "stock_available": stock, "active": active}
    return {"product_id": PRODUCT, "name": "Independent occasion dress",
            "description": "A literal reviewed garment description for synthetic browser testing.",
            "category_id": CATEGORY, "photo_urls": [],
            "skus": [sku(1, "M", 2), sku(2, "L", 0), sku(3, "XL", 4, False), sku(4, "S", None)]}


def source_hashes():
    paths = sorted((ROOT / "frontend/storefront/src").glob("*.js")) + sorted((ROOT / "frontend/storefront/src").glob("*.css"))
    paths += [ROOT / name for name in ["backend/app/v1/storefront/rendering.py", "backend/app/v1/storefront/design.py", "backend/app/schemas/storefront_theme_v1.py"]]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = source_hashes()
    dto = product()
    for theme, palette in [("editorial", "rose"), ("catalogue", "forest"), ("video", "indigo")]:
        design = ThemeConfig(theme=theme, palette=palette, hero_headline=f"Independent {theme} collection",
            hero_intro="Literal published introduction.", collection_heading="The independent collection",
            story_heading="Our independent story", story_body="Literal public synthetic boutique story.").model_dump()
        store = PublicStorefront(slug="experience", name="Independent QA Boutique", theme=theme,
            products=(dto,), categories=({"category_id": CATEGORY, "name": "Occasion pieces"},),
            shipping_policy="Confirm delivery with the boutique.", return_policy="Contact the boutique for returns.",
            publication_verified=True, checkout_enabled=True, payment_methods=("cod",), design=design)
        for variant, changes in [("standard", {}), ("empty", {"products": ()}),
            ("long", {"name": "Independent Boutique with a long published business name for narrow mobile screens",
                      "products": ({**dto, "name": "Occasion dress with an exceptionally detailed published garment title"},)})]:
            fixture = PublicStorefront(**{**store.__dict__, **changes})
            (OUT / f"{theme}-{variant}.html").write_text(render_storefront(fixture, ORIGIN))
    public_api_product = {**dto, "contract_version": "catalogue.v2", "mode": "operational", "business_id": BUSINESS,
                          "readiness": "active", "checkout_enabled": True,
                          "skus": [sku for sku in dto["skus"] if sku["active"]]}
    metadata = {"mode": "actual-renderer-and-live-source-synthetic-HTTP-no-database",
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_hashes_before": before, "source_hashes_after": source_hashes(),
        "source_unchanged_during_export": before == source_hashes(), "product_id": PRODUCT, "sku_id": SKU,
        "api_product": public_api_product,
        "fixture_hashes": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(OUT.glob("*.html"))}}
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Exported {len(metadata['fixture_hashes'])} fresh actual SSR fixtures; source unchanged={metadata['source_unchanged_during_export']}; no DB/network.")


if __name__ == "__main__":
    main()
