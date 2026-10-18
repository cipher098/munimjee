"""Pure command parsing/redaction and disabled-path isolation."""
from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timezone
import pytest
from app.services import customer_links as service
from app.config import settings


def test_secret_is_scoped_deterministic_256bit_and_not_saved_raw():
    row = SimpleNamespace(id=uuid4(), business_id=uuid4())
    secret = service.secret_for(row)
    assert len(secret) == 43 and service.EXACT.fullmatch(f'LINK {secret} I CONSENT')
    assert secret == service.secret_for(row) and len(service.secret_digest(secret)) == 64
    assert secret != service.secret_for(SimpleNamespace(id=row.id, business_id=uuid4()))
    assert not service.EXACT.fullmatch(f'LINK {secret} I CONSENT\n')
    assert not service.EXACT.fullmatch(f'link {secret} I CONSENT')
    assert service.REDACT.sub('[withheld]', f'operator copied LINK {secret} I CONSENT here') == 'operator copied [withheld] here'


@pytest.mark.asyncio
async def test_reserved_commands_suppressed_when_disabled_without_db_or_automation(monkeypatch):
    monkeypatch.setattr(settings, 'V1_CUSTOMER_LINKS_ENABLED', False)
    class NoDB:
        def __getattr__(self, key):
            raise AssertionError('Disabled capture must not access DB')
    for content in ['LINK ' + 'a'*43 + ' I CONSENT', 'link ' + 'b'*40, ' LINK ' + 'c'*80 + ' invalid']:
        assert await service.capture(NoDB(), uuid4(), 'instagram', 'page', 'sender', 'mid', datetime.now(timezone.utc), content)
    for content in ['link please', 'LINK', 'normal enquiry', None]:
        assert not await service.capture(NoDB(), uuid4(), 'instagram', 'page', 'sender', 'mid', None, content)
