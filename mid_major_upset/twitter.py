"""Tweet composition and posting via tweepy."""

import logging

import tweepy

from . import config
from .detector import Upset, UpsetContext

log = logging.getLogger(__name__)


def _ordinal(n: int) -> str:
    """Convert integer to ordinal string: 1 -> '1st', 2 -> '2nd', etc."""
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


TWEET_LIMIT = 280


def _rank_prefix(rank: int | None, name: str) -> str:
    return f"#{rank} {name}" if rank else name


def compose_tweet(upset: Upset, context: UpsetContext, winner_handle: str | None = None, winner_hashtag: str | None = None) -> str:
    """Build tweet text, peeling optional parts until it fits within 280 chars.

    Drop order when too long: trailing hashtag -> the school's @handle -> the
    conference-standing line. The headline and the season-total line always stay.
    """
    sport_display = config.SPORTS[upset.sport_key]["display"]
    winner_loc = upset.winner.location or upset.winner.display_name
    loser_str = _rank_prefix(upset.loser.rank, upset.loser.location or upset.loser.display_name)

    handle = None
    if winner_handle:
        handle = winner_handle if winner_handle.startswith("@") else f"@{winner_handle}"
    tag = None
    if winner_hashtag:
        tag = winner_hashtag if winner_hashtag.startswith("#") else f"#{winner_hashtag}"

    conf = upset.winner_conference_name
    if context.conference_tied:
        standing = f"The {conf} is tied for {_ordinal(context.conference_rank)} with {context.conference_count}."
    else:
        standing = f"The {conf} is {_ordinal(context.conference_rank)} with {context.conference_count}."

    def build(with_handle: bool, with_standing: bool, with_tag: bool) -> str:
        winner_name = f"{winner_loc} ({handle})" if (with_handle and handle) else winner_loc
        winner_str = _rank_prefix(upset.winner.rank, winner_name)
        lines = [
            f"{sport_display} Upset! {winner_str} defeated {loser_str} {upset.winner.score}-{upset.loser.score}.",
            f"This is the {_ordinal(context.sport_upset_total)} mid-major upset in {sport_display.lower()} this year.",
        ]
        if with_standing:
            lines.append(standing)
        text = "\n".join(lines)
        if with_tag and tag:
            text = f"{text}\n{tag}"
        return text

    # Full tweet, then progressively drop: hashtag, then @handle, then the standing line.
    for with_handle, with_standing, with_tag in [
        (True, True, True),
        (True, True, False),
        (False, True, False),
        (False, False, False),
    ]:
        text = build(with_handle, with_standing, with_tag)
        if len(text) <= TWEET_LIMIT:
            return text

    # Headline + season-total line alone still over the limit (shouldn't happen): hard-truncate.
    return text[: TWEET_LIMIT - 3] + "..."


def get_twitter_client() -> tweepy.Client | None:
    """Create a tweepy Client. Returns None if credentials are missing."""
    if not all([config.TWITTER_API_KEY, config.TWITTER_API_KEY_SECRET,
                config.TWITTER_ACCESS_TOKEN, config.TWITTER_ACCESS_TOKEN_SECRET]):
        log.warning("Twitter credentials not configured — tweets will be skipped")
        return None

    return tweepy.Client(
        consumer_key=config.TWITTER_API_KEY,
        consumer_secret=config.TWITTER_API_KEY_SECRET,
        access_token=config.TWITTER_ACCESS_TOKEN,
        access_token_secret=config.TWITTER_ACCESS_TOKEN_SECRET,
    )


def post_tweet(client: tweepy.Client, text: str) -> str | None:
    """Post a tweet. Returns the tweet ID on success, None on failure."""
    try:
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        log.info("Tweet posted: %s", tweet_id)
        return str(tweet_id)
    except tweepy.TooManyRequests:
        log.warning("Twitter rate limit reached")
        return None
    except tweepy.TwitterServerError as e:
        log.error("Twitter server error: %s", e)
        return None
    except Exception as e:
        log.error("Failed to post tweet: %s", e)
        return None
