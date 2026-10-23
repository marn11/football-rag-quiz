"""Sanity checks on riddle generation. Requires build_db.py + build_graph.py to have run.
Makes real network calls (media resolution) on first run per player; cached afterward.
"""

import pytest

from footy_quiz import db, riddle
from footy_quiz.ingest import DEFAULT_DB_PATH
from footy_quiz.riddle import _select_clue_pairs

DI_MARIA = 45320
RECURRING_COSTAR = 182913  # Adrien Rabiot -- shared Juventus (506) and PSG (583) with Di María


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


def test_select_clue_pairs_never_shows_two_unrelated_teammates_from_one_club():
    # Regression: real example -- a riddle showed "Messi at PSG 2021/22" AND
    # "Kehrer at PSG 2021/22" as two separate clues. Two unrelated teammates from the
    # same club reads as arbitrary padding, not information. A player whose only real
    # signal is one club (e.g. "spent 3+ years at Eibar") now gets exactly ONE honest
    # clue, never padded with a second, unrelated teammate from that same club.
    qualifying = [(100 + i, 500, 10 - i) for i in range(5)]  # 1 club, 5 teammates
    chosen = _select_clue_pairs(qualifying, max_clues=3)
    assert len(chosen) == 1


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


def test_di_maria_recurring_costar_with_rabiot():
    r = riddle.get_riddle(DI_MARIA, prefer_recurring=True)
    assert len(r.clues) >= 2
    teammate_ids = {c.teammate_player_id for c in r.clues}
    assert RECURRING_COSTAR in teammate_ids
    costar_clues = [c for c in r.clues if c.teammate_player_id == RECURRING_COSTAR]
    assert len(costar_clues) == 2
    assert {c.team_name for c in costar_clues} == {"Juventus FC", "Paris Saint-Germain"}


def test_clue_count_respects_max_clues():
    r = riddle.get_riddle(DI_MARIA, max_clues=1, prefer_recurring=True)
    assert len(r.clues) == 1


def test_no_clue_from_an_international_competition():
    r = riddle.get_riddle(DI_MARIA, prefer_recurring=True)
    for c in r.clues:
        assert "national" not in c.competition_name.lower()
        assert c.competition_name not in ("FIFA World Cup", "UEFA Euro", "Copa America")


def test_clues_have_distinct_teams_unless_recurring_costar():
    r = riddle.get_riddle(DI_MARIA, prefer_recurring=True)
    team_ids = [c.team_id for c in r.clues]
    assert len(team_ids) == len(set(team_ids))  # each clue is a distinct club


def test_di_maria_fills_remaining_breadth_after_recurring_costar():
    # Di María's career spans many genuinely qualifying clubs in this richer dataset, so
    # after the recurring co-star (Rabiot, 2 clues) the 3rd clue slot is filled by a
    # DIFFERENT teammate at a 3rd distinct club -- never an unrelated second teammate
    # padding one of the co-star's own clubs.
    r = riddle.get_riddle(DI_MARIA, max_clues=3, prefer_recurring=True)
    assert len(r.clues) == 3
    team_ids = [c.team_id for c in r.clues]
    assert len(team_ids) == len(set(team_ids))  # 3 distinct clubs
    costar_clues = [c for c in r.clues if c.teammate_player_id == RECURRING_COSTAR]
    assert len(costar_clues) == 2
    other_clues = [c for c in r.clues if c.teammate_player_id != RECURRING_COSTAR]
    assert len(other_clues) == 1


def test_every_clue_has_a_crest_and_sortable_year():
    r = riddle.get_riddle(DI_MARIA, prefer_recurring=True)
    for c in r.clues:
        assert c.team_crest_url is not None
        assert c.season_start_year > 1900


def test_unqualified_player_raises():
    with pytest.raises(ValueError):
        riddle.get_riddle(999_999_999)


def test_breadth_first_when_recurring_not_preferred():
    # Regression: with full-career data nearly every player has a recurring co-star, so
    # always preferring one made almost every riddle "X, X, Y". Without it, 3 clues must
    # come from 3 distinct clubs AND 3 distinct teammates when the data allows.
    qualifying = [(100, 1, 9), (100, 2, 8), (101, 2, 5), (102, 3, 5), (103, 4, 5)]
    chosen = _select_clue_pairs(qualifying, max_clues=3, prefer_recurring=False)
    assert len({t for _, t in chosen}) == 3
    assert len({m for m, _ in chosen}) == 3


def test_rng_varies_choices_but_stays_valid():
    import random
    qualifying = [(100 + i, 200 + i, 5) for i in range(10)]
    picks = {
        frozenset(_select_clue_pairs(qualifying, 3, False, random.Random(seed)))
        for seed in range(20)
    }
    assert len(picks) > 1


def test_club_selection_spreads_across_years_when_given_year_data():
    # Regression: easy-mode riddles tended to show consecutive seasons (2023, 2024, 2025).
    # Given each club's seasons, a 3-clue pick from clubs spanning 2010-2025 must never
    # settle for the three clubs bunched at the end.
    import random
    qualifying = [(100 + i, 200 + i, 5) for i in range(6)]
    years_by_club = {200: [2010], 201: [2012], 202: [2018], 203: [2023], 204: [2024], 205: [2025]}
    for seed in range(30):
        chosen = _select_clue_pairs(qualifying, 3, False, random.Random(seed), years_by_club)
        years = sorted(years_by_club[t][0] for _, t in chosen)
        assert years[-1] - years[0] >= 8, (seed, years)
