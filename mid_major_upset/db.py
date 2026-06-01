"""MySQL/MariaDB database initialization and query functions."""

from datetime import datetime, timezone

import pymysql
import pymysql.cursors

from . import config


def get_connection() -> pymysql.Connection:
    """Return a connection to the MySQL database.

    Uses DB_TUNNEL_PORT if an SSH tunnel is active (production via VPS),
    otherwise connects directly to DB_HOST:DB_PORT (local).
    """
    return pymysql.connect(
        host=config._get_db_host(),
        port=config._get_db_port(),
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def init_db(conn: pymysql.Connection) -> None:
    """Create all tables from schema.sql (safe to run repeatedly)."""
    schema_sql = config.SCHEMA_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        # Execute each statement separately — MySQL doesn't support executescript
        for statement in schema_sql.split(";"):
            statement = statement.strip()
            if statement:
                cur.execute(statement)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetchone(conn: pymysql.Connection, sql: str, args: tuple = ()) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def _fetchall(conn: pymysql.Connection, sql: str, args: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def _execute(conn: pymysql.Connection, sql: str, args: tuple = ()) -> int:
    """Execute a statement. Returns lastrowid for INSERTs."""
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.lastrowid


# ── Sports ────────────────────────────────────────────────────────────

def upsert_sport(conn: pymysql.Connection, sport_key: str, espn_slug: str, display_name: str) -> None:
    _execute(
        conn,
        """INSERT INTO sports (sport_key, espn_slug, display_name) VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE espn_slug=VALUES(espn_slug), display_name=VALUES(display_name)""",
        (sport_key, espn_slug, display_name),
    )


# ── Conferences ───────────────────────────────────────────────────────

def upsert_conference(
    conn: pymysql.Connection,
    sport_key: str,
    espn_conference_id: str,
    conference_name: str,
    is_power_four: bool,
    season_year: int,
) -> None:
    _execute(
        conn,
        """INSERT INTO conferences (sport_key, espn_conference_id, conference_name, is_power_four, season_year)
           VALUES (%s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE conference_name=VALUES(conference_name), is_power_four=VALUES(is_power_four)""",
        (sport_key, espn_conference_id, conference_name, is_power_four, season_year),
    )


def get_conference(conn: pymysql.Connection, sport_key: str, espn_conference_id: str, season_year: int) -> dict | None:
    return _fetchone(
        conn,
        "SELECT * FROM conferences WHERE sport_key=%s AND espn_conference_id=%s AND season_year=%s",
        (sport_key, espn_conference_id, season_year),
    )


def is_power_four_conference(conn: pymysql.Connection, sport_key: str, espn_conference_id: str, season_year: int) -> bool:
    row = get_conference(conn, sport_key, espn_conference_id, season_year)
    return bool(row and row["is_power_four"])


# ── Team Overrides ────────────────────────────────────────────────────

def upsert_team_override(
    conn: pymysql.Connection,
    sport_key: str,
    espn_team_id: str,
    treat_as_power_four: bool,
    reason: str,
    season_year: int,
) -> None:
    _execute(
        conn,
        """INSERT INTO team_overrides (sport_key, espn_team_id, treat_as_power_four, reason, season_year)
           VALUES (%s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE treat_as_power_four=VALUES(treat_as_power_four), reason=VALUES(reason)""",
        (sport_key, espn_team_id, treat_as_power_four, reason, season_year),
    )


def get_team_override(conn: pymysql.Connection, sport_key: str, espn_team_id: str, season_year: int) -> dict | None:
    return _fetchone(
        conn,
        "SELECT * FROM team_overrides WHERE sport_key=%s AND espn_team_id=%s AND season_year=%s",
        (sport_key, espn_team_id, season_year),
    )


# ── Teams (cache) ─────────────────────────────────────────────────────

def upsert_team(
    conn: pymysql.Connection,
    sport_key: str,
    espn_team_id: str,
    team_name: str,
    team_location: str,
    team_display_name: str,
    team_abbreviation: str,
    espn_conference_id: str | None,
    conference_name: str | None,
    is_power_four: bool,
    season_year: int,
) -> None:
    _execute(
        conn,
        """INSERT INTO teams (sport_key, espn_team_id, team_name, team_location, team_display_name,
                              team_abbreviation, espn_conference_id, conference_name, is_power_four,
                              season_year, last_updated)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE team_name=VALUES(team_name), team_location=VALUES(team_location),
                         team_display_name=VALUES(team_display_name), team_abbreviation=VALUES(team_abbreviation),
                         espn_conference_id=VALUES(espn_conference_id), conference_name=VALUES(conference_name),
                         is_power_four=VALUES(is_power_four), last_updated=VALUES(last_updated)""",
        (sport_key, espn_team_id, team_name, team_location, team_display_name,
         team_abbreviation, espn_conference_id, conference_name, is_power_four,
         season_year, _now()),
    )


def get_cached_team(conn: pymysql.Connection, sport_key: str, espn_team_id: str, season_year: int) -> dict | None:
    return _fetchone(
        conn,
        "SELECT * FROM teams WHERE sport_key=%s AND espn_team_id=%s AND season_year=%s",
        (sport_key, espn_team_id, season_year),
    )


def get_team_handle(conn: pymysql.Connection, sport_key: str, espn_team_id: str) -> str | None:
    row = _fetchone(
        conn,
        "SELECT twitter_handle FROM team_twitter WHERE sport_key=%s AND espn_team_id=%s",
        (sport_key, espn_team_id),
    )
    return row["twitter_handle"] if row else None


def get_team_hashtag(conn: pymysql.Connection, sport_key: str, espn_team_id: str) -> str | None:
    row = _fetchone(
        conn,
        "SELECT twitter_hashtag FROM team_twitter WHERE sport_key=%s AND espn_team_id=%s",
        (sport_key, espn_team_id),
    )
    return row["twitter_hashtag"] if row else None


def upsert_team_handle(
    conn: pymysql.Connection,
    sport_key: str,
    espn_team_id: str,
    twitter_handle: str | None,
    twitter_hashtag: str | None = None,
) -> None:
    _execute(
        conn,
        """INSERT INTO team_twitter (sport_key, espn_team_id, twitter_handle, twitter_hashtag)
           VALUES (%s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE
               twitter_handle  = COALESCE(VALUES(twitter_handle),  twitter_handle),
               twitter_hashtag = COALESCE(VALUES(twitter_hashtag), twitter_hashtag)""",
        (sport_key, espn_team_id, twitter_handle, twitter_hashtag),
    )


def insert_team_twitter_stubs(conn: pymysql.Connection) -> int:
    """Insert a NULL-handle stub row for every team not yet in team_twitter.

    Safe to re-run — only adds missing rows, never touches existing ones.
    Returns the number of rows inserted.
    """
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO team_twitter (sport_key, espn_team_id, twitter_handle, twitter_hashtag)
               SELECT DISTINCT t.sport_key, t.espn_team_id, NULL, NULL
               FROM teams t
               LEFT JOIN team_twitter tt
                   ON t.sport_key = tt.sport_key AND t.espn_team_id = tt.espn_team_id
               WHERE tt.espn_team_id IS NULL"""
        )
        return cur.rowcount


# ── Games ─────────────────────────────────────────────────────────────

def upsert_game(
    conn: pymysql.Connection,
    sport_key: str,
    espn_event_id: str,
    game_date: str,
    home_team_espn_id: str,
    away_team_espn_id: str,
    home_score: int | None,
    away_score: int | None,
    status: str,
) -> int:
    """Insert or update a game. Returns the game row id."""
    now = _now()
    _execute(
        conn,
        """INSERT INTO games (sport_key, espn_event_id, game_date, home_team_espn_id, away_team_espn_id,
                              home_score, away_score, status, first_seen_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE home_score=VALUES(home_score), away_score=VALUES(away_score),
                         status=VALUES(status),
                         completed_at=IF(VALUES(status)='final' AND completed_at IS NULL, %s, completed_at)""",
        (sport_key, espn_event_id, game_date, home_team_espn_id, away_team_espn_id,
         home_score, away_score, status, now, now),
    )
    row = _fetchone(
        conn,
        "SELECT id FROM games WHERE sport_key=%s AND espn_event_id=%s",
        (sport_key, espn_event_id),
    )
    return row["id"]


def get_unprocessed_final_games(conn: pymysql.Connection, sport_key: str, game_date: str) -> list[dict]:
    return _fetchall(
        conn,
        "SELECT * FROM games WHERE sport_key=%s AND game_date=%s AND status='final' AND processed=0",
        (sport_key, game_date),
    )


def mark_game_processed(conn: pymysql.Connection, game_id: int, is_upset: bool = False) -> None:
    _execute(conn, "UPDATE games SET processed=1, is_upset=%s WHERE id=%s", (is_upset, game_id))


# ── Upsets ────────────────────────────────────────────────────────────

def insert_upset(
    conn: pymysql.Connection,
    game_id: int,
    sport_key: str,
    season_year: int,
    game_date: str,
    winner_espn_team_id: str,
    winner_display_name: str,
    winner_abbreviation: str,
    winner_conference_name: str,
    winner_score: int,
    winner_rank: int | None,
    winner_record: str | None,
    winner_home_away: str | None,
    loser_espn_team_id: str,
    loser_display_name: str,
    loser_abbreviation: str,
    loser_conference_name: str,
    loser_score: int,
    loser_rank: int | None,
    loser_record: str | None,
) -> int:
    return _execute(
        conn,
        """INSERT INTO upsets (game_id, sport_key, season_year, game_date,
                               winner_espn_team_id, winner_display_name, winner_abbreviation, winner_conference_name, winner_score, winner_rank, winner_record, winner_home_away,
                               loser_espn_team_id, loser_display_name, loser_abbreviation, loser_conference_name, loser_score, loser_rank, loser_record,
                               created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (game_id, sport_key, season_year, game_date,
         winner_espn_team_id, winner_display_name, winner_abbreviation, winner_conference_name, winner_score, winner_rank, winner_record, winner_home_away,
         loser_espn_team_id, loser_display_name, loser_abbreviation, loser_conference_name, loser_score, loser_rank, loser_record,
         _now()),
    )


def get_sport_conference_counts(conn: pymysql.Connection, sport_key: str, season_year: int) -> dict[str, int]:
    """Upset counts per winning conference for a sport+season: {conference_name: count}."""
    rows = _fetchall(
        conn,
        """SELECT winner_conference_name AS c, COUNT(*) AS cnt FROM upsets
           WHERE sport_key=%s AND season_year=%s
           GROUP BY winner_conference_name""",
        (sport_key, season_year),
    )
    return {row["c"]: row["cnt"] for row in rows}


def mark_upset_tweeted(conn: pymysql.Connection, upset_id: int) -> None:
    _execute(conn, "UPDATE upsets SET tweeted=1 WHERE id=%s", (upset_id,))


def get_untweeted_upsets(conn: pymysql.Connection) -> list[dict]:
    return _fetchall(conn, "SELECT * FROM upsets WHERE tweeted=0 ORDER BY created_at")


# ── Tweet History ─────────────────────────────────────────────────────

def insert_tweet(
    conn: pymysql.Connection,
    upset_id: int | None,
    tweet_text: str,
    tweet_type: str,
    twitter_tweet_id: str | None,
    status: str,
    error_message: str | None = None,
) -> None:
    now = _now()
    _execute(
        conn,
        """INSERT INTO tweet_history (upset_id, tweet_text, tweet_type, twitter_tweet_id, status, error_message, attempted_at, sent_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (upset_id, tweet_text, tweet_type, twitter_tweet_id, status, error_message, now, now if status == "sent" else None),
    )
