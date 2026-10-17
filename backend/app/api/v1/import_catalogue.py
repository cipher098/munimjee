"""Native capability/CSRF protected import approval bridge, with bounded JSON."""
import asyncio
import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from app.api.v1.identity import current_actor
from app.api.v1.session import require_v1_mutation
from app.database import get_db
from app.schemas.import_catalogue import ImportCatalogueWrite, ImportCatalogueRead, ImportCataloguePreview
from app.services import import_catalogue as service
from app.services.imports_v1 import _access
from app.v1.imports import ImportReviewError

router = APIRouter(prefix='/api/v1/businesses/{business_id}/imports/candidates', tags=['v1-import-catalogue'])


async def read_command(request):
    length = request.headers.get('content-length')
    if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 10 or int(length) > 2_000_000):
        raise HTTPException(413, 'Review command exceeds 2 MB')
    body = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(body) + len(chunk) > 2_000_000:
                    raise HTTPException(413, 'Review command exceeds 2 MB')
                body.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, 'Review command timed out')
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON keys')
            result[key] = value
        return result
    try:
        data = json.loads(body, object_pairs_hook=unique_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON forbidden')))
        return ImportCatalogueWrite.model_validate(data)
    except (ValueError, ValidationError, RecursionError, UnicodeError):
        raise HTTPException(422, 'Invalid reviewed allocation command')


@router.get('/{candidate_id}/catalogue-preview', response_model=ImportCataloguePreview)
async def preview(business_id: UUID, candidate_id: UUID, actor=Depends(current_actor), db=Depends(get_db)):
    try:
        return await service.preview(db, actor, business_id, candidate_id)
    except (ValueError, ImportReviewError):
        raise HTTPException(422, 'Invalid stored import facts')


@router.post('/{candidate_id}/catalogue-draft', response_model=ImportCatalogueRead, status_code=201)
async def create(business_id: UUID, candidate_id: UUID, request: Request, response: Response,
                 actor=Depends(require_v1_mutation), db=Depends(get_db)):
    await _access(db, actor, business_id, write=True)
    payload = await read_command(request)
    try:
        result = await service.create_draft(db, actor, business_id, candidate_id, payload,
            reauthorize=lambda: require_v1_mutation(request, db))
    except (ValueError, ImportReviewError):
        raise HTTPException(422, 'Resolve source facts and explicitly allocate every SKU before creating a draft')
    response.status_code = 200 if result.replayed else 201
    return result
