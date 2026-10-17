"""Actual Alembic DDL and tenant/snapshot constraints, never create_all."""
from uuid import uuid4
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.identity import Business, Membership, User
from app.models.import_catalogue import ImportCatalogueBridge
from app.models.imports_v1 import ImportDraft, ImportJob
from app.models.product import Product
from app.models.seller import Seller


@pytest.fixture
async def records(migrated_engine):
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sessions() as db:
        rows = []
        for index in range(2):
            bid, uid, jid, cid, pid = (uuid4() for _ in range(5))
            db.add(Seller(id=bid, email=f"{bid}@example.test", password_hash="synthetic", is_active=True))
            await db.flush()
            db.add_all([Business(id=bid, name="Synthetic import"), User(id=uid, display_name="Synthetic reviewer")])
            await db.flush()
            db.add_all([Membership(id=uuid4(), business_id=bid, user_id=uid, role="owner"),
                ImportJob(id=jid, business_id=bid, creator_id=uid, idempotency_key=uuid4(),
                          request_hash="a"*64, source={"kind":"website"}),
                Product(id=pid, seller_id=bid, name="Private synthetic draft", floor_price=0,
                        listed_price=10000, stock_quantity=2, active=False)])
            await db.flush()
            db.add(ImportDraft(id=cid, business_id=bid, last_job_id=jid, document={"synthetic":True}))
            await db.flush()
            rows.append(dict(business_id=bid, candidate_id=cid, product_id=pid, actor_user_id=uid))
        yield db, rows


def receipt(values, **changes):
    return ImportCatalogueBridge(id=uuid4(), **{**values, **changes}, candidate_revision=1,
        idempotency_key=uuid4(), request_hash="b"*64, approved_snapshot={"stock":2},
        creation_snapshot={"private":True})


@pytest.mark.asyncio
async def test_actual_migration_head_and_receipt_table(records):
    db, _ = records
    applied = await db.scalar(text("SELECT version_num FROM alembic_version"))
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert "0047_v1_import_catalogue_bridge" in {
        item.revision for item in scripts.iterate_revisions(applied, "0046_v1_import_jobs")}
    assert await db.scalar(text("SELECT to_regclass('import_catalogue_bridges')")) == "import_catalogue_bridges"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["candidate_id", "product_id", "actor_user_id"])
async def test_database_rejects_cross_business_receipt(records, field):
    db, rows = records
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(receipt(rows[0], **{field:rows[1][field]}))
            await db.flush()


@pytest.mark.asyncio
async def test_receipt_snapshot_is_immutable_and_source_cannot_duplicate(records):
    db, rows = records
    item = receipt(rows[0]); db.add(item); await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(update(ImportCatalogueBridge).where(ImportCatalogueBridge.id == item.id)
                             .values(approved_snapshot={"stock":1000}))
    assert await db.scalar(select(ImportCatalogueBridge.approved_snapshot).where(
        ImportCatalogueBridge.id == item.id)) == {"stock":2}
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(receipt(rows[0])); await db.flush()
