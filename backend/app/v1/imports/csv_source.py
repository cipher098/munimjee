"""Bounded literal CSV facts; no inference, file identity, or network access."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass

from pydantic import ValidationError

from .contracts import DraftFacts, DraftPrice, clean_text
from .fetching import FetchError

MAX_CSV_BYTES = 256_000
HEADERS = frozenset(("product_ref", "title", "description", "price", "currency", "stock", "options_state"))


class CSVSourceError(FetchError):
    """Only fixed codes, numeric source lines and allowlisted columns escape."""
    def __init__(self, reason: str, *, line: int = 1, column: str | None = None):
        self.line, self.column = line, column
        super().__init__(f"csv_{reason}:line_{min(max(line, 1), MAX_CSV_BYTES)}" + (f":{column}" if column in HEADERS else ""))


@dataclass(frozen=True)
class CSVProduct:
    product_ref: str
    facts: DraftFacts
    line: int


def validate_csv_upload(content: bytes) -> str:
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_CSV_BYTES:
        raise CSVSourceError("size")
    return hashlib.sha256(content).hexdigest()


def _quoting(text: str) -> None:
    # csv.reader(strict=True) permits stray quotes inside unquoted fields. The
    # supported dialect deliberately forbids those, including post-quote text.
    state, line = "start", 1
    for char in text:
        if state == "quoted":
            if char == '"':
                state = "closed"
        elif state == "closed":
            if char == '"':
                state = "quoted"
            elif char == ',':
                state = "start"
            elif char == '\n':
                state = "start"
            else:
                raise CSVSourceError("quoting", line=line)
        elif char == '"':
            if state != "start":
                raise CSVSourceError("quoting", line=line)
            state = "quoted"
        elif char in ',\n':
            state = "start"
        else:
            state = "plain"
        if char == '\n':
            line += 1
    if state == "quoted":
        raise CSVSourceError("quoting", line=line)


def parse_csv(content: bytes) -> tuple[CSVProduct, ...]:
    """Validate every row before returning any candidates to the durable worker."""
    validate_csv_upload(content)
    try:
        text = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise CSVSourceError("encoding") from None
    text = text.replace("\r\n", "\n")
    if any(char == '\ufeff' or char == '\r' or (ord(char) < 32 and char not in '\n\t') or ord(char) == 127 for char in text):
        raise CSVSourceError("control")
    _quoting(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=',', quotechar='"', strict=True)
    products, seen, header = [], set(), None
    try:
        for row in reader:
            if not row:  # Wholly empty physical lines only, never ',,'.
                continue
            line = reader.line_num - sum(cell.count('\n') for cell in row)
            if header is None:
                if len(row) > len(HEADERS) or len(set(row)) != len(row) or not set(row) <= HEADERS or "product_ref" not in row:
                    raise CSVSourceError("headers", line=line)
                header = row
                continue
            if len(products) >= 200:
                raise CSVSourceError("row_limit", line=line)
            if len(row) != len(header):
                raise CSVSourceError("column_count", line=line)
            cells = dict(zip(header, row))
            def text_cell(name, limit, *, required=False):
                raw = cells.get(name, "")
                if len(raw) > limit:
                    raise CSVSourceError("field_limit", line=line, column=name)
                try:
                    return clean_text(raw, limit=limit) if raw.strip() or required else None
                except (ValueError, TypeError):
                    raise CSVSourceError("invalid_fact", line=line, column=name) from None
            reference = text_cell("product_ref", 200, required=True)
            if reference in seen:
                raise CSVSourceError("duplicate_ref", line=line, column="product_ref")
            seen.add(reference)
            title, description = text_cell("title", 200), text_cell("description", 4000)
            amount, currency = text_cell("price", 13), text_cell("currency", 3)
            if bool(amount) != bool(currency):
                raise CSVSourceError("price_currency_pair", line=line, column="currency")
            try:
                price = DraftPrice(amount=amount, currency=currency) if amount else None
            except ValidationError:
                raise CSVSourceError("invalid_fact", line=line, column="price") from None
            stock_text, option_text = text_cell("stock", 7), text_cell("options_state", 7)
            if stock_text is not None and (re.fullmatch(r"[0-9]{1,7}", stock_text) is None or int(stock_text) > 1_000_000):
                raise CSVSourceError("invalid_fact", line=line, column="stock")
            if option_text not in (None, "unknown", "none"):
                raise CSVSourceError("invalid_fact", line=line, column="options_state")
            facts = DraftFacts(title=title, description=description, price=price,
                stock=int(stock_text) if stock_text is not None else None,
                options=() if option_text == "none" else None)
            products.append(CSVProduct(reference, facts, line))
    except csv.Error:
        raise CSVSourceError("quoting", line=reader.line_num) from None
    if not products:
        raise CSVSourceError("no_products")
    return tuple(products)
