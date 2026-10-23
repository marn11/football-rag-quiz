CREATE TABLE competitions (
    -- Transfermarkt's own short codes ('GB1', 'CL', 'FIWC', ...), not numeric --
    -- kept as-is rather than inventing a synthetic integer id for them.
    competition_id VARCHAR NOT NULL,
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
    team_gender VARCHAR,
    -- Transfermarkt's crest CDN is keyed directly by team_id, deterministic (no lookup/
    -- disambiguation needed) -- populated at ingest time, not lazily like player_wiki.
    crest_url VARCHAR
);

CREATE TABLE matches (
    match_id INTEGER PRIMARY KEY,
    competition_id VARCHAR NOT NULL,
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
    country_name VARCHAR,
    -- Transfermarkt's own profile photo, direct and deterministic -- NULL when the
    -- source only had its generic "default.jpg" placeholder, in which case
    -- footy_quiz.media's lazy Wikipedia photo resolution is the fallback.
    photo_url VARCHAR
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
    competition_id VARCHAR NOT NULL,
    season_id INTEGER NOT NULL,
    matches_in_context INTEGER NOT NULL,
    PRIMARY KEY (player_id_a, player_id_b, team_id, competition_id, season_id),
    FOREIGN KEY (player_id_a, player_id_b, team_id)
        REFERENCES teammate_edges (player_id_a, player_id_b, team_id),
    FOREIGN KEY (competition_id, season_id) REFERENCES competitions (competition_id, season_id)
);

-- Each player's exact Wikipedia article, linked via Wikidata's Transfermarkt id by
-- scripts/build_wiki_links.py (never guessed from the name -- that confused same-named
-- players). wiki_title is NULL ('unresolved') when Wikidata has no English article for
-- them. photo_url is Wikidata's image, only used when players.photo_url is a placeholder.
-- NOTE: rebuilding the DB from scratch (ingest.build()) wipes this like everything else;
-- rerun build_wiki_links.py (cached, instant) and build_popularity.py afterwards.
CREATE TABLE player_wiki (
    player_id INTEGER PRIMARY KEY REFERENCES players(player_id),
    wiki_title VARCHAR,
    resolution_method VARCHAR NOT NULL,  -- 'wikidata' | 'unresolved'
    photo_url VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    -- Trailing-12-month en.wikipedia pageviews -- a real-world fame proxy, computed
    -- separately (and much later) from the row's initial insert, so NULL means "not
    -- looked up yet" vs. 0 meaning "looked up, genuinely near-zero traffic / no article".
    -- Only ever populated in bulk by scripts/build_popularity.py, not fetched per-request
    -- (it's an extra network call per player; difficulty banding needs it for potentially
    -- thousands of candidates at once, far too slow to do live).
    popularity_views BIGINT
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
