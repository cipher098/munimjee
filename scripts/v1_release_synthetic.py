"""Static synthetic fixtures for release rehearsal; no app/provider imports.

Only called while both existing P01 database leases are held. All identifiers,
customer placeholders and money values below are synthetic and deterministic.
"""
from __future__ import annotations

import json
import hashlib
import asyncio
import os
import stat
from pathlib import Path
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

STAMP = datetime.fromisoformat("2026-01-01T00:00:00+00:00")


def uid(label):
    return str(uuid5(NAMESPACE_URL, "munimjee:release-rehearsal:v1:" + label))


# Each JSON field uses an explicit PostgreSQL cast, avoiding driver inference.
JSON_FIELDS = {"customer", "address", "items", "options", "source", "keywords",
               "source_binding", "accepted_claim", "payload", "consent_history", "result"}


async def insert(connection, table, row):
    from sqlalchemy import text
    columns = list(row)
    values = [f"CAST(:{key} AS jsonb)" if key in JSON_FIELDS else f":{key}" for key in columns]
    params = {key: json.dumps(value) if key in JSON_FIELDS and value is not None else value for key, value in row.items()}
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


async def seed_base(connection):
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
    original = b'product_ref,title,price,currency,stock,options_state\nRESTORE,Synthetic CSV product,12.50,INR,0,none\n'
    digest = hashlib.sha256(original).hexdigest()
    await insert(connection, "v1_import_assets", dict(id=uid("csv-asset"), business_id=uid("seller"),
        creator_id=uid("owner"), idempotency_key=uid("csv-upload-key"), content_type="text/csv",
        sha256=digest, size_bytes=len(original), content=original, authorized_at=STAMP))
    await insert(connection, "v1_import_jobs", dict(id=uid("csv-job"), business_id=uid("seller"),
        creator_id=uid("owner"), idempotency_key=uid("csv-job-key"), request_hash="b"*64,
        source={"kind":"csv", "document_id":uid("csv-document"), "document_label":"Synthetic retained CSV",
                "media_id":"csv-document:"+uid("csv-document"), "upload_sha256":digest},
        asset_id=uid("csv-asset"), state="pending", authorized_at=STAMP, created_at=STAMP, available_at=STAMP))


async def newer_order_base(connection):
    from sqlalchemy import text
    await connection.execute(text("UPDATE catalogue_skus SET stock_available=stock_available-1 WHERE id=:id"), {"id": uid("sku")})
    await insert(connection, "commerce_orders", order("order-after-backup", paid=True))
    await reservation(connection, "order-after-backup")


FIXTURE_SHA256 = "1a33b7b2cfbc987e4a00611345026dd2bd40b07123357b4098933e11ed14c4d3"
RECORD_FIELDS = {'v1_activity_policies': ('business_id', 'mode', 'revision', 'updated_at'),
 'v1_activity_policy_commands': ('business_id',
                                 'idempotency_key',
                                 'actor_user_id',
                                 'request_hash',
                                 'mode',
                                 'revision',
                                 'notice_version',
                                 'created_at'),
 'v1_activity_contexts': ('id',
                          'business_id',
                          'idempotency_key',
                          'classification',
                          'reason',
                          'policy_revision',
                          'started_at',
                          'expires_at',
                          'retained_until',
                          'lossy'),
 'v1_activity_events': ('id',
                        'business_id',
                        'context_id',
                        'event_kind',
                        'product_id',
                        'created_at'),
 'v1_activity_gaps': ('business_id', 'classification', 'minute', 'reason'),
 'v1_order_activity': ('order_id',
                       'business_id',
                       'classification',
                       'reason',
                       'context_id',
                       'accepted_at'),
 'whatsapp_contacts': ('id',
                       'seller_id',
                       'phone',
                       'name',
                       'last_inbound_at',
                       'opted_out',
                       'utility_opt_in',
                       'marketing_opt_in',
                       'consent_updated_at',
                       'consent_history',
                       'created_at'),
 'whatsapp_messages': ('id',
                       'seller_id',
                       'contact_id',
                       'phone_number_id',
                       'provider_message_id',
                       'idempotency_key',
                       'direction',
                       'kind',
                       'text',
                       'payload',
                       'status',
                       'error',
                       'created_at',
                       'updated_at'),
 'whatsapp_enquiry_reviews': ('id',
                              'business_id',
                              'inbound_message_id',
                              'contact_id',
                              'phone_number_id',
                              'reason',
                              'created_at'),
 'v1_activity_sources': ('business_id',
                         'source_kind',
                         'source_id',
                         'classification',
                         'origin',
                         'created_at',
                         'retained_until'),
 'comment_rules': ('id',
                   'seller_id',
                   'name',
                   'enabled',
                   'media_id',
                   'keywords',
                   'product_id',
                   'private_reply',
                   'public_reply',
                   'created_at'),
 'comment_events': ('id',
                    'seller_id',
                    'comment_id',
                    'media_id',
                    'actor_id',
                    'text',
                    'commented_at',
                    'status',
                    'reason',
                    'rule_id',
                    'created_at',
                    'source_account_id',
                    'source_binding',
                    'source_verified_at',
                    'source_verification'),
 'comment_actions': ('id',
                     'seller_id',
                     'event_id',
                     'kind',
                     'body',
                     'status',
                     'error_code',
                     'provider_id',
                     'attempted_at',
                     'created_at',
                     'accepted_claim',
                     'claim_hash',
                     'claim_token',
                     'finalized_at'),
 'comment_action_audits': ('id',
                           'seller_id',
                           'event_id',
                           'action_id',
                           'claim_token',
                           'stage',
                           'before_status',
                           'after_status',
                           'reason',
                           'provider_id',
                           'created_at'),
 'comment_operator_commands': ('id',
                               'business_id',
                               'actor_id',
                               'idempotency_key',
                               'operation',
                               'request_hash',
                               'result',
                               'created_at'),
 'comment_operator_reviews': ('id',
                              'business_id',
                              'event_id',
                              'command_id',
                              'reason',
                              'created_at'),
 'whatsapp_enquiry_closures': ('id',
                               'business_id',
                               'enquiry_id',
                               'command_id',
                               'reason',
                               'created_at')}
