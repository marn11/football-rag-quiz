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

-- One row per (player_id_a, player_id_b, team_id): the two players shared a squad list for
-- `shared_matches` matches at that team, somewhere in the dataset's coverage. player_id_a is
-- always the smaller id -- an unordered pair stored once, not twice. Populated by footy_quiz.graph.
CREATE TABLE teammate_edges (
    player_id_a INTEGER NOT NULL REFERENCES players(player_id),
    player_id_b INTEGER NOT NULL REFERENCES players(player_id),
    team_id INTEGER NOT NULL REFERENCES teams(team_id),
    shared_matches INTEGER NOT NULL,
    first_shared_date DATE,
    last_shared_date DATE,
    PRIMARY KEY (player_id_a, player_id_b, team_id)
);

-- Same edges, broken down by competition/season, so a clue can cite *which* competition and
-- season the shared squad membership happened in (e.g. "the 2018/19 Champions League").
CREATE TABLE teammate_edge_contexts (
    player_id_a INTEGER NOT NULL,
    player_id_b INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    competition_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,
    matches_in_context INTEGER NOT NULL,
    PRIMARY KEY (player_id_a, player_id_b, team_id, competition_id, season_id),
    FOREIGN KEY (player_id_a, player_id_b, team_id)
        REFERENCES teammate_edges (player_id_a, player_id_b, team_id),
    FOREIGN KEY (competition_id, season_id) REFERENCES competitions (competition_id, season_id)
);
