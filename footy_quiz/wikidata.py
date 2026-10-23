"""Exact player -> Wikipedia article mapping via Wikidata's Transfermarkt player ID (P2446).

Our player_ids ARE transfermarkt ids, and Wikidata records that id on each footballer's
item, so this is an identity lookup, not a name match. Name-based resolution got common
names badly wrong: six different players called "Fabinho" all competed for the same
article, and an obscure one ended up with the Liverpool Fabinho's pageviews and trivia.
A player Wikidata hasn't linked to an English article simply gets no article.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "footy-quiz/0.1 (https://github.com/marn11/rag-footy-quiz)"
BATCH_SIZE = 400
_MAX_ATTEMPTS = 5

_QUERY = """
SELECT ?tm ?article ?image WHERE {{
  VALUES ?tm {{ {values} }}
  ?item wdt:P2446 ?tm .
  OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }}
  OPTIONAL {{ ?item wdt:P18 ?image }}
}}
"""


def _post(query: str) -> dict:
    body = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(
        SPARQL_URL,
        data=body,
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
    )
    for attempt in range(_MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == _MAX_ATTEMPTS - 1:
                raise
            wait_s = float(e.headers.get("Retry-After") or 2 ** (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            wait_s = 2 ** (attempt + 1)
        logger.info("Wikidata request failed, retrying in %.0fs", wait_s)
        time.sleep(wait_s)
    raise RuntimeError("unreachable")


def _title_from_article_url(url: str) -> str:
    return urllib.parse.unquote(url.rsplit("/wiki/", 1)[1]).replace("_", " ")


def _thumbnail_from_commons_url(url: str) -> str:
    # P18 values are Special:FilePath URLs, which redirect to the file -- ?width= makes
    # Commons serve a resized thumbnail instead of the full original upload.
    return url.replace("http://", "https://", 1) + "?width=330"


def fetch_links(player_ids: Iterable[int]) -> dict[int, tuple[Optional[str], Optional[str]]]:
    """player_id -> (enwiki article title or None, Wikidata photo URL or None), for every
    id Wikidata knows. Ids absent from the result have no Wikidata item at all."""
    ids = list(player_ids)
    links: dict[int, tuple[Optional[str], Optional[str]]] = {}
    for start in range(0, len(ids), BATCH_SIZE):
        batch = ids[start : start + BATCH_SIZE]
        values = " ".join(f'"{pid}"' for pid in batch)
        data = _post(_QUERY.format(values=values))
        for b in data["results"]["bindings"]:
            pid = int(b["tm"]["value"])
            title = _title_from_article_url(b["article"]["value"]) if "article" in b else None
            image = _thumbnail_from_commons_url(b["image"]["value"]) if "image" in b else None
            prev_title, prev_image = links.get(pid, (None, None))
            links[pid] = (prev_title or title, prev_image or image)
        logger.info("Wikidata: %d/%d ids queried", min(start + BATCH_SIZE, len(ids)), len(ids))
        time.sleep(1)  # politeness between batches -- WDQS is a shared public service
    return links
