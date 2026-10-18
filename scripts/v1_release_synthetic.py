"""Static synthetic fixtures for release rehearsal; no app/provider imports.

Only called while both existing P01 database leases are held. All identifiers,
customer placeholders and money values below are synthetic and deterministic.
"""
from __future__ import annotations

import json
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

STAMP = datetime.fromisoformat("2026-01-01T00:00:00+00:00")


def uid(label):
    return str(uuid5(NAMESPACE_URL, "munimjee:release-rehearsal:v1:" + label))


# Each JSON field uses an explicit PostgreSQL cast, avoiding driver inference.
JSON_FIELDS = {"customer", "address", "items", "options"}


async def insert(connection, table, row):
    from sqlalchemy import text
    columns = list(row)
    values = [f"CAST(:{key} AS jsonb)" if key in JSON_FIELDS else f":{key}" for key in columns]
    params = {key: json.dumps(value) if key in JSON_FIELDS else value for key, value in row.items()}
    # Identifiers come exclusively from constants in this module.
    await connection.execute(text(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(values)})"), params)


def order(label, *, paid=False):
    return dict(id=uid(label), seller_id=uid("seller"), customer_id=uid("customer"),
                idempotency_key=uid(label + "-key"), request_hash="a" * 64,
                customer={"name": "Synthetic Rehearsal"}, address={"synthetic": True},
                items=[{"_inventory_engine": "sku.v1", "sku_id": uid("sku"), "quantity": 1, "price_minor": 1200}],
                note="synthetic release fixture", subtotal=1200, shipping_fee=50, total=1250, currency="INR",
                payment_method="razorpay" if paid else "cod", payment_status="paid" if paid else "pending",
                fulfillment_status="pending", stock_released=False,
                created_at=STAMP, updated_at=STAMP)


async def reservation(connection, label):
    await insert(connection, "sku_reservations", dict(id=uid(label + "-reservation"), business_id=uid("seller"),
        order_id=uid(label), product_id=uid("product"), sku_id=uid("sku"), quantity=1, tracked=True,
        released=False, created_at=STAMP))


async def seed(connection):
    await insert(connection, "sellers", dict(id=uid("seller"), email="release-fixture@example.invalid",
        password_hash="synthetic-not-a-login-hash", business_name="Synthetic Rehearsal", created_at=STAMP))
    await insert(connection, "businesses", dict(id=uid("seller"), name="Synthetic Rehearsal", created_at=STAMP))
    await insert(connection, "users", dict(id=uid("owner"), legacy_seller_id=uid("seller"),
        display_name="Synthetic Owner", created_at=STAMP))
    await insert(connection, "memberships", dict(id=uid("membership"), business_id=uid("seller"),
        user_id=uid("owner"), role="owner", created_at=STAMP))
    await insert(connection, "products", dict(id=uid("product"), seller_id=uid("seller"), name="Synthetic Product",
        listed_price=1200, floor_price=1000, created_at=STAMP))
    await insert(connection, "catalogue_skus", dict(id=uid("sku"), business_id=uid("seller"), product_id=uid("product"),
        options={"size": "synthetic"}, price_minor=1200, currency="INR", stock_available=8, active=True, created_at=STAMP))
    await insert(connection, "commerce_customers", dict(id=uid("customer"), seller_id=uid("seller"),
        name="Synthetic Customer", phone="0000000000", email="synthetic@example.invalid", created_at=STAMP))
    for label, paid in (("order-paid", True), ("order-pending", False)):
        await insert(connection, "commerce_orders", order(label, paid=paid))
        await reservation(connection, label)
    await insert(connection, "sku_payment_attempts", dict(order_id=uid("order-pending"), state="unknown", updated_at=STAMP))
    await insert(connection, "conversations", dict(id=uid("conversation"), seller_id=uid("seller"),
        customer_instagram_id="synthetic-no-provider-account", product_id=uid("product"), created_at=STAMP))
    await insert(connection, "manual_actions", dict(id=uid("action"), seller_id=uid("seller"),
        conversation_id=uid("conversation"), kind="synthetic_review", status="open", created_at=STAMP))


async def validate_fixture(connection, snapshot):
    from v1_release_rehearsal import require
    expected = {"alembic_version": 1, "sellers": 1, "businesses": 1, "users": 1, "memberships": 1,
                "products": 1, "catalogue_skus": 1, "commerce_customers": 1, "commerce_orders": 2,
                "sku_reservations": 2, "sku_payment_attempts": 1, "conversations": 1, "manual_actions": 1}
    actual = {name: value["count"] for name, value in snapshot["tables"].items() if value["count"]}
    require(actual == expected, "Source contains data outside the fixed synthetic fixture")
    require(snapshot["totals"] == {"orders": 2, "placed_total_minor": 2500, "paid_total_minor": 1250,
        "cod_collected_minor": 0, "reservations": 2, "reserved_quantity": 2, "unknown_payments": 1, "open_actions": 1},
        "Synthetic monetary/reservation/pending fixture totals differ")


async def newer_order(connection):
    await insert(connection, "commerce_orders", order("order-after-backup", paid=True))
    await reservation(connection, "order-after-backup")
