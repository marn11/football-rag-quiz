"""Unit tests for footy_quiz.media that mock the Wikipedia HTTP layer -- no real network
calls, so these stay fast and deterministic. scripts/test_resolution.py is the
real-network eyeball check against actual tricky names, per checkpoint 5's verify step.
"""

import duckdb
import pytest

from footy_quiz import media

DISAMBIGUATION_NAME_LIST = {"type": "standard", "description": "Name list", "extract": "A given name."}
FOOTBALLER_SUMMARY = {
    "type": "standard",
    "description": "Argentine footballer",
    "extract": "Is an Argentine footballer who plays as a forward.",
    "thumbnail": {"source": "https://example.org/photo.jpg"},
}
CLUB_SUMMARY = {
    "type": "standard",
    "description": "Association football club in Spain",
    "extract": "Is a football club based in Madrid.",
    "thumbnail": {"source": "https://example.org/crest.png"},
}
CITY_SUMMARY = {"type": "standard", "description": "City and municipality in Catalonia, Spain"}


def test_is_football_summary_accepts_footballer():
    assert media._is_football_summary(FOOTBALLER_SUMMARY)


def test_is_football_summary_rejects_name_list():
    assert not media._is_football_summary(DISAMBIGUATION_NAME_LIST)


def test_is_football_summary_rejects_disambiguation_type():
    assert not media._is_football_summary({"type": "disambiguation", "extract": "footballer"})


def test_is_football_summary_rejects_unrelated_place():
    assert not media._is_football_summary(CITY_SUMMARY)


def test_resolve_player_nickname_direct_hit(monkeypatch):
    def fake_fetch_summary(title):
        return FOOTBALLER_SUMMARY if title == "Fernandinho" else None

    monkeypatch.setattr(media, "_fetch_summary", fake_fetch_summary)
    result = media.resolve_player("Fernando Luiz Rosa", "Fernandinho")
    assert result is not None
    title, summary, method = result
    assert title == "Fernandinho"
    assert method == "direct"


def test_resolve_player_falls_back_to_disambiguator_suffix(monkeypatch):
    def fake_fetch_summary(title):
        if title == "Danilo (footballer)":
            return FOOTBALLER_SUMMARY
        return DISAMBIGUATION_NAME_LIST  # plain "Danilo" is a name-list page

    monkeypatch.setattr(media, "_fetch_summary", fake_fetch_summary)
    result = media.resolve_player("Danilo Something", "Danilo")
    assert result is not None
    title, _, method = result
    assert title == "Danilo (footballer)"
    assert method == "disambiguator"


def test_resolve_player_falls_back_to_search(monkeypatch):
    monkeypatch.setattr(media, "_fetch_summary", lambda title: (
        FOOTBALLER_SUMMARY if title == "Obscure Player (footballer, born 1999)" else None
    ))
    monkeypatch.setattr(media, "_search_titles", lambda query, limit=5: [
        "Obscure Player (footballer, born 1999)"
    ])
    result = media.resolve_player("Obscure Player Full Name", None)
    assert result is not None
    title, _, method = result
    assert title == "Obscure Player (footballer, born 1999)"
    assert method == "search"


def test_resolve_player_returns_none_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(media, "_fetch_summary", lambda title: None)
    monkeypatch.setattr(media, "_search_titles", lambda query, limit=5: [])
    assert media.resolve_player("Totally Unknown Person", None) is None


def test_resolve_team_national_team_disambiguation(monkeypatch):
    def fake_fetch_summary(title):
        if title == "Portugal national football team":
            return CLUB_SUMMARY
        return {"type": "standard", "description": "Country in Southwestern Europe"}

    monkeypatch.setattr(media, "_fetch_summary", fake_fetch_summary)
    result = media.resolve_team("Portugal", is_national=True)
    assert result is not None
    title, _, method = result
    assert title == "Portugal national football team"
    assert method == "direct"  # first candidate for national teams IS the suffixed form


def test_get_or_fetch_player_photo_caches_result(monkeypatch):
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE players (player_id INTEGER, player_name VARCHAR, player_nickname VARCHAR)
        """
    )
    con.execute(
        """
        CREATE TABLE player_wiki (
            player_id INTEGER, wiki_title VARCHAR, resolution_method VARCHAR,
            photo_url VARCHAR, fetched_at TIMESTAMP
        )
        """
    )
    con.execute("INSERT INTO players VALUES (1, 'Lionel Andrés Messi Cuccittini', 'Messi')")

    call_count = 0

    def fake_resolve_player(name, nickname):
        nonlocal call_count
        call_count += 1
        return "Lionel Messi", FOOTBALLER_SUMMARY, "direct"

    monkeypatch.setattr(media, "resolve_player", fake_resolve_player)

    url1 = media.get_or_fetch_player_photo(con, 1, sleep_s=0)
    url2 = media.get_or_fetch_player_photo(con, 1, sleep_s=0)

    assert url1 == url2 == "https://example.org/photo.jpg"
    assert call_count == 1  # second call hit the cache, didn't re-resolve
    con.close()


def test_get_or_fetch_player_photo_caches_unresolved(monkeypatch):
    con = duckdb.connect()
    con.execute("CREATE TABLE players (player_id INTEGER, player_name VARCHAR, player_nickname VARCHAR)")
    con.execute(
        """
        CREATE TABLE player_wiki (
            player_id INTEGER, wiki_title VARCHAR, resolution_method VARCHAR,
            photo_url VARCHAR, fetched_at TIMESTAMP
        )
        """
    )
    con.execute("INSERT INTO players VALUES (2, 'Nobody Nobody', NULL)")
    monkeypatch.setattr(media, "resolve_player", lambda name, nickname: None)

    url = media.get_or_fetch_player_photo(con, 2, sleep_s=0)
    assert url is None
    method = con.execute("SELECT resolution_method FROM player_wiki WHERE player_id = 2").fetchone()[0]
    assert method == "unresolved"
    con.close()
