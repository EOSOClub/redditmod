import pytest
from unittest.mock import MagicMock, patch

from rules import handle_posts


@pytest.fixture
def mock_submission(mocker):
    """Fixture to create a mock PRAW submission object with a mock author."""
    submission = MagicMock()
    submission.author = MagicMock()
    submission.author.name = "test_author"
    submission.author.id = "author123"
    submission.author.link_karma = 10  # Set default karma
    submission.author.comment_karma = 10 # Set default karma
    submission.id = "submission123"
    submission.title = "Test Title"
    submission.selftext = "Test body"
    submission.mod = MagicMock()
    return submission


@patch('rules.handle_posts.SUBREDDIT_RULES', {
    "subreddits": {
        "testsub": {
            "rules": [
                {
                    "name": "check_account_restrictions",
                    "params": {
                        "min_combined_karma": 500,
                        "reason": "Karma too low."
                    }
                }
            ]
        }
    }
})
def test_handle_submission_triggers_removal(mock_submission):
    """
    Integration test to ensure handle_submission calls remove() and reply()
    when a rule is triggered.
    """
    # Mock the rule function itself to ensure it returns a reason
    with patch('rules.rule_functions.check_account_restrictions', return_value="Karma too low."):
        handle_posts.handle_submission(mock_submission, "testsub")

    # Verify that remove and reply were called
    mock_submission.mod.remove.assert_called_once()
    mock_submission.reply.assert_called_once_with("Karma too low.")
    # Verify approve was NOT called
    mock_submission.mod.approve.assert_not_called()


@patch('rules.handle_posts.SUBREDDIT_RULES', {
    "subreddits": {
        "testsub": {
            "rules": [
                {
                    "name": "check_account_restrictions",
                    "params": {
                        "min_combined_karma": 10
                    }
                }
            ]
        }
    }
})
def test_handle_submission_triggers_approval(mock_submission):
    """
    Integration test to ensure handle_submission calls approve()
    when no rules are triggered.
    """
    # Mock the rule function to ensure it passes (returns None)
    with patch('rules.rule_functions.check_account_restrictions', return_value=None):
        handle_posts.handle_submission(mock_submission, "testsub")

    # Verify that approve was called
    mock_submission.mod.approve.assert_called_once()
    # Verify remove and reply were NOT called
    mock_submission.mod.remove.assert_not_called()
    mock_submission.reply.assert_not_called()


@patch('rules.handle_posts.SUBREDDIT_RULES', {"subreddits": {"testsub": {"rules": []}}})
def test_handle_submission_no_rules(mock_submission):
    """
    Test that no action is taken if a subreddit has no rules defined.
    """
    handle_posts.handle_submission(mock_submission, "testsub")

    # Verify no moderation actions were taken
    mock_submission.mod.approve.assert_not_called()
    mock_submission.mod.remove.assert_not_called()
    mock_submission.reply.assert_not_called()
