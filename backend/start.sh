#!/bin/bash
# Start script for running both Celery worker and FastAPI backend inside Hugging Face Spaces Docker container

# Exit immediately if a command exits with a non-zero status
set -e

echo "Starting Celery worker process in the background..."
uv run celery -A app.worker.celery_app worker --loglevel=info &

echo "Starting FastAPI application server on port 7860..."
uv run uvicorn app.main:app --host 0.0.0.0 --port 7860