TIME_FIELDS = {"created_at", "updated_at", "started_at", "expires_at", "retained_until", "minute",
               "accepted_at", "last_inbound_at", "consent_updated_at", "commented_at",
               "source_verified_at", "attempted_at", "finalized_at"}


def fixture_0056():
    """One checked-in, bounded, versioned fixture; no caller-selected path."""
    from v1_release_rehearsal import require
    path = Path(__file__).with_name("v1_release_fixture_0056.json")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 65536, "Invalid fixed fixture file")
        payload = stream.read(65537)
    require(len(payload) <= 65536 and hashlib.sha256(payload).hexdigest() == FIXTURE_SHA256,
            "Fixed fixture digest differs from reviewed version")
    value = json.loads(payload)
    require(set(value) == {"format", "version", "source_counts", "source_totals", "scoped_counts", "records", "append"}
            and value["format"] == "munimjee.release-fixture.0056" and type(value["version"]) is int
            and value["version"] == 1, "Unsupported fixed fixture contract")
    require(set(value["records"]) == set(RECORD_FIELDS), "Unexpected fixed fixture tables")
    require(sum(value["source_counts"].values()) == 52 and sum(value["append"]["post_counts"].values()) == 58,
            "Fixed source/target counts differ")
    for table, rows in value["records"].items():
        require(len(rows) == value["source_counts"][table], "Fixed record count differs")
        for row in rows:
            require(tuple(row) == RECORD_FIELDS[table], "Unexpected fixed record columns")
            typed_row(row)
    for table, rows in value["append"]["records"].items():
        require(table in RECORD_FIELDS, "Unexpected append table")
        for row in rows:
            require(tuple(row) == RECORD_FIELDS[table], "Unexpected append columns")
            typed_row(row)
    return value


def typed_row(row):
    # Only top-level SQL timestamp columns are converted. JSON timestamps remain
    # exact claim/payload strings, and nullable proof fields stay SQL NULL.
    from v1_release_rehearsal import require
    result = dict(row)
    for key in TIME_FIELDS.intersection(row):
        if row[key] is not None:
            require(isinstance(row[key], str), "Fixture timestamps must be explicit ISO strings")
            value = datetime.fromisoformat(row[key])
            require(value.tzinfo is not None and value.utcoffset().total_seconds() == 0,
                    "Fixture timestamps must be timezone-aware UTC")
            result[key] = value
    return result


