from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_ENV: str = "development"
    SECRET_KEY: str
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:3001"]

    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"

    META_APP_ID: str = ""
    META_APP_SECRET: str = ""         # used for token exchange
    META_WEBHOOK_SECRET: str = ""     # used for webhook signature verification
    META_VERIFY_TOKEN: str
    META_API_VERSION: str = "v19.0"

    SARVAM_API_KEY: str = ""
    ANTHROPIC_API_KEY: str

    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET_NAME: str = "sellerbot-uploads"

    WHATSAPP_API_URL: str = ""
    WHATSAPP_API_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""

    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    DASHBOARD_PASSWORD: str = "changeme"
    DASHBOARD_ALLOWED_PHONES: List[str] = ["8233089333", "7023456161"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
