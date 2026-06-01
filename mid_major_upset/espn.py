"""ESPN API client and team caching."""

import logging
import re
import pymysql
from dataclasses import dataclass

import httpx

from . import config, db

log = logging.getLogger(__name__)

_client = httpx.Client(timeout=15.0)

# Cached basketball standings: school location -> conference name.
# Used as a fallback when the baseball team endpoint doesn't return conference data.
_basketball_conference_cache: dict[str, str] | None = None


@dataclass
class Competitor:
    espn_team_id: str
    display_name: str
    location: str
    name: str
    abbreviation: str
    conference_id: str | None
    score: int | None
    home_away: str
    winner: bool | None
    rank: int | None  # None if unranked (ESPN uses 99 for unranked)
    record: str | None  # overall W-L summary, e.g. "18-1"


@dataclass
class Event:
    espn_event_id: str
    name: str
    date: str  # YYYY-MM-DD
    status_name: str  # STATUS_FINAL, STATUS_IN_PROGRESS, etc.
    completed: bool
    home: Competitor
    away: Competitor
    season_year: int | None
    neutral_site: bool


def _parse_rank(curated_rank: dict | None) -> int | None:
    """Return the rank (1-25) or None if unranked."""
    if not curated_rank:
        return None
    rank = curated_rank.get("current", 99)
    return rank if rank != 99 else None


def _parse_score(score_str: str | None) -> int | None:
    if score_str is None or score_str == "":
        return None
    try:
        return int(score_str)
    except ValueError:
        return None


def _parse_competitor(comp: dict) -> Competitor:
    team = comp.get("team", {})
    records = comp.get("records") or []
    record = next((r.get("summary") for r in records if r.get("type") == "total"), None)
    return Competitor(
        espn_team_id=str(team.get("id", "")),
        display_name=team.get("displayName", ""),
        location=team.get("location", ""),
        name=team.get("name", ""),
        abbreviation=team.get("abbreviation", ""),
        conference_id=str(team["conferenceId"]) if team.get("conferenceId") else None,
        score=_parse_score(comp.get("score")),
        home_away=comp.get("homeAway", ""),
        winner=comp.get("winner"),
        rank=_parse_rank(comp.get("curatedRank")),
        record=record,
    )


def _parse_event(event: dict) -> Event | None:
    """Parse a single event from the scoreboard response."""
    competitions = event.get("competitions", [])
    if not competitions:
        return None
    comp = competitions[0]

    competitors = comp.get("competitors", [])
    if len(competitors) < 2:
        return None

    # ESPN puts home first, away second
    home_comp = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away_comp = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    status = comp.get("status", {}).get("type", {})

    # Extract date as YYYY-MM-DD from ISO string
    date_str = event.get("date", "")[:10]

    # Extract season year from the event if available
    season_year = None
    season = event.get("season", {})
    if isinstance(season, dict):
        season_year = season.get("year")

    return Event(
        espn_event_id=str(event.get("id", "")),
        name=event.get("name", ""),
        date=date_str,
        status_name=status.get("name", ""),
        completed=status.get("completed", False),
        home=_parse_competitor(home_comp),
        away=_parse_competitor(away_comp),
        season_year=season_year,
        neutral_site=bool(comp.get("neutralSite")),
    )


def fetch_scoreboard(sport_key: str, date_str: str) -> list[Event]:
    """Fetch the scoreboard for a sport on a given date (YYYYMMDD format).

    Returns parsed Event objects.
    """
    sport_cfg = config.SPORTS.get(sport_key)
    if not sport_cfg:
        log.error("Unknown sport: %s", sport_key)
        return []

    url = f"{config.ESPN_BASE}/{sport_cfg['slug']}/scoreboard"
    params = {"dates": date_str, "limit": 200}

    try:
        resp = _client.get(url, params=params)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.error("ESPN scoreboard request failed for %s on %s: %s", sport_key, date_str, e)
        return []

    data = resp.json()

    # Try to get season year from the league-level data
    season_year = None
    for league in data.get("leagues", []):
        s = league.get("season", {})
        if isinstance(s, dict) and s.get("year"):
            season_year = s["year"]
            break

    events = []
    for raw_event in data.get("events", []):
        event = _parse_event(raw_event)
        if event:
            if event.season_year is None:
                event.season_year = season_year
            events.append(event)

    return events


