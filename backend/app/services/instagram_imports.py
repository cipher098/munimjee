"""Job-bound production composition, closed until primary API approval is explicit."""
from app.config import settings
from app.services.instagram_credentials import credential, snapshot
from app.v1.imports.instagram_owned import OwnedInstagramProvider, OwnedMediaCapabilities


def provider_for(sessions, claim):
    async def load(business_id, account_id):
        async with sessions.begin() as db:
            current = await snapshot(db, business_id)
            return credential(current, business_id, account_id, claim.source.get('_connection'))

    async def checkpoint(business_id, account_id):
        from app.services.imports_v1 import check_claim
        if business_id != claim.business_id or account_id != claim.source.get('account_id'):
            return False
        async with sessions.begin() as db:
            return await check_claim(db, claim)

    return OwnedInstagramProvider(credential_loader=load, checkpoint=checkpoint,
        graph_version=settings.META_API_VERSION,
        capabilities=OwnedMediaCapabilities(ig_login_media=settings.V1_INSTAGRAM_OWNED_MEDIA_ENABLED,
            carousel=False))
