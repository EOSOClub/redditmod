import json
import logging
import os
import threading
import time
import signal
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterable, List, Optional, Dict, Any

import praw
from dotenv import load_dotenv

from utilities.globals import reddit, SUBREDDIT, SUBREDDIT_RULES
from utilities.metrics import METRICS
from utilities.logging_config import setup_logging
from rules.handle_posts import handle_submission

logger = logging.getLogger(__name__)


@contextmanager
def log_context(logger_obj, operation_name: str, level: int = logging.INFO):
    """Context manager for logging operation start and end."""
    logger_obj.log(level, f"Starting: {operation_name}")
    start_time = datetime.now()

    try:
        yield
        duration = (datetime.now() - start_time).total_seconds()
        logger_obj.log(level, f"Completed: {operation_name} (took {duration:.4f}s)")
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger_obj.error(f"Failed: {operation_name} after {duration:.4f}s - {str(e)}")
        raise
load_dotenv()

# -------------------------------
# Shutdown and timing helpers
# -------------------------------

_STOP_EVENT = threading.Event()


def sleep_with_stop(total_seconds: float) -> None:
    """Efficiently sleep until timeout or shutdown, without active polling."""
    if total_seconds <= 0:
        return
    # Event.wait blocks the thread and wakes only on STOP or timeout
    _STOP_EVENT.wait(timeout=total_seconds)


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0, jitter_ratio: float = 0.3) -> float:
    """
    Exponential backoff with jitter.
    - attempt: 1-based retry count
    - base: base seconds
    - cap: maximum backoff seconds
    - jitter_ratio: +/- jitter percentage of the computed delay
    """
    exp = min(cap, base * (2 ** (attempt - 1)))
    jitter = exp * jitter_ratio
    # Uniform jitter in [exp - jitter, exp + jitter]
    import random
    return max(0.0, random.uniform(exp - jitter, exp + jitter))


# -------------------------------
# Seen submissions cache
# -------------------------------

class SeenCache:
    """
    Simple JSON-backed de-duplication store for submission IDs.
    Keeps an in-memory set and persists in the background or on update thresholds.
    """

    def __init__(self, path: str = "seen_submissions.json", autosave_every: int = 50):
        self._path = path
        self._lock = threading.Lock()
        self._seen: set[str] = set()
        self._dirty = 0
        self._autosave_every = autosave_every
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._seen = set(data)
                elif isinstance(data, dict) and "ids" in data:
                    self._seen = set(data.get("ids", []))
                logger.info(f"Seen cache loaded from {self._path}: {len(self._seen)} IDs.")
            else:
                logger.info(f"No seen cache found at {self._path}; starting fresh.")
        except Exception as e:
            logger.exception(f"Failed to load seen cache from {self._path}: {e}")

    def save(self) -> None:
        try:
            with self._lock:
                ids = list(self._seen)
                self._dirty = 0
            tmp_path = f"{self._path}.tmp"
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"ids": ids, "count": len(ids)}, f)
            os.replace(tmp_path, self._path)
            logger.info(f"Seen cache saved: {len(ids)} IDs.")
        except Exception as e:
            logger.exception(f"Failed to save seen cache to {self._path}: {e}")

    def seen(self, submission_id: str) -> bool:
        with self._lock:
            return submission_id in self._seen

    def add(self, submission_id: str) -> None:
        with self._lock:
            if submission_id not in self._seen:
                self._seen.add(submission_id)
                self._dirty += 1
                dirty = self._dirty
            else:
                dirty = self._dirty
        if dirty >= self._autosave_every:
            self.save()

    def shutdown(self) -> None:
        self.save()


_SEEN_CACHE = SeenCache(path=os.getenv("SEEN_CACHE_PATH", "seen_submissions.json"))


