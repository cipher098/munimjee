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
    warranty_months: int | None = Form(default=None, description="Warranty in months, omit for no warranty"),
    stock_quantity: int | None = Form(default=None, description="Stock count, omit if not tracking"),
    photo_urls: str | None = Form(default=None, description="JSON array of additional photo URLs"),
    reel_urls: str | None = Form(default=None, description="JSON array of Instagram reel URLs linked to this product"),
    category_id: str | None = Form(default=None, description="UUID of an existing ProductCategory to assign"),
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
    image_bytes = await image.read()
    dest.write_bytes(image_bytes)
    photo_url = f"/uploads/{filename}"
    logger.info("Saved product image to %s", dest)

    # Validate image matches product name before saving to DB
    try:
        import base64 as _b64
        image_b64 = _b64.b64encode(image_bytes).decode()
        is_match, detected = await _validate_image_matches_name(
            image_b64, image.content_type or "image/jpeg", name
        )
        if not is_match:
            dest.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"Image looks like a '{detected}' but product name is '{name}'. Please upload a correct image or fix the product name."
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Image validation failed: %s — skipping check", exc)

    # Auto-generate description if not provided
    if not description.strip():
        try:
            description = await _generate_description_from_bytes(
                image_b64, image.content_type or "image/jpeg", name
            )
            logger.info("Auto-generated description for %r: %r", name, description)
        except Exception as exc:
            logger.warning("Description auto-generation failed: %s — leaving blank", exc)
            description = ""

    # Suggest category in the background (non-blocking — returned to frontend)
    category_suggestion = None
    try:
        from app.integrations.claude import ClaudeClient as _Claude
        _claude = _Claude()
        category_suggestion = await _claude.suggest_category(name, description)
        logger.info("Category suggestion for %r: %r", name, category_suggestion)
    except Exception as exc:
        logger.warning("Category suggestion failed: %s", exc)

    import json as _json
    parsed_photo_urls = None
    if photo_urls:
        try:
            parsed_photo_urls = _json.loads(photo_urls)
            if not isinstance(parsed_photo_urls, list):
                parsed_photo_urls = None
        except Exception:
            parsed_photo_urls = None

    parsed_reel_urls = None
    if reel_urls:
        try:
            parsed_reel_urls = _json.loads(reel_urls)
            if not isinstance(parsed_reel_urls, list):
                parsed_reel_urls = None
        except Exception:
            parsed_reel_urls = None
    if parsed_reel_urls:
        parsed_reel_urls = await _resolve_reel_urls_to_ids(parsed_reel_urls, seller)

    product = Product(
        seller_id=seller_id,
        category_id=category_id or None,
        name=name,
        description=description or None,
        listed_price=listed_price * 100,   # rupees → paise
        floor_price=floor_price * 100,
        photo_url=photo_url,
        photo_urls=parsed_photo_urls,
        reel_urls=parsed_reel_urls,
        warranty_months=warranty_months,
        stock_quantity=stock_quantity,
        active=True,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "category_id": str(product.category_id) if product.category_id else None,
        "listed_price_rupees": listed_price,
        "floor_price_rupees": floor_price,
        "photo_url": product.photo_url,
        "photo_urls": product.photo_urls,
        "reel_urls": product.reel_urls,
        "warranty_months": product.warranty_months,
        "stock_quantity": product.stock_quantity,
        "category_suggestion": category_suggestion,
    }


@router.get("")
async def list_products(seller_id: str, include_inactive: bool = False, db: AsyncSession = Depends(get_db)):
    """List products for a seller. Pass include_inactive=true to see all."""
    query = select(Product).where(Product.seller_id == seller_id)
    if not include_inactive:
        query = query.where(Product.active == True)
    query = query.order_by(Product.created_at.desc())
    result = await db.execute(query)
    products = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "category_id": str(p.category_id) if p.category_id else None,
            "listed_price_rupees": p.listed_price // 100,
            "floor_price_rupees": p.floor_price // 100,
            "photo_url": p.photo_url,
            "photo_urls": p.photo_urls,
            "reel_urls": p.reel_urls,
            "warranty_months": p.warranty_months,
            "stock_quantity": p.stock_quantity,
            "active": p.active,
        }
        for p in products
    ]


