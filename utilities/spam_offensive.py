import logging
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, Sequence, Tuple, List, Dict

from better_profanity import profanity

from utilities.globals import chicago_tz, recent_posts
from utilities.words import soft_curse_words
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
# Convert to a set once for O(1) membership checks
_SOFT_CURSE_WORDS_SET = set(soft_curse_words)

# Tokenizer that keeps simple word tokens and apostrophes (e.g., don't, it's)
_WORD_RE = re.compile(r"\b[\w']+\b")


def _mask_word(w: str) -> str:
    """
    Mask a word to avoid logging offensive terms in plaintext.
    Keeps first/last character when possible, masks the middle.
    """
    if not w:
        return ""
    if len(w) <= 2:
        return "*" * len(w)
    return f"{w[0]}{'*' * (len(w) - 2)}{w[-1]}"


def is_spamming(
    author: str,
    max_posts: int,
    window_hours: int,
    window_minutes: int,
    subreddit_name: Optional[str] = None,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """
    Return True if the user has posted at least `max_posts` items within the given window.

    Notes:
    - Uses timezone-aware timestamps based on `chicago_tz`.
    - The comparison is "at least" (>=) rather than "exceeds" to match typical rate-limit semantics.
    - Accepts an optional `now` for testability.
    """
    # Basic validation
    if not author:
        logger.warning(
            "is_spamming_invalid_author",
            extra={
                "component": "spam_offensive",
                "func": "is_spamming",
                "reason": "empty_author",
                "subreddit": subreddit_name,
            },
        )
        return False

    if max_posts <= 0:
        # Consider non-positive thresholds as "always spamming" to avoid divide-by-zero semantics downstream.
        logger.warning(
            "is_spamming_non_positive_threshold",
            extra={
                "component": "spam_offensive",
                "func": "is_spamming",
                "author": author,
                "subreddit": subreddit_name,
                "max_posts": max_posts,
                "window_hours": window_hours,
                "window_minutes": window_minutes,
            },
        )
        return True

    # Normalize/validate window
    if window_hours < 0 or window_minutes < 0:
        logger.warning(
            "is_spamming_negative_window_normalized",
            extra={
                "component": "spam_offensive",
                "func": "is_spamming",
                "author": author,
                "subreddit": subreddit_name,
                "window_hours_in": window_hours,
                "window_minutes_in": window_minutes,
            },
        )
        window_hours = max(0, window_hours)
        window_minutes = max(0, window_minutes)

    # Allow injecting time for deterministic tests
    _now = now or datetime.now(chicago_tz)
    window_start = _now - timedelta(hours=window_hours, minutes=window_minutes)

    # Retrieve and filter posts in the given window.
    # Key is (author, subreddit_name) to support per-subreddit rate limits.
    # If your system also needs global-per-author limits, consider checking (author, None) separately.
    try:
        user_posts: Sequence[datetime] = recent_posts.get((author, subreddit_name), [])
    except Exception as e:
        logger.exception(
            "is_spamming_recent_posts_error",
            extra={
                "component": "spam_offensive",
                "func": "is_spamming",
                "author": author,
                "subreddit": subreddit_name,
                "error": str(e),
            },
        )
        user_posts = []

    # Keep only timestamps strictly inside the time window
    user_posts_in_window = [t for t in user_posts if t > window_start]

    posts_in_window = len(user_posts_in_window)
    is_spam = posts_in_window >= max_posts

    logger.info(
        "is_spamming_result",
        extra={
            "component": "spam_offensive",
            "func": "is_spamming",
            "author": author,
            "subreddit": subreddit_name,
            "max_posts": max_posts,
            "window_hours": window_hours,
            "window_minutes": window_minutes,
            "window_start": window_start.isoformat(),
            "window_end": _now.isoformat(),
            "known_posts_total": len(user_posts),
            "posts_in_window": posts_in_window,
            "result": is_spam,
        },
    )

    return is_spam


def is_actually_offensive(text: Optional[str]) -> bool:
    """
    Heuristic offensive-content check:
    - Uses better_profanity.contains_profanity for initial screening.
    - Tokenizes text and re-checks flagged words individually.
    - If all flagged words are from a configured "soft" set, return False (allow).
    - If any flagged word is not soft, return True (block).
    - Avoids logging raw offensive terms; logs masked examples and counts instead.
    """
    if text is None:
        logger.debug(
            "offensive_check_empty_text",
            extra={"component": "spam_offensive", "func": "is_actually_offensive", "reason": "none"},
        )
        return False

    # Normalize whitespace and case
    lowered = text.strip().lower()
    if not lowered:
        logger.debug(
            "offensive_check_empty_text",
            extra={"component": "spam_offensive", "func": "is_actually_offensive", "reason": "blank"},
        )
        return False

    # Fast path: no profanity at all
    try:
        contains_any = profanity.contains_profanity(lowered)
    except Exception as e:
        # Be conservative on library errors: do not block
        logger.exception(
            "offensive_check_library_error",
            extra={"component": "spam_offensive", "func": "is_actually_offensive", "error": str(e)},
        )
        return False

    if not contains_any:
        logger.debug(
            "offensive_check_no_profanity",
            extra={
                "component": "spam_offensive",
                "func": "is_actually_offensive",
                "length": len(lowered),
                "words": len(_WORD_RE.findall(lowered)),
            },
        )
        return False

    # Tokenize once; use a set to avoid repeated checks for duplicates
    words = set(_WORD_RE.findall(lowered))
    if not words:
        logger.debug(
            "offensive_check_no_tokens",
            extra={"component": "spam_offensive", "func": "is_actually_offensive", "length": len(lowered)},
        )
        return False

    # Identify flagged words; using a set reduces redundant library calls
    try:
        flagged = {w for w in words if profanity.contains_profanity(w)}
    except Exception as e:
        logger.exception(
            "offensive_check_flagging_error",
            extra={"component": "spam_offensive", "func": "is_actually_offensive", "error": str(e)},
        )
        return False

    if not flagged:
        # Library flagged the whole text but not individual words;
        # be conservative and allow, since nothing specific was found.
        logger.info(
            "offensive_check_inconclusive_allow",
            extra={
                "component": "spam_offensive",
                "func": "is_actually_offensive",
                "length": len(lowered),
                "token_count": len(words),
            },
        )
        return False

    # Split into soft and hard/unknown
    soft = {w for w in flagged if w in _SOFT_CURSE_WORDS_SET}
    hard = flagged - soft

    result = len(hard) > 0

    # Prepare masked examples for logging
    sample_soft = [_mask_word(w) for w in list(soft)[:3]]
    sample_hard = [_mask_word(w) for w in list(hard)[:3]]

    logger.log(
        level=(20 if result else 10),  # INFO if actually offensive, else DEBUG
        msg="offensive_check_result",
        extra={
            "component": "spam_offensive",
            "func": "is_actually_offensive",
            "length": len(lowered),
            "token_count": len(words),
            "flagged_count": len(flagged),
            "soft_count": len(soft),
            "hard_count": len(hard),
            "sample_soft_masked": sample_soft,
            "sample_hard_masked": sample_hard,
            "result": result,
        },
    )

    return result