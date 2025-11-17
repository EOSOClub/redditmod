import time
import logging
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from threading import Condition, Lock
from typing import Optional, Dict, Any

# Create logger directly instead of importing from logs
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


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

class RateLimiter:
    """
    Sliding-window rate limiter with structured, low-noise logging:
    - Allows at most `max_requests` events per `time_window` seconds.
    - Thread-safe via a Condition; does not sleep while holding the lock.
    - Emits debug logs for waits (sampled) and info for configuration changes and notable events.
    """

    def __init__(
        self,
        max_requests: int,
        time_window: float,
        *,
        name: Optional[str] = None,
        log_sample_every: int = 50,
    ):
        """
        :param max_requests: Maximum number of accepted events in the window (>=1).
        :param time_window: Sliding window size in seconds (>0).
        :param name: Optional identifier for logs/metrics when multiple limiters exist.
        :param log_sample_every: Sample frequency for repetitive debug logs (>=1).
        """
        if max_requests <= 0:
            raise ValueError("max_requests must be >= 1")
        if time_window <= 0:
            raise ValueError("time_window must be > 0")
        if log_sample_every <= 0:
            raise ValueError("log_sample_every must be >= 1")

        self.max_requests = int(max_requests)
        self.time_window = float(time_window)
        self.name = name or "default"
        self._events = deque()  # stores monotonic timestamps of accepted requests
        self._cond = Condition(Lock())

        # Counters/metrics
        self._total_acquired = 0
        self._total_denied = 0
        self._total_time_waited = 0.0
        self._debug_counter = 0
        self._log_sample_every = int(log_sample_every)

        logger.info(
            "ratelimiter_initialized",
            extra=self._extra_fields()
        )

    def _extra_fields(self) -> Dict[str, Any]:
        return {
            "component": "RateLimiter",
            "limiter_name": self.name,  # renamed from "name" to avoid clobbering LogRecord.name
            "max_requests": self.max_requests,
            "time_window_s": self.time_window,
        }

    def _state_fields(self) -> Dict[str, Any]:
        # Called while holding the condition lock for consistency
        return {
            "in_window": len(self._events),
            "utilization": round(len(self._events) / self.max_requests, 3),
            "oldest_age_s": 0.0 if not self._events else round(self._now() - self._events[0], 6),
        }

    def _now(self) -> float:
        return time.monotonic()

    def _prune(self, now: float) -> None:
        cutoff = now - self.time_window
        while self._events and self._events[0] <= cutoff:
            self._events.popleft()

    def next_available_in(self) -> float:
        """
        Returns seconds until the next request is allowed (0 if available now).
        """
        with self._cond:
            now = self._now()
            self._prune(now)
            if len(self._events) < self.max_requests:
                return 0.0
            oldest = self._events[0]
            remaining = self.time_window - (now - oldest)
            return max(0.0, remaining)

    def acquire(self, block: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Attempt to consume one slot.
        - If block=False, return immediately with True/False.
        - If block=True, wait until a slot is available or until `timeout` elapses.
        Returns True if a slot was acquired, False otherwise.
        """
        start_wait = self._now()
        deadline = None if timeout is None else start_wait + max(0.0, timeout)

        with self._cond:
            while True:
                now = self._now()
                self._prune(now)

                # Fast path: slot available
                if len(self._events) < self.max_requests:
                    self._events.append(now)
                    self._total_acquired += 1
                    waited = now - start_wait
                    if waited > 0:
                        self._total_time_waited += waited
                    # Notify in case others are waiting on room/metrics
                    self._cond.notify_all()

                    # Sampled debug to avoid log storms
                    self._debug_counter += 1
                    if self._debug_counter % self._log_sample_every == 0:
                        logger.debug(
                            "ratelimiter_acquired",
                            extra={
                                **self._extra_fields(),
                                **self._state_fields(),
                                "waited_s": round(waited, 6),
                                "total_acquired": self._total_acquired,
                            },
                        )
                    return True

                # No slot and non-blocking: deny
                if not block:
                    self._total_denied += 1
                    self._debug_counter += 1
                    if self._debug_counter % self._log_sample_every == 0:
                        logger.debug(
                            "ratelimiter_denied_nonblocking",
                            extra={**self._extra_fields(), **self._state_fields(), "total_denied": self._total_denied},
                        )
                    return False

                # Compute time until the next event expires
                wait_for = self.time_window - (now - self._events[0])
                wait_for = max(0.0, wait_for)

                # Apply timeout constraint if any
                if deadline is not None:
                    remaining = max(0.0, deadline - now)
                    if remaining <= 0.0:
                        self._total_denied += 1
                        logger.info(
                            "ratelimiter_timeout",
                            extra={
                                **self._extra_fields(),
                                **self._state_fields(),
                                "timeout_s": timeout,
                                "total_denied": self._total_denied,
                            },
                        )
                        return False
                    wait_for = min(wait_for, remaining)

                # Sample a debug log right before waiting if delay is notable or sampled
                noteworthy = wait_for >= 1.0  # log more readily for longer waits
                self._debug_counter += 1
                if noteworthy or (self._debug_counter % self._log_sample_every == 0):
                    logger.debug(
                        "ratelimiter_waiting",
                        extra={**self._extra_fields(), **self._state_fields(), "wait_for_s": round(wait_for, 6)},
                    )

                # Wait releases the lock, avoiding active sleep
                self._cond.wait(timeout=wait_for)

    def try_acquire(self) -> bool:
        """Non-blocking acquire."""
        return self.acquire(block=False)

    def utilization(self) -> float:
        """
        Current window utilization ratio in [0, 1].
        """
        with self._cond:
            now = self._now()
            self._prune(now)
            return min(1.0, len(self._events) / self.max_requests)

    def stats(self) -> Dict[str, Any]:
        """
        Snapshot of limiter statistics.
        """
        with self._cond:
            now = self._now()
            self._prune(now)
            return {
                **self._extra_fields(),
                **self._state_fields(),
                "total_acquired": self._total_acquired,
                "total_denied": self._total_denied,
                "total_time_waited_s": round(self._total_time_waited, 6),
            }

    def log_stats(self, level: int = logging.INFO) -> None:
        """
        Emit a one-shot structured log with current stats.
        """
        logger.log(level, "ratelimiter_stats", extra=self.stats())

    def set_limits(self, max_requests: int, time_window: float) -> None:
        """
        Reconfigure the limiter limits safely.
        """
        if max_requests <= 0:
            raise ValueError("max_requests must be >= 1")
        if time_window <= 0:
            raise ValueError("time_window must be > 0")

        with self._cond:
            old = {"max_requests": self.max_requests, "time_window_s": self.time_window}
            self.max_requests = int(max_requests)
            self.time_window = float(time_window)
            # Prune to the new window immediately
            self._prune(self._now())

            logger.info(
                "ratelimiter_reconfigured",
                extra={**self._extra_fields(), "old": old, **self._state_fields()},
            )
            # Wake any waiters so they can recompute wait times
            self._cond.notify_all()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        # Nothing to release; using context manager is just syntactic sugar.
        return False

    def __repr__(self) -> str:
        # Use doubled braces to include literal braces in an f-string.
        return (
            f"RateLimiter(name={self.name!r}, max_requests={self.max_requests}, "
            f"time_window={self.time_window}, "
            f"stats={{'acq': {self._total_acquired}, 'deny': {self._total_denied}}})"
        )


# Example: 100 requests per 60 seconds
RATE_LIMITER = RateLimiter(max_requests=100, time_window=60.0)