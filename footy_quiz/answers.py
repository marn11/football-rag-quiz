"""Answer validation + autocomplete for "guess the player" mode.

Fans overwhelmingly guess by surname alone ("Messi", "Ramos"), not a player's full legal
name ("Lionel Andrés Messi Cuccittini") -- so matching is tiered: exact full name/nickname,
then exact match against just the nickname's surname (handling compound surnames like
"Di María" via a small particle list), then small-edit-distance typo tolerance on top of
that surname. Deliberately NOT token-subset fuzzy matching (e.g. rapidfuzz's
token_set_ratio): it would also accept a guess of just "Angel" (Di María's common first
name, shared by many players) as a perfect match, which is too lenient for a guessing game.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Optional

from rapidfuzz.distance import Levenshtein

from footy_quiz.db import connect

# Compound-surname particles (Spanish/Portuguese/Dutch/Arabic etc.) -- if the nickname's
# second-to-last token is one of these, the surname unit is the last TWO tokens, not one
# (so "Di María", not just "María").
SURNAME_PARTICLES = {
    "di", "de", "da", "do", "dos", "das", "van", "von", "der", "den", "el", "al", "bin", "ibn",
}

MAX_TYPO_EDIT_DISTANCE = 2
MIN_GUESS_LEN_FOR_TYPO_TOLERANCE = 3

# Below this, autocomplete doesn't query at all -- checked against our own data: every
# 1-character name/nickname token turned out to be a data artifact (a Catalan compound-
# surname conjunction like "Puyol i Saforcada", or an abbreviated initial like "W.
# Sneijder"), never a genuine short name. Real short names (e.g. "Wu Lei" -> "wu", "lei")
# are both >=2 chars, so this costs nothing real. Doesn't affect check_answer at all --
# a full guess can still be submitted and judged correct regardless of this minimum.
MIN_AUTOCOMPLETE_PREFIX_LEN = 2


@dataclass
class AnswerResult:
    correct: bool
    matched_name: Optional[str]  # which stored name (full name or nickname) matched
    confidence: Optional[Literal["exact", "exact_nospace", "exact_surname", "fuzzy"]]
    edit_distance: int  # 0 for exact tiers; the smallest distance found otherwise


def normalize(s: str) -> str:
    """NFKD-strip accents, lowercase, strip punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _surname_unit_from_tokens(tokens: list[str]) -> str:
    if len(tokens) >= 2 and tokens[-2] in SURNAME_PARTICLES:
        return " ".join(tokens[-2:])
    return tokens[-1]


def _surname_candidates(player_name: str, player_nickname: Optional[str]) -> set[str]:
    """Surname-only identifying token(s), derived from WHICHEVER name fields are
    available -- not just the nickname, since not every player has one stored (e.g.
    "Giuseppe Rossi" has no separate nickname, so without this his surname-only guess
    "Rossi" would be silently rejected). Mononym names (1 token) are skipped -- they
    already match via the exact full-form check, nickname == surname there anyway."""
    surnames: set[str] = set()
    for name in (player_nickname, player_name):
        if not name:
            continue
        tokens = normalize(name).split()
        if len(tokens) >= 2:
            surnames.add(_surname_unit_from_tokens(tokens))
    return surnames