async def seed(connection):
    from sqlalchemy import text
    fixture = fixture_0056()
    await seed_base(connection)
    for table, rows in fixture["records"].items():
        for retained in rows:
            row = typed_row(retained)
            if table == "comment_actions" and row["attempted_at"] is not None:
                initial = {**row, "status": "pending", "error_code": None, "claim_token": None,
                           "attempted_at": None, "provider_id": None, "finalized_at": None}
                await insert(connection, table, initial)
                await connection.execute(text("""UPDATE comment_actions SET status='sending',
                  claim_token=:claim_token,attempted_at=:attempted_at WHERE id=:id"""), row_subset(row, ("claim_token", "attempted_at", "id")))
                await connection.execute(text("""UPDATE comment_actions SET status=:status,error_code=:error_code,
                  provider_id=:provider_id,finalized_at=:finalized_at WHERE id=:id"""),
                  row_subset(row, ("status", "error_code", "provider_id", "finalized_at", "id")))
            else:
                await insert(connection, table, {**row, "lossy": False} if table == "v1_activity_contexts" else row)
        if table == "v1_activity_gaps":
            context = fixture["records"]["v1_activity_contexts"][0]
            await connection.execute(text("UPDATE v1_activity_contexts SET lossy=true WHERE id=:id"), {"id": context["id"]})


def row_subset(row, keys):
    return {key: row[key] for key in keys}


async def newer_order(connection):
    from sqlalchemy import text
    fixture = fixture_0056()
    await newer_order_base(connection)
    for table, rows in fixture["append"]["records"].items():
        for row in rows:
            await insert(connection, table, typed_row(row))
    update = fixture["append"]["allowed_updates"][0]
    await connection.execute(text("""UPDATE v1_activity_policies SET mode=:mode,revision=:revision,updated_at=:updated_at
      WHERE business_id=:business_id AND mode=:old_mode AND revision=:old_revision AND updated_at=:old_updated_at"""),
      {**typed_row(update["to"]), "business_id": update["business_id"], "old_mode": update["from"]["mode"],
       "old_revision": update["from"]["revision"], "old_updated_at": typed_row(update["from"])["updated_at"]})


def expected_records(post_cutover=False):
    fixture = fixture_0056()
    rows = fixture["records"]
    if post_cutover:
        for table, extra in fixture["append"]["records"].items():
            rows[table].extend(extra)
        rows["v1_activity_policies"][0].update(fixture["append"]["allowed_updates"][0]["to"])
    return rows


