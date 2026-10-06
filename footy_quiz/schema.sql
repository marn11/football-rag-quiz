CREATE TABLE competitions (
    competition_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,
    competition_name VARCHAR NOT NULL,
    season_name VARCHAR NOT NULL,
    country_name VARCHAR,
    competition_gender VARCHAR,
    competition_international BOOLEAN,
    PRIMARY KEY (competition_id, season_id)
);

CREATE TABLE teams (
    team_id INTEGER PRIMARY KEY,
    team_name VARCHAR NOT NULL,
    country_name VARCHAR,
    team_gender VARCHAR
);

CREATE TABLE matches (
    match_id INTEGER PRIMARY KEY,
    competition_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,
    match_date DATE,
    competition_stage VARCHAR,
    home_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    away_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    home_score INTEGER,
    away_score INTEGER,
    FOREIGN KEY (competition_id, season_id) REFERENCES competitions(competition_id, season_id)
);

CREATE TABLE players (
    player_id INTEGER PRIMARY KEY,
    player_name VARCHAR NOT NULL,
    player_nickname VARCHAR,
    normalized_name VARCHAR NOT NULL,
    country_name VARCHAR
);

-- One row per player named in a team's squad list for a match. "Played with" means shared
-- a squad list for a match -- players don't need to have overlapped on the pitch, so unused
-- substitutes count too (primary_position is NULL for them, since they have no position stint).
CREATE TABLE appearances (
    match_id INTEGER NOT NULL REFERENCES matches(match_id),
    team_id INTEGER NOT NULL REFERENCES teams(team_id),
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    jersey_number INTEGER,
    primary_position VARCHAR,
    PRIMARY KEY (match_id, player_id)
);
