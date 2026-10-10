"""Cloud API transport: fixed Meta origin, bearer credentials, no automatic POST retries."""
import re
import httpx
from fastapi import HTTPException
from app.config import settings
from app.services.channel_credentials import decrypt


class SendUncertain(Exception):
    """Provider may have accepted the request; never retry automatically."""


async def graph(token, method, path, *, data=None, params=None):
    version = getattr(settings, 'WHATSAPP_GRAPH_VERSION', 'v23.0')
    if not re.fullmatch(r'v\d+\.\d+', version):
        raise HTTPException(503, 'Invalid WhatsApp Graph API version configuration')
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, f'https://graph.facebook.com/{version}/{path}', headers={'Authorization': f'Bearer {token}'}, json=data, params=params)
    except httpx.HTTPError:
        if method == 'POST':
            raise SendUncertain('Provider response was not received; review before sending again')
        raise HTTPException(502, 'WhatsApp could not be reached')
    if response.status_code >= 500 and method == 'POST':
        raise SendUncertain('Provider response was inconclusive; review before sending again')
    if response.is_error:
        raise HTTPException(502, 'WhatsApp rejected the request; check permissions and account configuration')
    try:
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except ValueError:
        if method == 'POST':
            raise SendUncertain('Provider returned an unreadable response; review before sending again')
        raise HTTPException(502, 'Unexpected WhatsApp response')


async def collection(token, path, **params):
    rows, after = [], None
    for _ in range(100):
        page = await graph(token, 'GET', path, params={**params, **({'after': after} if after else {}), 'limit': 100})
        rows.extend(page.get('data', []))
        paging = page.get('paging') or {}
        if not paging.get('next'):
            return rows
        cursor = (paging.get('cursors') or {}).get('after')
        if not cursor or cursor == after:
            break
        after = cursor
    raise HTTPException(502, 'WhatsApp returned an incomplete collection; try again')


async def verify_connection(token, waba_id, phone_id):
    phones = await collection(token, f'{waba_id}/phone_numbers', fields='id,display_phone_number')
    phone = next((p for p in phones if p.get('id') == phone_id), None)
    if not phone:
        raise HTTPException(422, 'The phone number does not belong to this WhatsApp Business Account')
    return phone


async def fetch_templates(account):
    return await collection(decrypt(account.access_token), f'{account.waba_id}/message_templates', fields='name,language,status,category,components')


async def send(account, contact, message):
    data = {'messaging_product':'whatsapp', 'recipient_type':'individual', 'to':contact.phone, 'type':message.kind, 'biz_opaque_callback_data':str(message.id)}
    if message.kind == 'template':
        p = message.payload
        data['template'] = {'name':p['name'], 'language':{'code':p['language']}}
        if p.get('parameters'):
            data['template']['components'] = [{'type':'body','parameters':[{'type':'text','text':x} for x in p['parameters']]}]
    else:
        data['text'] = {'body':message.text, 'preview_url':False}
    result = await graph(decrypt(account.access_token), 'POST', f'{account.phone_number_id}/messages', data=data)
    messages = result.get('messages') or []
    if not messages or not messages[0].get('id'):
        raise SendUncertain('Provider accepted the request without a message ID; review before sending again')
    return messages[0]['id']
