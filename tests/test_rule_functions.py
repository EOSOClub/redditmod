import time
from datetime import datetime, timedelta

import pytest
from unittest.mock import MagicMock

from rules import rule_functions
from utilities.globals import chicago_tz


@pytest.fixture
def mock_author(mocker):
    """Fixture to create a mock PRAW author object."""
    author = MagicMock()
    author.name = "test_author"
    author.id = "author123"
    # Set created_utc to a fixed time in the past (e.g., 100 days ago)
    author.created_utc = (datetime.now(chicago_tz) - timedelta(days=100)).timestamp()
    author.link_karma = 50
    author.comment_karma = 50
    return author


@pytest.fixture
def mock_submission(mocker, mock_author):
    """Fixture to create a mock PRAW submission object."""
    submission = MagicMock()
    submission.author = mock_author
    submission.title = "Test Title"
    submission.selftext = "Test body content."
    submission.over_18 = False
    submission.link_flair_text = "Discussion"
    return submission


# --- Tests for check_account_restrictions ---

def test_check_account_restrictions_pass(mock_submission, mock_author):
    """Test that the rule passes when account is old enough and has enough karma."""
    params = {"min_account_age_days": 90, "min_combined_karma": 100}
    result = rule_functions.check_account_restrictions(mock_submission, mock_author, params)
    assert result is None


def test_check_account_restrictions_fail_age(mock_submission, mock_author):
    """Test that the rule fails when account is too new."""
    params = {"min_account_age_days": 120, "reason": "Account too new."}
    result = rule_functions.check_account_restrictions(mock_submission, mock_author, params)
    assert result == "Account too new."


def test_check_account_restrictions_fail_karma(mock_submission, mock_author):
    """Test that the rule fails when account has too little karma."""
    params = {"min_combined_karma": 200, "reason": "Not enough karma."}
    result = rule_functions.check_account_restrictions(mock_submission, mock_author, params)
    assert result == "Not enough karma."


# --- Tests for enforce_rate_limit ---

def test_enforce_rate_limit_pass(mocker, mock_submission, mock_author):
    """Test that the rule passes when user is not spamming."""
    mocker.patch('rules.rule_functions.is_spamming', return_value=False)
    params = {"max_posts": 1, "window_hours": 24}
    result = rule_functions.enforce_rate_limit(mock_submission, mock_author, params, subreddit_name="testsub")
    assert result is None


def test_enforce_rate_limit_fail(mocker, mock_submission, mock_author):
    """Test that the rule fails when user is spamming."""
    mocker.patch('rules.rule_functions.is_spamming', return_value=True)
    params = {"max_posts": 1, "window_hours": 24, "reason": "Too many posts."}
    result = rule_functions.enforce_rate_limit(mock_submission, mock_author, params, subreddit_name="testsub")
    assert result == "Too many posts."


# --- Tests for disallow_nsfw_and_offensive ---

def test_disallow_nsfw_pass(mock_submission):
    """Test that a normal post passes the NSFW check."""
    result = rule_functions.disallow_nsfw_and_offensive(mock_submission, mock_submission.author, {})
    assert result is None


def test_disallow_nsfw_fail_flag(mock_submission):
    """Test that a post flagged as over_18 fails."""
    mock_submission.over_18 = True
    params = {"reason": "NSFW content is not allowed."}
    result = rule_functions.disallow_nsfw_and_offensive(mock_submission, mock_submission.author, params)
    assert result == "NSFW content is not allowed."


def test_disallow_nsfw_fail_offensive_word(mocker, mock_submission):
    """Test that a post with an offensive word fails."""
    mocker.patch('rules.rule_functions.is_actually_offensive', return_value=True)
    params = {"reason": "Offensive content."}
    result = rule_functions.disallow_nsfw_and_offensive(mock_submission, mock_submission.author, params)
    assert result == "Offensive content."


# --- Tests for require_ad_flair ---

def test_require_ad_flair_pass(mock_submission):
    """Test that the rule passes when the flair is correct."""
    mock_submission.link_flair_text = "Advertisement"
    params = {"flairs": ["Advertisement", "Sponsored"]}
    result = rule_functions.require_ad_flair(mock_submission, mock_submission.author, params)
    assert result is None


def test_require_ad_flair_fail(mock_submission):
    """Test that the rule fails when the flair is incorrect."""
    mock_submission.link_flair_text = "Wrong Flair"
    params = {"flairs": ["Advertisement", "Sponsored"], "reason": "Incorrect flair."}
    result = rule_functions.require_ad_flair(mock_submission, mock_submission.author, params)
    assert result == "Incorrect flair."


def test_require_ad_flair_fail_no_flair(mock_submission):
    """Test that the rule fails when there is no flair."""
    mock_submission.link_flair_text = None
    params = {"flairs": ["Advertisement", "Sponsored"], "reason": "Missing flair."}
    result = rule_functions.require_ad_flair(mock_submission, mock_submission.author, params)
    assert result == "Missing flair."