# -------------------------------
# Health endpoint
# -------------------------------

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/health", "/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(METRICS.snapshot()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress default http.server logging; use our logger if needed
        logger.debug(f"HealthServer: {format % args}")


class HealthServer(threading.Thread):
    def __init__(self, host: str = "127.0.0.1", port: int = 8520):
        super().__init__(name="health-server", daemon=True)
        self._host = host
        self._port = port
        self._server: Optional[HTTPServer] = None

    def run(self):
        try:
            self._server = HTTPServer((self._host, self._port), HealthHandler)
            # Set timeout once; handle_request() will block efficiently until timeout or a request arrives
            self._server.timeout = 0.5
            logger.info(f"Health server running at http://{self._host}:{self._port}/health")
            while not _STOP_EVENT.is_set():
                self._server.handle_request()
        except OSError as e:
            logger.warning(f"Health server failed to start: {e}")
        except Exception as e:
            logger.exception(f"Health server error: {e}")

    def shutdown(self):
        if self._server:
            try:
                self._server.server_close()
            except Exception:
                pass


# -------------------------------
# Messaging with simple rate limit
# -------------------------------

_MESSAGE_LOCK = threading.Lock()
_LAST_MESSAGE_TS = 0.0
_MESSAGE_MIN_INTERVAL = 2.0  # seconds


def send_message(author_name: str, subject: str, message: str, *, max_retries: int = 3) -> None:
    """
    Sends a message while respecting a minimum interval between messages.
    Avoids sleeping while holding the lock to reduce contention and CPU wake-ups.
    """
    global _LAST_MESSAGE_TS
    attempt = 0
    while not _STOP_EVENT.is_set() and attempt < max_retries:
        attempt += 1

        # Wait until the next allowed send time without holding the lock
        while not _STOP_EVENT.is_set():
            with _MESSAGE_LOCK:
                now = time.monotonic()
                next_allowed = _LAST_MESSAGE_TS + _MESSAGE_MIN_INTERVAL
                wait_for = max(0.0, next_allowed - now)
                if wait_for <= 0:
                    # Reserve the slot by updating timestamp
                    _LAST_MESSAGE_TS = now
                    break
            # Block efficiently until the slot is available or stop is requested
            if _STOP_EVENT.wait(timeout=wait_for):
                # Stop requested
                return

        try:
            reddit.redditor(author_name).message(subject, message)
            logger.info(f"Message sent to u/{author_name}")
            METRICS.incr_message()
            return
        except praw.exceptions.RedditAPIException as e:
            METRICS.set_error(f"send_message: {e}")
            delay = backoff_delay(attempt, base=1.0, cap=60.0, jitter_ratio=0.3)
            logger.warning(
                f"Error sending message to u/{author_name} (attempt {attempt}/{max_retries}): {e}. "
                f"Backing off {delay:.2f}s."
            )
            sleep_with_stop(delay)
        except Exception as e:
            METRICS.set_error(f"send_message_unexpected: {e}")
            logger.exception(f"Unexpected error sending message to u/{author_name}: {e}")
            break


# -------------------------------
# Submissions monitoring
# -------------------------------

def _normalize_subreddit_list(raw: Optional[Iterable]) -> List[str]:
    """Accept list/tuple/set or comma-separated string; return a clean list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [s.strip() for s in raw.split(",")]
    else:
        items = [str(s).strip() for s in raw]
    seen: set[str] = set()
    result: List[str] = []
    for s in items:
        if s and s not in seen:
            seen.add(s)
            result.append(s)
    return result


def _iter_submissions(subreddit_name: str) -> Iterable:
    subreddit = reddit.subreddit(subreddit_name)
    # pause_after lets us periodically check for stop and avoid blocking forever
    stream = subreddit.stream.submissions(skip_existing=True, pause_after=5)
    while not _STOP_EVENT.is_set():
        try:
            for submission in stream:
                if submission is None:
                    break
                yield submission
        except praw.exceptions.RedditAPIException as e:
            METRICS.set_error(f"stream_{subreddit_name}: {e}")
            # Use backoff with jitter on API errors
            for attempt in range(1, 5):
                if _STOP_EVENT.is_set():
                    break
                delay = backoff_delay(attempt, base=1.0, cap=30.0, jitter_ratio=0.3)
                logger.warning(f"Streaming error in r/{subreddit_name}: {e}. Backing off {delay:.2f}s.")
                sleep_with_stop(delay)
            # After backoff, loop re-uses the same stream iterator
        except Exception as e:
            METRICS.set_error(f"stream_unexpected_{subreddit_name}: {e}")
            logger.exception(f"Unexpected streaming error in r/{subreddit_name}: {e}")
            sleep_with_stop(5)


def monitor_subreddit(subreddit_name: str) -> None:
    threading.current_thread().name = f"sub-{subreddit_name}"
    logger.info(f"Monitoring subreddit: r/{subreddit_name}...")
    for submission in _iter_submissions(subreddit_name):
        if _STOP_EVENT.is_set():
            break
        sub_id = getattr(submission, "id", None)
        if not sub_id:
            continue
        if _SEEN_CACHE.seen(sub_id):
            continue
        try:
            handle_submission(submission, subreddit_name)
            _SEEN_CACHE.add(sub_id)
            METRICS.incr_submission(subreddit_name, last_id=sub_id)
        except Exception as e:
            METRICS.set_error(f"handle_submission_{subreddit_name}: {e}")
            logger.exception(f"Error handling submission {sub_id} in r/{subreddit_name}: {e}")


def monitor_submissions() -> None:
    subreddits = _normalize_subreddit_list(SUBREDDIT)
    if not subreddits:
        logger.error("No subreddits configured. Set the SUBREDDIT list or comma-separated string.")
        return

    logger.info(f"Starting monitors for: {', '.join(f'r/{s}' for s in subreddits)}")

    # Health server
    health_host = os.getenv("HEALTH_HOST", "127.0.0.1")
    health_port = int(os.getenv("HEALTH_PORT", "8520"))
    health_server = HealthServer(host=health_host, port=health_port)
    health_server.start()

    threads: List[threading.Thread] = []
    for subreddit_name in subreddits:
        t = threading.Thread(target=monitor_subreddit, args=(subreddit_name,), daemon=True)
        threads.append(t)
        t.start()

    try:
        # Sleep indefinitely and wake on shutdown, avoiding periodic wake-ups
        _STOP_EVENT.wait()
    except KeyboardInterrupt:
        logger.info("Shutdown requested (KeyboardInterrupt).")
        _STOP_EVENT.set()
    finally:
        # Ensure seen cache is flushed
        _SEEN_CACHE.shutdown()
        # Stop health server
        health_server.shutdown()

    for t in threads:
        t.join(timeout=5.0)
        if t.is_alive():
            logger.warning(f"Thread {t.name} did not exit cleanly.")


def _install_signal_handlers() -> None:
    def _handle_sigterm(signum, frame):
        logger.info(f"Received signal {signum}. Initiating shutdown.")
        _STOP_EVENT.set()

    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
        signal.signal(signal.SIGINT, _handle_sigterm)
    except Exception:
        # Signals might be unsupported in some environments
        pass


if __name__ == "__main__":
    setup_logging()
    _install_signal_handlers()
    logger.info("Starting the bot...")
    logger.info("Loaded subreddit rules:")
    logger.info(f"{SUBREDDIT_RULES}")
    monitor_submissions()