def check_answer(target_player_id: int, guess: str) -> AnswerResult:
    con = connect()
    try:
        row = con.execute(
            "SELECT player_name, player_nickname FROM players WHERE player_id = ?",
            [target_player_id],
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise ValueError(f"unknown player_id {target_player_id}")

    player_name, player_nickname = row
    normalized_guess = normalize(guess)
    guess_nospace = normalized_guess.replace(" ", "")

    # (display_name, normalized_form) pairs to check, strictest/most-specific first.
    full_forms = [(n, normalize(n)) for n in (player_nickname, player_name) if n]

    for display, normalized in full_forms:
        if normalized == normalized_guess:
            return AnswerResult(True, display, "exact", 0)
    for display, normalized in full_forms:
        if normalized.replace(" ", "") == guess_nospace:
            return AnswerResult(True, display, "exact_nospace", 0)

    surnames = _surname_candidates(player_name, player_nickname)
    for surname in surnames:
        if surname == normalized_guess or surname.replace(" ", "") == guess_nospace:
            return AnswerResult(True, player_nickname or player_name, "exact_surname", 0)

    if len(normalized_guess) < MIN_GUESS_LEN_FOR_TYPO_TOLERANCE:
        return AnswerResult(False, None, None, min(len(normalized_guess), 99))

    compare_targets = [normalized for _, normalized in full_forms] + list(surnames)

    best_distance = min(Levenshtein.distance(t, normalized_guess) for t in compare_targets)
    if best_distance <= MAX_TYPO_EDIT_DISTANCE:
        matched_display = player_nickname or player_name
        return AnswerResult(True, matched_display, "fuzzy", best_distance)

    return AnswerResult(False, None, None, best_distance)


def autocomplete_candidates(prefix: str, limit: int = 10) -> list[dict]:
    """Players whose name or nickname contains `prefix` starting at a word boundary, so
    "ram" -> "Sergio Ramos" (second word) and multi-word input keeps matching as you type
    a full name ("lionel m" -> "Lionel Messi", "di mar" -> "Ángel Di María"). Names are
    normalized in SQL exactly like the prefix is (accents stripped, punctuation -> space),
    so "ngolo"/"n golo" and "marc andre" still find "N'Golo Kanté" / "Marc-André ter
    Stegen". Ranked by how many matches they have in the dataset (a cheap popularity
    proxy)."""
    normalized_prefix = normalize(prefix)
    if len(normalized_prefix) < MIN_AUTOCOMPLETE_PREFIX_LEN:
        return []

    con = connect()
    try:
        rows = con.execute(
            """
            WITH match_counts AS (
                SELECT player_id, COUNT(*) AS n_matches FROM appearances GROUP BY player_id
            ),
            names AS (
                SELECT player_id, player_name, player_nickname,
                       ' ' || regexp_replace(regexp_replace(lower(strip_accents(player_name)),
                           '[^a-z0-9 ]', ' ', 'g'), ' +', ' ', 'g') AS norm_name,
                       ' ' || regexp_replace(regexp_replace(lower(strip_accents(COALESCE(player_nickname, ''))),
                           '[^a-z0-9 ]', ' ', 'g'), ' +', ' ', 'g') AS norm_nick,
                       ' ' || replace(regexp_replace(lower(strip_accents(player_name)),
                           '[^a-z0-9 ]', '', 'g'), ' ', '') AS squashed_name
                FROM players
            )
            SELECT p.player_id, p.player_name, p.player_nickname,
                   COALESCE(mc.n_matches, 0) AS n_matches
            FROM names p
            LEFT JOIN match_counts mc ON mc.player_id = p.player_id
            WHERE p.norm_name LIKE '% ' || ? || '%'
               OR p.norm_nick LIKE '% ' || ? || '%'
               -- one-word input only ("ngolo" -> "N'Golo"); with a space it would also
               -- glue words together ("cristiano r" -> "Cristian Oros")
               OR (position(' ' IN ?) = 0 AND p.squashed_name LIKE ' ' || ? || '%')
            ORDER BY n_matches DESC
            LIMIT ?
            """,
            [normalized_prefix, normalized_prefix, normalized_prefix, normalized_prefix, limit],
        ).fetchall()
        ids = [r[0] for r in rows]
        main_clubs = _main_clubs(con, ids)
        photos = _stored_photos(con, ids)
    finally:
        con.close()

    return [
        {
            "player_id": pid,
            "player_name": name,
            "player_nickname": nickname,
            "n_matches": n,
            "main_club": main_clubs.get(pid),
            "photo_url": photos.get(pid),
        }
        for pid, name, nickname, n in rows
    ]


def _stored_photos(con, player_ids: list[int]) -> dict[int, str]:
    """Already-stored photos only (the transfermarkt photo, else a Wikipedia one cached
    from an earlier lookup) -- never a live Wikipedia resolution, which would make every
    keystroke wait on the network."""
    if not player_ids:
        return {}
    placeholders = ",".join("?" for _ in player_ids)
    rows = con.execute(
        f"""
        SELECT p.player_id, COALESCE(p.photo_url, pw.photo_url)
        FROM players p LEFT JOIN player_wiki pw ON pw.player_id = p.player_id
        WHERE p.player_id IN ({placeholders})
        """,
        player_ids,
    ).fetchall()
    return {pid: url for pid, url in rows if url}


def _main_clubs(con, player_ids: list[int]) -> dict[int, str]:
    """The club each player appeared for most -- shown next to autocomplete suggestions
    so same-named players (several "Messias", "Marcelo", ...) can be told apart."""
    if not player_ids:
        return {}
    placeholders = ",".join("?" for _ in player_ids)
    rows = con.execute(
        f"""
        SELECT player_id, arg_max(team_name, n) FROM (
            SELECT a.player_id, t.team_name, COUNT(*) AS n
            FROM appearances a
            JOIN teams t ON t.team_id = a.team_id
            JOIN matches m ON m.match_id = a.match_id
            JOIN competitions c ON c.competition_id = m.competition_id AND c.season_id = m.season_id
            WHERE a.player_id IN ({placeholders}) AND NOT c.competition_international
            GROUP BY a.player_id, t.team_name
        ) GROUP BY player_id
        """,
        player_ids,
    ).fetchall()
    return dict(rows)
