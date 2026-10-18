"""Actual application composition on one disposable P01 lane; providers blocked."""
from tests.safety import install_test_safety
install_test_safety()
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.PUBLIC_BASE_URL='http://127.0.0.1:8163'
from app.main import app
import uvicorn
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8163,log_level='warning')