def projection_digest(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def canonical_records(records):
    output = {}
    for table, rows in records.items():
        normalized = []
        for row in rows:
            fields = row_subset(row, RECORD_FIELDS[table])
            for key in TIME_FIELDS.intersection(fields):
                if fields[key] is not None:
                    fields[key] = datetime.fromisoformat(fields[key]).isoformat()
            normalized.append(fields)
        output[table] = sorted(normalized, key=lambda row: json.dumps(row, sort_keys=True))
    return output


def scoped_counts(rows):
    actions = rows["comment_actions"]
    closed = {row["enquiry_id"] for row in rows["whatsapp_enquiry_closures"]}
    return {
      "activity_test_contexts": sum(row["classification"] == "test" for row in rows["v1_activity_contexts"]),
      "activity_lossy_contexts": sum(row["lossy"] is True for row in rows["v1_activity_contexts"]),
      "activity_product_view": sum(row["event_kind"] == "product_view" for row in rows["v1_activity_events"]),
      "activity_checkout_opened": sum(row["event_kind"] == "checkout_opened" for row in rows["v1_activity_events"]),
      "activity_gaps": len(rows["v1_activity_gaps"]),
      "order_activity_test": sum(row["classification"] == "test" for row in rows["v1_order_activity"]),
      "order_activity_unknown": sum(row["classification"] == "unknown" for row in rows["v1_order_activity"]),
      "source_ledger_test_inbound": sum(row["classification"] == "test" and row["origin"] == "inbound" for row in rows["v1_activity_sources"]),
      **{"comment_" + status: sum(row["status"] == status for row in actions) for status in ("pending", "unknown", "sent")},
      "comment_legacy_review_required": sum(row["status"] == "review_required" and row["accepted_claim"] is None for row in actions),
      "bound_claims": sum(row["accepted_claim"] is not None for row in actions),
      "attempted_claims": sum(row["claim_token"] is not None and row["attempted_at"] is not None for row in actions),
      "synthetic_provider_receipts": sum(row["provider_id"] is not None for row in actions),
      "comment_audits": len(rows["comment_action_audits"]), "comment_reviews": len(rows["comment_operator_reviews"]),
      "wa_enquiries_open": sum(row["id"] not in closed for row in rows["whatsapp_enquiry_reviews"]),
      "wa_enquiries_closed": sum(row["id"] in closed for row in rows["whatsapp_enquiry_reviews"]),
      "wa_outbound_messages": sum(row["direction"] == "outbound" for row in rows["whatsapp_messages"])}


async def semantic_state(connection):
    from v1_release_rehearsal import query, require
    records = {}
    for table in RECORD_FIELDS:
        values = list((await query(connection, f'SELECT to_jsonb(t) FROM public."{table}" t LIMIT 1001')).scalars())
        require(len(values) <= 1000, "Semantic projection exceeds row bound")
        records[table] = [json.loads(value) if isinstance(value, str) else value for value in values]
    normalized = canonical_records(records)
    return {"counts": scoped_counts(normalized), "retained_sha256": projection_digest(normalized)}


async def validate_fixture(connection, snapshot, *, post_cutover=False):
    from v1_release_rehearsal import require
    fixture = fixture_0056()
    expected_counts = fixture["append"]["post_counts"] if post_cutover else fixture["source_counts"]
    actual = {name: value["count"] for name, value in snapshot["tables"].items() if value["count"]}
    require(actual == expected_counts, "Data differs from fixed source/target count contract")
    totals = fixture["append"]["post_totals"] if post_cutover else fixture["source_totals"]
    require(snapshot["totals"] == totals, "Fixed monetary/reservation/pending totals differ")
    expected = canonical_records(expected_records(post_cutover))
    wanted = {"counts": scoped_counts(expected), "retained_sha256": projection_digest(expected)}
    require(snapshot["semantics"] == wanted, "Fixed retained semantic fields or links differ")
    if not post_cutover:
        require(wanted["counts"] == fixture["scoped_counts"], "Reviewed source state counts differ")
    require(snapshot["historical_offenders"]["count"] == 0, "Fixed fixture has historical tenant offenders")


async def rollback_owned(transaction):
    """Drain rollback even when cancellation arrives during cleanup."""
    worker = asyncio.create_task(transaction.rollback())
    cancelled = None
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError as error:
            cancelled = error
    worker.result()
    if cancelled is not None:
        raise cancelled


def fk_error(error):
    """Recognize diagnostics through SQLAlchemy/asyncpg wrappers, never text."""
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if getattr(current, "sqlstate", None) == "23503" and getattr(current, "constraint_name", None) == "comment_action_event_tenant":
            return True
        pending.extend(value for value in (getattr(current, "orig", None), getattr(current, "__cause__", None)) if value is not None)
    return False


async def probe_comment_fk(connection):
    """Standalone rollback-only writes; called only at clean owned boundaries."""
    from v1_release_rehearsal import require, snapshot
    require(not connection.in_transaction(), "FK probe requires a clean transaction boundary")
    try:
        before = await snapshot(connection)
    finally:
        await rollback_owned(connection)
    outer = await connection.begin()
    try:
        events = fixture_0056()["records"]["comment_events"]
        def probe(label, seller, event):
            return dict(id=uid(label), seller_id=seller, event_id=event, kind="public",
                        body="Synthetic rollback-only constraint probe", status="pending", created_at=STAMP,
                        accepted_claim=None, claim_hash=None, claim_token=None, attempted_at=None,
                        provider_id=None, finalized_at=None, error_code=None)
        await insert(connection, "comment_actions", probe("probe-positive", uid("seller"), events[0]["id"]))
        await insert(connection, "sellers", dict(id=uid("probe-second-seller"), email="probe-second@example.invalid",
          password_hash="synthetic-not-a-login-hash", business_name="Rollback only", created_at=STAMP))
        savepoint = await connection.begin_nested()
        try:
            try:
                await insert(connection, "comment_actions", probe("probe-negative", uid("probe-second-seller"), events[1]["id"]))
            except Exception as error:
                require(fk_error(error), "Expected exact tenant FK SQLSTATE23503 and constraint name")
            else:
                require(False, "Cross-tenant comment write unexpectedly succeeded")
        finally:
            await rollback_owned(savepoint)
    finally:
        await rollback_owned(outer)
    try:
        require(await snapshot(connection) == before, "Rollback-only FK probe changed retained state")
    finally:
        await rollback_owned(connection)
    return {"same_tenant": "accepted_rolled_back", "cross_tenant": "23503:comment_action_event_tenant",
            "unchanged": True}
