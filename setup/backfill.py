"""Backfill historical games from a date range.

Usage:
    python setup/backfill.py --sport baseball --start 20260201 --end 20260401
    python setup/backfill.py --sport basketball --start 20260301 --end 20260320 --dry-run
    python setup/backfill.py --sport football --start 20250901 --end 20250930 -y  # skip SSH prompt
"""

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from utils.ssh_tunnel import setup_ssh_tunnel_if_configured
setup_ssh_tunnel_if_configured()

from mid_major_upset.main import _get_season_year, poll_sport
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def backfill(sport_key: str, start: str, end: str, dry_run: bool = False) -> None:
    start_date = datetime.strptime(start, "%Y%m%d")
    end_date = datetime.strptime(end, "%Y%m%d")

    current = start_date
    total_upsets = 0
    days = 0

    while current <= end_date:
        date_str = current.strftime("%Y%m%d")
        season_year = _get_season_year(sport_key, current.replace(tzinfo=ET))

        print(f"Backfilling {sport_key} for {date_str} (season {season_year})...")
        upsets = poll_sport(sport_key, date_str, season_year, dry_run=dry_run)
        total_upsets += upsets
        days += 1

        if upsets:
            print(f"  → {upsets} upset(s) found!")

        current += timedelta(days=1)
        time.sleep(0.5)

    print(f"\nBackfill complete: {days} days, {total_upsets} upset(s) found.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical games")
    parser.add_argument("--sport", required=True, choices=["football", "basketball", "baseball"])
    parser.add_argument("--start", required=True, help="Start date (YYYYMMDD)")
    parser.add_argument("--end", required=True, help="End date (YYYYMMDD)")
    parser.add_argument("--dry-run", action="store_true", help="Don't post tweets")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip SSH tunnel confirmation")
    args = parser.parse_args()
    backfill(args.sport, args.start, args.end, dry_run=args.dry_run)
