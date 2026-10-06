"""Sanity checks on answer validation + autocomplete. Requires build_db.py to have run."""

import duckdb
import pytest

from footy_quiz import answers
from footy_quiz.ingest import DEFAULT_DB_PATH

MESSI = 5503  # nickname "Lionel Messi"
DI_MARIA = 2995  # nickname "Ángel Di María" -- compound surname via particle "di"


@pytest.fixture(scope="module", autouse=True)
def _require_db():
    if not DEFAULT_DB_PATH.exists():
        pytest.skip(f"{DEFAULT_DB_PATH} not built yet -- run scripts/build_db.py first")
    conn = duckdb.connect(str(DEFAULT_DB_PATH), read_only=True)
    conn.close()


def test_exact_full_name_and_nickname():
    assert answers.check_answer(MESSI, "Lionel Andrés Messi Cuccittini").correct
    assert answers.check_answer(MESSI, "Lionel Messi").correct


def test_surname_only_guess_is_correct():
    r = answers.check_answer(MESSI, "Messi")
    assert r.correct
    assert r.confidence == "exact_surname"


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


def test_autocomplete_matches_second_word_token():
    results = answers.autocomplete_candidates("ram", limit=10)
    assert any("Ramos" in r["player_nickname"] or "" for r in results)
    names = [r["player_name"] for r in results]
    assert any("Ramos" in n for n in names)


def test_autocomplete_empty_for_nonsense_prefix():
    assert answers.autocomplete_candidates("zzqxqz") == []


def test_autocomplete_respects_limit():
    results = answers.autocomplete_candidates("a", limit=3)
    assert len(results) <= 3
