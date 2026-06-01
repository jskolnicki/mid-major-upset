"""Load verified Twitter handles from a CSV into the team_twitter table.

Only rows where verified=yes (case-insensitive) and proposed_handle is non-empty
are loaded. Safe to re-run — uses ON DUPLICATE KEY UPDATE.

Usage:
    python setup/load_team_handles.py
    python setup/load_team_handles.py --input setup/data/twitter_handles.csv
"""

import argparse
import csv
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from utils.ssh_tunnel import setup_ssh_tunnel_if_configured
setup_ssh_tunnel_if_configured()

from mid_major_upset import db


def run(input_path: Path) -> None:
    conn = db.get_connection()
    db.init_db(conn)

    loaded = 0
    skipped = 0
    with open(input_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            handle = row.get("proposed_handle", "").strip().lstrip("@")
            verified = row.get("verified", "").strip().lower()
            if not handle or verified != "yes":
                skipped += 1
                continue
            hashtag = row.get("proposed_hashtag", "").strip().lstrip("#") or None
            db.upsert_team_handle(conn, row["sport_key"], row["espn_team_id"], handle, hashtag)
            loaded += 1

    conn.commit()
    conn.close()
    print(f"Loaded {loaded} handles, skipped {skipped} unverified/empty rows.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load verified Twitter handles into team_twitter")
    parser.add_argument(
        "--input", type=Path,
        default=Path("setup/data/twitter_handles.csv"),
        help="Input CSV path (default: setup/data/twitter_handles.csv)",
    )
    args = parser.parse_args()
    run(args.input)
