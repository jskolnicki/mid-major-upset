"""Upset detection and context stat computation."""

import logging
import pymysql
from dataclasses import dataclass

from . import config, db
from .espn import Competitor, Event, resolve_team_conference

log = logging.getLogger(__name__)


@dataclass
class Upset:
    game_id: int
    sport_key: str
    season_year: int
    game_date: str
    # Winner (mid-major)
    winner: Competitor
    winner_conference_name: str
    # Loser (Power 4)
    loser: Competitor
    loser_conference_name: str
    neutral_site: bool


@dataclass
class UpsetContext:
    sport_upset_total: int   # e.g. 8 → "8th mid-major upset in college baseball this year"
    conference_count: int    # e.g. 2 → "with 2"
    conference_rank: int     # e.g. 2 → "2nd"
    conference_tied: bool    # True → "tied for 2nd"


def detect_upset(
    conn: pymysql.Connection,
    event: Event,
    game_id: int,
    sport_key: str,
    season_year: int,
) -> Upset | None:
    """Check if a completed game is a mid-major upset.

    Returns an Upset if a non-P4 team beat a P4 team, else None.
    """
    home = event.home
    away = event.away

    # Both must have scores
    if home.score is None or away.score is None:
        return None

    # Resolve conferences
    home_conf_id, home_conf_name, home_is_p4 = resolve_team_conference(conn, sport_key, home, season_year)
    away_conf_id, away_conf_name, away_is_p4 = resolve_team_conference(conn, sport_key, away, season_year)

    # Need exactly one P4 and one non-P4
    if home_is_p4 == away_is_p4:
        return None

    # Determine winner
    if home.winner is True:
        winner, loser = home, away
        winner_conf_name = home_conf_name
        loser_conf_name = away_conf_name
        winner_is_p4 = home_is_p4
    elif away.winner is True:
        winner, loser = away, home
        winner_conf_name = away_conf_name
        loser_conf_name = home_conf_name
        winner_is_p4 = away_is_p4
    else:
        # No winner determined (tie or missing data)
        # Fall back to score comparison
        if home.score > away.score:
            winner, loser = home, away
            winner_conf_name = home_conf_name
            loser_conf_name = away_conf_name
            winner_is_p4 = home_is_p4
        elif away.score > home.score:
            winner, loser = away, home
            winner_conf_name = away_conf_name
            loser_conf_name = home_conf_name
            winner_is_p4 = away_is_p4
        else:
            return None  # Tie — skip

    # Only an upset if the NON-P4 team won
    if winner_is_p4:
        return None

    return Upset(
        game_id=game_id,
        sport_key=sport_key,
        season_year=season_year,
        game_date=event.date,
        winner=winner,
        winner_conference_name=config.canonical_conference_name(winner_conf_name) or "Unknown",
        loser=loser,
        loser_conference_name=config.canonical_conference_name(loser_conf_name) or "Unknown",
        neutral_site=event.neutral_site,
    )


def build_context(conn: pymysql.Connection, upset: Upset) -> UpsetContext:
    """Compute point-in-time stats for an upset: the sport-season total and this
    conference's standing (rank + tie + count) among conferences in the sport+season.
    """
    counts = db.get_sport_conference_counts(conn, upset.sport_key, upset.season_year)
    # The current upset isn't inserted yet, so include it.
    conf = upset.winner_conference_name
    counts[conf] = counts.get(conf, 0) + 1

    conf_count = counts[conf]
    return UpsetContext(
        sport_upset_total=sum(counts.values()),
        conference_count=conf_count,
        conference_rank=1 + sum(1 for n in counts.values() if n > conf_count),
        conference_tied=sum(1 for n in counts.values() if n == conf_count) > 1,
    )
