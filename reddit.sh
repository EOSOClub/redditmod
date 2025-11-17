#!/usr/bin/env sh
set -eu

# Predefine to satisfy set -u and avoid "referenced but not assigned"
__exit_rc=0
trap '__exit_rc=$?; if [ "$__exit_rc" -ne 0 ]; then echo "[reddit.sh] Error (exit $__exit_rc)"; fi; exit "$__exit_rc"' EXIT

# Resolve repo root (directory of this script)
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

DOCKER_COMPOSE="docker compose"

# Optional: set project name for consistent names across runs
: "${COMPOSE_PROJECT_NAME:=redditbot}"
export COMPOSE_PROJECT_NAME

# Target service (default matches compose service name)
SERVICE_NAME="${1:-reddit-bot}"

# Health check URL (override with HEALTH_URL if needed)
: "${HEALTH_URL:=http://127.0.0.1:8520/health}"
: "${HEALTH_TIMEOUT_SECS:=60}"
: "${HEALTH_INTERVAL_SECS:=2}"

# Checks
command -v docker >/dev/null 2>&1 || { echo "[reddit.sh] docker not found"; exit 1; }
$DOCKER_COMPOSE version >/dev/null 2>&1 || { echo "[reddit.sh] 'docker compose' not available"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "[reddit.sh] curl not found"; exit 1; }
[ -f docker-compose.yml ] || [ -f compose.yml ] || { echo "[reddit.sh] compose file not found"; exit 1; }

# Capture current image (to delete later if new build is healthy)
OLD_IMAGE_ID="$($DOCKER_COMPOSE images -q "$SERVICE_NAME" 2>/dev/null || true)"
if [ -n "${OLD_IMAGE_ID:-}" ]; then
  echo "[reddit.sh] Current image for $SERVICE_NAME: $OLD_IMAGE_ID"
else
  echo "[reddit.sh] No existing image found for $SERVICE_NAME"
fi

# Stop and remove only the target service container (and orphans)
echo "[reddit.sh] Stopping container for service: $SERVICE_NAME..."
$DOCKER_COMPOSE stop "$SERVICE_NAME" >/dev/null 2>&1 || true

echo "[reddit.sh] Removing container for service: $SERVICE_NAME..."
$DOCKER_COMPOSE rm -f "$SERVICE_NAME" >/dev/null 2>&1 || true

# Also remove orphans from prior runs
$DOCKER_COMPOSE down --remove-orphans >/dev/null 2>&1 || true

# Build fresh image (do not remove old image yet)
echo "[reddit.sh] Building fresh image..."
$DOCKER_COMPOSE build --pull "$SERVICE_NAME"

# Start service
echo "[reddit.sh] Starting service..."
$DOCKER_COMPOSE up -d "$SERVICE_NAME"

# Determine new image id
NEW_IMAGE_ID="$($DOCKER_COMPOSE images -q "$SERVICE_NAME" 2>/dev/null || true)"
if [ -n "${NEW_IMAGE_ID:-}" ]; then
  echo "[reddit.sh] New image for $SERVICE_NAME: $NEW_IMAGE_ID"
else
  echo "[reddit.sh] Warning: Could not determine new image ID for $SERVICE_NAME"
fi

# Health check loop
echo "[reddit.sh] Waiting for health at: $HEALTH_URL (timeout: ${HEALTH_TIMEOUT_SECS}s)..."
end_time=$(( $(date +%s) + HEALTH_TIMEOUT_SECS ))
healthy=0
while [ "$(date +%s)" -lt "$end_time" ]; do
  if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep "$HEALTH_INTERVAL_SECS"
done

if [ "$healthy" -eq 1 ]; then
  echo "[reddit.sh] Service reported healthy."

  # If healthy and old image exists and differs, delete the old image
  if [ -n "${OLD_IMAGE_ID:-}" ] && [ "$OLD_IMAGE_ID" != "$NEW_IMAGE_ID" ]; then
    echo "[reddit.sh] Removing old image: $OLD_IMAGE_ID"
    docker image rm -f "$OLD_IMAGE_ID" >/dev/null 2>&1 || {
      echo "[reddit.sh] Warning: Failed to remove old image $OLD_IMAGE_ID"
    }
  fi
else
  echo "[reddit.sh] Warning: Health check did not pass within ${HEALTH_TIMEOUT_SECS}s. Old image retained."
fi

echo "[reddit.sh] Following logs for: $SERVICE_NAME (Ctrl-C to stop tailing)"
exec $DOCKER_COMPOSE logs -f "$SERVICE_NAME"