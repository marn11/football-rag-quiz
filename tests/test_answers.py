"""Sanity checks on answer validation + autocomplete. Requires build_db.py to have run."""

import pytest

from footy_quiz import answers, db
from footy_quiz.ingest import DEFAULT_DB_PATH

MESSI = 28003  # player_name "Lionel Messi" -- player_nickname is NULL (see note below)
DI_MARIA = 45320  # "Ángel Di María" -- compound surname via particle "di"
GIUSEPPE_ROSSI = 19104  # also nickname IS NULL -- every transfermarkt-sourced player is

# transfermarkt's `name` field is already the common display form (never a full legal
# name needing a separate nickname to get back to), so player_nickname is NULL for every
# player in this dataset -- the "surname must come from player_name" case below isn't a
# rare edge case here, it's the norm.


@pytest.fixture(scope="module", autouse=True)
def _require_db():
    if not DEFAULT_DB_PATH.exists():
        pytest.skip(f"{DEFAULT_DB_PATH} not built yet -- run scripts/build_db.py first")
    conn = db.connect()
    conn.close()


def test_exact_full_name_guess_is_correct():
    assert answers.check_answer(MESSI, "Lionel Messi").correct


def test_surname_only_guess_is_correct():
    r = answers.check_answer(MESSI, "Messi")
    assert r.correct
    assert r.confidence == "exact_surname"


def test_surname_only_guess_works_without_a_stored_nickname():
    # Regression: found live via the API -- a player with player_nickname = NULL
    # must still accept a surname-only guess, derived from player_name instead.
    r = answers.check_answer(GIUSEPPE_ROSSI, "Rossi")
    assert r.correct
    assert r.confidence == "exact_surname"
    assert answers.check_answer(GIUSEPPE_ROSSI, "rossi").correct
    assert not answers.check_answer(GIUSEPPE_ROSSI, "Giuseppe").correct


def test_case_and_accent_insensitive():
    assert answers.check_answer(MESSI, "MESSI").correct
    assert answers.check_answer(DI_MARIA, "ANGEL DI MARIA").correct


def test_compound_surname_with_particle():
    # "Di María" -- the particle "di" must stay attached to the surname unit, so "maria"
    # alone (a very common first/middle name) is NOT accepted, only "di maria" is.
    assert answers.check_answer(DI_MARIA, "Di Maria").correct
    assert answers.check_answer(DI_MARIA, "dimaria").correct  # dropped space
    assert not answers.check_answer(DI_MARIA, "Maria").correct
    assert not answers.check_answer(DI_MARIA, "Angel").correct


def test_one_letter_typo_is_tolerated():
    assert answers.check_answer(MESSI, "Mesi").correct
    assert answers.check_answer(MESSI, "Messy").correct


def test_unrelated_name_is_rejected():
    r = answers.check_answer(MESSI, "Cristiano Ronaldo")
    assert not r.correct
    assert r.matched_name is None


def test_very_short_guess_is_rejected_not_fuzzy_matched():
    r = answers.check_answer(MESSI, "xx")
    assert not r.correct


def test_unknown_player_id_raises():
    with pytest.raises(ValueError):
        answers.check_answer(999_999_999, "anyone")


def test_autocomplete_below_min_length_returns_empty_without_querying():
    assert answers.autocomplete_candidates("a", limit=10) == []


def test_autocomplete_at_min_length_finds_a_real_two_letter_name():
    # Josué Sá -- a real player in our data whose surname is exactly 2 characters. "sa" is
    # also the start of many far more common names (Salah, Sánchez, Sané, ...), so a
    # generous limit is needed to confirm he's matched at all, not excluded by some length
    # heuristic -- this isn't testing autocomplete's popularity ranking/limit behavior,
    # that's covered separately by test_autocomplete_respects_limit.
    results = answers.autocomplete_candidates("sa", limit=1000)
    assert any("Josué Sá" == r["player_name"] for r in results)


def test_autocomplete_matches_second_word_token():
    results = answers.autocomplete_candidates("ram", limit=10)
    names = [r["player_name"] for r in results]
    assert any("Ramos" in n for n in names)


def test_autocomplete_empty_for_nonsense_prefix():
    assert answers.autocomplete_candidates("zzqxqz") == []


def test_autocomplete_respects_limit():
    results = answers.autocomplete_candidates("a", limit=3)
    assert len(results) <= 3


def test_autocomplete_keeps_matching_multi_word_input():
    # Regression: each name word was matched separately against the whole prefix, so as
    # soon as you typed a space ("lionel m") the suggestions vanished.
    for prefix, expected in [
        ("lionel m", "Lionel Messi"),
        ("lionel messi", "Lionel Messi"),
        ("cristiano r", "Cristiano Ronaldo"),
        ("di mar", "Ángel Di María"),
    ]:
        names = [r["player_name"] for r in answers.autocomplete_candidates(prefix, limit=10)]
        assert expected in names, (prefix, names)


def test_autocomplete_normalizes_punctuation_like_the_prefix():
    for prefix in ("ngolo", "n golo", "n'golo"):
        names = [r["player_name"] for r in answers.autocomplete_candidates(prefix, limit=10)]
        assert "N'Golo Kanté" in names, (prefix, names)
    names = [r["player_name"] for r in answers.autocomplete_candidates("marc andre", limit=10)]
    assert "Marc-André ter Stegen" in names
