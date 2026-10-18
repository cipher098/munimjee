"""Actual main, migrated P01 lane, fixed local TLS origin; no provider allowance."""
from tests.safety import install_test_safety
install_test_safety()
import sys
from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_STOREFRONT_ENABLED = True
settings.V1_STOREFRONT_ASSETS_DIR = ''
settings.PUBLIC_BASE_URL = 'https://127.0.0.1:8156'
from app.main import app

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8156, log_level='warning',
        ssl_certfile=sys.argv[1], ssl_keyfile=sys.argv[2])
