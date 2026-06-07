"""Tests for the deterministic UPI screenshot verifier (app.bot.payment_verification).

Pure logic — no DB. Covers payee matching (exact + masked + name), the time
window, and the full evaluate_payment outcome matrix.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.bot import payment_verification as pv

IST = pv.IST


def _ext(**kw) -> dict:
    base = {"payee_upi_id": None, "payee_name": None, "amount_rupees": None,
            "datetime": None, "utr": None, "app": None, "status_text": "Paid"}
    base.update(kw)
    return base


# --- payee matching ---------------------------------------------------------

def test_payee_exact_upi_match():
    assert pv.payee_matches(_ext(payee_upi_id="Shop@okaxis"), "shop@okaxis", "Shop India") is True


def test_payee_masked_upi_same_domain_match():
    # "sh****is@okaxis" — visible prefix 'sh' + suffix 'is' + domain match
    assert pv.payee_matches(_ext(payee_upi_id="sh****@okaxis"), "shop@okaxis", None) is True


def test_payee_name_match_when_upi_absent():
    assert pv.payee_matches(_ext(payee_name="Shop India"), "shop@okaxis", "Shop India") is True


def test_payee_mismatch():
    assert pv.payee_matches(_ext(payee_upi_id="other@ybl", payee_name="Someone"),
                            "shop@okaxis", "Shop India") is False


# --- datetime + window ------------------------------------------------------

def test_parse_and_window_inside():
    ref = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    dt = pv.parse_payment_datetime("5 Jun 2026, 4:28 PM", ref)  # IST → 10:58 UTC
    assert dt is not None and dt.tzinfo is not None
    shared = datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)
    received = datetime(2026, 6, 5, 11, 30, tzinfo=timezone.utc)
    assert pv.within_window(dt, shared, received) is True


def test_window_rejects_payment_before_share():
    shared = datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)
    received = datetime(2026, 6, 5, 11, 0, tzinfo=timezone.utc)
    old = datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc)  # well before share - grace
    assert pv.within_window(old, shared, received) is False


# --- evaluate_payment matrix ------------------------------------------------

def _args(**over):
    a = dict(
        method_upi_id="shop@okaxis", method_account_name="Shop India",
        shared_at=datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 6, 5, 11, 0, tzinfo=timezone.utc),
        remaining_due_paise=115000, utr_already_used=False,
    )
    a.update(over)
    return a


_GOOD_DT = "5 Jun 2026, 3:30 PM"  # 10:00 UTC — inside [10:00,11:00]+grace


def test_confirmed_full():
    v = pv.evaluate_payment(_ext(payee_upi_id="shop@okaxis", amount_rupees=1150,
                                 datetime=_GOOD_DT, utr="UTR123"), **_args())
    assert v.outcome == pv.CONFIRMED_FULL and v.amount_paise == 115000 and v.utr == "UTR123"


def test_partial_payment():
    v = pv.evaluate_payment(_ext(payee_upi_id="shop@okaxis", amount_rupees=500,
                                 datetime=_GOOD_DT, utr="UTR124"), **_args())
    assert v.outcome == pv.PARTIAL and v.amount_paise == 50000


def test_duplicate_utr():
    v = pv.evaluate_payment(_ext(payee_upi_id="shop@okaxis", amount_rupees=1150,
                                 datetime=_GOOD_DT, utr="UTR123"),
                            **_args(utr_already_used=True))
    assert v.outcome == pv.DUPLICATE


def test_manual_when_no_utr():
    v = pv.evaluate_payment(_ext(payee_upi_id="shop@okaxis", amount_rupees=1150,
                                 datetime=_GOOD_DT, utr=None), **_args())
    assert v.outcome == pv.MANUAL_REVIEW


def test_manual_on_payee_mismatch():
    v = pv.evaluate_payment(_ext(payee_upi_id="hacker@ybl", amount_rupees=1150,
                                 datetime=_GOOD_DT, utr="UTRX"), **_args())
    assert v.outcome == pv.MANUAL_REVIEW


def test_manual_outside_window():
    v = pv.evaluate_payment(_ext(payee_upi_id="shop@okaxis", amount_rupees=1150,
                                 datetime="5 Jun 2026, 6:00 AM", utr="UTRY"), **_args())
    assert v.outcome == pv.MANUAL_REVIEW


def test_manual_on_failed_status():
    v = pv.evaluate_payment(_ext(payee_upi_id="shop@okaxis", amount_rupees=1150,
                                 datetime=_GOOD_DT, utr="UTRZ", status_text="Failed"), **_args())
    assert v.outcome == pv.MANUAL_REVIEW


def test_manual_when_amount_unreadable():
    v = pv.evaluate_payment(_ext(payee_upi_id="shop@okaxis", amount_rupees=None,
                                 datetime=_GOOD_DT, utr="UTRA"), **_args())
    assert v.outcome == pv.MANUAL_REVIEW
