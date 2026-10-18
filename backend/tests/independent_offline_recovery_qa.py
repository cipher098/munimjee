"""Finite synthetic persistence/transport fixtures; not a SQL engine or DB proof.

The real services mutate real ORM row objects. This store only evaluates the
SELECT predicates/projections used by those services; it never chooses job states,
lease tokens, candidate IDs, retry outcomes or source facts for the application.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import wraps
import json
import operator
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter, BooleanClauseList, Grouping

from app.models.identity import Business
from app.models.imports_v1 import ImportAudit, ImportDraft, ImportJob
from app.services import imports_v1 as service
from app.v1.imports import runner
from app.v1.imports.fetching import FetchedSource

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
TENANTS = (UUID(int=2001), UUID(int=2002))


def bounded_scenario(function):
    @wraps(function)
    async def run(*args, **kwargs):
        return await asyncio.wait_for(function(*args, **kwargs), 5)
    return run


def evaluate(expression, row):
    if isinstance(expression, Grouping):
        return evaluate(expression.element, row)
    if isinstance(expression, BooleanClauseList):
        values = [evaluate(clause, row) for clause in expression.clauses]
        return all(values) if expression.operator is operators.and_ else any(values)
    left = getattr(row, expression.left.key)
    right = expression.right.value if isinstance(expression.right, BindParameter) else None
    operation = {operators.eq: operator.eq, operators.le: operator.le,
                 operators.lt: operator.lt, operators.ge: operator.ge,
                 operators.gt: operator.gt, operators.in_op: lambda a, b: a in b}.get(expression.operator)
    if operation is None:
        raise AssertionError("Synthetic SELECT predicate is not supported")
    # SQL comparisons with NULL are not true in a WHERE predicate.
    return False if left is None or right is None else operation(left, right)


class MemorySessions:
    """Global synthetic transaction lock; excludes actual DB race/rollback claims."""
    no_autoflush = nullcontext()

    def __init__(self, count=24):
        assert 0 <= count <= 24
        self.clock = NOW
        self.jobs = {}
        self.drafts = {}
        self.audits = {}
        self.lock = asyncio.Lock()
        self.in_transaction = ContextVar("independent_qa_transaction", default=False)
        self.transactions = 0
        self.queue_batch_sizes = []
        self.authorized = set(TENANTS)
        for index in range(count):
            row = ImportJob(id=UUID(int=1000 + index), business_id=TENANTS[index % 2],
                creator_id=UUID(int=3000 + index % 2), idempotency_key=UUID(int=4000 + index),
                request_hash="a" * 64, source={"kind": "website", "url": f"https://shop.example.com/product-{index}"},
                asset_id=None, state="pending", revision=1, attempts=0, candidate_count=0,
                error_code=None, lease_token=None, lease_expires_at=None,
                created_at=NOW, available_at=NOW)
            self.jobs[row.id] = row

    @asynccontextmanager
    async def begin(self):
        async with self.lock:
            token = self.in_transaction.set(True)
            try:
                yield self
                self.transactions += 1
            finally:
                self.in_transaction.reset(token)

    def rows(self, query):
        model = query.column_descriptions[0]["entity"]
        if model is ImportJob:
            rows = list(self.jobs.values())
        elif model is ImportDraft:
            rows = list(self.drafts.values())
        elif model is Business:
            rows = [SimpleNamespace(id=business_id) for business_id in TENANTS]
        else:
            raise AssertionError("Unallocated synthetic model query")
        rows = [row for row in rows if all(evaluate(clause, row) for clause in query._where_criteria)]
        for clause in reversed(query._order_by_clauses):
            rows.sort(key=lambda row: getattr(row, clause.key))
        if query._limit_clause is not None:
            rows = rows[:query._limit_clause.value]
        return rows

    async def scalar(self, query):
        rows = self.rows(query)
        assert len(rows) <= 1, "Scalar query must resolve a unique synthetic record"
        return rows[0] if rows else None

    async def execute(self, query):
        rows = self.rows(query)
        projected = [tuple(getattr(row, column.key) for column in query.selected_columns) for row in rows]
        self.queue_batch_sizes.append(len(projected))
        return SimpleNamespace(all=lambda: projected)

    def add(self, row):
        if type(row) is ImportDraft:
            key = (row.business_id, row.id)
            assert key not in self.drafts, "Duplicate candidate insertion"
            self.drafts[key] = row
        elif type(row) is ImportAudit:
            key = (row.business_id, row.idempotency_key)
            assert key not in self.audits, "Duplicate audit idempotency receipt"
            self.audits[key] = row
        else:
            raise AssertionError("Unexpected synthetic domain write")

    async def flush(self):
        pass

    def install(self, monkeypatch):
        async def authorize(db, actor, business_id, capability):
            assert db is self and capability == "catalogue.write"
            if business_id not in self.authorized:
                from fastapi import HTTPException
                raise HTTPException(404, "Synthetic membership revoked")
            return service.AccessSnapshot("owner", None)
        monkeypatch.setattr(service, "require_business_access", authorize)
        monkeypatch.setattr(service, "_fresh_access", authorize)
        monkeypatch.setattr(service, "now", lambda: self.clock)
        monkeypatch.setattr(runner, "now", lambda: self.clock)


class FiniteFetcher:
    def __init__(self, store, *, gate=None):
        self.store = store
        self.gate = gate
        self.calls = []
        self.active = self.peak = self.total_body_bytes = 0
        self.started = asyncio.Condition()

    async def wait_for_calls(self, count):
        async with self.started:
            await asyncio.wait_for(self.started.wait_for(lambda: len(self.calls) >= count), 1)

    async def fetch(self, url, *, authorized_origin):
        assert not self.store.in_transaction.get(), "Fetch must follow committed claim/check transactions"
        assert url == authorized_origin
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls.append(url)
        try:
            async with self.started:
                self.started.notify_all()
            if self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(0)
            body = json.dumps({"@type": "Product", "sku": "one", "name": "Synthetic recovery dress",
                               "offers": {"price": "19.00", "priceCurrency": "INR"}}).encode()
            assert len(body) <= 4096
            self.total_body_bytes += len(body)
            return FetchedSource(url, "application/ld+json", body)
        finally:
            self.active -= 1


async def run_finite(store, fetcher, rows):
    """QA load generator's explicit four-caller ceiling, not an app worker cap."""
    assert len(rows) <= 24
    slots = asyncio.Semaphore(4)
    async def invoke(row):
        async with slots:
            return await service.run_job(store, row.business_id, row.id, fetcher=fetcher)
    return await asyncio.wait_for(asyncio.gather(*(invoke(row) for row in rows)), 5)
