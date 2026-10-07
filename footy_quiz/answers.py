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


def _surname_unit(normalized_nickname: str) -> str:
    tokens = normalized_nickname.split()
    if len(tokens) >= 2 and tokens[-2] in SURNAME_PARTICLES:
        return " ".join(tokens[-2:])
    return tokens[-1]


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

    surname = _surname_unit(normalize(player_nickname)) if player_nickname else None
    if surname:
        if surname == normalized_guess or surname.replace(" ", "") == guess_nospace:
            return AnswerResult(True, player_nickname, "exact_surname", 0)

    if len(normalized_guess) < MIN_GUESS_LEN_FOR_TYPO_TOLERANCE:
        return AnswerResult(False, None, None, min(len(normalized_guess), 99))

    compare_targets = [normalized for _, normalized in full_forms]
    if surname:
        compare_targets.append(surname)

    best_distance = min(Levenshtein.distance(t, normalized_guess) for t in compare_targets)
    if best_distance <= MAX_TYPO_EDIT_DISTANCE:
        matched_display = player_nickname or player_name
        return AnswerResult(True, matched_display, "fuzzy", best_distance)

    return AnswerResult(False, None, None, best_distance)


def autocomplete_candidates(prefix: str, limit: int = 10) -> list[dict]:
    """Players whose name or nickname has a word starting with `prefix` (e.g. "ram" ->
    "Sergio Ramos", matching the second word, not just the start of the full string),
    ranked by how many matches they have in the dataset (a cheap popularity proxy)."""
    normalized_prefix = normalize(prefix)
    if len(normalized_prefix) < MIN_AUTOCOMPLETE_PREFIX_LEN:
        return []

    con = connect()
    try:
        rows = con.execute(
            """
            WITH match_counts AS (
                SELECT player_id, COUNT(*) AS n_matches FROM appearances GROUP BY player_id
            )
            SELECT p.player_id, p.player_name, p.player_nickname,
                   COALESCE(mc.n_matches, 0) AS n_matches
            FROM players p
            LEFT JOIN match_counts mc ON mc.player_id = p.player_id
            WHERE EXISTS (
                SELECT 1 FROM UNNEST(string_split(p.normalized_name, ' ')) AS t(tok)
                WHERE tok LIKE ? || '%'
            ) OR (
                p.player_nickname IS NOT NULL AND EXISTS (
                    SELECT 1
                    FROM UNNEST(string_split(lower(strip_accents(p.player_nickname)), ' ')) AS t(tok)
                    WHERE tok LIKE ? || '%'
                )
            )
            ORDER BY n_matches DESC
            LIMIT ?
            """,
            [normalized_prefix, normalized_prefix, limit],
        ).fetchall()
    finally:
        con.close()

    return [
        {"player_id": pid, "player_name": name, "player_nickname": nickname, "n_matches": n}
        for pid, name, nickname, n in rows
    ]
