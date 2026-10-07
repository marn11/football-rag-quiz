"""LLM hint phrasing: turns 1-3 retrieved Wikipedia chunks into one natural-sounding
trivia hint via Claude Haiku 4.5 -- a short rephrasing task with no reasoning required,
so no extended thinking is used.

Falls back to the raw (redacted) chunk text if the API call fails or refuses, and to a
fixed message if the session has no eligible chunk left at all (footy_quiz.hints.session
already handles the "no chunk" case by returning None; NO_HINTS_LEFT_MESSAGE is what the
caller should show in that case).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import anthropic
from dotenv import load_dotenv

from footy_quiz.hints.retrieval import _name_tokens

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 200
NO_HINTS_LEFT_MESSAGE = "I'm out of trivia for this one -- time to take a guess!"

SYSTEM_PROMPT = """You are a trivia host for a "guess the footballer" quiz game.
You will be given 1-3 factual sentences about a mystery player, sourced from Wikipedia,
plus the player's real name (for your reference only).

Rewrite the given facts into ONE short, natural-sounding trivia hint (1-2 sentences,
under 40 words).

Rules, no exceptions:
1. NEVER write the player's name, nickname, or initials anywhere in your output.
2. NEVER mention their nationality, current/former club names, or primary playing
   position -- those are covered by other parts of the game.
3. Do not invent or add facts beyond what's given.
4. If a given fact can't be phrased without naming the player or a banned detail, drop
   it and use the remaining fact(s) instead.

Output ONLY the hint text -- no preamble, no quotes around it."""

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _redact(text: str, player_name: str, player_nickname: Optional[str]) -> str:
    """Belt-and-suspenders fallback redaction. Chunks reaching this point should
    already be contains_name=False (footy_quiz.hints.retrieval's hard exclusion); this
    only guards the fallback path itself against something slipping through."""
    for token in _name_tokens(player_name, player_nickname):
        text = re.sub(rf"\b{re.escape(token)}\b", "they", text, flags=re.IGNORECASE)
    return text


def phrase_hint(
    chunks: list[str],
    player_name: str,
    player_nickname: Optional[str],
    hint_number: int,
) -> str:
    """Turns 1-3 raw retrieved chunks into one natural hint. Never raises -- falls back
    to redacted raw text on any API failure or refusal."""
    if not chunks:
        return NO_HINTS_LEFT_MESSAGE

    fallback = f"Fun fact: {_redact(chunks[0], player_name, player_nickname)}"

    user_message = (
        f"Mystery player's real name (do not reveal): {player_name}\n"
        f"Hint number: {hint_number} (higher = ok to be a bit more specific)\n"
        "Source facts:\n" + "\n".join(f"- {c}" for c in chunks)
    )

    try:
        response = _get_client().messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=0.7,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.APIStatusError) as e:
        logger.warning("LLM hint phrasing call failed (%s), falling back to raw chunk", e)
        return fallback

    if response.stop_reason == "refusal":
        logger.warning("LLM hint phrasing refused, falling back to raw chunk")
        return fallback

    text = next((b.text for b in response.content if b.type == "text"), None)
    return text.strip() if text else fallback
