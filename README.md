# Reddit Bot

Monitor one or more subreddits for new submissions, apply your rules, optionally message users, and expose a lightweight health/metrics endpoint. Includes structured logging and graceful shutdown.

## Configuration

Set via environment variables (a .env file is supported):

- Reddit API credentials (required)
  - CLIENT_ID, CLIENT_SECRET, USER_AGENT, USERNAME, PASSWORD (or your preferred auth setup)
- SUBREDDIT (required)
  - Either a comma-separated string (e.g., "sub1, sub2") or a list; duplicates are removed.
- Optional settings
  - SEEN_CACHE_PATH: Path to the JSON file storing processed submission IDs (default: seen_submissions.json).
  - HEALTH_HOST: Health server bind address (default: 127.0.0.1).
  - HEALTH_PORT: Health server port (default: 8520).

Logging
- Colorized console logs are enabled by default.
- File logs are rotated (size- or time-based). You can adjust format/rotation by editing the logging setup if needed.

## Running

Local (Python)
- Ensure your environment variables/.env are set, including Reddit credentials and SUBREDDIT.
- Run your app’s entry point that starts the monitors. The process will:
  - Start a health server on HEALTH_HOST:HEALTH_PORT
  - Spawn a thread per subreddit
  - Persist a “seen” cache for de-duplication across restarts

Docker (via helper script)
- Requires a docker compose file in the repo root.
- Rebuild, start, and follow logs:

```shell script
bash
./reddit.sh
```


- To target a different service name (must match your compose service):

```shell script
bash
./reddit.sh my-service-name
```


Environment variables can be provided via your compose file or an .env file.

## Health and Metrics

- Endpoint: http://HEALTH_HOST:HEALTH_PORT/health (also available at /metrics and /)
- Returns JSON with:
  - uptime_seconds
  - subreddits: processed count, last processed timestamp, last submission ID
  - messages_sent
  - last_error (if any)

Example:

```shell script
bash
curl http://127.0.0.1:8520/health
```


## How It Works (High Level)

- Streams new submissions from each configured subreddit.
- Skips submissions already recorded in the “seen” cache.
- Invokes your rule handler for each new submission.
- Provides a helper to message users with a global minimal interval and retries (to be polite with API limits).
- Tracks metrics and serves a health endpoint.
- Shuts down gracefully on SIGINT/SIGTERM, flushing caches and stopping threads.

## Extending Rules

- Implement your logic in the submission handler (the function that receives a submission and its subreddit name).
- From your rule code, use the provided messaging helper to contact authors; it includes:
  - Global pacing between messages (to avoid rapid bursts)
  - Retry with exponential backoff and jitter on API errors
- You can add custom counters or fields to metrics if needed; keep updates thread-safe.

## Troubleshooting

- Health server fails to start (port in use)
  - The bot continues running but logs a warning. Change HEALTH_PORT or free the port.
- No activity
  - Verify SUBREDDIT is set and credentials are valid.
  - Check logs for API/auth errors.
- Duplicate processing
  - Ensure the SEEN_CACHE_PATH file is writable and persists between runs (especially in containers/volumes).
- Docker issues
  - Confirm Docker and docker compose are installed and that a compose file exists in the project root.
  - Pass the correct service name to the helper script if your service isn’t named “reddit-bot”.