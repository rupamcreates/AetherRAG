FROM python:3.12-slim

# Install system dependencies (including git for HF tools and postgres client libraries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install UV package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    ENV=production \
    DEBUG=false

WORKDIR /app

# Create a non-root user for Hugging Face Spaces compatibility
RUN useradd -m -u 1000 user
RUN chown -R user:user /app

# Copy dependency specifications
COPY --chown=user:user pyproject.toml uv.lock ./

# Switch to the non-root user
USER user

# Sync project dependencies
RUN uv sync --frozen --no-cache

# Copy application files and scripts
COPY --chown=user:user app/ ./app/
COPY --chown=user:user start.sh ./

# Make start.sh executable
RUN chmod +x start.sh

# Expose Hugging Face Spaces default port
EXPOSE 7860

# Run the startup script
CMD ["./start.sh"]
