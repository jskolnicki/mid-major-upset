"""One-time setup: seed the database with reference data the bot needs before it can run.

This script populates three things:

1. Sports table — the 3 sports we track (football, basketball, baseball)
   and their ESPN API slugs so the bot knows which endpoints to hit.

2. Conferences table — the 4 Power 4 conferences (ACC, Big 12, Big Ten, SEC)
   with their ESPN IDs for each sport. ESPN uses different IDs per sport
   (e.g., SEC is ID 8 in football but ID 23 in basketball), so we store
   all 12 combinations (4 conferences x 3 sports) per season year.

3. Team overrides — Notre Dame is listed as "Independent" by ESPN in football,
   but we want to treat them as Power 4. This adds an override so the bot
   doesn't count Notre Dame losses as mid-major upsets.

Run this once, or again when a new season starts:
    python setup/seed_db.py
    python setup/seed_db.py --seasons 2027
    python setup/seed_db.py -y                # skip SSH tunnel confirmation
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from utils.ssh_tunnel import setup_ssh_tunnel_if_configured
setup_ssh_tunnel_if_configured()

from mid_major_upset import config, db


def seed(season_years: list[int]) -> None:
    conn = db.get_connection()
    db.init_db(conn)

    # ── Sports ────────────────────────────────────────────────────────
    for sport_key, sport_cfg in config.SPORTS.items():
        db.upsert_sport(conn, sport_key, sport_cfg["slug"], sport_cfg["display"])
    conn.commit()
    print(f"Seeded {len(config.SPORTS)} sports.")

    # ── Conferences + Overrides per season ────────────────────────────
    for season_year in season_years:
        count = 0
        for sport_key, conf_map in config.POWER_FOUR_CONFERENCE_IDS.items():
            for espn_id, conf_name in conf_map.items():
                db.upsert_conference(conn, sport_key, espn_id, conf_name, is_power_four=True, season_year=season_year)
                count += 1
        conn.commit()
        print(f"Seeded {count} Power 4 conference entries (season {season_year}).")

        # Notre Dame: Power 4 for football (already ACC for basketball/baseball)
        db.upsert_team_override(
            conn,
            sport_key="football",
            espn_team_id=config.NOTRE_DAME_FOOTBALL_ID,
            treat_as_power_four=True,
            reason="Notre Dame is ACC-affiliated and plays a Power 4 schedule",
            season_year=season_year,
        )
        conn.commit()
        print(f"Seeded Notre Dame football override (season {season_year}).")

    conn.close()
    print(f"Done. Database: {config.DB_NAME} on {config._get_db_host()}:{config._get_db_port()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the mid-major-upset database")
    parser.add_argument("--seasons", type=int, nargs="+", default=[2025, 2026],
                        help="Season years to seed (default: 2025 2026)")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip SSH tunnel confirmation")
    args = parser.parse_args()
    seed(args.seasons)
