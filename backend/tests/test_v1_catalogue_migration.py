"""Inspect real migration operations without opening any database connection."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU


def test_migration_schema_matches_models_and_enforces_tenant_pair(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0041_v1_catalogue.py"
    spec = spec_from_file_location("catalogue_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    metadata = sa.MetaData()
    sa.Table("sellers", metadata, sa.Column("id", postgresql.UUID, primary_key=True))
    sa.Table("businesses", metadata, sa.Column("id", postgresql.UUID, sa.ForeignKey("sellers.id"), primary_key=True))
    products = sa.Table("products", metadata, sa.Column("id", postgresql.UUID, primary_key=True),
                        sa.Column("seller_id", postgresql.UUID, nullable=False))

    class Capture:
        def create_unique_constraint(self, name, table, columns):
            assert table == "products"
            products.append_constraint(sa.UniqueConstraint(*columns, name=name))

        def create_table(self, name, *columns):
            sa.Table(name, metadata, *columns)

    monkeypatch.setattr(module, "op", Capture())
    module.upgrade()
    assert module.revision == "0041_v1_catalogue" and module.down_revision == "0040_v1_identity"
    assert {constraint.name for constraint in products.constraints} >= {"products_seller_id_id"}
    for model in (CatalogueSKU, CatalogueProductMapping):
        migrated = metadata.tables[model.__tablename__]
        orm = model.__table__
        assert [(c.name, str(c.type), c.nullable, c.primary_key) for c in migrated.columns] == [
            (c.name, str(c.type), c.nullable, c.primary_key) for c in orm.columns]
        assert {str(c.sqltext) for c in migrated.constraints if isinstance(c, sa.CheckConstraint)} == {
            str(c.sqltext) for c in orm.constraints if isinstance(c, sa.CheckConstraint)}
        assert {tuple(c.columns.keys()) for c in migrated.constraints if isinstance(c, sa.UniqueConstraint)} == {
            tuple(c.columns.keys()) for c in orm.constraints if isinstance(c, sa.UniqueConstraint)}
        pairs = {tuple((e.parent.name, e.target_fullname) for e in fk.elements) for fk in migrated.foreign_key_constraints}
        assert (("business_id", "products.seller_id"), ("product_id", "products.id")) in pairs
        assert (("business_id", "businesses.id"),) in pairs
        sql = str(CreateTable(migrated).compile(dialect=postgresql.dialect()))
        assert "UPDATE " not in sql and "products (seller_id, id)" in sql