def fetch_team_info(sport_key: str, espn_team_id: str) -> dict | None:
    """Fetch detailed team info from ESPN. Returns raw team dict or None."""
    sport_cfg = config.SPORTS.get(sport_key)
    if not sport_cfg:
        return None

    url = f"{config.ESPN_BASE}/{sport_cfg['slug']}/teams/{espn_team_id}"
    try:
        resp = _client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.error("ESPN team request failed for %s/%s: %s", sport_key, espn_team_id, e)
        return None

    return resp.json().get("team")


def _parse_conference_from_standing(standing_summary: str | None) -> str | None:
    """Extract conference name from standingSummary like '1st in ACC - Atlantic'.

    Division suffixes like ' - Atlantic', ' - East', ' - West' have spaces around
    the dash and get stripped. Conference names with dashes like 'C-USA' and
    'A-Sun' have NO spaces around the dash and are preserved.
    """
    if not standing_summary:
        return None
    m = re.search(r"in\s+(.+?)(?:\s+- [A-Za-z]+)?$", standing_summary)
    return m.group(1).strip() if m else None


def _get_basketball_conference_map() -> dict[str, str]:
    """Fetch basketball standings and build a school location -> conference name map.

    ESPN's basketball standings have proper conference breakdowns for all 365 D1 schools.
    This is used as a fallback when the baseball team endpoint doesn't return conference data.
    The result is cached for the lifetime of the process.
    """
    global _basketball_conference_cache
    if _basketball_conference_cache is not None:
        return _basketball_conference_cache

    url = f"{config.ESPN_BASE}/basketball/mens-college-basketball/standings"
    # Standings endpoint uses a different base path
    url = "https://site.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings"
    try:
        resp = _client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("Failed to fetch basketball standings for conference fallback: %s", e)
        _basketball_conference_cache = {}
        return _basketball_conference_cache

    data = resp.json()
    mapping = {}
    for child in data.get("children", []):
        conf_name = child.get("name", "")
        # Clean up conference names (ESPN uses "Big East Conference", we want "Big East")
        conf_name = conf_name.replace(" Conference", "")
        for entry in child.get("standings", {}).get("entries", []):
            team = entry.get("team", {})
            location = team.get("location", "").strip()
            if location:
                mapping[location] = conf_name

    log.info("Loaded %d school-to-conference mappings from basketball standings", len(mapping))
    _basketball_conference_cache = mapping
    return mapping


def _resolve_conference_from_team_endpoint(
    sport_key: str, espn_team_id: str, team_location: str = ""
) -> tuple[str | None, str | None]:
    """Fetch team endpoint and extract (conference_id, conference_name).

    For baseball where conferenceId isn't on the scoreboard.
    Returns (groups.parent.id or groups.id, parsed conference name).

    If the team endpoint doesn't return a conference name (common in baseball),
    falls back to basketball standings which has conference data for all D1 schools.
    """
    team_data = fetch_team_info(sport_key, espn_team_id)
    if not team_data:
        return None, None

    groups = team_data.get("groups", {})
    conf_id = None
    if groups:
        is_conference = groups.get("isConference", False)
        if is_conference:
            conf_id = str(groups.get("id", ""))
        else:
            parent = groups.get("parent", {})
            conf_id = str(parent.get("id", "")) if parent else None

    # Try standingSummary first
    conf_name = _parse_conference_from_standing(team_data.get("standingSummary"))

    # "Division I" is a generic ESPN label, not a real conference — treat as unknown
    if conf_name == "Division I":
        conf_name = None

    # Fallback: cross-reference with basketball standings by school name
    if not conf_name:
        location = team_location or team_data.get("location", "")
        if location:
            bball_map = _get_basketball_conference_map()
            conf_name = bball_map.get(location)
            if conf_name:
                log.debug("Resolved %s conference via basketball fallback: %s", location, conf_name)

    return conf_id, conf_name