@router.patch("/{product_id}")
async def update_product(
    product_id: str,
    name: str = Form(default=None),
    listed_price: int = Form(default=None, description="Price in rupees"),
    floor_price: int = Form(default=None, description="Minimum acceptable price in rupees"),
    description: str = Form(default=None),
    warranty_months: int = Form(default=-1, description="Warranty in months; send 0 to clear"),
    stock_quantity: int = Form(default=-1, description="Stock quantity; send 0 to clear"),
    photo_urls: str | None = Form(default=None, description="JSON array of additional photo URLs; send '[]' to clear"),
    reel_urls: str | None = Form(default=None, description="JSON array of Instagram reel URLs; send '[]' to clear"),
    active: bool = Form(default=None),
    category_id: str | None = Form(default=None, description="UUID of ProductCategory; send empty string to clear"),
    image: UploadFile = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Update any fields of a product. Only supplied fields are changed."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    name_changed = name is not None and name != product.name
    if name is not None:
        product.name = name
    if description is not None:
        product.description = description or None
    if active is not None:
        product.active = active
    if category_id is not None:
        product.category_id = category_id if category_id else None

    if listed_price is not None:
        product.listed_price = listed_price * 100
    if floor_price is not None:
        product.floor_price = floor_price * 100

    # Validate prices after update
    if product.floor_price > product.listed_price:
        raise HTTPException(status_code=400, detail="Floor price cannot exceed listed price")

    # If name changed but no new image supplied, validate existing image against new name
    if name_changed and not (image and image.filename) and product.photo_url:
        try:
            import base64 as _b64
            existing_path = UPLOAD_DIR / Path(product.photo_url).name
            if existing_path.exists():
                existing_bytes = existing_path.read_bytes()
                image_b64 = _b64.b64encode(existing_bytes).decode()
                ext = existing_path.suffix.lower()
                content_type = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
                is_match, detected = await _validate_image_matches_name(
                    image_b64, content_type, product.name
                )
                if not is_match:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Existing product image looks like a '{detected}' but new name is '{product.name}'. Please also upload a matching image."
                    )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Image validation (name change) failed: %s — skipping check", exc)

    # warranty_months: -1 = not supplied, 0 = clear warranty, >0 = set warranty
    if warranty_months != -1:
        product.warranty_months = warranty_months if warranty_months > 0 else None

    if stock_quantity != -1:
        product.stock_quantity = stock_quantity if stock_quantity > 0 else None

    if image and image.filename:
        if image.content_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail="Image must be JPEG, PNG, or WebP")
        ext = Path(image.filename).suffix or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = UPLOAD_DIR / filename
        image_bytes = await image.read()
        dest.write_bytes(image_bytes)

        # Validate image matches the (possibly updated) product name
        try:
            import base64 as _b64
            image_b64 = _b64.b64encode(image_bytes).decode()
            is_match, detected = await _validate_image_matches_name(
                image_b64, image.content_type or "image/jpeg", product.name
            )
            if not is_match:
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=400,
                    detail=f"Image looks like a '{detected}' but product name is '{product.name}'. Please upload a correct image or fix the product name."
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Image validation failed: %s — skipping check", exc)

        product.photo_url = f"/uploads/{filename}"

    if photo_urls is not None:
        import json as _json
        try:
            parsed = _json.loads(photo_urls)
            product.photo_urls = parsed if isinstance(parsed, list) else None
        except Exception:
            pass

    if reel_urls is not None:
        import json as _json
        try:
            parsed = _json.loads(reel_urls)
            if isinstance(parsed, list):
                # Reload seller to get token for oEmbed resolution
                from app.models.seller import Seller as _Seller
                seller_result = await db.execute(select(_Seller).where(_Seller.id == product.seller_id))
                _seller = seller_result.scalar_one_or_none()
                parsed = await _resolve_reel_urls_to_ids(parsed, _seller)
                product.reel_urls = parsed
            else:
                product.reel_urls = None
        except Exception:
            pass

    await db.commit()
    await db.refresh(product)

    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "category_id": str(product.category_id) if product.category_id else None,
        "listed_price_rupees": product.listed_price // 100,
        "floor_price_rupees": product.floor_price // 100,
        "photo_url": product.photo_url,
        "photo_urls": product.photo_urls,
        "reel_urls": product.reel_urls,
        "warranty_months": product.warranty_months,
        "stock_quantity": product.stock_quantity,
        "active": product.active,
    }


import re as _re
_IG_URL_RE = _re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+")


async def _resolve_reel_urls_to_ids(urls: list, seller) -> list:
    """For each entry that looks like an Instagram URL, resolve it to a numeric media_id via oEmbed.
    Entries that are already numeric IDs or can't be resolved are kept as-is."""
    from app.integrations.instagram import InstagramClient

    if not seller or not seller.instagram_token:
        return urls

    client = InstagramClient(seller.instagram_token, seller.fb_page_id)
    resolved = []
    for entry in urls:
        if isinstance(entry, str) and _IG_URL_RE.search(entry):
            try:
                media_id = await client.resolve_ig_url_to_media_id(entry)
                if media_id:
                    logger.info("Resolved reel URL %s → media_id %s", entry, media_id)
                    resolved.append(str(media_id))
                else:
                    resolved.append(entry)  # keep original if unresolvable
            except Exception as exc:
                logger.warning("Failed to resolve reel URL %s: %s", entry, exc)
                resolved.append(entry)
        else:
            resolved.append(entry)
    return resolved


async def _validate_image_matches_name(
    image_b64: str, content_type: str, product_name: str
) -> tuple[bool, str]:
    """Ask Claude Vision whether the image matches the seller's product name.
    Returns (is_match, detected_product_type).
    """
    import json as _json
    import anthropic
    from app.config import settings
    from app.integrations.claude import MODEL

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"A seller is listing a product named: '{product_name}'.\n"
                        "Look at the image carefully and identify exactly what physical object is shown.\n"
                        "Be STRICT — similar categories are NOT the same. Examples of mismatches:\n"
                        "  - wall clock / desk clock image ≠ watch / wristwatch / hand watch\n"
                        "  - shoe image ≠ sandal\n"
                        "  - shirt image ≠ jacket\n"
                        "Return ONLY valid JSON, no other text:\n"
                        '{"match": true/false, "detected": "<exact object in image, 2-4 words>"}'
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
    text = response.content[0].text.strip()
    logger.warning("Image validation for %r — Claude response: %s", product_name, text)
    try:
        result = _json.loads(text)
        return bool(result.get("match", True)), result.get("detected", "unknown product")
    except Exception:
        logger.warning("Image validation parse error for %r — raw: %s", product_name, text)
        return True, "unknown product"  # fail open — don't block upload on parse error


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
