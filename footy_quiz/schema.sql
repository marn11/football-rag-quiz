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

-- Wikipedia-backed media cache, one row per player/team the first time it's looked up
-- (lazy, on demand -- not bulk-prefetched). wiki_title/photo_url(/crest_url) are NULL when
-- resolution_method = 'unresolved', so we don't keep re-attempting a name we already tried.
-- NOTE: rebuilding the DB from scratch (ingest.build()) wipes this cache like everything
-- else -- acceptable since full rebuilds are rare, deliberate, dev-time operations.
CREATE TABLE player_wiki (
    player_id INTEGER PRIMARY KEY REFERENCES players(player_id),
    wiki_title VARCHAR,
    resolution_method VARCHAR NOT NULL,  -- 'direct' | 'disambiguator' | 'search' | 'unresolved'
    photo_url VARCHAR,
    fetched_at TIMESTAMP NOT NULL
);

CREATE TABLE team_wiki (
    team_id INTEGER PRIMARY KEY REFERENCES teams(team_id),
    wiki_title VARCHAR,
    resolution_method VARCHAR NOT NULL,
    crest_url VARCHAR,
    fetched_at TIMESTAMP NOT NULL
);

-- Full Wikipedia article text for a player (reuses player_wiki's already-resolved title --
-- this is a different endpoint, the full plaintext body, not the short summary extract
-- used for the photo/description check). One row per player, fetched lazily.
CREATE TABLE wiki_pages (
    player_id INTEGER PRIMARY KEY REFERENCES players(player_id),
    wiki_title VARCHAR NOT NULL,
    raw_extract VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL
);

-- Sentence-level (occasionally 2-sentence) chunks of wiki_pages.raw_extract, embedded
-- with all-MiniLM-L6-v2 (384-dim) for the live RAG hint retrieval pipeline.
-- contains_name = TRUE chunks are never eligible as hints (they'd name the player
-- outright); specificity (1-3) softly gates how revealing an eligible hint can be.
CREATE TABLE wiki_chunks (
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    chunk_index INTEGER NOT NULL,
    text VARCHAR NOT NULL,
    embedding FLOAT[384] NOT NULL,
    contains_name BOOLEAN NOT NULL,
    specificity SMALLINT NOT NULL,
    PRIMARY KEY (player_id, chunk_index)
);
