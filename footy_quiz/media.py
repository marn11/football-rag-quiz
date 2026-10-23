"""Wikipedia-backed player data: fallback photo, article text for hints, and fame.

Which article belongs to which player is decided once, exactly, by
scripts/build_wiki_links.py (Wikidata's Transfermarkt id -> enwiki article, see
footy_quiz.wikidata) and stored in player_wiki. Nothing here guesses an article from a
player's name: that used to hand an obscure "Fabinho" the Liverpool Fabinho's pageviews
and trivia. A player with no linked article simply has no Wikipedia data.

Club crests and most player photos come directly from the vendored transfermarkt source
(teams.crest_url, players.photo_url); player_wiki.photo_url (Wikidata's image) is only the
fallback when that source has just a placeholder.
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

ACTION_API_URL = "https://en.wikipedia.org/w/api.php"
PAGEVIEWS_URL = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "en.wikipedia/all-access/all-agents/{article}/monthly/{start}/{end}"
)
USER_AGENT = "footy-quiz/0.1 (https://github.com/marn11/rag-footy-quiz)"
REQUEST_TIMEOUT_S = 10
POPULARITY_WINDOW_MONTHS = 12

_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BACKOFF_S = 0.5
_MAX_RETRY_AFTER_S = 30  # a server asking for longer than this isn't worth waiting out inline


def _http_get_json(url: str, params: Optional[dict] = None) -> Optional[dict]:
    """A 404 (genuinely no such page) is NOT retried and returns None immediately -- that's
    a real answer, not a failure. Transient failures (timeout, connection reset, 429/5xx)
    are retried a few times before giving up, and a 429's `Retry-After` header is honored
    (Wikimedia's rate limiter sends e.g. "retry-after: 11"; a short fixed backoff was
    exhausting retries while still rate-limited)."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404 or e.code not in _RETRYABLE_HTTP_STATUS or attempt == _MAX_RETRIES:
                logger.debug("GET %s failed: %s", url, e)
                return None
            retry_after = e.headers.get("Retry-After") if e.headers else None
            try:
                wait_s = min(float(retry_after), _MAX_RETRY_AFTER_S)
            except (TypeError, ValueError):
                wait_s = _RETRY_BACKOFF_S * (2**attempt)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            if attempt == _MAX_RETRIES:
                logger.debug("GET %s failed: %s", url, e)
                return None
            wait_s = _RETRY_BACKOFF_S * (2**attempt)
        time.sleep(wait_s)
    return None


def fetch_full_extract(title: str) -> Optional[str]:
    """Full plaintext article body for a linked title, for the hint pipeline
    (footy_quiz.hints.store) to chunk. redirects=1 so a renamed article still returns its
    real body instead of an empty redirect stub."""
    data = _http_get_json(
        ACTION_API_URL,
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "redirects": 1,
            "titles": title,
            "format": "json",
        },
    )
    if not data:
        return None
    for page in data.get("query", {}).get("pages", {}).values():
        extract = page.get("extract")
        if extract:
            return extract
    return None


def _months_before(dt: datetime, n: int) -> datetime:
    month = dt.month - n
    year = dt.year
    while month <= 0:
        month += 12
        year -= 1
    return dt.replace(year=year, month=month, day=1)


def fetch_pageviews(title: str, months: int = POPULARITY_WINDOW_MONTHS) -> Optional[int]:
    """Total en.wikipedia pageviews over the trailing `months` months -- a real-world fame
    proxy, used to stop well-logged-but-obscure players from being banded "easy"/"normal".
    Titles come from Wikidata sitelinks, which are canonical (the pageviews API has no
    redirect handling, so an alias would silently undercount). None if there's no data."""
    now = datetime.now(timezone.utc)
    start = _months_before(now, months - 1).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    article = urllib.parse.quote(title.replace(" ", "_"), safe="")
    data = _http_get_json(PAGEVIEWS_URL.format(article=article, start=start, end=end))
    if not data or not data.get("items"):
        return None
    return sum(item["views"] for item in data["items"])


def get_or_fetch_player_photo(con: duckdb.DuckDBPyConnection, player_id: int) -> Optional[str]:
    """The player's linked Wikidata photo, or None. No network call: it's already stored by
    scripts/build_wiki_links.py, and a player missing from player_wiki has no known article."""
    row = con.execute(
        "SELECT photo_url FROM player_wiki WHERE player_id = ?", [player_id]
    ).fetchone()
    return row[0] if row else None


def get_or_fetch_player_popularity(
    con: duckdb.DuckDBPyConnection, player_id: int, sleep_s: float = 0.2
) -> int:
    """Cached trailing-12-month pageview count for this player's linked article (0 if they
    have none). Computed once and cached; only ever called by scripts/build_popularity.py's
    batch pass, never per-request."""
    row = con.execute(
        "SELECT wiki_title, popularity_views FROM player_wiki WHERE player_id = ?", [player_id]
    ).fetchone()
    if row is None:
        return 0
    title, cached = row
    if cached is not None:
        return cached

    views = 0
    if title:
        views = fetch_pageviews(title) or 0
        time.sleep(sleep_s)
    con.execute(
        "UPDATE player_wiki SET popularity_views = ? WHERE player_id = ?", [views, player_id]
    )
    return views
