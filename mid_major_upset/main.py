"""Entry point: poll ESPN → detect upsets → tweet.

Usage:
    python -m mid_major_upset                             # Auto-detect active sports, poll today
    python -m mid_major_upset --sport basketball          # Poll specific sport
    python -m mid_major_upset --date 20260320             # Poll specific date
    python -m mid_major_upset --sport baseball --date 20260401
    python -m mid_major_upset --dry-run                   # Detect upsets but don't tweet
    python -m mid_major_upset --dry-run -y                # Skip SSH tunnel confirmation prompt
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from . import config, db
from .detector import build_context, detect_upset
from .espn import fetch_scoreboard
from .twitter import compose_tweet, get_twitter_client, post_tweet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Seconds to pause between consecutive tweets in one run, so multiple upsets in a single
# poll are spaced out instead of posted back-to-back. Override via env on the server.
TWEET_DELAY_SECONDS = float(os.environ.get("TWEET_DELAY_SECONDS", "24"))

def _is_sport_active(sport_key: str, now: datetime) -> bool:
    """Check if a sport is in-season and within polling hours."""
    months = config.SPORT_SEASONS.get(sport_key, [])
    if now.month not in months:
        return False

    start_h, end_h = config.SPORT_POLL_HOURS.get(sport_key, (0, 24))
    current_hour = now.hour
    # Handle overnight (e.g., 10 to 26 means 10 AM to 2 AM next day)
    if end_h > 24:
        return current_hour >= start_h or current_hour < (end_h - 24)
    return start_h <= current_hour < end_h


def _get_season_year(sport_key: str, date: datetime) -> int:
    """Determine the season year for a sport on a given date.

    Football: Aug-Dec → that year, Jan → previous year.
    Basketball: Nov-Dec → next year, Jan-Apr → that year.
    Baseball: Always the calendar year.
    """
    if sport_key == "football":
        return date.year if date.month >= 7 else date.year - 1
    elif sport_key == "basketball":
        return date.year + 1 if date.month >= 10 else date.year
    else:
        return date.year


def poll_sport(sport_key: str, date_str: str, season_year: int, dry_run: bool = False) -> int:
    """Poll a single sport for a single date. Returns number of upsets found."""
    conn = db.get_connection()
    db.init_db(conn)

    log_id = db.start_poll_log(conn, sport_key, date_str)
    conn.commit()

    twitter_client = None if dry_run else get_twitter_client()
    upsets_found = 0
    tweets_posted = 0  # used to space out consecutive posts within one run

    try:
        events = fetch_scoreboard(sport_key, date_str)
        log.info("[%s] Fetched %d events for %s", sport_key, len(events), date_str)

        for event in events:
            # Determine season year from event or fallback
            sy = event.season_year or season_year

            # Map ESPN status to our status
            if event.completed:
                status = "final"
            elif event.status_name == "STATUS_CANCELED":
                status = "canceled"
            elif event.status_name == "STATUS_POSTPONED":
                status = "postponed"
            elif event.status_name in ("STATUS_IN_PROGRESS", "STATUS_HALFTIME", "STATUS_END_PERIOD"):
                status = "in_progress"
            else:
                status = "scheduled"

            # Upsert the game
            game_id = db.upsert_game(
                conn, sport_key, event.espn_event_id, event.date,
                event.home.espn_team_id, event.away.espn_team_id,
                event.home.score, event.away.score, status,
            )
            conn.commit()

            # Only process final games that haven't been processed yet
            if status != "final":
                continue

            # Check if already processed
            with conn.cursor() as cur:
                cur.execute("SELECT processed FROM games WHERE id=%s", (game_id,))
                game_row = cur.fetchone()
            if game_row and game_row["processed"]:
                continue

            # Detect upset
            upset = detect_upset(conn, event, game_id, sport_key, sy)

            if upset:
                upsets_found += 1
                ctx = build_context(conn, upset)

                # Insert upset record
                winner_site = "neutral" if upset.neutral_site else upset.winner.home_away
                upset_id = db.insert_upset(
                    conn, game_id, sport_key, sy, event.date,
                    upset.winner.espn_team_id, upset.winner.display_name,
                    upset.winner.abbreviation, upset.winner_conference_name,
                    upset.winner.score, upset.winner.rank, upset.winner.record, winner_site,
                    upset.loser.espn_team_id, upset.loser.display_name,
                    upset.loser.abbreviation, upset.loser_conference_name,
                    upset.loser.score, upset.loser.rank, upset.loser.record,
                )

                # Compose tweet
                winner_handle = db.get_team_handle(conn, sport_key, upset.winner.espn_team_id)
                winner_hashtag = db.get_team_hashtag(conn, sport_key, upset.winner.espn_team_id)
                tweet_text = compose_tweet(upset, ctx, winner_handle, winner_hashtag)
                log.info("[%s] UPSET DETECTED: %s", sport_key, tweet_text)

                # Post tweet
                if twitter_client and not dry_run:
                    # Space out consecutive posts so several upsets in one poll
                    # don't fire back-to-back.
                    if tweets_posted:
                        time.sleep(TWEET_DELAY_SECONDS)
                    tweet_id = post_tweet(twitter_client, tweet_text)
                    tweets_posted += 1
                    if tweet_id:
                        db.insert_tweet(conn, upset_id, tweet_text, "upset", tweet_id, "sent")
                        db.mark_upset_tweeted(conn, upset_id)
                    else:
                        db.insert_tweet(conn, upset_id, tweet_text, "upset", None, "failed")
                else:
                    log.info("[DRY RUN] Would tweet: %s", tweet_text)

            # Mark game as processed regardless
            db.mark_game_processed(conn, game_id, is_upset=upset is not None)
            conn.commit()

        db.complete_poll_log(conn, log_id, len(events), upsets_found)
        conn.commit()

    except Exception as e:
        log.exception("Poll failed for %s on %s", sport_key, date_str)
        db.fail_poll_log(conn, log_id, str(e))
        conn.commit()

    finally:
        conn.close()

    return upsets_found


def main():
    parser = argparse.ArgumentParser(description="Mid-Major Upset Bot")
    parser.add_argument("--sport", choices=["football", "basketball", "baseball"],
                        help="Poll a specific sport (default: auto-detect active sports)")
    parser.add_argument("--date", help="Date to poll in YYYYMMDD format (default: today)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect upsets but don't post tweets")
    args = parser.parse_args()

    now = datetime.now(ET)

    # On the auto path, poll yesterday AND today (ET). A West Coast/Hawaii game still in
    # progress at ET midnight ends under the *previous* ET date on ESPN's scoreboard, so a
    # today-only poll would miss it. With an explicit --date, poll just that date.
    if args.date:
        dates = [args.date]
    else:
        dates = [(now - timedelta(days=1)).strftime("%Y%m%d"), now.strftime("%Y%m%d")]

    if args.sport:
        sports_to_poll = [args.sport]
    else:
        # Auto-detect which sports are active right now
        sports_to_poll = [s for s in config.SPORTS if _is_sport_active(s, now)]
        if not sports_to_poll:
            log.info("No sports are currently active. Use --sport to force a poll.")
            sys.exit(0)

    total_upsets = 0
    for sport_key in sports_to_poll:
        for date_str in dates:
            poll_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=ET)
            season_year = _get_season_year(sport_key, poll_date)
            log.info("Polling %s for %s (season %d)", sport_key, date_str, season_year)
            total_upsets += poll_sport(sport_key, date_str, season_year, dry_run=args.dry_run)

    log.info("Done. %d upset(s) found across %d sport(s).", total_upsets, len(sports_to_poll))


if __name__ == "__main__":
    main()
