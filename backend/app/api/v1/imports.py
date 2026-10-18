"""Factory requires the integrator's native mutation dependency; no fallback."""
import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from fastapi.responses import Response

from app.api.v1.identity import current_actor
from app.database import get_db
from app.schemas.imports_v1 import (
    CandidatePage, CandidateReviewWrite, ImportCandidateRead, ImportJobCreate,
    ImportJobRead, JobMutation, UploadCreate, UploadRead,
)
from app.services import imports_v1 as service
from app.services.identity import require_business_access
from app.v1.imports import ImportReviewError
from app.v1.imports.fetching import FetchError


async def bounded_upload(request: Request, *, limit: int = 5_000_000) -> bytes:
    length = request.headers.get("content-length")
    if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 10 or int(length) > limit):
        raise HTTPException(413, "Upload exceeds the supported byte limit")
    body = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(body) + len(chunk) > limit:
                    raise HTTPException(413, "Upload exceeds the supported byte limit")
                body.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "Upload timed out")
    return bytes(body)


async def _call(awaitable):
    try:
        return await awaitable
    except service.ImportNotFound:
        raise HTTPException(404, "Import resource not found")
    except service.ImportRevisionConflict:
        raise HTTPException(409, {"code":"import_revision_stale", "message":"Import revision changed before this action was accepted. Refresh and review the current facts."})
    except service.ImportConflict:
        raise HTTPException(409, "Import revision or idempotency conflict")
    except (ImportReviewError, FetchError, ValidationError, ValueError):
        raise HTTPException(422, "Invalid import source or review")


def create_router(require_v1_mutation) -> APIRouter:
    """Mount with app.api.v1.session.business_mutation("catalogue.write").

    The shared transaction dependency checks the native session and capability
    before request work and again before get_db commits, including lock/body waits.

    No queue dispatch occurs in a request: pending rows are the durable queue and
    recovery polling happens only after the HTTP transaction commits.
    """
    if not callable(require_v1_mutation):
        raise TypeError("Native mutation dependency is required")
    router = APIRouter(prefix="/api/v1/businesses/{business_id}/imports", tags=["v1-imports"])

    @router.get("/sources/instagram")
    async def instagram_source(request: Request, business_id: UUID, actor=Depends(current_actor), db=Depends(get_db)):
        from app.config import settings
        from app.services.instagram_credentials import snapshot
        await require_business_access(db, actor, business_id, "catalogue.read")
        available = False
        reason = "provider_capability_pending"
        if settings.V1_INSTAGRAM_OWNED_MEDIA_ENABLED:
            available = (await snapshot(db,business_id)).usable()
            reason = "available" if available else "current_connection_required"
        if await current_actor(request,db) != actor:
            raise HTTPException(401,'The native session changed')
        await require_business_access(db,actor,business_id,"catalogue.read")
        return {"contract_version":"instagram-import-readiness.v1","available":available,"reason":reason,"carousel_available":False}

    @router.post("/uploads", status_code=201, response_model=UploadRead)
    async def upload(business_id: UUID, request: Request, idempotency_key: UUID,
                     source_authorized: str = Query(..., pattern="^true$"),
                     actor=Depends(require_v1_mutation), db=Depends(get_db)):
        # Permission precedes consuming any upload bytes; a denied tenant cannot
        # spend bounded storage or trigger full-body buffering by FastAPI.
        await require_business_access(db, actor, business_id, "catalogue.write")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in ("image/jpeg", "image/png", "video/mp4", "text/csv"):
            raise HTTPException(415, "Supported media content type required")
        content = await bounded_upload(request, limit=256_000 if content_type == "text/csv" else 5_000_000)
        payload = UploadCreate(idempotency_key=idempotency_key, content_type=content_type, source_authorized=True)
        return await _call(service.put_upload(db, actor, business_id, payload, content=content))

    @router.post("/jobs", status_code=202, response_model=ImportJobRead)
    async def create(business_id: UUID, payload: ImportJobCreate,
                     actor=Depends(require_v1_mutation), db=Depends(get_db)):
        return await _call(service.create_job(db, actor, business_id, payload))

    @router.get("/jobs", response_model=list[ImportJobRead])
    async def jobs(business_id: UUID, after: UUID | None = None, limit: int = Query(50, ge=1, le=100),
                   actor=Depends(current_actor), db=Depends(get_db)):
        return await _call(service.list_jobs(db, actor, business_id, after=after, limit=limit))

    @router.get("/jobs/{job_id}", response_model=ImportJobRead)
    async def job(business_id: UUID, job_id: UUID, actor=Depends(current_actor), db=Depends(get_db)):
        return await _call(service.get_job(db, actor, business_id, job_id))

    @router.post("/jobs/{job_id}/cancel", response_model=ImportJobRead)
    async def cancel(business_id: UUID, job_id: UUID, payload: JobMutation,
                     actor=Depends(require_v1_mutation), db=Depends(get_db)):
        return await _call(service.mutate_job(db, actor, business_id, job_id, payload, action="cancel"))

    @router.post("/jobs/{job_id}/retry", status_code=202, response_model=ImportJobRead)
    async def retry(business_id: UUID, job_id: UUID, payload: JobMutation,
                    actor=Depends(require_v1_mutation), db=Depends(get_db)):
        return await _call(service.mutate_job(db, actor, business_id, job_id, payload, action="retry"))

    @router.get("/candidates", response_model=CandidatePage)
    async def candidates(business_id: UUID, after: UUID | None = None, limit: int = Query(50, ge=1, le=100),
                         actor=Depends(current_actor), db=Depends(get_db)):
        items = await _call(service.list_candidates(db, actor, business_id, after=after, limit=limit))
        return CandidatePage(items=items, next_after=items[-1].candidate_id if len(items) == limit else None)

    @router.post("/candidates/{candidate_id}/review", response_model=ImportCandidateRead)
    async def review(business_id: UUID, candidate_id: UUID, payload: CandidateReviewWrite,
                     actor=Depends(require_v1_mutation), db=Depends(get_db)):
        return await _call(service.review_candidate(db, actor, business_id, candidate_id, payload))

    @router.get("/candidates/{candidate_id}/originals")
    async def original_manifest(request: Request, business_id: UUID, candidate_id: UUID, actor=Depends(current_actor), db=Depends(get_db)):
        from app.services.import_originals import originals
        result = await originals(db, actor, business_id, candidate_id)
        if await current_actor(request, db) != actor:
            raise HTTPException(401, 'The native session changed')
        await require_business_access(db,actor,business_id,"catalogue.read")
        return result

    @router.get("/candidates/{candidate_id}/originals/{asset_id}")
    async def original_bytes(request: Request, business_id: UUID, candidate_id: UUID, asset_id: UUID, actor=Depends(current_actor), db=Depends(get_db)):
        from app.services.import_originals import originals
        metadata, content = await originals(db, actor, business_id, candidate_id, asset_id=asset_id)
        if await current_actor(request, db) != actor:
            raise HTTPException(401, 'The native session changed')
        await require_business_access(db,actor,business_id,"catalogue.read")
        return Response(content, media_type=metadata['content_type'], headers={
            "Cache-Control":"no-store, private", "Referrer-Policy":"no-referrer", "X-Content-Type-Options":"nosniff",
            "Content-Disposition":'attachment; filename="original'+('.mp4' if metadata['content_type']=='video/mp4' else '.png' if metadata['content_type']=='image/png' else '.jpg')+'"'})

    return router
