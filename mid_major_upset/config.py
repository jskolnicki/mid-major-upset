"""Configuration, constants, and Power 4 conference definitions."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")


# --- MySQL database credentials ---
# If DB_TUNNEL_PORT is set (by ssh_tunnel.py), route through the tunnel.
def _get_db_host() -> str:
    if os.getenv("DB_TUNNEL_PORT"):
        return "127.0.0.1"
    return os.getenv("DB_HOST", "127.0.0.1")


def _get_db_port() -> int:
    tunnel_port = os.getenv("DB_TUNNEL_PORT")
    if tunnel_port:
        return int(tunnel_port)
    return int(os.getenv("DB_PORT", "3306"))


DB_USER = os.environ.get("DB_USER", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "mid_major_upset")

# --- Twitter credentials ---
TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY", "")
TWITTER_API_KEY_SECRET = os.environ.get("TWITTER_API_KEY_SECRET", "")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "")

# --- Schema path ---
SCHEMA_PATH = _project_root / "schema.sql"

# --- Sports definitions ---
SPORTS = {
    "football": {
        "slug": "football/college-football",
        "display": "College Football",
    },
    "basketball": {
        "slug": "basketball/mens-college-basketball",
        "display": "College Basketball",
    },
    "baseball": {
        "slug": "baseball/college-baseball",
        "display": "College Baseball",
    },
}

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# --- Power 4 conference IDs per sport ---
POWER_FOUR_CONFERENCE_IDS = {
    "football": {
        "1": "ACC",
        "4": "Big 12",
        "5": "Big Ten",
        "8": "SEC",
    },
    "basketball": {
        "2": "ACC",
        "7": "Big Ten",
        "8": "Big 12",
        "23": "SEC",
    },
    "baseball": {
        "37": "ACC",
        "44": "Big 12",
        "48": "Big Ten",
        "29": "SEC",
    },
}

# Power 4 conference names (for matching standingSummary text in baseball)
POWER_FOUR_NAMES = {"ACC", "Big 12", "Big Ten", "Big 10", "SEC"}

# Collapse the different name strings ESPN/our resolver emit for one conference (full standings
# name vs abbreviation) to a single canonical form, so the per-conference tweet/count stops
# fragmenting (e.g. "West Coast" and "WCC" must not be counted separately).
CONFERENCE_NAME_ALIASES = {
    "Atlantic Coast": "ACC", "Southeastern": "SEC", "Big 10": "Big Ten",
    "West Coast": "WCC", "Mid-American": "MAC", "Atlantic 10": "A-10",
    "Conference USA": "C-USA", "CUSA": "C-USA", "Missouri Valley": "MVC",
    "Coastal Athletic Association": "CAA", "Patriot": "Patriot League",
    "Western Athletic": "WAC", "Mid-Eastern Athletic": "MEAC",
    "Southwestern Athletic": "SWAC", "Metro Atlantic Athletic": "MAAC",
}


def canonical_conference_name(name: str | None) -> str | None:
    """Return the canonical name for a conference, collapsing known spelling variants."""
    return CONFERENCE_NAME_ALIASES.get(name, name) if name else name

# --- Season months (inclusive) ---
SPORT_SEASONS = {
    "football": [8, 9, 10, 11, 12, 1],
    "basketball": [11, 12, 1, 2, 3, 4],
    "baseball": [2, 3, 4, 5, 6],
}

# --- Polling hours (ET, 24h; end > 24 means "next day", e.g. 29 = 5 AM) ---
# 10 AM–5 AM ET covers from before any game finishes through the latest West Coast/Hawaii
# finishes; the 5 AM–10 AM ET gap has no college games starting or ending. Hours are checked
# in Eastern regardless of server timezone (main.py uses ZoneInfo("America/New_York")).
SPORT_POLL_HOURS = {
    "football": (10, 29),
    "basketball": (10, 29),
    "baseball": (10, 29),
}

# --- Notre Dame football team ID on ESPN ---
NOTRE_DAME_FOOTBALL_ID = "87"
