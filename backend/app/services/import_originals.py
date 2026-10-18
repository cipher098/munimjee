"""Append-only application paths for exact retrieved originals and private reads.

Existing tables have no immutability trigger: metadata, tenant and byte integrity
are checked on every replay/read. No signed URL, token, caption or inference is stored.
"""
import hashlib
from uuid import UUID, uuid5
from fastapi import HTTPException
from sqlalchemy import select
from app.models.imports_v1 import ImportAsset, ImportAudit, ImportDraft, ImportJob
from app.v1.imports.extraction import validate_upload
from app.v1.imports.fetching import FetchError


def checked_assets(claim, batch):
    if batch.account_id != claim.source.get('account_id') or batch.media_id != claim.source.get('media_id') or batch.connection_version != claim.source.get('_connection', {}).get('version'):
        raise FetchError('instagram_binding_changed')
    # Carousel remains closed: a single original must exactly match its parent.
    if batch.media_type not in {'IMAGE','VIDEO'} or len(batch.assets) != 1:
        raise FetchError('instagram_asset_invalid')
    original, = batch.assets
    expected_types = {'IMAGE': {'image/jpeg','image/png'}, 'VIDEO': {'video/mp4'}}
    if original.media_id != batch.media_id or type(original.content) is not bytes or original.content_type not in expected_types[batch.media_type] or validate_upload(original.content, original.content_type) != original.sha256:
        raise FetchError('instagram_asset_invalid')
    return batch.assets


async def retain(db, claim, candidate, batch):
    from app.services.imports_v1 import digest, now
    for original in checked_assets(claim, batch):
        key=uuid5(claim.job_id,'instagram-original:'+original.media_id+':'+original.sha256)
        asset=await db.scalar(select(ImportAsset).where(ImportAsset.business_id==claim.business_id,ImportAsset.idempotency_key==key))
        if asset is None:
            asset=ImportAsset(id=key,business_id=claim.business_id,creator_id=claim.actor_id,idempotency_key=key,
                content_type=original.content_type,content=original.content,sha256=original.sha256,size_bytes=len(original.content),authorized_at=now())
            db.add(asset); await db.flush()
        if (asset.id,asset.creator_id,asset.sha256,asset.size_bytes,asset.content_type,bytes(asset.content)) != (key,claim.actor_id,original.sha256,len(original.content),original.content_type,original.content):
            raise FetchError('instagram_asset_invalid')
        manifest={'contract_version':'instagram-owned-manifest.v1','parent_media_id':batch.media_id,
            'asset_media_id':original.media_id,'asset_id':str(asset.id),'sha256':original.sha256,
            'size_bytes':len(original.content),'content_type':original.content_type,'connection_version':batch.connection_version}
        manifest_key=uuid5(claim.job_id,'instagram-manifest:'+str(candidate.id)+':'+original.media_id+':'+original.sha256)
        audit=await db.scalar(select(ImportAudit).where(ImportAudit.business_id==claim.business_id,ImportAudit.idempotency_key==manifest_key))
        if audit is None:
            db.add(ImportAudit(id=manifest_key,business_id=claim.business_id,actor_id=claim.actor_id,idempotency_key=manifest_key,
                request_hash=digest(manifest),action='instagram_assets_retained',job_id=claim.job_id,candidate_id=candidate.id,details=manifest))
        elif (audit.actor_id,audit.action,audit.job_id,audit.candidate_id,audit.request_hash,audit.details)!=(claim.actor_id,'instagram_assets_retained',claim.job_id,candidate.id,digest(manifest),manifest):
            raise FetchError('instagram_asset_invalid')


async def originals(db, actor, business_id, candidate_id, *, asset_id=None):
    from app.services.imports_v1 import _access, digest
    await _access(db,actor,business_id)
    asset_id=UUID(str(asset_id)) if asset_id is not None else None
    draft=await db.scalar(select(ImportDraft).where(ImportDraft.business_id==business_id,ImportDraft.id==candidate_id))
    if draft is None: raise HTTPException(404,'Import original not found')
    rows=(await db.scalars(select(ImportAudit).where(ImportAudit.business_id==business_id,
        ImportAudit.candidate_id==candidate_id,ImportAudit.job_id==draft.last_job_id,
        ImportAudit.action=='instagram_assets_retained').order_by(ImportAudit.id).limit(11))).all()
    if len(rows)>10: raise HTTPException(409,'Import original integrity check failed')
    result=[]
    for audit in rows:
        job=await db.scalar(select(ImportJob).where(ImportJob.business_id==business_id,ImportJob.id==audit.job_id))
        m=audit.details
        try:
            expected_keys={'contract_version','parent_media_id','asset_media_id','asset_id','sha256','size_bytes','content_type','connection_version'}
            assert set(m)==expected_keys and m['contract_version']=='instagram-owned-manifest.v1'
            assert job and job.creator_id==audit.actor_id and job.source['kind']=='instagram'
            assert m['parent_media_id']==m['asset_media_id']==job.source['media_id']
            assert type(m['connection_version']) is int and m['connection_version']==job.source['_connection']['version']
            key=uuid5(job.id,'instagram-original:'+m['asset_media_id']+':'+m['sha256'])
            assert UUID(m['asset_id'])==key
            assert audit.idempotency_key==uuid5(job.id,'instagram-manifest:'+str(candidate_id)+':'+m['asset_media_id']+':'+m['sha256'])
            assert audit.request_hash==digest(m)
            asset=await db.scalar(select(ImportAsset).where(ImportAsset.business_id==business_id,ImportAsset.id==key))
            assert asset and asset.idempotency_key==key and asset.creator_id==job.creator_id
            assert (asset.sha256,asset.size_bytes,asset.content_type)==(m['sha256'],m['size_bytes'],m['content_type'])
            assert validate_upload(bytes(asset.content),asset.content_type)==asset.sha256
            assert len(asset.content)==asset.size_bytes
        except (AssertionError,KeyError,ValueError,TypeError,FetchError):
            raise HTTPException(409,'Import original integrity check failed') from None
        safe={**m,'job_id':str(job.id),'candidate_id':str(candidate_id)}
        if asset_id is None: result.append(safe)
        elif asset.id==asset_id: result.append((safe,bytes(asset.content)))
    await _access(db,actor,business_id)
    if asset_id is not None:
        if len(result)!=1:raise HTTPException(404,'Import original not found')
        return result[0]
    return {'contract_version':'instagram-originals.v1','items':result}
