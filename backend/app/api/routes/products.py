"""Product management — upload image, create product, auto-generate description."""
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard_auth import verify_dashboard_cookie
from app.database import get_db
from app.models.product import Product
from app.models.seller import Seller

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/products", tags=["products"], dependencies=[Depends(verify_dashboard_cookie)])

UPLOAD_DIR = Path("/app/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.post("")
async def create_product(
    seller_id: str = Form(...),
    name: str = Form(...),
    listed_price: int = Form(..., description="Price in rupees"),
    floor_price: int = Form(..., description="Minimum acceptable price in rupees"),
    description: str = Form(default=""),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a product for a seller.
    - Saves image locally under /uploads/
    - If description is empty, auto-generates one using Claude Vision
    - Prices are accepted in rupees and stored as paise internally
    """
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Image must be JPEG, PNG, or WebP")

    if floor_price > listed_price:
        raise HTTPException(status_code=400, detail="Floor price cannot exceed listed price")

    # Verify seller exists
    result = await db.execute(select(Seller).where(Seller.id == seller_id))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    # Save image to disk
    ext = Path(image.filename).suffix or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / filename
    dest.write_bytes(await image.read())
    photo_url = f"/uploads/{filename}"
    logger.info("Saved product image to %s", dest)

    # Auto-generate description if not provided
    if not description.strip():
        try:
            from app.integrations.claude import ClaudeClient
            # Build a publicly accessible URL for Claude Vision
            # In dev we pass the file contents directly via base64
            image_bytes = dest.read_bytes()
            import base64
            image_b64 = base64.b64encode(image_bytes).decode()
            description = await _generate_description_from_bytes(
                image_b64, image.content_type or "image/jpeg", name
            )
            logger.info("Auto-generated description for %r: %r", name, description)
        except Exception as exc:
            logger.warning("Description auto-generation failed: %s — leaving blank", exc)
            description = ""

    product = Product(
        seller_id=seller_id,
        name=name,
        description=description or None,
        listed_price=listed_price * 100,   # rupees → paise
        floor_price=floor_price * 100,
        photo_url=photo_url,
        active=True,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "listed_price_rupees": listed_price,
        "floor_price_rupees": floor_price,
        "photo_url": product.photo_url,
    }


@router.get("")
async def list_products(seller_id: str, db: AsyncSession = Depends(get_db)):
    """List all active products for a seller."""
    result = await db.execute(
        select(Product).where(Product.seller_id == seller_id, Product.active == True)
    )
    products = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "listed_price_rupees": p.listed_price // 100,
            "floor_price_rupees": p.floor_price // 100,
            "photo_url": p.photo_url,
        }
        for p in products
    ]


async def _generate_description_from_bytes(
    image_b64: str, content_type: str, product_name: str
) -> str:
    """Call Claude Vision with raw base64 bytes — no public URL needed."""
    import anthropic
    from app.config import settings
    from app.integrations.claude import MODEL

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"You are helping an Indian small business seller list a product called '{product_name}'.\n"
                        "Write a short product description (2-3 sentences) based on this image.\n"
                        "Mention: material, colour, key features, typical use.\n"
                        "Write in simple English. No marketing fluff. Return ONLY the description text."
                    ),
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": image_b64,
                    },
                },
            ],
        }],
    )
    return response.content[0].text.strip()
