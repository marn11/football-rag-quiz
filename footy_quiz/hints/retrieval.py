"""Spoiler-safety and difficulty tagging for hint chunks.

`contains_name` is a HARD exclusion: a chunk that names the target player is never
eligible as a hint, at any difficulty -- it would just spoil the answer outright. This
is enforced structurally (checked at ingestion, filtered at retrieval time), not left to
the LLM to "not mention" later.

`specificity` is a SOFT gate (1 = vague, 3 = revealing) used to stage how pointed a hint
is allowed to be as more hints get requested in a session (checkpoint 11) -- e.g. "he is
known for his composure in front of goal" (1) vs. "he scored a hat-trick against Real
Madrid in the 2019 Champions League semi-final" (3, loaded with identifying specifics).
Both are simple additive heuristics computed once per chunk at ingestion time
(footy_quiz.hints.store), not re-derived at serve time, and are deliberately eyeballed/
tuned against real chunks rather than trained classifiers -- there's no need for an ML
model to answer "does this sentence have a year and two proper nouns in it".
"""

from __future__ import annotations

import re
from typing import Optional

_NAME_TOKEN_MIN_LEN = 3  # skip short tokens/particles ("de", "da") -- too many false hits

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_QUOTE_RE = re.compile(r"[\"'‘’“”]")
# Rough proper-noun detector: a capitalized word not at the very start of the chunk or
# right after a sentence-ending ". " -- i.e. not just capitalized because it starts a
# sentence. Not perfect, but good enough for an additive heuristic meant to be eyeballed.
_MID_SENTENCE_CAPITALIZED_RE = re.compile(r"(?<!^)(?<!\.\s)(?<!\?\s)(?<!\!\s)\b[A-Z][a-z]+\b")


_QUOTED_AKA_RE = re.compile(r"[\"“]([A-Z][a-zA-Z]+)[\"”]")


def extract_aka_nickname(opening_text: str) -> Optional[str]:
    """Wikipedia bios conventionally introduce an informal nickname in quotes right in
    the opening sentence, e.g. 'Lionel Andrés "Leo" Messi (born ...)'. Neither StatsBomb's
    player_name nor player_nickname field would ever contain "Leo" -- it's a prose-only
    nickname -- so without this, a chunk using it wouldn't be flagged as a spoiler."""
    match = _QUOTED_AKA_RE.search(opening_text)
    return match.group(1) if match else None


def _name_tokens(player_name: str, player_nickname: Optional[str], aka: Optional[str] = None) -> set[str]:
    tokens: set[str] = set()
    for name in (player_name, player_nickname, aka):
        if not name:
            continue
        for token in _WORD_RE.findall(name):
            if len(token) >= _NAME_TOKEN_MIN_LEN:
                tokens.add(token.lower())
    return tokens


def contains_name(
    chunk_text: str, player_name: str, player_nickname: Optional[str], aka: Optional[str] = None
) -> bool:
    tokens = _name_tokens(player_name, player_nickname, aka)
    if not tokens:
        return False
    lowered = chunk_text.lower()
    return any(re.search(rf"\b{re.escape(tok)}\b", lowered) for tok in tokens)


def specificity(chunk_text: str) -> int:
    """1 (vague) to 3 (specific/revealing)."""
    score = 0
    if _YEAR_RE.search(chunk_text):
        score += 1
    if len(_MID_SENTENCE_CAPITALIZED_RE.findall(chunk_text)) >= 2:
        score += 1
    if _QUOTE_RE.search(chunk_text):
        score += 1
    return 1 if score == 0 else (2 if score == 1 else 3)
