"""Own loopback app.main composition; P01 actual DB, workers/provider calls off."""
from tests.safety import install_test_safety
install_test_safety()
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.V1_IMPORTS_ENABLED=False
settings.V1_IMPORT_BRIDGE_ENABLED=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8156'
from app.main import app
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8156,log_level='warning')
