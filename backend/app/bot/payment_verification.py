"""Deterministic verification of a UPI payment screenshot.

The vision subagent (`extract_payment_details`) only EXTRACTS fields; the
pass/fail decision is made here in code — never trust the LLM for the verdict.

Auto-confirm requires (per product owner):
  - payee UPI id / account name matches the method we shared to this customer
  - payment datetime within [QR shared → screenshot received] (+ grace)
  - a readable UTR that has not been used before (anti-replay)
  - amount: >= remaining due → confirm; < remaining → partial (ask remainder)
Anything missing/ambiguous → `manual_review` (seller decides). Never auto-reject.

`evaluate_payment` is pure (no DB / no I/O) so it's fully unit-testable; the
caller supplies `utr_already_used` from a DB lookup and applies the side effects.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
WINDOW_GRACE = timedelta(minutes=15)  # clock-skew / timezone tolerance

# Outcomes
CONFIRMED_FULL = "confirmed_full"
PARTIAL = "partial"
DUPLICATE = "duplicate"
MANUAL_REVIEW = "manual_review"


@dataclass
class Verdict:
    outcome: str                 # one of the constants above
    amount_paise: int = 0        # verified amount to record (0 for duplicate/manual_review)
    utr: Optional[str] = None
    payment_dt: Optional[datetime] = None  # parsed, UTC
    reason: str = ""


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def payee_matches(extracted: dict, method_upi_id: Optional[str], method_account_name: Optional[str]) -> bool:
    """True if the screenshot's payee matches the shared method by UPI id or name.

    UPI ids in screenshots are often masked (e.g. 'sh****@okaxis'); we match the
    bank-handle (@domain) plus any visible leading/trailing chars. Falls back to
    a name match (normalized contains either-way) since the payee name is usually
    the most reliably-visible field.
    """
    ext_upi = (extracted.get("payee_upi_id") or "").strip().lower()
    method_upi = (method_upi_id or "").strip().lower()
    if ext_upi and method_upi:
        if ext_upi == method_upi:
            return True
        if "@" in ext_upi and "@" in method_upi:
            ext_user, ext_dom = ext_upi.split("@", 1)
            m_user, m_dom = method_upi.split("@", 1)
            if ext_dom == m_dom:
                # masked local part: compare the non-mask chars positionally
                mask_chars = set("*xX•·")
                ok = True
                # leading visible chars
                for e, m in zip(ext_user, m_user):
                    if e in mask_chars:
                        break
                    if e != m:
                        ok = False
                        break
                # trailing visible chars
                for e, m in zip(reversed(ext_user), reversed(m_user)):
                    if e in mask_chars:
                        break
                    if e != m:
                        ok = False
                        break
                if ok and any(c in mask_chars for c in ext_user):
                    return True

    ext_name = _norm(extracted.get("payee_name"))
    m_name = _norm(method_account_name)
    if ext_name and m_name and (ext_name == m_name or ext_name in m_name or m_name in ext_name):
        return True
    return False


def parse_payment_datetime(raw: Optional[str], reference_dt: datetime) -> Optional[datetime]:
    """Parse a screenshot datetime string into an aware UTC datetime.

    Assumes IST when no timezone is present, and fills a missing year from
    `reference_dt`. Returns None if unparseable."""
    if not raw or not raw.strip():
        return None
    s = raw.strip()
    dt: Optional[datetime] = None
    try:
        from dateutil import parser as _dp  # type: ignore
        default = datetime(reference_dt.year, 1, 1, tzinfo=IST)
        dt = _dp.parse(s, default=default, fuzzy=True)
    except Exception:
        for fmt in ("%d %b %Y, %I:%M %p", "%d %b %Y %I:%M %p", "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M", "%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M",
                    "%b %d, %Y %I:%M %p", "%d %b %Y"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc)


def within_window(payment_dt: Optional[datetime], shared_at: datetime, received_at: datetime,
                  grace: timedelta = WINDOW_GRACE) -> bool:
    if payment_dt is None:
        return False
    return (shared_at - grace) <= payment_dt <= (received_at + grace)


def _looks_failed(status_text: Optional[str]) -> bool:
    t = (status_text or "").lower()
    return any(w in t for w in ("fail", "declined", "pending", "cancel", "unsuccess"))


def evaluate_payment(
    extracted: dict,
    *,
    method_upi_id: Optional[str],
    method_account_name: Optional[str],
    shared_at: datetime,
    received_at: datetime,
    remaining_due_paise: int,
    utr_already_used: bool,
) -> Verdict:
    """Pure verdict. Caller does the DB utr lookup + side effects."""
    utr = (extracted.get("utr") or "").strip() or None

    if _looks_failed(extracted.get("status_text")):
        return Verdict(MANUAL_REVIEW, reason="screenshot shows a non-success status")
    if not utr:
        return Verdict(MANUAL_REVIEW, reason="no readable UTR / reference number")
    if utr_already_used:
        return Verdict(DUPLICATE, utr=utr, reason="UTR already recorded")
    if not payee_matches(extracted, method_upi_id, method_account_name):
        return Verdict(MANUAL_REVIEW, utr=utr, reason="payee UPI id / name did not match the shared method")

    payment_dt = parse_payment_datetime(extracted.get("datetime"), received_at)
    if not within_window(payment_dt, shared_at, received_at):
        return Verdict(MANUAL_REVIEW, utr=utr, payment_dt=payment_dt,
                       reason="payment time missing or outside the share→screenshot window")

    amount_rupees = extracted.get("amount_rupees")
    try:
        amount_paise = int(round(float(amount_rupees) * 100)) if amount_rupees is not None else 0
    except (TypeError, ValueError):
        amount_paise = 0
    if amount_paise <= 0:
        return Verdict(MANUAL_REVIEW, utr=utr, payment_dt=payment_dt, reason="amount not readable")

    if amount_paise >= remaining_due_paise:
        return Verdict(CONFIRMED_FULL, amount_paise=amount_paise, utr=utr, payment_dt=payment_dt,
                       reason="amount covers the balance")
    return Verdict(PARTIAL, amount_paise=amount_paise, utr=utr, payment_dt=payment_dt,
                   reason="amount less than balance — partial payment")
