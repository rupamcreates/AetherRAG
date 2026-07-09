import os
from celery import Celery
from app.core.config import settings

redis_url = settings.REDIS_URL
if redis_url.startswith("rediss://") and "ssl_cert_reqs" not in redis_url:
    separator = "&" if "?" in redis_url else "?"
    redis_url = f"{redis_url}{separator}ssl_cert_reqs=none"

celery_app = Celery(
    "tasks",
    broker=redis_url,
    backend=redis_url,
    include=["app.worker.tasks"]
)

# Celery Configurations for stable execution with Upstash Redis
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    # Upstash free tier rate limits might require setting a concurrency limit
    worker_concurrency=2,  # Free tier Render or Hugging Face spaces
    task_time_limit=900,   # 15 minutes max task execution time
    task_soft_time_limit=600
)

# Optional: Adjust broker transport options for Upstash
if settings.REDIS_URL.startswith("rediss://"):
    celery_app.conf.update(
        broker_use_ssl={
            "ssl_cert_reqs": None  # Allow self-signed / public certs from Upstash
        },
        redis_backend_use_ssl={
            "ssl_cert_reqs": None
        }
    )
