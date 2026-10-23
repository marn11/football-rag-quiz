#!/usr/bin/env python3
"""Links every player to their exact English Wikipedia article via Wikidata's Transfermarkt
id (see footy_quiz/wikidata.py), and rewrites the player_wiki cache from it.

1. Fetch: one batched Wikidata query per 400 players, cached to data/wikidata_links.json
   (rerunning skips the network entirely -- delete the file to refetch). Reads player ids
   from the vendored source, so this step works even while the API server holds the DB.
2. Apply (needs the DB -- stop the API server first): replaces player_wiki. Pageview counts
   are kept only where the article is unchanged; anyone whose article changed gets NULL
   so scripts/build_popularity.py recomputes it, and anyone with no article gets 0. Hint
   corpora (wiki_pages/wiki_chunks) built from a different article are deleted -- they
   were trivia about the wrong person -- and rebuild lazily on the next hint request.

Usage: uv run scripts/build_wiki_links.py   (then: uv run scripts/build_popularity.py)
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from footy_quiz import wikidata
from footy_quiz.ingest import DEFAULT_DB_PATH, DEFAULT_VENDOR_PATH

CACHE_PATH = DEFAULT_DB_PATH.parent / "wikidata_links.json"


def _fetch() -> dict[int, tuple]:
    if CACHE_PATH.exists():
        raw = json.loads(CACHE_PATH.read_text())
        print(f"Using cached Wikidata links from {CACHE_PATH} ({len(raw)} players)")
        return {int(k): tuple(v) for k, v in raw.items()}

    src = duckdb.connect(str(DEFAULT_VENDOR_PATH), read_only=True)
    ids = [pid for (pid,) in src.execute("SELECT player_id FROM players ORDER BY 1").fetchall()]
    src.close()
    print(f"Querying Wikidata for {len(ids)} transfermarkt ids ...")
    links = wikidata.fetch_links(ids)
    CACHE_PATH.write_text(json.dumps({str(k): v for k, v in links.items()}))
    return links


def _apply(links: dict[int, tuple]) -> None:
    con = duckdb.connect(str(DEFAULT_DB_PATH))
    try:
        old = {
            pid: (title, views)
            for pid, title, views in con.execute(
                "SELECT player_id, wiki_title, popularity_views FROM player_wiki"
            ).fetchall()
        }
        player_ids = [pid for (pid,) in con.execute("SELECT player_id FROM players").fetchall()]
        now = datetime.now(timezone.utc).isoformat()

        rows, kept, recompute, changed = [], 0, 0, 0
        for pid in player_ids:
            title, image = links.get(pid, (None, None))
            old_title, old_views = old.get(pid, (None, None))
            if title is None:
                views = 0
            elif title == old_title and old_views is not None:
                views, kept = old_views, kept + 1
            else:
                views, recompute = None, recompute + 1
            changed += pid in old and old_title != title
            rows.append(
                {
                    "player_id": pid,
                    "wiki_title": title,
                    "resolution_method": "wikidata" if title else "unresolved",
                    "photo_url": image,
                    "fetched_at": now,
                    "popularity_views": views,
                }
            )

        tmp = CACHE_PATH.with_suffix(".rows.json")
        tmp.write_text(json.dumps(rows))
        con.execute("BEGIN")
        # Hint corpora whose source article is no longer this player's article.
        con.execute(
            f"""
            CREATE TEMP TABLE _new AS
            SELECT player_id, wiki_title FROM read_json_auto('{tmp.as_posix()}')
            """
        )
        stale = con.execute(
            """
            SELECT COUNT(*) FROM wiki_pages wp LEFT JOIN _new n USING (player_id)
            WHERE n.wiki_title IS NULL OR n.wiki_title != wp.wiki_title
            """
        ).fetchone()[0]
        for table in ("wiki_chunks", "wiki_pages"):
            con.execute(
                f"""
                DELETE FROM {table} WHERE player_id IN (
                    SELECT wp.player_id FROM wiki_pages wp LEFT JOIN _new n USING (player_id)
                    WHERE n.wiki_title IS NULL OR n.wiki_title != wp.wiki_title
                )
                """
            )
        con.execute("DELETE FROM player_wiki")
        con.execute(
            f"""
            INSERT INTO player_wiki
                (player_id, wiki_title, resolution_method, photo_url, fetched_at, popularity_views)
            SELECT player_id, wiki_title, resolution_method, photo_url,
                   CAST(fetched_at AS TIMESTAMP), popularity_views
            FROM read_json_auto('{tmp.as_posix()}')
            """
        )
        con.execute("COMMIT")
        tmp.unlink()

        linked = sum(1 for r in rows if r["wiki_title"])
        print(
            f"{len(rows)} players: {linked} linked to an article, {len(rows) - linked} with none.\n"
            f"Article changed for {changed} previously-cached players; "
            f"{kept} pageview counts kept, {recompute} to recompute "
            f"(run scripts/build_popularity.py). {stale} wrong-article hint corpora deleted."
        )
    finally:
        con.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    links = _fetch()
    try:
        _apply(links)
    except duckdb.IOException as e:
        raise SystemExit(
            f"Fetched and cached the links, but couldn't open the DB to apply them ({e}).\n"
            "Stop the API server and rerun -- the fetch step is cached and won't repeat."
        )


if __name__ == "__main__":
    main()
