from __future__ import annotations

import os
import re
from json import load
from pathlib import Path
from typing import Dict, List, Pattern, Final

import praw
import pytz

try:
    # Optional: load .env only in local/dev environments
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # dotenv is optional; ignoring failures keeps prod containers lighter
    pass

# Timezone (keep a single shared tzinfo)
chicago_tz: Final = pytz.timezone("America/Chicago")


# App configuration helpers
def _get_env(name: str, *, required: bool = True, default: str | None = None) -> str | None:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


# PRAW/Reddit client setup — read credentials from environment (do NOT hardcode)
REDDIT_CLIENT_ID = _get_env("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = _get_env("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = _get_env("REDDIT_USERNAME")
REDDIT_PASSWORD = _get_env("REDDIT_PASSWORD")
REDDIT_USER_AGENT = _get_env("REDDIT_USER_AGENT", required=False, default="EmpireGuard/1.0 (by u/<your-username>)")

reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    username=REDDIT_USERNAME,
    password=REDDIT_PASSWORD,
    user_agent=REDDIT_USER_AGENT,
)

# Subreddits list (CSV in env). Filter blanks and strip spaces
_subs_raw = os.getenv("SUBREDDITS", "")
SUBREDDIT: List[str] = [s.strip() for s in _subs_raw.split(",") if s.strip()]

# Defaults (consider moving to rules JSON; keep here if needed globally)
TIME_WINDOW_HOURS: Final[int] = 24
MAX_POSTS: Final[int] = 1
MIN_ACCOUNT_AGE_DAYS: Final[int] = 60
MIN_COMBINED_KARMA: Final[int] = 20

# Track recent posts; keep empty at startup to avoid stale fixtures
# Key convention: (author_key, subreddit_name) where author_key is author.id or author.name
recent_posts: Dict[tuple, List] = {}

# Profanity library init is cheap but guard just in case
try:
    from better_profanity import profanity

    profanity.load_censor_words()
except Exception:
    # If loading fails, the app should still function; the checker can handle absence gracefully
    pass

# Banned patterns (kept here only if you need a global fallback).
# Prefer configuring patterns per-subreddit in rules JSON.
BANNED_PATTERNS: List[Pattern[str]] = [
    re.compile(r"(?i)\binvite[-\s]?for[-\s]?invite\b"),
    re.compile(r"(?i)\bfree\s+nitro\b"),
    re.compile(r"(?i)\bgiveaway\b"),
]

# Robust Discord invite matcher: supports discord.gg and discord.com/invite
# Ignores trailing punctuation like ')' or '.'
REQUIRED_DISCORD_LINK: Final[Pattern[str]] = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?(?:discord\.gg|discord\.com/invite)/[A-Za-z0-9-]+(?=[^\w-]|$)"
)

# Load rules from JSON (UTF-8). Log-and-continue if missing or invalid.
RULES_PATH = Path("./config/subreddit_rules.json")
try:
    if RULES_PATH.is_file():
        with RULES_PATH.open("r", encoding="utf-8") as rules_file:
            SUBREDDIT_RULES = load(rules_file)
    else:
        SUBREDDIT_RULES = {}
except Exception as e:
    # Keep running even if rules fail to load
    SUBREDDIT_RULES = {}