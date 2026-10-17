"""Literal structured website extraction and validated media fallback, no AI."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from html.parser import HTMLParser

from pydantic import ValidationError

from .contracts import DraftFacts, DraftPrice, clean_text
from .fetching import FetchError, FetchedSource


class ProductScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("type", "").lower() == "application/ld+json"
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            if len(self.scripts) >= 20:
                raise FetchError("too_many_structured_blocks")
            self.scripts.append("".join(self.parts))
            self.parts = []
            self.active = False


def extract_website(source: FetchedSource) -> tuple[tuple[str, DraftFacts], ...]:
    try:
        text = source.body.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise FetchError("invalid_source_encoding") from exc
    if source.content_type == "text/html":
        parser = ProductScripts()
        parser.feed(text)
        scripts = parser.scripts
    else:
        scripts = [text]
    products: list[dict] = []
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FetchError("ambiguous_structured_json")
            result[key] = value
        return result

    for script in scripts:
        try:
            document = json.loads(script, parse_float=Decimal,
                                  object_pairs_hook=unique_keys,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except FetchError:
            raise
        except (ValueError, RecursionError):
            continue
        pending = list(document) if isinstance(document, list) else [document]
        visited = 0
        while pending:
            item = pending.pop(0)
            visited += 1
            if visited > 1000:
                raise FetchError("structured_source_too_complex")
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("@graph"), list):
                pending.extend(item["@graph"])
            kind = item.get("@type")
            if kind == "Product" or isinstance(kind, list) and "Product" in kind:
                products.append(item)
                if len(products) > 200:
                    raise FetchError("too_many_source_products")
    result = []
    seen = set()
    for item in products:
        key = item.get("@id") or item.get("sku") or item.get("productID")
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            # A lone Product can be stably identified by this source page. For
            # multiple products, never guess identity from mutable list position.
            if len(products) != 1:
                raise FetchError("stable_product_key_required")
            key = "page-product"
        try:
            key = clean_text(key, limit=200)
        except ValueError as exc:
            raise FetchError("invalid_source_product_key") from exc
        if key in seen:
            raise FetchError("duplicate_source_product_key")
        seen.add(key)
        facts = {}
        for source_key, target_key in (("name", "title"), ("description", "description")):
            if isinstance(item.get(source_key), str):
                facts[target_key] = item[source_key]
        offer = item.get("offers")
        if isinstance(offer, dict) and "price" in offer and "priceCurrency" in offer:
            try:
                facts["price"] = DraftPrice(amount=offer["price"], currency=offer["priceCurrency"])
            except ValidationError:
                pass  # An invalid/ambiguous offer remains unknown, never guessed.
        # schema.org availability is not an exact stock count or SKU allocation.
        try:
            result.append((key, DraftFacts.model_validate(facts)))
        except ValidationError as exc:
            raise FetchError("invalid_structured_facts") from exc
    if not result:
        raise FetchError("structured_products_not_found")
    return tuple(result)


def validate_upload(content: bytes, content_type: str) -> str:
    if not content or len(content) > 5_000_000:
        raise FetchError("invalid_upload_size")
    valid = (
        content_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff")
        or content_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")
        or content_type == "video/mp4" and len(content) >= 12 and content[4:8] == b"ftyp"
    )
    if not valid:
        raise FetchError("unsupported_upload_type")
    # Signature validation is not antivirus, full media decoding or fact inference.
    return hashlib.sha256(content).hexdigest()
