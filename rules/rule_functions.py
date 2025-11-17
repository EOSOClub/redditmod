
import re
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import pytz

from utilities.globals import chicago_tz, REQUIRED_DISCORD_LINK
from utilities.spam_offensive import is_actually_offensive, is_spamming

logger = logging.getLogger(__name__)


def check_account_restrictions(submission, author, params: Dict[str, Any], **kwargs) -> Optional[str]:
    """
    Checks if the author's account meets age and karma requirements.
    """
    now = datetime.now(chicago_tz)
    min_age_days = params.get("min_account_age_days")
    min_karma = params.get("min_combined_karma")

    if not min_age_days and not min_karma:
        return None

    try:
        # Account Age Check
        if min_age_days is not None:
            created_utc = getattr(author, "created_utc", None)
            if created_utc:
                account_created_dt = datetime.fromtimestamp(created_utc, pytz.utc).astimezone(chicago_tz)
                account_age_days = (now - account_created_dt).days
                if account_age_days < min_age_days:
                    logger.debug(f"Account age ({account_age_days}d) is less than required ({min_age_days}d).")
                    return params.get("reason", "Account does not meet age requirements.")
            else:
                logger.warning("Could not determine account age for author.")

        # Karma Check
        if min_karma is not None:
            link_karma = getattr(author, "link_karma", 0)
            comment_karma = getattr(author, "comment_karma", 0)
            combined_karma = (link_karma or 0) + (comment_karma or 0)
            if combined_karma < min_karma:
                logger.debug(f"Combined karma ({combined_karma}) is less than required ({min_karma}).")
                return params.get("reason", "Account does not meet karma requirements.")

    except Exception as e:
        logger.exception(f"Failed to evaluate account restrictions: {e}")

    return None


def enforce_rate_limit(submission, author, params: Dict[str, Any], subreddit_name: str, **kwargs) -> Optional[str]:
    """
    Enforces a rate limit on user submissions.
    """
    max_posts = params.get("max_posts")
    window_hours = params.get("window_hours", 0)
    window_minutes = params.get("window_minutes", 0)

    if not max_posts or (window_hours == 0 and window_minutes == 0):
        return None

    author_key = getattr(author, "id", getattr(author, "name", "<unknown>"))
    if is_spamming(author_key, max_posts, window_hours, window_minutes, subreddit_name):
        return params.get("reason", "You are posting too frequently.")

    return None


def disallow_nsfw_and_offensive(submission, author, params: Dict[str, Any], **kwargs) -> Optional[str]:
    """
    Checks for NSFW flags or offensive content in title/body.
    """
    title = submission.title or ""
    body = submission.selftext or ""

    try:
        is_nsfw = getattr(submission, "over_18", False)
        title_offensive = bool(title) and is_actually_offensive(title)
        body_offensive = bool(body) and is_actually_offensive(body)

        if is_nsfw or title_offensive or body_offensive:
            return params.get("reason", "Post contains NSFW or offensive content.")
    except Exception as e:
        logger.exception(f"Failed NSFW/offensive evaluation: {e}")

    return None


def require_discord_link(submission, author, params: Dict[str, Any], **kwargs) -> Optional[str]:
    """
    Requires a Discord invite link in the title or body.
    """
    title = submission.title or ""
    body = submission.selftext or ""

    try:
        has_invite = REQUIRED_DISCORD_LINK.search(title) or REQUIRED_DISCORD_LINK.search(body)
        if not has_invite:
            return params.get("reason", "Post must contain a Discord invite link.")
    except Exception as e:
        logger.exception(f"Failed Discord link check: {e}")

    return None


def check_banned_patterns(submission, author, params: Dict[str, Any], **kwargs) -> Optional[str]:
    """
    Checks the title and body against a list of banned regex patterns.
    """
    title = submission.title or ""
    body = submission.selftext or ""
    patterns = params.get("patterns", [])

    for pattern in patterns:
        try:
            if re.search(pattern, title, re.IGNORECASE) or re.search(pattern, body, re.IGNORECASE):
                # Return a more specific reason if possible
                specific_reason = params.get("reason", "Post contains a banned pattern.")
                return f"{specific_reason} (Matched: '{pattern}')"
        except re.error as e:
            logger.error(f"Invalid regex pattern in ban_patterns '{pattern}': {e}")

    return None


def respect_privacy(submission, author, params: Dict[str, Any], **kwargs) -> Optional[str]:
    """
    Checks for content that violates privacy rules (doxxing, personal info, etc.).
    """
    body = submission.selftext or ""
    privacy_patterns = [
        r"\\bleak(ed|s)?\\b",
        r"\\bdoxx(ing|ed|es)?\\b",
        r"personal info(?:rmation)?",
        r"(?<!not\\s)(?<!no\\s)\\bip\\s?(address|log)?\\b",
        r"\\b(real\\s)?name\\b",
        r"\\b(address(es)?|home\\saddress|location|coords?)\\b",
        r"(discord\\s)?user(name|tag)[\\s:]*[a-zA-Z0-9#]{5,}",
        r"(snapchat|instagram|twitter|email|phone\\s?number|contact info)",
        r"(?<!not\\s)(?<!no\\s)\\bface\\s?(reveal|pic|photo)?\\b",
        r"(?<!not\\s)(?<!no\\s)\\birl\\b",
        r"\\bexposed\\b",
    ]

    try:
        for pattern in privacy_patterns:
            if re.search(pattern, body, re.IGNORECASE):
                return params.get("reason", "Post violates privacy rules.")
    except re.error as e:
        logger.error(f"Invalid regex in privacy patterns: {e}")

    return None


def require_ad_flair(submission, author, params: Dict[str, Any], **kwargs) -> Optional[str]:
    """
    Requires the submission to have a specific link flair.
    """
    required_flairs = params.get("flairs", [])
    if not required_flairs:
        logger.warning("No flairs configured for 'require_ad_flair' rule.")
        return None

    flair = getattr(submission, "link_flair_text", None)
    if not flair or flair.lower() not in [f.lower() for f in required_flairs]:
        return params.get("reason", f"Post must have one of the required flairs: {', '.join(required_flairs)}")

    return None


def validate_post_format(submission, author, params: Dict[str, Any], **kwargs) -> Optional[str]:
    """
    Validates that the post title matches a required format (e.g., starts with '[WTS]').
    """
    title_pattern = params.get("title_pattern")
    if not title_pattern:
        logger.warning("No title_pattern configured for 'validate_post_format' rule.")
        return None

    title = submission.title or ""
    try:
        if not re.search(title_pattern, title):
            return params.get("reason", "Post title does not match the required format.")
    except re.error as e:
        logger.error(f"Invalid regex in validate_post_format pattern '{title_pattern}': {e}")

    return None


def monitor_for_heated_discussion_keywords(submission, author, params: Dict[str, Any], **kwargs) -> Optional[str]:
    """
    Checks for keywords that might indicate a heated or uncivil discussion.
    """
    title = submission.title or ""
    body = submission.selftext or ""
    keywords = params.get("keywords", [])

    for keyword in keywords:
        try:
            # Using word boundaries to avoid matching parts of other words
            pattern = r'\\b' + re.escape(keyword) + r'\\b'
            if re.search(pattern, title, re.IGNORECASE) or re.search(pattern, body, re.IGNORECASE):
                return params.get("reason", f"Post contains keywords that suggest a heated discussion ('{keyword}'). Please remain civil.")
        except re.error as e:
            logger.error(f"Invalid regex created from keyword '{keyword}': {e}")

    return None
