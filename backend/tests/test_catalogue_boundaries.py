"""HTTP regressions with two sellers in isolated Postgres; external AI is stubbed."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.main import app
from app.database import get_db
from app.api.dashboard_auth import _make_token
from app.models import Seller, Product, ProductCategory, CategoryTag, ProductTagValue
from tests.conftest_db import db_session  # noqa: F401


@pytest_asyncio.fixture
async def catalogue(db_session, monkeypatch):
    from app.integrations.claude import ClaudeClient
    from app.api.routes import products

    monkeypatch.setattr(ClaudeClient, "suggest_category", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ClaudeClient, "suggest_tags_for_category", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        products,
        "_validate_image_matches_name",
        AsyncMock(return_value=(True, "shirt")),
    )
    sellers = [
        Seller(id=uuid4(), email=f"{uuid4()}@example.com", password_hash="unused")
        for _ in range(2)
    ]
    db_session.add_all(sellers)
    await db_session.flush()
    cats = [
        ProductCategory(id=uuid4(), seller_id=s.id, name="Clothing") for s in sellers
    ]
    db_session.add_all(cats)
    await db_session.flush()
    prods = [
        Product(
            id=uuid4(),
            seller_id=s.id,
            category_id=c.id,
            name="Shirt",
            listed_price=10000,
            floor_price=8000,
            stock_quantity=7,
        )
        for s, c in zip(sellers, cats)
    ]
    tags = [
        CategoryTag(id=uuid4(), category_id=c.id, name="fabric", display_name="Fabric")
        for c in cats
    ]
    db_session.add_all(prods + tags)
    await db_session.commit()
    ids = SimpleNamespace(
        sellers=[s.id for s in sellers],
        products=[p.id for p in prods],
        categories=[c.id for c in cats],
        tags=[t.id for t in tags],
        db=db_session,
    )

    async def session_override():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = session_override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={
            "dashboard_session": _make_token("seller", str(ids.sellers[0]), "test")
        },
    ) as client:
        ids.client = client
        yield ids
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("PATCH", "/products/{p}", {"active": "false", "listed_price": "1"}),
        ("GET", "/categories/product/{p}/tags", None),
        ("PATCH", "/categories/product/{p}/tags", []),
        (
            "POST",
            "/categories/{c}/tags",
            {"name": "private", "display_name": "Private"},
        ),
        (
            "PATCH",
            "/categories/{c}/tags/{t}",
            {"name": "changed", "display_name": "Changed"},
        ),
        ("DELETE", "/categories/{c}/tags/{t}", None),
        ("POST", "/categories/{c}/suggest-tags", None),
    ],
)
async def test_foreign_objects_are_not_accessible(catalogue, method, path, body):
    c = catalogue
    path = path.format(p=c.products[1], c=c.categories[1], t=c.tags[1])
    response = await c.client.request(
        method,
        path,
        **({"data": body} if path.startswith("/products/") else {"json": body}),
    )
    assert response.status_code == 404, response.text
    assert (await c.db.get(Product, c.products[1])).listed_price == 10000
    assert (await c.db.get(CategoryTag, c.tags[1])).name == "fabric"


async def test_foreign_category_assignment_is_rejected(catalogue):
    c = catalogue
    response = await c.client.patch(
        f"/products/{c.products[0]}", data={"category_id": str(c.categories[1])}
    )
    assert response.status_code == 404, response.text
    assert (await c.db.get(Product, c.products[0])).category_id == c.categories[0]


async def test_create_rejects_foreign_category(catalogue):
    c = catalogue
    response = await c.client.post(
        "/products",
        data={
            "name": "Shirt",
            "description": "Cotton",
            "listed_price": "100",
            "floor_price": "80",
            "category_id": str(c.categories[1]),
        },
        files={"image": ("shirt.jpg", b"test-image", "image/jpeg")},
    )
    assert response.status_code == 404, response.text
    assert (
        len(
            (
                await c.db.execute(
                    select(Product).where(Product.seller_id == c.sellers[0])
                )
            )
            .scalars()
            .all()
        )
        == 1
    )


@pytest.mark.parametrize("foreign", [False, True])
async def test_tag_values_must_match_category_and_reject_atomically(catalogue, foreign):
    c = catalogue
    invalid = c.tags[1]
    if not foreign:
        other = ProductCategory(id=uuid4(), seller_id=c.sellers[0], name="Other")
        c.db.add(other)
        await c.db.flush()
        tag = CategoryTag(
            id=uuid4(), category_id=other.id, name="other", display_name="Other"
        )
        c.db.add(tag)
        await c.db.commit()
        invalid = tag.id
    response = await c.client.patch(
        f"/categories/product/{c.products[0]}/tags",
        json=[
            {"tag_id": str(c.tags[0]), "value": "Cotton"},
            {"tag_id": str(invalid), "value": "Wrong"},
        ],
    )
    assert response.status_code == 404, response.text
    assert not (await c.db.execute(select(ProductTagValue))).scalars().all()


async def test_owned_catalogue_can_still_be_edited(catalogue):
    c = catalogue
    response = await c.client.patch(
        f"/products/{c.products[0]}", data={"listed_price": "120"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["listed_price_rupees"] == 120
    response = await c.client.patch(
        f"/categories/product/{c.products[0]}/tags",
        json=[{"tag_id": str(c.tags[0]), "value": "Cotton"}],
    )
    assert response.status_code == 200, response.text
    response = await c.client.get(f"/categories/product/{c.products[0]}/tags")
    assert response.json()["tags"][0]["value"] == "Cotton"


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"stock_quantity": "0"}, 0),
        ({"stock_quantity": "4"}, 4),
        ({"description": "Updated"}, 7),
        ({"clear_stock_tracking": "true"}, None),
    ],
)
async def test_zero_untracked_and_omitted_stock(catalogue, data, expected):
    c = catalogue
    response = await c.client.patch(f"/products/{c.products[0]}", data=data)
    assert response.status_code == 200, response.text
    assert response.json()["stock_quantity"] == expected


@pytest.mark.parametrize(
    "data",
    [
        {"listed_price": "-1"},
        {"floor_price": "-1"},
        {"stock_quantity": "-2"},
        {"stock_quantity": "3", "clear_stock_tracking": "true"},
    ],
)
async def test_invalid_values_are_rejected(catalogue, data):
    c = catalogue
    response = await c.client.patch(f"/products/{c.products[0]}", data=data)
    assert response.status_code in (400, 422), response.text
    p = await c.db.get(Product, c.products[0])
    assert (p.listed_price, p.floor_price, p.stock_quantity) == (10000, 8000, 7)


async def test_seller_cannot_use_admin_view_cookie(catalogue):
    c = catalogue
    c.client.cookies.set("view_seller", str(c.sellers[1]))
    response = await c.client.patch(
        f"/products/{c.products[1]}", data={"active": "false"}
    )
    assert response.status_code == 404


async def test_admin_selected_seller_is_respected(catalogue):
    c = catalogue
    c.client.cookies.clear()
    c.client.cookies.set("dashboard_session", _make_token("admin", None, "admin"))
    c.client.cookies.set("view_seller", str(c.sellers[1]))
    assert (
        await c.client.patch(f"/products/{c.products[1]}", data={"stock_quantity": "0"})
    ).status_code == 200
    assert (
        await c.client.patch(f"/products/{c.products[0]}", data={"stock_quantity": "0"})
    ).status_code == 404


async def test_unauthenticated_mutation_is_rejected(catalogue):
    c = catalogue
    c.client.cookies.clear()
    assert (
        await c.client.patch(f"/products/{c.products[0]}", data={"active": "false"})
    ).status_code == 302
