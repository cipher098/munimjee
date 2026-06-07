"""Category, tag, and tag-value management."""
import logging
from datetime import timezone, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dashboard_auth import verify_dashboard_cookie, current_seller_id
from app.database import get_db
from app.models.category_tag import CategoryTag
from app.models.product import Product
from app.models.product_category import ProductCategory
from app.models.product_tag_value import ProductTagValue
from app.models.seller import Seller
from app.models.seller_alert import SellerAlert

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/categories",
    tags=["categories"],
    dependencies=[Depends(verify_dashboard_cookie)],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CategoryCreate(BaseModel):
    seller_id: str | None = None   # ignored — seller comes from the auth cookie
    name: str


class TagCreate(BaseModel):
    name: str           # slug e.g. "power_source"
    display_name: str   # "Power Source"
    value_type: str = "text"          # enum | text | number
    allowed_values: list[str] | None = None


class TagValueSet(BaseModel):
    tag_id: str
    value: str


# ---------------------------------------------------------------------------
# Category endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_categories(seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    """Return all categories for a seller with their tags."""
    result = await db.execute(
        select(ProductCategory)
        .where(ProductCategory.seller_id == seller_id)
        .options(selectinload(ProductCategory.tags))
        .order_by(ProductCategory.name)
    )
    categories = result.scalars().all()
    return [_category_dict(c) for c in categories]


