from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "track_extractor",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)
celery_app.conf.task_track_started = True
celery_app.conf.worker_prefetch_multiplier = 1

