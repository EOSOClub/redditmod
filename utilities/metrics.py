import threading
import time
from typing import Dict, Any

class Metrics:
    """A thread-safe class for tracking application metrics."""
    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {
            "start_time": time.time(),
            "subreddits": {},
            "messages_sent": 0,
            "rules_triggered": {},
            "last_error": None,
        }

    def incr_submission(self, subreddit: str, count: int = 1, last_id: str = None) -> None:
        """Increments the counter for processed submissions for a subreddit."""
        with self._lock:
            s = self._data["subreddits"].setdefault(subreddit, {
                "processed": 0,
                "last_processed_ts": None,
                "last_submission_id": None,
            })
            s["processed"] += count
            s["last_processed_ts"] = time.time()
            if last_id:
                s["last_submission_id"] = last_id

    def incr_message(self, count: int = 1) -> None:
        """Increments the counter for sent messages."""
        with self._lock:
            self._data["messages_sent"] += count

    def incr_rule_trigger(self, rule_name: str, count: int = 1) -> None:
        """Increments the counter for a triggered moderation rule."""
        with self._lock:
            self._data["rules_triggered"][rule_name] = self._data["rules_triggered"].get(rule_name, 0) + count

    def set_error(self, msg: str) -> None:
        """Records the last error message."""
        with self._lock:
            self._data["last_error"] = {"message": msg, "time": time.time()}

    def snapshot(self) -> Dict[str, Any]:
        """Returns a copy of the current metrics."""
        with self._lock:
            snap = dict(self._data)
            # Deep copy mutable structures
            snap["subreddits"] = {k: dict(v) for k, v in self._data["subreddits"].items()}
            snap["rules_triggered"] = dict(self._data["rules_triggered"])
            snap["uptime_seconds"] = time.time() - self._data["start_time"]
            return snap

# Global singleton instance
METRICS = Metrics()
