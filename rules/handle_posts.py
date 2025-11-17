import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Any, Optional, Callable

from utilities.globals import chicago_tz, recent_posts, SUBREDDIT_RULES
from utilities.messaging import send_reply_with_footer
from utilities.ratelimiter import RATE_LIMITER
from utilities.metrics import METRICS
from . import rule_functions

# All logging is now configured at the application entry point
logger = logging.getLogger(__name__)

# Rule Registry to map rule names from JSON to functions
RULE_REGISTRY: Dict[str, Callable[..., Optional[str]]] = {
    "check_account_restrictions": rule_functions.check_account_restrictions,
    "enforce_rate_limit": rule_functions.enforce_rate_limit,
    "disallow_nsfw_and_offensive": rule_functions.disallow_nsfw_and_offensive,
    "require_discord_link": rule_functions.require_discord_link,
    "check_banned_patterns": rule_functions.check_banned_patterns,
    "respect_privacy": rule_functions.respect_privacy,
    "require_ad_flair": rule_functions.require_ad_flair,
    "validate_post_format": rule_functions.validate_post_format,
    "monitor_for_heated_discussion_keywords": rule_functions.monitor_for_heated_discussion_keywords,
}


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


def _make_log(submission, subreddit_name: str) -> logging.LoggerAdapter:
    """Creates a logger adapter with contextual submission info."""
    author = getattr(submission, "author", None)
    extra = {
        "submission_id": getattr(submission, "id", "<no-id>"),
        "subreddit": subreddit_name,
        "author_id": getattr(author, "id", "<no-author-key>") if author else "<no-author-key>",
        "author_name": getattr(author, "name", "<unknown>") if author else "<no-author>",
    }
    return logging.LoggerAdapter(logger, extra)


def _apply_moderation_action(submission, reason: str, triggered_rule: str, log: logging.LoggerAdapter, subreddit_name: str):
    """Removes a post and replies with the reason."""
    try:
        # Increment the counter for the triggered rule first
        METRICS.incr_rule_trigger(triggered_rule)

        wait = RATE_LIMITER.next_available_in()
        if wait > 0:
            log.debug(f"Rate limit slot not immediately available; waiting ~{wait:.2f}s")
        with RATE_LIMITER:
            submission.mod.remove()
        log.warning(
            "Removed post",
            extra={"reason": reason, "triggered_rule": triggered_rule, "action": "remove"},
        )
        with RATE_LIMITER:
            send_reply_with_footer(submission, reason, subreddit_name)
    except Exception as e:
        log.exception(f"Failed to apply moderation action for rule '{triggered_rule}': {e}")


def _approve_post(submission, log: logging.LoggerAdapter):
    """Approves a post."""
    try:
        wait = RATE_LIMITER.next_available_in()
        if wait > 0:
            log.debug(f"Rate limit slot not immediately available; waiting ~{wait:.2f}s")
        with RATE_LIMITER:
            submission.mod.approve()
        log.info("Post approved", extra={"action": "approve"})
    except Exception as e:
        log.exception(f"Failed to approve post: {e}")


def handle_submission(submission, subreddit_name: str) -> None:
    """
    Handles a new submission by processing it through a data-driven rule pipeline.
    """
    log = _make_log(submission, subreddit_name)
    operation_name = f"handle_submission(id={getattr(submission, 'id', '<no-id>')}, sub={subreddit_name})"

    with log_context(log.logger, operation_name):
        author = getattr(submission, "author", None)
        if not author:
            log.warning("Submission has no author; skipping moderation.")
            return

        # Load rules for the current subreddit
        subreddit_config = SUBREDDIT_RULES.get("subreddits", {}).get(subreddit_name, {})
        rules_to_run = subreddit_config.get("rules", [])

        if not rules_to_run:
            log.warning("No rules found for subreddit, taking no action.")
            return

        # --- Rule Processing Loop ---
        removal_reason = None
        triggered_rule = None

        for rule in rules_to_run:
            rule_name = rule.get("name")
            rule_params = rule.get("params", {})
            rule_func = RULE_REGISTRY.get(rule_name)

            if not rule_func:
                log.error(f"Rule function '{rule_name}' not found in registry. Skipping.")
                continue

            log.debug(f"Executing rule: {rule_name}")
            try:
                # Pass common objects to every rule function
                reason = rule_func(
                    submission=submission,
                    author=author,
                    params=rule_params,
                    subreddit_name=subreddit_name,
                    log=log
                )
                if reason:
                    removal_reason = reason
                    triggered_rule = rule_name
                    log.info(f"Rule '{rule_name}' triggered removal. Reason: {reason}")
                    break  # Stop on the first triggered rule
            except Exception as e:
                log.exception(f"An unexpected error occurred while executing rule '{rule_name}': {e}")
                # Optional: decide if a single rule failure should stop the whole process
                # For now, we'll log and continue
                continue

        # --- Apply Final Action ---
        if removal_reason and triggered_rule:
            _apply_moderation_action(submission, removal_reason, triggered_rule, log, subreddit_name)
        else:
            # If no rules resulted in removal, approve the post
            _approve_post(submission, log)

        # Always record post for rate-limiting purposes, even if removed
        try:
            author_key = getattr(author, "id", getattr(author, "name", "<unknown>"))
            now = datetime.now(chicago_tz)
            recent_posts.setdefault((author_key, subreddit_name), []).append(now)
        except Exception as e:
            log.exception("Failed to record recent post for rate-limiting: {e}")