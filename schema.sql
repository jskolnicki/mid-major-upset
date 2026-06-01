-- Mid-Major Upset Bot — Database Schema (MySQL/MariaDB)

CREATE TABLE IF NOT EXISTS sports (
    sport_key     VARCHAR(20) PRIMARY KEY,
    espn_slug     VARCHAR(100) NOT NULL,
    display_name  VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS conferences (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    sport_key          VARCHAR(20) NOT NULL,
    espn_conference_id VARCHAR(20) NOT NULL,
    conference_name    VARCHAR(50) NOT NULL,
    is_power_four      TINYINT(1) NOT NULL DEFAULT 0,
    season_year        INT NOT NULL,
    UNIQUE KEY uq_conf (sport_key, espn_conference_id, season_year),
    FOREIGN KEY (sport_key) REFERENCES sports(sport_key)
);

CREATE TABLE IF NOT EXISTS teams (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    sport_key          VARCHAR(20) NOT NULL,
    espn_team_id       VARCHAR(20) NOT NULL,
    team_name          VARCHAR(100) NOT NULL,
    team_location      VARCHAR(100) NOT NULL,
    team_display_name  VARCHAR(100) NOT NULL,
    team_abbreviation  VARCHAR(20) NOT NULL,
    espn_conference_id VARCHAR(20),
    conference_name    VARCHAR(50),
    is_power_four      TINYINT(1) DEFAULT 0,
    season_year        INT NOT NULL,
    last_updated       VARCHAR(50) NOT NULL,
    UNIQUE KEY uq_team (sport_key, espn_team_id, season_year),
    FOREIGN KEY (sport_key) REFERENCES sports(sport_key)
);

CREATE TABLE IF NOT EXISTS team_twitter (
    sport_key        VARCHAR(20)  NOT NULL,
    espn_team_id     VARCHAR(20)  NOT NULL,
    twitter_handle   VARCHAR(50)  NULL,
    twitter_hashtag  VARCHAR(50)  NULL,
    PRIMARY KEY (sport_key, espn_team_id),
    FOREIGN KEY (sport_key) REFERENCES sports(sport_key)
);
-- Allow NULL handles so every team can have a stub row before its handle is researched
ALTER TABLE team_twitter MODIFY COLUMN twitter_handle VARCHAR(50) NULL;

CREATE TABLE IF NOT EXISTS team_overrides (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    sport_key           VARCHAR(20) NOT NULL,
    espn_team_id        VARCHAR(20) NOT NULL,
    treat_as_power_four TINYINT(1) NOT NULL,
    reason              TEXT,
    season_year         INT NOT NULL,
    UNIQUE KEY uq_override (sport_key, espn_team_id, season_year)
);

CREATE TABLE IF NOT EXISTS games (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    sport_key         VARCHAR(20) NOT NULL,
    espn_event_id     VARCHAR(50) NOT NULL,
    game_date         VARCHAR(10) NOT NULL,
    home_team_espn_id VARCHAR(20) NOT NULL,
    away_team_espn_id VARCHAR(20) NOT NULL,
    home_score        INT,
    away_score        INT,
    status            VARCHAR(20) NOT NULL,
    is_upset          TINYINT(1) DEFAULT 0,
    processed         TINYINT(1) DEFAULT 0,
    first_seen_at     VARCHAR(50) NOT NULL,
    completed_at      VARCHAR(50),
    UNIQUE KEY uq_game (sport_key, espn_event_id),
    FOREIGN KEY (sport_key) REFERENCES sports(sport_key)
);

CREATE TABLE IF NOT EXISTS upsets (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    game_id                     INT NOT NULL,
    sport_key                   VARCHAR(20) NOT NULL,
    season_year                 INT NOT NULL,
    game_date                   VARCHAR(10) NOT NULL,
    winner_espn_team_id         VARCHAR(20) NOT NULL,
    winner_display_name         VARCHAR(100) NOT NULL,
    winner_abbreviation         VARCHAR(20) NOT NULL,
    winner_conference_name      VARCHAR(50) NOT NULL,
    winner_score                INT NOT NULL,
    winner_rank                 INT,
    winner_record               VARCHAR(15),
    winner_home_away            VARCHAR(10),
    loser_espn_team_id          VARCHAR(20) NOT NULL,
    loser_display_name          VARCHAR(100) NOT NULL,
    loser_abbreviation          VARCHAR(20) NOT NULL,
    loser_conference_name       VARCHAR(50) NOT NULL,
    loser_score                 INT NOT NULL,
    loser_rank                  INT,
    loser_record                VARCHAR(15),
    tweeted                     TINYINT(1) DEFAULT 0,
    created_at                  VARCHAR(50) NOT NULL,
    UNIQUE KEY uq_upset_game (game_id),
    FOREIGN KEY (game_id) REFERENCES games(id)
);

-- Idempotent migrations so pre-existing upsets tables pick up new columns (init_db runs these each time).
-- IMPORTANT keep these comment lines free of the semicolon character, since init_db splits the file on it.
ALTER TABLE upsets ADD COLUMN IF NOT EXISTS winner_rank INT AFTER winner_score;
ALTER TABLE upsets ADD COLUMN IF NOT EXISTS winner_record VARCHAR(15) AFTER winner_rank;
ALTER TABLE upsets ADD COLUMN IF NOT EXISTS winner_home_away VARCHAR(10) AFTER winner_record;
ALTER TABLE upsets ADD COLUMN IF NOT EXISTS loser_record VARCHAR(15) AFTER loser_rank;
-- Derived per-tweet context is computed at compose time (not stored). Drop the legacy columns.
ALTER TABLE upsets DROP COLUMN IF EXISTS upset_number_for_conference;
ALTER TABLE upsets DROP COLUMN IF EXISTS conference_rank_for_season;

CREATE TABLE IF NOT EXISTS tweet_history (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    upset_id         INT,
    tweet_text       TEXT NOT NULL,
    tweet_type       VARCHAR(20) NOT NULL DEFAULT 'upset',
    twitter_tweet_id VARCHAR(50),
    status           VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message    TEXT,
    attempted_at     VARCHAR(50) NOT NULL,
    sent_at          VARCHAR(50),
    retry_count      INT DEFAULT 0,
    FOREIGN KEY (upset_id) REFERENCES upsets(id)
);

CREATE TABLE IF NOT EXISTS poll_log (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    sport_key    VARCHAR(20) NOT NULL,
    poll_date    VARCHAR(10) NOT NULL,
    started_at   VARCHAR(50) NOT NULL,
    completed_at VARCHAR(50),
    events_found INT DEFAULT 0,
    upsets_found INT DEFAULT 0,
    errors       TEXT,
    status       VARCHAR(20) NOT NULL DEFAULT 'running',
    KEY idx_poll_log_sport_date (sport_key, poll_date)
);

-- Indexes for hot query paths
-- games: unprocessed-final scan (sport_key + game_date + status + processed)
CREATE INDEX IF NOT EXISTS idx_games_date_status ON games (sport_key, game_date, status, processed);
-- upsets: context query (get_sport_conference_counts) and untweeted retry scan
CREATE INDEX IF NOT EXISTS idx_upsets_sport_season_conf ON upsets (sport_key, season_year, winner_conference_name);
CREATE INDEX IF NOT EXISTS idx_upsets_tweeted ON upsets (tweeted, created_at);
