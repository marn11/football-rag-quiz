"""Unit tests for footy_quiz.media / footy_quiz.wikidata with the network mocked out -- fast
and deterministic, no real Wikipedia/Wikidata calls."""

import duckdb

from footy_quiz import media, wikidata


def _player_wiki_con():
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE player_wiki (
            player_id INTEGER, wiki_title VARCHAR, resolution_method VARCHAR,
            photo_url VARCHAR, fetched_at TIMESTAMP, popularity_views BIGINT
        )
        """
    )
    return con


def test_player_photo_comes_from_the_stored_link_without_any_network_call(monkeypatch):
    con = _player_wiki_con()
    con.execute("INSERT INTO player_wiki VALUES (1, 'Lionel Messi', 'wikidata', 'https://x/messi.jpg', now(), NULL)")
    monkeypatch.setattr(media, "_http_get_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert media.get_or_fetch_player_photo(con, 1) == "https://x/messi.jpg"
    assert media.get_or_fetch_player_photo(con, 999) is None  # never linked: no guessing


def test_popularity_is_zero_for_a_player_with_no_linked_article(monkeypatch):
    con = _player_wiki_con()
    con.execute("INSERT INTO player_wiki VALUES (2, NULL, 'unresolved', NULL, now(), NULL)")
    monkeypatch.setattr(media, "fetch_pageviews", lambda title: (_ for _ in ()).throw(AssertionError("network")))
    assert media.get_or_fetch_player_popularity(con, 2, sleep_s=0) == 0
    assert media.get_or_fetch_player_popularity(con, 999, sleep_s=0) == 0


def test_popularity_is_fetched_once_for_the_linked_title_then_cached(monkeypatch):
    con = _player_wiki_con()
    con.execute("INSERT INTO player_wiki VALUES (3, 'Fabinho (footballer, born 1996)', 'wikidata', NULL, now(), NULL)")
    calls = []
    monkeypatch.setattr(media, "fetch_pageviews", lambda title: calls.append(title) or 1234)
    assert media.get_or_fetch_player_popularity(con, 3, sleep_s=0) == 1234
    assert media.get_or_fetch_player_popularity(con, 3, sleep_s=0) == 1234
    assert calls == ["Fabinho (footballer, born 1996)"]


def test_wikidata_parses_titles_and_photos_per_transfermarkt_id(monkeypatch):
    # Regression for the name-collision bug: each Fabinho id maps to its OWN article.
    fake = {"results": {"bindings": [
        {"tm": {"value": "225693"}, "article": {"value": "https://en.wikipedia.org/wiki/Fabinho_(footballer,_born_1993)"},
         "image": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/Fabinho%202018.jpg"}},
        {"tm": {"value": "661284"}, "article": {"value": "https://en.wikipedia.org/wiki/Fabinho_(footballer,_born_1996)"}},
        {"tm": {"value": "1091605"}},  # Wikidata item, but no English article
        {"tm": {"value": "21"}, "article": {"value": "https://en.wikipedia.org/wiki/%C3%81ngel_Di_Mar%C3%ADa"}},
    ]}}
    monkeypatch.setattr(wikidata, "_post", lambda q: fake)
    monkeypatch.setattr(wikidata.time, "sleep", lambda s: None)
    links = wikidata.fetch_links([225693, 661284, 1091605, 21, 5])
    assert links[225693] == (
        "Fabinho (footballer, born 1993)",
        "https://commons.wikimedia.org/wiki/Special:FilePath/Fabinho%202018.jpg?width=330",
    )
    assert links[661284] == ("Fabinho (footballer, born 1996)", None)
    assert links[1091605] == (None, None)
    assert links[21][0] == "Ángel Di María"
    assert 5 not in links  # no Wikidata item at all
