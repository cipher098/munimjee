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
    # Instagram-direct OAuth (Instagram API with Instagram Login). These are
    # separate from META_APP_ID/SECRET — Meta issues a distinct "Instagram App ID"
    # under Use cases → Manage messaging on Instagram → API setup with Instagram
    # login → Set up Instagram business login. Without these, OAuth fails at
    # token exchange because api.instagram.com rejects the Facebook app secret.
    INSTAGRAM_APP_ID: str = ""
    INSTAGRAM_APP_SECRET: str = ""
    INSTAGRAM_API_VERSION: str = "v22.0"

    SARVAM_API_KEY: str = ""
    ANTHROPIC_API_KEY: str

    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET_NAME: str = "sellerbot-uploads"

    PUBLIC_BASE_URL: str = ""  # e.g. https://abc123.ngrok.io — used to build public image URLs for Meta

    WHATSAPP_API_URL: str = ""
    WHATSAPP_API_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""

    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    DASHBOARD_PASSWORD: str = "changeme"
    DASHBOARD_ALLOWED_PHONES: List[str] = ["8233089333", "7023456161"]

    # If the seller replies manually from the IG inbox, the bot pauses for that
    # conversation. The clock resets on every manual reply; after this many
    # minutes of seller silence, the bot resumes on the next customer message.
    # 360 minutes = 6h default; smaller values are useful during testing.
    BOT_AUTO_RESUME_AFTER_MINUTES: int = 1

    # How often the periodic beat task scans for expired pauses and dispatches
    # wake_paused_conversation. 60s is a good default — small enough that
    # resume feels immediate, large enough that the scan SQL stays cheap.
    RESUME_SCAN_EVERY_SECONDS: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
