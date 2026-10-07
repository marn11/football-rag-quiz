"""Sanity checks on riddle generation. Requires build_db.py + build_graph.py to have run.
Makes real network calls (media resolution) on first run per player; cached afterward.
"""

import pytest

from footy_quiz import db, riddle
from footy_quiz.ingest import DEFAULT_DB_PATH
from footy_quiz.riddle import _select_clue_pairs

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


# --- _select_clue_pairs: pure logic, no DB needed -----------------------------------


def test_select_clue_pairs_maximizes_club_breadth():
    # Regression: a player who played for 10 clubs (one qualifying teammate each) must
    # get clues from multiple DIFFERENT clubs, not the same club repeated 3 times.
    qualifying = [(100 + i, 200 + i, 5) for i in range(10)]
    chosen = _select_clue_pairs(qualifying, max_clues=3)
    assert len(chosen) == 3
    assert len({team_id for _, team_id in chosen}) == 3


def test_select_clue_pairs_falls_back_to_same_club_when_few_clubs_exist():
    qualifying = [(100 + i, 500, 10 - i) for i in range(5)]  # 1 club, 5 teammates
    chosen = _select_clue_pairs(qualifying, max_clues=3)
    assert len(chosen) == 3
    assert all(team_id == 500 for _, team_id in chosen)
    assert len({teammate_id for teammate_id, _ in chosen}) == 3  # distinct teammates


def test_select_clue_pairs_prioritizes_recurring_costar_then_fills_breadth():
    qualifying = [
        (999, 1, 8), (999, 2, 6),  # co-star shared across clubs 1 and 2
        (111, 3, 5),  # a third, different club/teammate
    ]
    chosen = _select_clue_pairs(qualifying, max_clues=3)
    assert set(chosen) == {(999, 1), (999, 2), (111, 3)}


def test_select_clue_pairs_respects_max_clues_with_many_options():
    qualifying = [(100 + i, 200 + i, 5) for i in range(10)]
    assert len(_select_clue_pairs(qualifying, max_clues=1)) == 1


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


def test_di_maria_fills_available_clue_slots_not_just_the_costar_pair():
    # Regression: clue generation used to stop at however many "rich" clubs a player
    # had (often just the recurring co-star's clubs), instead of using every club with
    # at least one qualifying teammate. Di María played for several clubs beyond Real
    # Madrid/PSG (Benfica, Manchester United, Juventus), so a 3rd clue should be
    # available even though only 2 clubs supply the Ramos co-star storyline.
    r = riddle.get_riddle(DI_MARIA, max_clues=3)
    assert len(r.clues) == 3


def test_every_clue_has_a_crest_and_sortable_year():
    r = riddle.get_riddle(DI_MARIA)
    for c in r.clues:
        assert c.team_crest_url is not None
        assert c.season_start_year > 1900


def test_unqualified_player_raises():
    with pytest.raises(ValueError):
        riddle.get_riddle(999_999_999)
