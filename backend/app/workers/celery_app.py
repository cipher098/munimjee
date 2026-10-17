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
        "app.workers.instagram_ingress",
        "app.workers.v1_imports",
        "app.workers.nudge",
        "app.workers.commerce",
        "app.workers.whatsapp",
        "app.workers.comment_automation",
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
    "v1-import-recovery": {"task": "app.workers.v1_imports.recover_import_jobs", "schedule": 30},
    "recover-instagram-ingress": {
        "task": "app.workers.instagram_ingress.recover_instagram_ingress", "schedule": 30,
    },
    "dispatch-whatsapp-outbox": {"task": "app.workers.whatsapp.drain_outbox", "schedule": 30},
    "dispatch-comment-replies": {"task": "app.workers.comment_automation.dispatch_pending_comments", "schedule": 30},
    "expire-commerce-reservations": {
        "task": "app.workers.commerce.expire_reservations",
        "schedule": 60,
    },
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
    "scan-for-nudge-candidates": {
        "task": "app.workers.nudge.scan_for_nudge_candidates",
        "schedule": settings.CUSTOMER_NUDGE_SCAN_EVERY_MINUTES * 60,  # default hourly
    },
}
