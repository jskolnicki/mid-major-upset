# Mid-Major Upset Bot

Twitter bot that tweets when a non-Power 4 conference team defeats a Power 4 team in college basketball, college football, or college baseball.

## Example tweets

```
College Football Upset! South Florida defeated #13 Florida 18-16.
This is the 5th mid-major upset in college football this year.
The American is 1st with 2.
```

```
College Baseball Upset! Kent State defeated #7 Arkansas 4-2.
This is the 8th mid-major upset in college baseball this year.
The MAC is tied for 2nd with 2.
```

When the winner has a Twitter handle/hashtag, the handle is appended to its name (`Kent State (@KentStBSB)`) and the hashtag goes on a trailing line. To stay within Twitter's 280-character limit, `compose_tweet` drops optional parts in this order until it fits: **trailing hashtag → the school's @handle → the conference-standing line**. The headline and the season-total line are always kept.

When one poll finds multiple upsets, tweets are spaced out by `TWEET_DELAY_SECONDS` (default 24, env-overridable) instead of firing back-to-back. The first tweet posts immediately; each subsequent one waits the delay. Dry-run/backfill never sleeps.

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your MySQL credentials. Then create the database:

```sql
CREATE DATABASE mid_major_upset;
```

Seed the reference data (conferences, Notre Dame override):

```bash
python setup/seed_db.py --seasons 2025 2026
```

### Twitter handles

Each team gets a `team_twitter` row automatically: every poll, `insert_team_twitter_stubs`
adds a `NULL`-handle stub for any team in `teams` that lacks one, so the table stays aligned
to the teams actually seen in games. Handles and hashtags are filled in **manually** in the
database (e.g. `UPDATE team_twitter SET twitter_handle='KentStBSB' WHERE ...`). There is no
CSV import step — `compose_tweet` simply omits the @handle/hashtag for any team whose row is
still `NULL`.

## Usage

```bash
# Auto-detect active sports, poll today
python -m mid_major_upset

# Poll a specific sport and date
python -m mid_major_upset --sport football --date 20250906

# Dry run (detect upsets but don't tweet)
python -m mid_major_upset --sport basketball --date 20251125 --dry-run

# Backfill a date range
python setup/backfill.py --sport baseball --start 20260201 --end 20260401 --dry-run
```

## Production (VPS)

To run against the production database from your local machine, uncomment the `DB_SSH_*` variables in `.env`. An SSH tunnel will be created automatically. See `DATABASE-PATTERN.md` in the parent directory for details.

On the VPS itself, set up a cron job that runs **every 4 minutes, 24/7**:

```cron
*/4 * * * * cd /opt/mid-major-upset && venv/bin/python -m mid_major_upset >> /opt/mid-major-upset/logs/cron.log 2>&1
```

Because the cron redirects output to a file (not a terminal), the app logs at `ERROR` and `cron.log` collects only tracebacks — a healthy run writes nothing, so the file grows only when something fails (no rotation needed). Run the command by hand in a terminal and you get the full `INFO` poll trail instead. Tweet success/failure is recorded in the `tweet_history` table either way.

Run cron unconditionally — **do not** restrict the cron hours. The app gates its own active window in **Eastern time** (`SPORT_SEASONS` + `SPORT_POLL_HOURS`, currently 10 AM–5 AM ET), using `ZoneInfo("America/New_York")`, so it stays correct even though the VPS clock is UTC. Outside the active window or off-season, the run exits immediately without hitting ESPN.

Each auto run polls **yesterday and today** (ET). A West Coast/Hawaii game still in progress at ET midnight finishes under the *previous* ET date on ESPN's scoreboard, so polling both dates guarantees those late finals aren't missed; already-processed games are skipped, so the extra fetch is cheap.

> **Note:** The `-y` flag is only needed when running locally with an SSH tunnel (`DB_SSH_*` set). On the VPS the DB is local, so no tunnel is opened and `-y` is neither required nor valid (argparse will reject it).

## Data source

All game data comes from the ESPN hidden API (free, no auth). The bot polls the scoreboard endpoint for each sport, detects completed games where a non-P4 team beat a P4 team, and tweets with contextual stats.

## Captured context

An upset is still any win by a non-Power-4 team over a Power-4 team. For each upset the `upsets` table stores, for both teams:

- **Rank** (`winner_rank` / `loser_rank`) — ESPN `curatedRank`, the AP/coaches **poll** rank (1–25), null when unranked. This is a poll ranking, **not** NET or RPI (those aren't in the ESPN scoreboard payload). A ranked mid-major winner is rare but shows up in the tweet too (e.g. `#23 Team defeated #7 Team`); unranked teams get no prefix.
- **Record** (`winner_record` / `loser_record`) — overall W-L at game time, e.g. `"18-1"`.
- **Site** (`winner_home_away`) — `home` / `away` / `neutral`, so road upsets are identifiable.

Records and site are stored for context/analysis; only the rank prefix appears in tweet text today.

Conference names are normalized to one canonical form via `config.canonical_conference_name()` (e.g. ESPN's "West Coast" and "WCC" both store as `WCC`), so the per-conference tweet count never fragments.

## Power 4 conferences

ACC, Big 12, Big Ten, SEC (`config.POWER_FOUR_CONFERENCE_IDS`). Notre Dame is treated as Power 4 for all sports (they're ACC for basketball/baseball, and have a team override for football where ESPN lists them as Independent).

> **Seasons covered:** only the **post-2024-realignment era** is tracked — football 2024+, basketball/baseball 2025+. This is the period in which the four-conference Power-4 definition is unambiguous, so there is **no Pac-12 special case** (the Pac-12 dissolved after the 2023-24 year; its Oregon State / Washington State remnant is just a mid-major). Restricting to recent seasons also keeps baseball accurate, since ESPN's team endpoint reports *current* conference membership.
