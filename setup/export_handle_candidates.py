"""Export a CSV of mid-major teams needing Twitter handle research.

Fetches the full team list from ESPN for each sport, keeps only non-Power-4 teams,
LEFT JOINs team_twitter to skip any already verified, and writes a reviewable CSV.

Usage:
    python setup/export_handle_candidates.py
    python setup/export_handle_candidates.py --output setup/data/twitter_handles.csv

Fill in proposed_handle and source_url for each row, set verified=yes, then run
load_team_handles.py to push verified rows into the database.
"""

import argparse
import csv
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from utils.ssh_tunnel import setup_ssh_tunnel_if_configured
setup_ssh_tunnel_if_configured()

import httpx
from mid_major_upset import config, db


def _fetch_all_teams(sport_key: str) -> list[dict]:
    """Return all ESPN teams for a sport as raw dicts with id, displayName, conferenceId."""
    sport_cfg = config.SPORTS[sport_key]
    url = f"{config.ESPN_BASE}/{sport_cfg['slug']}/teams"
    teams = []
    page = 1
    client = httpx.Client(timeout=15.0)
    while True:
        resp = client.get(url, params={"limit": 500, "page": page})
        resp.raise_for_status()
        data = resp.json()
        items = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
        for item in items:
            team = item.get("team", {})
            conf = team.get("groups", {})
            conference_id = str(conf.get("id", "")) if conf else ""
            teams.append({
                "espn_team_id": str(team.get("id", "")),
                "display_name": team.get("displayName", ""),
                "conference_id": conference_id,
            })
        count = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("count", len(items))
        if len(teams) >= count:
            break
        page += 1
    return teams


def _is_power_four(sport_key: str, conference_id: str) -> bool:
    return conference_id in config.POWER_FOUR_CONFERENCE_IDS.get(sport_key, {})


def run(output_path: Path, include_all: bool = False) -> None:
    conn = db.get_connection()
    db.init_db(conn)

    # Build set of teams already in team_twitter
    from mid_major_upset.db import _fetchall
    existing = {
        (row["sport_key"], row["espn_team_id"])
        for row in _fetchall(conn, "SELECT sport_key, espn_team_id FROM team_twitter")
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "sport_key", "espn_team_id", "team_display_name",
            "proposed_handle", "source_url", "verified",
        ])
        writer.writeheader()
        for sport_key in config.SPORTS:
            print(f"Fetching {sport_key} teams from ESPN...")
            teams = _fetch_all_teams(sport_key)
            if include_all:
                filtered = teams
                label = f"all {len(teams)}"
            else:
                filtered = [t for t in teams if not _is_power_four(sport_key, t["conference_id"])]
                label = f"{len(filtered)} mid-major (of {len(teams)} total)"
            mid_majors = filtered
            print(f"  {label} teams")
            for team in sorted(mid_majors, key=lambda t: t["display_name"]):
                key = (sport_key, team["espn_team_id"])
                if key in existing:
                    continue
                writer.writerow({
                    "sport_key": sport_key,
                    "espn_team_id": team["espn_team_id"],
                    "team_display_name": team["display_name"],
                    "proposed_handle": "",
                    "source_url": "",
                    "verified": "",
                })
                rows_written += 1

    conn.close()
    print(f"Wrote {rows_written} candidates to {output_path}")
    print("Fill in proposed_handle + source_url, set verified=yes, then run load_team_handles.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export teams needing Twitter handles")
    parser.add_argument(
        "--output", type=Path,
        default=Path("setup/data/twitter_handles.csv"),
        help="Output CSV path (default: setup/data/twitter_handles.csv)",
    )
    parser.add_argument(
        "--include-all", action="store_true",
        help="Include Power 4 teams (default: mid-major only)",
    )
    args = parser.parse_args()
    run(args.output, include_all=args.include_all)
