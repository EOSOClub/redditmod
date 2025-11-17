FROM python:3.13-slim AS runtime

# Prevent Python from writing .pyc files and buffer logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps (minimal). Uncomment if you need TLS/CA extras or build tools
RUN apt-get update -y && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*


# Working dir
WORKDIR /app

# Install dependencies first for better layer caching
# requirements.txt must exist; pin versions for reproducibility
COPY ./requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -r /app/requirements.txt

# Copy the application
COPY . /app

# Default environment for health server to bind to all interfaces
ENV HEALTH_HOST=0.0.0.0 \
    HEALTH_PORT=8520 \
    SEEN_CACHE_PATH=/app/data/seen_submissions.json

# Optional: make filesystem read-only at runtime via compose; ensure /app/data is writable
# Expose health port (documentation only; Compose does the actual mapping)
EXPOSE 8520

# Run the bot
CMD ["python", "reddit.py"]