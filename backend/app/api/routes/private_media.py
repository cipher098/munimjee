"""Authenticated evidence files; ordinary catalogue uploads remain public."""
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.staticfiles import StaticFiles
from app.api.dashboard_auth import current_seller_id, require_admin
from app.database import get_db
from app.models.commerce_safeguards import PaymentReview
from app.models.transaction import Transaction
from app.models.order import Order
from app.paths import UPLOAD_DIR

router = APIRouter(tags=["private-media"])


class PublicUploads(StaticFiles):
    """Defense in depth if the authenticated route does not match a path."""
    async def get_response(self, path, scope):
        normalized = path.replace('\\', '/').strip('/').casefold()
        if normalized == 'training' or normalized.startswith('training/') or \
                normalized == 'payment_screenshots/received' or normalized.startswith('payment_screenshots/received/'):
            raise HTTPException(404, "File not found")
        return await super().get_response(path, scope)


def _private_file(folder: Path, filename: str) -> Path:
    # Basenames only, no nested paths, symlinks, or sibling-directory escapes.
    if not filename or filename in ('.', '..') or '/' in filename or '\\' in filename:
        raise HTTPException(404, "File not found")
    candidate = folder / filename
    if candidate.is_symlink() or candidate.resolve().parent != folder.resolve() or not candidate.is_file():
        raise HTTPException(404, "File not found")
    return candidate


@router.get('/uploads/payment_screenshots/received/{filename}')
async def payment_evidence(filename: str, seller_id: str = Depends(current_seller_id),
                           db: AsyncSession = Depends(get_db)):
    url = f'/uploads/payment_screenshots/received/{filename}'
    evidence = (await db.execute(select(PaymentReview.id).where(
        PaymentReview.seller_id == seller_id, PaymentReview.screenshot_url == url).limit(1))).first()
    if evidence is None:
        evidence = (await db.execute(select(Transaction.id).join(Order, Order.id == Transaction.order_id).where(
            Transaction.seller_id == seller_id, Order.seller_id == seller_id,
            Transaction.screenshot_url == url).limit(1))).first()
    if evidence is None:
        raise HTTPException(404, "File not found")
    return FileResponse(_private_file(UPLOAD_DIR / 'payment_screenshots' / 'received', filename),
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/uploads/training/{filename}')
async def training_evidence(filename: str, admin=Depends(require_admin)):
    return FileResponse(_private_file(UPLOAD_DIR / 'training', filename),
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
