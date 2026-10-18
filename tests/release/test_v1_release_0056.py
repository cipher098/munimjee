"""Finite 0056 release-harness units: no database, container or restore proof.

Catalog rows and connection responses below are declared boundary fixtures. They
do not evaluate SQL or establish real FK enforcement, persistence or dump parity.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import v1_release_rehearsal as rehearsal
import v1_release_synthetic as synthetic


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("0056 unit tests must never connect or resolve a host")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


# Independently transcribed from the approved0055 contract, never obtained by
# asking the validator for its own expected row. No quote/case/schema stripping.
KNOWN_FK = (
    "public", "comment_actions", "comment_action_event_tenant", "f",
    "public", "comment_events", ["seller_id", "event_id"], ["seller_id", "id"],
    "a", "a", "s", False, False, False,
    "FOREIGN KEY (seller_id, event_id) REFERENCES comment_events(seller_id, id) NOT VALID",
)
METADATA_MUTATIONS = [
    ("schema-quoted", 0, '"public"'),
    ("table-quoted", 1, '"comment_actions"'),
    ("name-case", 2, "COMMENT_ACTION_EVENT_TENANT"),
    ("type", 3, "p"),
    ("reference-schema-quoted", 4, '"public"'),
    ("reference-table-case", 5, "Comment_Events"),
    ("local-column-order", 6, ["event_id", "seller_id"]),
    ("reference-column-order", 7, ["id", "seller_id"]),
    ("update-action", 8, "c"),
    ("delete-action", 9, "c"),
    ("match-type", 10, "f"),
    ("deferrable", 11, True),
    ("initially-deferred", 12, True),
    ("validated", 13, True),
    ("definition-quoted", 14, 'FOREIGN KEY (seller_id, event_id) REFERENCES "comment_events"(seller_id, id) NOT VALID'),
]


def test_r1_exact_known_fk_and_ordinary_validated_constraint_are_accepted():
    ordinary = ("public", "synthetic_table", "synthetic_pkey", "p", None, None,
                ["id"], None, " ", " ", " ", False, False, True, "PRIMARY KEY (id)")
    rehearsal.validate_constraint_metadata([deepcopy(KNOWN_FK), ordinary])


def test_r1_missing_known_fk_refused():
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.validate_constraint_metadata([])


@pytest.mark.parametrize("label,index,value", METADATA_MUTATIONS, ids=[row[0] for row in METADATA_MUTATIONS])
def test_r1_every_known_fk_field_remains_exact(label, index, value):
    row = list(deepcopy(KNOWN_FK))
    row[index] = value
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.validate_constraint_metadata([row])


def test_r1_unrelated_not_valid_constraint_refused():
    other = ("public", "other_table", "other_fk", "f", "public", "comment_events",
             ["seller_id", "event_id"], ["seller_id", "id"], "a", "a", "s", False, False, False,
             "FOREIGN KEY (seller_id, event_id) REFERENCES comment_events(seller_id, id) NOT VALID")
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.validate_constraint_metadata([deepcopy(KNOWN_FK), other])


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["cast-reparse", "quoted-identifier-change"])
async def test_r1_duplicate_constraint_inventory_uses_only_narrow_normalization(monkeypatch, variant):
    original = "CHECK (((role)::text = ANY ((ARRAY['owner'::character varying])::text[])))"
    reparsed = "CHECK (((role)::text = ANY (ARRAY[('owner'::character varying)::text])))"
    if variant == "quoted-identifier-change":
        original = 'CHECK ("((ARRAY[\'owner\'::character varying])::text[])" IS NOT NULL)'
        reparsed = 'CHECK ("(ARRAY[(\'owner\'::character varying)::text])" IS NOT NULL)'
    calls = []
    async def query(connection, sql, params=None):
        calls.append((connection, sql))
        definition = original if connection == "source" else reparsed
        if "SELECT n.nspname,c.relname,k.conname,k.contype" in sql:
            rows = [deepcopy(KNOWN_FK), ("public", "ordinary", "ordinary_check", "c", None, None,
                ["role"], [], " ", " ", " ", False, False, True, definition)]
        elif "FROM pg_constraint" in sql:
            rows = [["comment_actions", "comment_action_event_tenant", KNOWN_FK[-1], False],
                    ["ordinary", "ordinary_check", definition, True]]
        else:
            rows = []
        return SimpleNamespace(all=lambda: rows)
    monkeypatch.setattr(rehearsal, "query", query)
    source, restored = await rehearsal.schema_fingerprint("source"), await rehearsal.schema_fingerprint("restored")
    assert (source == restored) is (variant == "cast-reparse")
    for label in ("source", "restored"):
        sql = [query for connection, query in calls if connection == label]
        assert sql.index("SET LOCAL search_path = pg_catalog, public") < next(i for i, text in enumerate(sql) if "FROM pg_constraint" in text)


class ProbeTransaction:
    def __init__(self, scene, kind):
        self.scene, self.kind = scene, kind
        self.markers = list(scene.markers)
        self.rolled_back = False

    async def rollback(self):
        assert not self.rolled_back
        self.rolled_back = True
        self.scene.events.append("rollback:" + self.kind)
        self.scene.markers[:] = self.markers
        if self.kind == "outer":
            self.scene.active = False


class ProbeConnection:
    """Transaction/call markers only: it never parses or evaluates SQL."""
    def __init__(self):
        self.active = False
        self.events, self.markers, self.inserted = [], [], []
        self.started = asyncio.Event()
        self.transactions = []

    def in_transaction(self):
        return self.active

    async def rollback(self):
        self.events.append("rollback:autobegin")
        self.active = False

    async def begin(self):
        assert not self.active
        self.active = True
        self.events.append("begin:outer")
        transaction = ProbeTransaction(self, "outer")
        self.transactions.append(transaction)
        return transaction

    async def begin_nested(self):
        assert self.active
        self.events.append("begin:savepoint")
        transaction = ProbeTransaction(self, "savepoint")
        self.transactions.append(transaction)
        return transaction

    async def commit(self):
        pytest.fail("The rollback-only probe committed")


def wrapped_fk_error(mode):
    from sqlalchemy.exc import IntegrityError
    driver = RuntimeError("Message text23503 comment_action_event_tenant must not authorize diagnostics")
    driver.sqlstate = "23505" if mode == "wrong-state" else "23503"
    driver.constraint_name = {"wrong-constraint": "other_tenant_fk", "missing-constraint": None}.get(mode, "comment_action_event_tenant")
    adapter = RuntimeError("opaque adapter")
    adapter.__cause__ = driver
    return IntegrityError("private synthetic SQL withheld", {}, adapter)


def probe_scene(monkeypatch, mode):
    scene = ProbeConnection()
    async def snapshot(connection):
        assert connection is scene
        scene.active = True  # Models SQLAlchemy autobegin, not database state.
        scene.events.append("snapshot")
        return {"markers": list(scene.markers)}
    async def insert(connection, table, row):
        assert connection is scene and scene.active
        row = deepcopy(row)
        scene.inserted.append((table, row))
        if table == "comment_actions":
            actions = [value for name, value in scene.inserted if name == "comment_actions"]
            assert row["kind"] == "public" and row["status"] == "pending"
            assert all(row[key] is None for key in ("accepted_claim", "claim_hash", "claim_token", "attempted_at", "provider_id", "finalized_at"))
            if len(actions) == 1:
                assert row["seller_id"] == synthetic.uid("seller")
                assert row["event_id"] == "215b7f8b-eaf4-5c28-9eb5-ce8bb9a72c49"  # Reviewed pending event.
                if mode == "positive-failure":
                    raise RuntimeError("positive write refused")
                scene.events.append("positive:accepted")
            else:
                assert len(actions) == 2 and "positive:accepted" in scene.events
                assert row["id"] != actions[0]["id"] and row["event_id"] != actions[0]["event_id"]
                assert row["seller_id"] != actions[0]["seller_id"]
                assert row["event_id"] == "6cb62451-5f68-5156-b4da-799169b3d119"  # Different unknown event.
                temporary = [value for name, value in scene.inserted if name == "sellers"]
                assert len(temporary) == 1 and row["seller_id"] == temporary[0]["id"]
                assert scene.events[-1] == "begin:savepoint"
                scene.events.append("negative:attempted")
                scene.started.set()
                if mode == "cancel":
                    await asyncio.Event().wait()
                if mode != "unexpected-success":
                    raise wrapped_fk_error(mode)
        else:
            assert table == "sellers" and row["id"] == synthetic.uid("probe-second-seller")
            scene.events.append("temporary-seller:accepted")
        scene.markers.append((table, row["id"]))
    monkeypatch.setattr(rehearsal, "snapshot", snapshot)
    monkeypatch.setattr(synthetic, "insert", insert)
    return scene


def assert_probe_unwound(scene, *, savepoint=True):
    assert not scene.active and not scene.markers
    assert all(t.rolled_back for t in scene.transactions)
    assert "rollback:outer" in scene.events
    if savepoint:
        assert scene.events.index("rollback:savepoint") < scene.events.index("rollback:outer")


@pytest.mark.asyncio
async def test_r2_wrapped_named23503_has_positive_then_negative_and_rollback(monkeypatch):
    scene = probe_scene(monkeypatch, "valid")
    result = await synthetic.probe_comment_fk(scene)
    assert result == {"same_tenant": "accepted_rolled_back", "cross_tenant": "23503:comment_action_event_tenant", "unchanged": True}
    assert scene.events.count("snapshot") == 2
    assert_probe_unwound(scene)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["wrong-state", "wrong-constraint", "missing-constraint", "unexpected-success"])
async def test_r2_wrong_diagnostic_or_no_negative_error_is_not_fk_proof(monkeypatch, mode):
    scene = probe_scene(monkeypatch, mode)
    with pytest.raises(rehearsal.RehearsalError):
        await synthetic.probe_comment_fk(scene)
    assert_probe_unwound(scene)


@pytest.mark.asyncio
async def test_r2_positive_insert_failure_rolls_back_outer(monkeypatch):
    scene = probe_scene(monkeypatch, "positive-failure")
    with pytest.raises(RuntimeError, match="positive write refused"):
        await synthetic.probe_comment_fk(scene)
    assert_probe_unwound(scene, savepoint=False)
    assert len(scene.inserted) == 1


@pytest.mark.asyncio
async def test_r2_cancelled_negative_probe_drains_savepoint_and_outer(monkeypatch):
    scene = probe_scene(monkeypatch, "cancel")
    task = asyncio.create_task(synthetic.probe_comment_fk(scene))
    await asyncio.wait_for(scene.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_probe_unwound(scene)


SOURCE_COUNTS = {
    "alembic_version": 1, "sellers": 1, "businesses": 1, "users": 1, "memberships": 1,
    "products": 1, "catalogue_skus": 1, "commerce_customers": 1, "commerce_orders": 2,
    "sku_reservations": 2, "sku_payment_attempts": 1, "conversations": 1, "manual_actions": 1,
    "v1_import_assets": 1, "v1_import_jobs": 1, "v1_activity_policies": 1,
    "v1_activity_policy_commands": 1, "v1_activity_contexts": 1, "v1_activity_events": 2,
    "v1_activity_gaps": 1, "v1_order_activity": 2, "whatsapp_contacts": 1, "whatsapp_messages": 2,
    "whatsapp_enquiry_reviews": 2, "v1_activity_sources": 1, "comment_rules": 1,
    "comment_events": 4, "comment_actions": 4, "comment_action_audits": 8,
    "comment_operator_commands": 2, "comment_operator_reviews": 1, "whatsapp_enquiry_closures": 1,
}
SOURCE_TOTALS = {"orders": 2, "placed_total_minor": 2500, "paid_total_minor": 1250,
    "cod_collected_minor": 0, "reservations": 2, "reserved_quantity": 2, "unknown_payments": 1,
    "open_actions": 1, "available_stock": 8}
SCOPED = {"activity_test_contexts": 1, "activity_lossy_contexts": 1, "activity_product_view": 1,
    "activity_checkout_opened": 1, "activity_gaps": 1, "order_activity_test": 1,
    "order_activity_unknown": 1, "source_ledger_test_inbound": 1, "comment_pending": 1,
    "comment_unknown": 1, "comment_sent": 1, "comment_legacy_review_required": 1, "bound_claims": 3,
    "attempted_claims": 2, "synthetic_provider_receipts": 1, "comment_audits": 8, "comment_reviews": 1,
    "wa_enquiries_open": 1, "wa_enquiries_closed": 1, "wa_outbound_messages": 0}
FIXED_SHA = "1a33b7b2cfbc987e4a00611345026dd2bd40b07123357b4098933e11ed14c4d3"


def approved_proposal():
    # Independent already-reviewed base artifact, not implementation expectations.
    return json.loads((SCRIPTS.parent / "artifacts/v1/restore-0056-review/fixture-delta-proposal.json").read_text())


def counts(post=False):
    result = dict(SOURCE_COUNTS)
    if post:
        for name in ("commerce_orders", "sku_reservations", "v1_order_activity", "v1_activity_policy_commands",
                     "comment_operator_commands", "whatsapp_enquiry_closures"):
            result[name] += 1
    return result


def totals(post=False):
    result = dict(SOURCE_TOTALS)
    if post:
        result.update(orders=3, placed_total_minor=3750, paid_total_minor=2500,
                      reservations=3, reserved_quantity=3, available_stock=7)
    return result


def independent_semantics(post=False):
    proposal = approved_proposal()
    records = proposal["record_templates_final_retained_state"]
    if post:
        append = proposal["future_target_only_append_NOT_EXECUTED"]
        for table, rows in append["records"].items():
            records[table].extend(rows)
        records["v1_activity_policies"][0].update(append["allowed_updates"][0]["to"])
    canonical = {table: sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)) for table, rows in records.items()}
    state_counts = dict(SCOPED)
    if post:
        state_counts.update(order_activity_test=2, wa_enquiries_open=0, wa_enquiries_closed=2)
    return {"counts": state_counts, "retained_sha256": hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def boundary_snapshot(post=False):
    return {"head": "0056_v1_comment_operator", "tables": {name: {"count": n, "row_sha256": "a" * 64} for name, n in counts(post).items()},
            "schema_sha256": "b" * 64, "totals": totals(post), "semantics": independent_semantics(post),
            "historical_offenders": {"count": 0, "row_sha256": hashlib.sha256(b"[]").hexdigest()}}


class WriteCalls:
    """Record SQL and bind parameters without implementing a database."""
    def __init__(self):
        self.calls = []

    async def execute(self, statement, parameters=None):
        self.calls.append((str(statement), deepcopy(parameters)))
        return SimpleNamespace(rowcount=1)


def inserts(calls):
    result = []
    for sql, parameters in calls:
        if match := re.match(r"INSERT INTO ([a-z_0-9]+) ", sql):
            result.append((match[1], parameters))
    return result


@pytest.mark.asyncio
async def test_r3_fixed_fixture_has_independent_52_58_contract_links_and_semantic_projection(monkeypatch):
    fixture = synthetic.fixture_0056()
    assert fixture["format"] == "munimjee.release-fixture.0056" and type(fixture["version"]) is int and fixture["version"] == 1
    assert synthetic.FIXTURE_SHA256 == FIXED_SHA
    assert fixture["source_counts"] == counts() and sum(counts().values()) == 52
    assert fixture["append"]["post_counts"] == counts(True) and sum(counts(True).values()) == 58
    assert fixture["source_totals"] == totals() and fixture["append"]["post_totals"] == totals(True)
    assert fixture["records"] == approved_proposal()["record_templates_final_retained_state"]
    records = fixture["records"]
    assert len(records) == 17 and sum(map(len, records.values())) == 35
    events = {row["id"]: row for row in records["comment_events"]}
    actions = {row["id"]: row for row in records["comment_actions"]}
    for action in actions.values():
        event = events[action["event_id"]]
        assert action["seller_id"] == event["seller_id"]
        if action["accepted_claim"] is not None:
            assert action["accepted_claim"]["connection"] == event["source_binding"]
    for audit in records["comment_action_audits"]:
        action = actions[audit["action_id"]]
        assert (audit["seller_id"], audit["event_id"]) == (action["seller_id"], action["event_id"])
    messages = {row["id"]: row for row in records["whatsapp_messages"]}
    contact = records["whatsapp_contacts"][0]
    assert contact["opted_out"] is True and not records["comment_rules"][0]["enabled"]
    for review in records["whatsapp_enquiry_reviews"]:
        message = messages[review["inbound_message_id"]]
        assert review["business_id"] == message["seller_id"] == contact["seller_id"]
        assert review["contact_id"] == message["contact_id"] == contact["id"]
        assert review["phone_number_id"] == message["phone_number_id"] and message["direction"] == "inbound"
    ledger = records["v1_activity_sources"][0]
    assert ledger["source_id"] in messages and ledger["created_at"] == messages[ledger["source_id"]]["created_at"]
    calls = []
    async def query(connection, sql, params=None):
        calls.append(sql)
        match = re.fullmatch(r'SELECT to_jsonb\(t\) FROM public\."([a-z_0-9]+)" t LIMIT 1001', sql)
        assert match and match[1] in records
        return SimpleNamespace(scalars=lambda: deepcopy(records[match[1]]))
    monkeypatch.setattr(rehearsal, "query", query)
    assert await synthetic.semantic_state(object()) == independent_semantics()
    assert len(calls) == 17


@pytest.mark.asyncio
async def test_r3_json_casts_preserve_sql_null_and_exact_json_values():
    connection = WriteCalls()
    row = {"source_binding": None, "accepted_claim": None, "result": None, "keywords": [],
           "payload": {"synthetic": True}, "consent_history": [], "customer": {}, "address": {},
           "items": [], "options": {}, "source": {"kind": "synthetic"}}
    await synthetic.insert(connection, "synthetic_table", row)
    sql, params = connection.calls[0]
    for field, value in row.items():
        assert f"CAST(:{field} AS jsonb)" in sql
        assert params[field] == (json.dumps(value) if value is not None else None)


@pytest.mark.asyncio
async def test_r3_seed_uses_accepted_then_sending_then_final_state_without_direct_attempt_insert():
    connection = WriteCalls()
    await synthetic.seed(connection)
    written = inserts(connection.calls)
    assert Counter(table for table, _ in written) == Counter({name: n for name, n in counts().items() if name != "alembic_version"})
    actions = [row for table, row in written if table == "comment_actions"]
    assert Counter(row["status"] for row in actions) == {"pending": 3, "review_required": 1}
    for row in actions:
        assert all(row[key] is None for key in ("claim_token", "attempted_at", "provider_id", "finalized_at"))
    attempted = [row for row in approved_proposal()["record_templates_final_retained_state"]["comment_actions"] if row["attempted_at"] is not None]
    for final in attempted:
        indices = [i for i, (sql, params) in enumerate(connection.calls) if params.get("id") == final["id"]]
        assert len(indices) == 3
        statements = [connection.calls[i] for i in indices]
        assert statements[0][0].startswith("INSERT INTO comment_actions")
        assert "status='sending'" in statements[1][0] and statements[1][1]["claim_token"] == final["claim_token"]
        assert statements[2][1]["status"] == final["status"] and statements[2][1]["provider_id"] == final["provider_id"]
    assert any(sql.startswith("UPDATE v1_activity_contexts SET lossy=true") for sql, _ in connection.calls)


@pytest.mark.asyncio
async def test_r3_target_append_has_six_new_rows_only_and_conditional_policy_update():
    connection = WriteCalls()
    await synthetic.newer_order(connection)
    written = inserts(connection.calls)
    assert Counter(table for table, _ in written) == {"commerce_orders": 1, "sku_reservations": 1,
        "v1_order_activity": 1, "v1_activity_policy_commands": 1, "comment_operator_commands": 1, "whatsapp_enquiry_closures": 1}
    order = next(row for table, row in written if table == "commerce_orders")
    link = next(row for table, row in written if table == "v1_order_activity")
    assert order["total"] == 1250 and order["payment_status"] == "paid"
    assert link["order_id"] == order["id"] and link["accepted_at"] == order["created_at"]
    updates = [(sql, row) for sql, row in connection.calls if sql.startswith("UPDATE")]
    assert len(updates) == 2
    assert "stock_available=stock_available-1" in updates[0][0]
    assert all(part in updates[1][0] for part in ("mode=:old_mode", "revision=:old_revision", "updated_at=:old_updated_at"))
    assert (updates[1][1]["old_mode"], updates[1][1]["old_revision"], updates[1][1]["mode"], updates[1][1]["revision"]) == ("test", 1, "off", 2)
    assert not any("UPDATE comment_" in sql or "UPDATE whatsapp_" in sql for sql, _ in connection.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["hash", "format", "symlink", "size"])
async def test_r3_fixed_fixture_tampering_refused_before_any_tool_engine_or_archive(tmp_path, monkeypatch, mutation):
    original = (SCRIPTS / "v1_release_fixture_0056.json").read_bytes()
    path = tmp_path / "v1_release_fixture_0056.json"
    if mutation == "hash":
        path.write_bytes(original + b" ")
    elif mutation == "format":
        value = json.loads(original)
        value["format"] = "unreviewed.fixture"
        path.write_text(json.dumps(value))
        monkeypatch.setattr(synthetic, "FIXTURE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    elif mutation == "symlink":
        target = tmp_path / "target.json"
        target.write_bytes(original)
        path.symlink_to(target)
    else:
        path.write_bytes(b"x" * 65537)
    monkeypatch.setattr(synthetic, "__file__", str(tmp_path / "v1_release_synthetic.py"))
    monkeypatch.setattr(rehearsal, "pg_tools", lambda *args: pytest.fail("Tools before fixed fixture validation"))
    with pytest.raises((rehearsal.RehearsalError, OSError)):
        await rehearsal.run(SimpleNamespace(), {})


@pytest.mark.asyncio
@pytest.mark.parametrize("post", [False, True], ids=["source52", "target58"])
async def test_r4_independent_source_and_target_validator_inputs_pass(post):
    await synthetic.validate_fixture(object(), boundary_snapshot(post), post_cutover=post)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["count", "extra-table", "financial-total", "semantic-count", "semantic-digest"])
async def test_r4_fixed_reconciliation_corruption_refused(mutation, monkeypatch):
    snapshot = boundary_snapshot()
    if mutation == "count":
        snapshot["tables"]["comment_actions"]["count"] -= 1
    elif mutation == "extra-table":
        snapshot["tables"]["unexpected_populated"] = {"count": 1, "row_sha256": "c" * 64}
    elif mutation == "financial-total":
        snapshot["totals"]["paid_total_minor"] += 1
    elif mutation == "semantic-count":
        snapshot["semantics"]["counts"]["wa_outbound_messages"] = 1
    else:
        records = approved_proposal()["record_templates_final_retained_state"]
        records["whatsapp_enquiry_reviews"][0]["contact_id"] = "ffffffff-ffff-4fff-8fff-ffffffffffff"
        async def query(connection, sql, params=None):
            match = re.fullmatch(r'SELECT to_jsonb\(t\) FROM public\."([a-z_0-9]+)" t LIMIT 1001', sql)
            assert match and match[1] in records
            return SimpleNamespace(scalars=lambda: deepcopy(records[match[1]]))
        monkeypatch.setattr(rehearsal, "query", query)
        snapshot["semantics"] = await synthetic.semantic_state(object())
        assert snapshot["semantics"]["counts"] == independent_semantics()["counts"]
        assert snapshot["semantics"]["retained_sha256"] != independent_semantics()["retained_sha256"]
    with pytest.raises(rehearsal.RehearsalError):
        await synthetic.validate_fixture(object(), snapshot)


@pytest.mark.asyncio
async def test_r5_historical_offender_digest_keeps_full_rows_order_and_multiplicity(monkeypatch):
    rows = ['{"id":"synthetic-b","body":"retained"}', '{"id":"synthetic-a","body":"private"}',
            '{"id":"synthetic-a","body":"private"}']
    scripted = [list(rows), list(reversed(rows)), [rows[0].replace("retained", "changed"), *rows[1:]]]
    async def query(connection, sql, params=None):
        assert "e.seller_id=a.seller_id AND e.id=a.event_id" in sql
        assert "WHERE e.id IS NULL LIMIT 1001" in sql
        return SimpleNamespace(scalars=lambda: scripted.pop(0))
    monkeypatch.setattr(rehearsal, "query", query)
    original = await rehearsal.historical_offenders(object())
    reordered = await rehearsal.historical_offenders(object())
    changed = await rehearsal.historical_offenders(object())
    assert original == {"count": 3, "row_sha256": hashlib.sha256(json.dumps(sorted(rows), separators=(",", ":")).encode()).hexdigest()}
    assert original == reordered and changed != original and changed["count"] == 3
    assert set(original) == {"count", "row_sha256"} and not scripted


def release_env():
    return {"REHEARSAL_SOURCE_URL": "postgresql+asyncpg://test:synthetic@127.0.0.1:55461/munimjee_test_release_src",
            "REHEARSAL_TARGET_URL": "postgresql+asyncpg://test:synthetic@127.0.0.1:55461/munimjee_test_release_dst"}


def flow_scene(tmp_path, monkeypatch, failure=None):
    scene = SimpleNamespace(events=[], held=set(), post=False, restored=False, source_reads=0)
    class Connection:
        def __init__(self, lane):
            self.lane = lane
        async def commit(self):
            scene.events.append("commit:" + self.lane)
        @asynccontextmanager
        async def begin(self):
            scene.events.append("begin:" + self.lane)
            yield self
    class Engine:
        def __init__(self, lane):
            self.lane = lane
        @asynccontextmanager
        async def connect(self):
            try:
                yield Connection(self.lane)
            finally:
                scene.held.discard(self.lane)
                scene.events.append("close:" + self.lane)
        async def dispose(self):
            scene.events.append("dispose:" + self.lane)
    validate, _ = rehearsal.p01()
    async def lease(connection, database):
        scene.held.add(database.lane)
    monkeypatch.setattr(rehearsal, "p01", lambda: (validate, lease))
    from sqlalchemy.ext import asyncio as sa
    monkeypatch.setattr(sa, "create_async_engine", lambda url, **kwargs: Engine("release_src" if "release_src" in url else "release_dst"))
    async def no_sql(*args):
        return None
    monkeypatch.setattr(rehearsal, "pg16", no_sql)
    monkeypatch.setattr(rehearsal, "empty_database", no_sql)
    def held():
        assert scene.held == {"release_src", "release_dst"}
    async def seed(connection):
        held()
        assert connection.lane == "release_src"
        scene.events.append("seed")
    async def append(connection):
        held()
        assert connection.lane == "release_dst" and scene.restored
        scene.post = True
        scene.events.append("target-append")
    async def probe(connection):
        held()
        label = "source-probe" if connection.lane == "release_src" else "target-probe"
        assert scene.events[-1] == ("commit:release_src" if label == "source-probe" else "restore")
        scene.events.append(label)
        if failure == label:
            raise rehearsal.RehearsalError("Injected owned probe failure")
        return {"unchanged": True}
    async def snapshot(connection):
        held()
        scene.events.append("snapshot:" + connection.lane)
        if connection.lane == "release_src":
            scene.source_reads += 1
            result = boundary_snapshot()
            if failure == "source-drift" and scene.source_reads > 1:
                result["semantics"]["retained_sha256"] = "c" * 64
            return result
        result = boundary_snapshot(scene.post)
        if failure == "restored-snapshot" and not scene.post:
            result["tables"]["comment_actions"]["row_sha256"] = "c" * 64
        if failure == "target-reconciliation" and scene.post:
            result["totals"]["paid_total_minor"] += 1
        return result
    async def query(connection, sql, params=None):
        held()
        if sql == "SELECT pg_export_snapshot()":
            return SimpleNamespace(scalar_one=lambda: "00000001-00000002-1")
        if sql == "SELECT id,total,payment_status FROM commerce_orders ORDER BY id":
            assert scene.post
            return SimpleNamespace(all=lambda: [("one", 1250, "paid"), ("two", 1250, "pending"), ("three", 1250, "paid")])
        assert sql.startswith("SET "), "Unexpected control-flow SQL"
        return SimpleNamespace(all=lambda: [])
    def command(argv, env, **kwargs):
        held()
        if "tests.migrate_test_database" in argv:
            scene.events.append("migration")
        elif argv[0] == "pg_dump":
            scene.events.append("dump")
            kwargs["stdout"].write(b"synthetic unit archive; no SQL dump")
        else:
            assert argv[0] == "pg_restore" and "--single-transaction" in argv
            assert "--clean" not in argv and "--create" not in argv
            assert argv[argv.index("--dbname") + 1] == "munimjee_test_release_dst"
            assert not any("://" in arg or "synthetic" in arg for arg in argv)
            scene.restored = True
            scene.events.append("restore")
    monkeypatch.setattr(rehearsal, "pg_tools", lambda *args: {"pg_dump": "pg_dump", "pg_restore": "pg_restore"})
    monkeypatch.setattr(rehearsal, "command", command)
    monkeypatch.setattr(rehearsal, "query", query)
    monkeypatch.setattr(rehearsal, "snapshot", snapshot)
    monkeypatch.setattr(synthetic, "seed", seed)
    monkeypatch.setattr(synthetic, "newer_order", append)
    monkeypatch.setattr(synthetic, "probe_comment_fk", probe)
    attestation = tmp_path / "ownership.json"
    attestation.write_text(json.dumps({"format": "munimjee.release-ownership.v1", "source_lane": "release_src", "target_lane": "release_dst",
        "synthetic_only": True, "allocated": True, "owner": "synthetic-unit-only"}))
    attestation.chmod(0o600)
    args = SimpleNamespace(source_lane="release_src", target_lane="release_dst", attestation=attestation,
                           archive_dir=tmp_path / "new-private-archive", pg_bin=tmp_path)
    return scene, args


def assert_flow_closed(scene):
    assert not scene.held
    for lane in ("release_src", "release_dst"):
        assert scene.events.count("close:" + lane) == 1
        assert scene.events.count("dispose:" + lane) == 1


@pytest.mark.asyncio
async def test_r5_full_control_flow_keeps_probes_equality_and_target_only_new_facts(tmp_path, monkeypatch):
    scene, args = flow_scene(tmp_path, monkeypatch)
    evidence = await rehearsal.run(args, release_env())
    assert evidence["head"] == "0056_v1_comment_operator"
    assert evidence["reconciliation"] == boundary_snapshot()
    assert evidence["post_cutover_reconciliation"] == boundary_snapshot(True)
    assert evidence["fixture_sha256"] == FIXED_SHA and evidence["fk_probes"] == {"source": {"unchanged": True}, "target": {"unchanged": True}}
    order = [scene.events.index(label) for label in ("seed", "source-probe", "dump", "restore", "target-probe", "target-append")]
    assert order == sorted(order) and scene.source_reads == 2
    assert_flow_closed(scene)
    assert (args.archive_dir / "synthetic.dump").stat().st_mode & 0o777 == 0o600
    with pytest.raises(rehearsal.RehearsalError):
        await rehearsal.run(args, release_env())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["source-probe", "target-probe", "restored-snapshot", "target-reconciliation", "source-drift"])
async def test_r5_probe_and_reconciliation_failures_hold_leases_until_cleanup(tmp_path, monkeypatch, failure):
    scene, args = flow_scene(tmp_path, monkeypatch, failure)
    with pytest.raises(rehearsal.RehearsalError):
        await rehearsal.run(args, release_env())
    assert_flow_closed(scene)
    assert not (args.archive_dir / "evidence.json").exists()
    if failure == "source-probe":
        assert "dump" not in scene.events
    else:
        assert scene.events.index("source-probe") < scene.events.index("dump") < scene.events.index("restore")
