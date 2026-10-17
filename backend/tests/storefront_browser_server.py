"""Actual local app/native API with canonical publication; all external sockets blocked."""
from tests.safety import install_test_safety
install_test_safety()
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8150'
settings.V1_STOREFRONT_ENABLED=True
settings.V1_STOREFRONT_ASSETS_DIR=''
from app.main import app
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8150,log_level='warning')
