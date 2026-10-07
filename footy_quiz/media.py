"""Media assets: Wikipedia-backed player photos and club crests.

StatsBomb's data has zero images (pure box-score data) -- this resolves each player/team
to the right Wikipedia article and reads its lead image via the REST "page/summary"
endpoint, which conveniently returns a `thumbnail.source` URL alongside a
`description`/`extract` we use to confirm we landed on the right article (a footballer,
not a disambiguation/"name list" page, nor an unrelated person or place with the same
name).

Fetching is lazy and on-demand (get_or_fetch_*), not a bulk prefetch job -- cached in
player_wiki/team_wiki so a given player/team is only ever looked up once. Phase 2's hint
pipeline reuses player_wiki's resolved title instead of re-resolving from scratch.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import duckdb

logger = logging.getLogger(__name__)

REST_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
ACTION_API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "footy-quiz/0.1 (https://github.com/marn11/rag-footy-quiz)"
REQUEST_TIMEOUT_S = 10
SEARCH_RESULT_LIMIT = 5

FOOTBALL_KEYWORDS = (
    "footballer",
    "football player",
    "association football",
    "football club",
    "national football team",
    "soccer",
)


def _http_get_json(url: str, params: Optional[dict] = None) -> Optional[dict]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        logger.debug("GET %s failed: %s", url, e)
        return None


def _is_football_summary(summary: dict) -> bool:
    if summary.get("type") == "disambiguation":
        return False
    text = f"{summary.get('description') or ''} {summary.get('extract') or ''}".lower()
    return any(kw in text for kw in FOOTBALL_KEYWORDS)


def _fetch_summary(title: str) -> Optional[dict]:
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    return _http_get_json(REST_SUMMARY_URL.format(title=encoded))


def _search_titles(query: str, limit: int = SEARCH_RESULT_LIMIT) -> list[str]:
    data = _http_get_json(
        ACTION_API_URL,
        {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": limit},
    )
    if not data:
        return []
    return [r["title"] for r in data.get("query", {}).get("search", [])]


def fetch_full_extract(title: str) -> Optional[str]:
    """Full plaintext article body for an ALREADY-RESOLVED title -- a different endpoint
    from _fetch_summary (which only returns a short intro, used for resolution/photos).
    Used by the hint pipeline (footy_quiz.hints.store) to get real prose to chunk."""
    data = _http_get_json(
        ACTION_API_URL,
        {"action": "query", "prop": "extracts", "explaintext": 1, "titles": title, "format": "json"},
    )
    if not data:
        return None
    for page in data.get("query", {}).get("pages", {}).values():
        extract = page.get("extract")
        if extract:
            return extract
    return None


def _resolve(
    candidate_titles: list[tuple[str, str]], search_query: str
) -> Optional[tuple[str, dict, str]]:
    """Tries each (title, method) candidate via the REST summary endpoint, then falls back
    to search. Returns (resolved_title, summary_json, method), or None if nothing resolved."""
    for title, method in candidate_titles:
        summary = _fetch_summary(title)
        if summary and _is_football_summary(summary):
            return title, summary, method

    for title in _search_titles(search_query):
        summary = _fetch_summary(title)
        if summary and _is_football_summary(summary):
            return title, summary, "search"

    return None


def resolve_player(player_name: str, player_nickname: Optional[str]) -> Optional[tuple[str, dict, str]]:
    """Nickname first: StatsBomb's player_name is often a full legal name (e.g. "Fernando
    Luiz Rosa"), while player_nickname is usually much closer to the real Wikipedia title
    (e.g. "Fernandinho"). "direct" = the plain name resolved as-is; "disambiguator" = we
    needed the "(footballer)" suffix to land on the right article."""
    candidates: list[tuple[str, str]] = []
    if player_nickname:
        candidates.append((player_nickname, "direct"))
        candidates.append((f"{player_nickname} (footballer)", "disambiguator"))
    candidates.append((player_name, "direct"))
    candidates.append((f"{player_name} (footballer)", "disambiguator"))

    search_name = player_nickname or player_name
    return _resolve(candidates, f"{search_name} footballer")


def resolve_team(team_name: str, is_national: bool) -> Optional[tuple[str, dict, str]]:
    if is_national:
        candidates = [
            (f"{team_name} national football team", "direct"),
            (team_name, "direct"),
        ]
    else:
        candidates = [
            (team_name, "direct"),
            (f"{team_name} F.C.", "disambiguator"),
            (f"{team_name} CF", "disambiguator"),
            (f"{team_name} (football club)", "disambiguator"),
        ]
    return _resolve(candidates, f"{team_name} football club")


def _is_national_team(con: duckdb.DuckDBPyConnection, team_id: int) -> bool:
    row = con.execute(
        """
        SELECT COUNT(*) FROM matches m
        JOIN competitions c ON c.competition_id = m.competition_id AND c.season_id = m.season_id
        WHERE (m.home_team_id = ? OR m.away_team_id = ?) AND c.competition_international
        """,
        [team_id, team_id],
    ).fetchone()
    return row[0] > 0


def get_or_fetch_player_photo(
    con: duckdb.DuckDBPyConnection, player_id: int, sleep_s: float = 0.2
) -> Optional[str]:
    cached = con.execute(
        "SELECT photo_url FROM player_wiki WHERE player_id = ?", [player_id]
    ).fetchone()
    if cached:
        return cached[0]

    name, nickname = con.execute(
        "SELECT player_name, player_nickname FROM players WHERE player_id = ?", [player_id]
    ).fetchone()

    result = resolve_player(name, nickname)
    time.sleep(sleep_s)

    title, method, photo_url = (None, "unresolved", None)
    if result:
        title, summary, method = result
        photo_url = (summary.get("thumbnail") or {}).get("source")

    con.execute(
        "INSERT INTO player_wiki VALUES (?, ?, ?, ?, ?)",
        [player_id, title, method, photo_url, datetime.now(timezone.utc)],
    )
    if result is None:
        logger.warning("Could not resolve Wikipedia page for player %s (%s)", player_id, name)
    return photo_url


def get_or_fetch_team_crest(
    con: duckdb.DuckDBPyConnection, team_id: int, sleep_s: float = 0.2
) -> Optional[str]:
    cached = con.execute("SELECT crest_url FROM team_wiki WHERE team_id = ?", [team_id]).fetchone()
    if cached:
        return cached[0]

    (team_name,) = con.execute(
        "SELECT team_name FROM teams WHERE team_id = ?", [team_id]
    ).fetchone()
    is_national = _is_national_team(con, team_id)

    result = resolve_team(team_name, is_national)
    time.sleep(sleep_s)

    title, method, crest_url = (None, "unresolved", None)
    if result:
        title, summary, method = result
        crest_url = (summary.get("thumbnail") or {}).get("source")

    con.execute(
        "INSERT INTO team_wiki VALUES (?, ?, ?, ?, ?)",
        [team_id, title, method, crest_url, datetime.now(timezone.utc)],
    )
    if result is None:
        logger.warning("Could not resolve Wikipedia page for team %s (%s)", team_id, team_name)
    return crest_url
