"""Sanity checks on riddle generation. Requires build_db.py + build_graph.py to have run.
Makes real network calls (media resolution) on first run per player; cached afterward.
"""

import pytest

from footy_quiz import db, riddle
from footy_quiz.ingest import DEFAULT_DB_PATH

DI_MARIA = 2995
RAMOS = 5201


@pytest.fixture(scope="module", autouse=True)
def _require_db():
    if not DEFAULT_DB_PATH.exists():
        pytest.skip(f"{DEFAULT_DB_PATH} not built yet -- run scripts/build_db.py first")
    conn = db.connect()
    if conn.sql("SELECT COUNT(*) FROM teammate_edges").fetchone()[0] == 0:
        pytest.skip("teammate_edges is empty -- run scripts/build_graph.py first")
    conn.close()


def test_di_maria_recurring_costar_with_ramos():
    r = riddle.get_riddle(DI_MARIA)
    assert len(r.clues) >= 2
    teammate_ids = {c.teammate_player_id for c in r.clues}
    assert RAMOS in teammate_ids
    ramos_clues = [c for c in r.clues if c.teammate_player_id == RAMOS]
    assert len(ramos_clues) == 2
    assert {c.team_name for c in ramos_clues} == {"Real Madrid", "Paris Saint-Germain"}


def test_clue_count_respects_max_clues():
    r = riddle.get_riddle(DI_MARIA, max_clues=1)
    assert len(r.clues) == 1


def test_no_clue_from_an_international_competition():
    r = riddle.get_riddle(DI_MARIA)
    for c in r.clues:
        assert "national" not in c.competition_name.lower()
        assert c.competition_name not in ("FIFA World Cup", "UEFA Euro", "Copa America")


def test_clues_have_distinct_teams_unless_recurring_costar():
    r = riddle.get_riddle(DI_MARIA)
    team_ids = [c.team_id for c in r.clues]
    assert len(team_ids) == len(set(team_ids))  # each clue is a distinct club


def test_every_clue_has_a_crest_and_sortable_year():
    r = riddle.get_riddle(DI_MARIA)
    for c in r.clues:
        assert c.team_crest_url is not None
        assert c.season_start_year > 1900


def test_unqualified_player_raises():
    with pytest.raises(ValueError):
        riddle.get_riddle(999_999_999)
