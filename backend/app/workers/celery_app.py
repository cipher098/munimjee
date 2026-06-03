from celery import Celery
from celery.schedules import crontab
from app.config import settings

celery_app = Celery(
    "sellerbot",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.notify_dispatch",
        "app.workers.conversation",
        "app.workers.process_statement",
        "app.workers.refresh_tokens",
        "app.workers.message_batch",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "retry-failed-notifications": {
        "task": "app.workers.notify_dispatch.retry_failed",
        "schedule": 600,  # every 10 mins
    },
    "expire-stale-conversations": {
        "task": "app.workers.conversation.expire_stale",
        "schedule": crontab(hour="*/2"),  # every 2 hours
    },
    "statement-upload-reminder": {
        "task": "app.workers.process_statement.send_reminder",
        "schedule": crontab(hour=9, minute=0),  # 9am IST daily
    },
    "refresh-instagram-tokens": {
        "task": "app.workers.refresh_tokens.refresh_expiring_instagram_tokens",
        "schedule": crontab(hour=10, minute=0),  # daily at 10am IST
    },
    "scan-resume-paused-conversations": {
        "task": "app.workers.message_batch.scan_resume_paused_conversations",
        "schedule": settings.RESUME_SCAN_EVERY_SECONDS,  # default 60s
    },
}
