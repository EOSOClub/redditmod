
def send_reply_with_footer(submission, reason, subreddit_name):
    """
    Sends a reply to a submission, appending a standard bot footer.

    :param submission: The PRAW submission object to reply to.
    :param reason: The primary content of the reply message.
    :param subreddit_name: The name of the subreddit, used to build the modmail link.
    """
    footer = f"""

---

*I am a bot, and this action was performed automatically. Please [contact the moderators of this subreddit](/message/compose/?to=/r/{subreddit_name}) if you have any questions or concerns.*"""
    full_message = reason + footer
    submission.reply(full_message)