@router.post("")
async def create_category(body: CategoryCreate, seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    """Create a new product category for a seller (scoped to the logged-in seller)."""
    result = await db.execute(select(Seller).where(Seller.id == seller_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Seller not found")

    category = ProductCategory(seller_id=seller_id, name=body.name)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    # New category has no tags yet — return directly to avoid lazy-load in async context
    return {"id": str(category.id), "seller_id": str(category.seller_id), "name": category.name, "tags": []}


@router.post("/{category_id}/tags")
async def add_tag(category_id: str, body: TagCreate, db: AsyncSession = Depends(get_db)):
    """Add a tag definition to a category."""
    result = await db.execute(select(ProductCategory).where(ProductCategory.id == category_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Category not found")

    tag = CategoryTag(
        category_id=category_id,
        name=body.name,
        display_name=body.display_name,
        value_type=body.value_type,
        allowed_values=body.allowed_values,
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return _tag_dict(tag)


@router.patch("/{category_id}/tags/{tag_id}")
async def update_tag(
    category_id: str, tag_id: str, body: TagCreate, db: AsyncSession = Depends(get_db)
):
    """Update a tag definition."""
    result = await db.execute(
        select(CategoryTag).where(CategoryTag.id == tag_id, CategoryTag.category_id == category_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    tag.name = body.name
    tag.display_name = body.display_name
    tag.value_type = body.value_type
    tag.allowed_values = body.allowed_values
    await db.commit()
    await db.refresh(tag)
    return _tag_dict(tag)


@router.post("/{category_id}/suggest-tags")
async def suggest_tags(category_id: str, db: AsyncSession = Depends(get_db)):
    """Ask Claude to suggest tags for this category. Returns suggestions only — does NOT save them."""
    result = await db.execute(select(ProductCategory).where(ProductCategory.id == category_id))
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    from app.integrations.claude import ClaudeClient
    claude = ClaudeClient()
    suggestions = await claude.suggest_tags_for_category(category.name)
    return {"suggestions": suggestions}


@router.delete("/{category_id}/tags/{tag_id}")
async def delete_tag(category_id: str, tag_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a tag definition (and all product values for it)."""
    result = await db.execute(
        select(CategoryTag).where(CategoryTag.id == tag_id, CategoryTag.category_id == category_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    await db.delete(tag)
    await db.commit()
    return {"deleted": tag_id}


# ---------------------------------------------------------------------------
# Product tag-value endpoints
# ---------------------------------------------------------------------------

@router.get("/product/{product_id}/tags")
async def get_product_tags(product_id: str, db: AsyncSession = Depends(get_db)):
    """Return all tags for the product's category + which ones have values filled."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.category_id:
        return {"category": None, "tags": []}

    result = await db.execute(
        select(ProductCategory)
        .where(ProductCategory.id == product.category_id)
        .options(selectinload(ProductCategory.tags))
    )
    category = result.scalar_one_or_none()
    if not category:
        return {"category": None, "tags": []}

    result = await db.execute(
        select(ProductTagValue).where(ProductTagValue.product_id == product_id)
    )
    values_by_tag = {str(v.tag_id): v.value for v in result.scalars().all()}

    return {
        "category": {"id": str(category.id), "name": category.name},
        "tags": [
            {
                **_tag_dict(t),
                "value": values_by_tag.get(str(t.id)),
            }
            for t in category.tags
        ],
    }


@router.patch("/product/{product_id}/tags")
async def set_product_tag_values(
    product_id: str,
    body: list[TagValueSet],
    db: AsyncSession = Depends(get_db),
):
    """Set or update tag values for a product. Also resumes any waiting conversations."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    filled_tag_ids = []
    for item in body:
        result = await db.execute(
            select(ProductTagValue).where(
                ProductTagValue.product_id == product_id,
                ProductTagValue.tag_id == item.tag_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = item.value
        else:
            db.add(ProductTagValue(product_id=product_id, tag_id=item.tag_id, value=item.value))
        filled_tag_ids.append(item.tag_id)

    await db.flush()

    # Resolve alerts and resume waiting conversations for the filled tags
    resumed = 0
    for tag_id in filled_tag_ids:
        # Resolve unresolved alerts for this tag + product
        alert_result = await db.execute(
            select(SellerAlert).where(
                SellerAlert.product_id == product_id,
                SellerAlert.tag_id == tag_id,
                SellerAlert.resolved_at.is_(None),
            )
        )
        for alert in alert_result.scalars().all():
            alert.resolved_at = datetime.now(timezone.utc)

        # Resume waiting conversations (conversations whose active conv_product is waiting for this tag)
        from app.models.conversation import Conversation
        from app.models.conversation_product import ConversationProduct
        cp_result = await db.execute(
            select(ConversationProduct).where(
                ConversationProduct.product_id == product_id,
                ConversationProduct.pending_tag_id == tag_id,
                ConversationProduct.state == "waiting_for_tag",
            )
        )
        waiting_cps = cp_result.scalars().all()
        for cp in waiting_cps:
            conv_result = await db.execute(
                select(Conversation).where(Conversation.id == cp.conversation_id)
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                await _resume_conversation(conv, product, cp, db)
                resumed += 1

    await db.commit()
    return {"updated": len(filled_tag_ids), "conversations_resumed": resumed}


# ---------------------------------------------------------------------------
# Seller alerts endpoint
# ---------------------------------------------------------------------------

@router.get("/alerts")
async def list_alerts(seller_id: str = Depends(current_seller_id), db: AsyncSession = Depends(get_db)):
    """Return all unresolved seller alerts (missing tag values blocking conversations)."""
    result = await db.execute(
        select(SellerAlert)
        .where(SellerAlert.seller_id == seller_id, SellerAlert.resolved_at.is_(None))
        .options(
            selectinload(SellerAlert.product),
            selectinload(SellerAlert.tag),
        )
        .order_by(SellerAlert.created_at.desc())
    )
    alerts = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "product_id": str(a.product_id),
            "product_name": a.product.name if a.product else None,
            "tag_id": str(a.tag_id),
            "tag_display_name": a.tag.display_name if a.tag else None,
            "tag_name": a.tag.name if a.tag else None,
            "allowed_values": a.tag.allowed_values if a.tag else None,
            "value_type": a.tag.value_type if a.tag else None,
            "conversation_id": str(a.conversation_id),
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _category_dict(c: ProductCategory) -> dict:
    return {
        "id": str(c.id),
        "seller_id": str(c.seller_id),
        "name": c.name,
        "tags": [_tag_dict(t) for t in (c.tags or [])],
    }


def _tag_dict(t: CategoryTag) -> dict:
    return {
        "id": str(t.id),
        "category_id": str(t.category_id),
        "name": t.name,
        "display_name": t.display_name,
        "value_type": t.value_type,
        "allowed_values": t.allowed_values,
    }


async def _resume_conversation(conv, product, conv_product, db: AsyncSession) -> None:
    """Reset conv_product state and re-run the last customer message through the bot."""
    from app.models.seller import Seller
    from app.bot.conversation import advance_conversation

    messages = conv.messages or []
    last_customer_msg = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "customer"), None
    )
    if not last_customer_msg:
        logger.warning("Cannot resume conversation %s — no customer message found", conv.id)
        return

    result = await db.execute(select(Seller).where(Seller.id == conv.seller_id))
    seller = result.scalar_one_or_none()
    if not seller:
        return

    # Restore state to product_inquiry before re-processing
    if conv_product is not None:
        conv_product.state = "product_inquiry"
        conv_product.pending_tag_id = None
    await db.flush()

    logger.info("Resuming conversation %s after tag fill for product %s", conv.id, product.name)
    await advance_conversation(conv, seller, last_customer_msg, db, send_reply=True, resume=True)