def resolve_team_conference(
    conn: pymysql.Connection,
    sport_key: str,
    competitor: Competitor,
    season_year: int,
) -> tuple[str | None, str | None, bool]:
    """Resolve a competitor's conference ID, name, and Power 4 status.

    Uses conferenceId from the scoreboard if available (football/basketball),
    falls back to team cache or ESPN team endpoint (baseball).

    Returns (conference_id, conference_name, is_power_four).
    """
    espn_team_id = competitor.espn_team_id

    # 1. Check team-level override (Notre Dame football, etc.)
    override = db.get_team_override(conn, sport_key, espn_team_id, season_year)
    if override:
        # Still need conf name for display; get from cache or API
        cached = db.get_cached_team(conn, sport_key, espn_team_id, season_year)
        conf_name = cached["conference_name"] if cached else "Independent"
        return None, conf_name, bool(override["treat_as_power_four"])

    # 2. If conferenceId is on the scoreboard (football/basketball)
    if competitor.conference_id:
        conf_id = competitor.conference_id
        p4_ids = config.POWER_FOUR_CONFERENCE_IDS.get(sport_key, {})
        is_p4 = conf_id in p4_ids
        conf_name = p4_ids.get(conf_id)
        if not conf_name:
            # Check conferences table
            row = db.get_conference(conn, sport_key, conf_id, season_year)
            if row:
                conf_name = row["conference_name"]
            else:
                # Check team cache
                cached = db.get_cached_team(conn, sport_key, espn_team_id, season_year)
                if cached and cached["conference_name"]:
                    conf_name = cached["conference_name"]
                else:
                    # Fetch from team endpoint to discover the conference name
                    _, resolved_name = _resolve_conference_from_team_endpoint(sport_key, espn_team_id, competitor.location)
                    if not resolved_name:
                        # Last resort: basketball standings cross-reference
                        bball_map = _get_basketball_conference_map()
                        resolved_name = bball_map.get(competitor.location)
                    conf_name = resolved_name or f"Conf-{conf_id}"
                    # Cache the team and auto-discover the conference
                    db.upsert_team(
                        conn, sport_key, espn_team_id,
                        team_name=competitor.name, team_location=competitor.location,
                        team_display_name=competitor.display_name, team_abbreviation=competitor.abbreviation,
                        espn_conference_id=conf_id, conference_name=conf_name,
                        is_power_four=is_p4, season_year=season_year,
                    )
                    db.upsert_conference(conn, sport_key, conf_id, conf_name, is_p4, season_year)
                    conn.commit()
        return conf_id, conf_name, is_p4

    # 3. Check team cache
    cached = db.get_cached_team(conn, sport_key, espn_team_id, season_year)
    if cached and cached["espn_conference_id"]:
        conf_id = cached["espn_conference_id"]
        p4_ids = config.POWER_FOUR_CONFERENCE_IDS.get(sport_key, {})
        is_p4 = conf_id in p4_ids or bool(cached["is_power_four"])
        return conf_id, cached["conference_name"], is_p4

    # 4. Fetch from ESPN team endpoint (baseball fallback)
    conf_id, conf_name = _resolve_conference_from_team_endpoint(sport_key, espn_team_id, competitor.location)
    if conf_id:
        p4_ids = config.POWER_FOUR_CONFERENCE_IDS.get(sport_key, {})
        is_p4 = conf_id in p4_ids or (conf_name in config.POWER_FOUR_NAMES if conf_name else False)

        # Cache the team
        db.upsert_team(
            conn, sport_key, espn_team_id,
            team_name=competitor.name,
            team_location=competitor.location,
            team_display_name=competitor.display_name,
            team_abbreviation=competitor.abbreviation,
            espn_conference_id=conf_id,
            conference_name=conf_name,
            is_power_four=is_p4,
            season_year=season_year,
        )

        # Auto-discover conference if not in DB
        existing = db.get_conference(conn, sport_key, conf_id, season_year)
        if not existing and conf_name:
            db.upsert_conference(conn, sport_key, conf_id, conf_name, is_p4, season_year)

        conn.commit()
        return conf_id, conf_name, is_p4

    log.warning("Could not resolve conference for %s %s (team %s)", sport_key, competitor.display_name, espn_team_id)
    return None, None, False
