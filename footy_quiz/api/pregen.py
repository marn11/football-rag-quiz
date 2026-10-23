"""Speculative riddle pre-generation.

Building a riddle's clues can be slow the first time a brand-new club/teammate needs its
crest/photo resolved from Wikipedia (network round-trip per entity). Rather than pay
that cost synchronously on every "New Game" click, we keep one ready-to-serve Riddle per
difficulty in a small in-memory pool: the moment one is served, a background thread
immediately starts generating the next one for that same difficulty -- which then has
the player's entire next game session (tens of seconds to minutes) to finish, long
before they click "New Game" again. First-ever request for a difficulty (or a refill
that hasn't finished yet) falls back to generating synchronously, same as before.
"""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from typing import Optional

import footy_quiz
from footy_quiz.riddle import Riddle

logger = logging.getLogger(__name__)

_DIFFICULTIES = ("easy", "normal", "hard", "extreme")

# Candidates per difficulty to draw from, and how many recently-generated targets to avoid
# repeating. The old top-200 pool plus pure random.choice made repeats (e.g. the same
# player twice in a few games) very likely -- birthday-paradox odds at that pool size.
CANDIDATE_POOL_SIZE = 1000
RECENT_MEMORY = 150

_recent: dict[str, deque] = {}
_pool: dict[str, Riddle] = {}
_locks: dict[str, threading.Lock] = {d: threading.Lock() for d in _DIFFICULTIES}


def _generate(difficulty: str) -> Optional[Riddle]:
    candidates = footy_quiz.list_candidate_target_players(
        difficulty=difficulty, limit=CANDIDATE_POOL_SIZE
    )
    if not candidates:
        return None
    recent = _recent.setdefault(difficulty, deque(maxlen=RECENT_MEMORY))
    fresh = [c for c in candidates if c not in recent]
    target_player_id = random.choice(fresh or candidates)
    recent.append(target_player_id)
    return footy_quiz.get_riddle(target_player_id, difficulty=difficulty)


def _refill(difficulty: str) -> None:
    lock = _locks[difficulty]
    if not lock.acquire(blocking=False):
        return  # a refill for this difficulty is already running
    try:
        riddle = _generate(difficulty)
        if riddle is not None:
            _pool[difficulty] = riddle
    except Exception:
        logger.exception("Failed to pre-generate a riddle for difficulty=%s", difficulty)
    finally:
        lock.release()


def get_riddle_for(difficulty: str) -> Optional[Riddle]:
    """Pops the pre-generated riddle for this difficulty if one's ready; otherwise
    generates one synchronously (cold-start / pool-not-filled-yet fallback). Either way,
    kicks off a background refill so the *next* call has a head start."""
    riddle = _pool.pop(difficulty, None)
    if riddle is None:
        riddle = _generate(difficulty)
    if difficulty in _locks:  # an unrecognized difficulty string has nothing to refill
        threading.Thread(target=_refill, args=(difficulty,), daemon=True).start()
    return riddle


def warm_all() -> None:
    """Called once at server startup: fills the pool for every difficulty in the
    background (non-blocking) so even the very first "New Game" click doesn't pay the
    cold-start cost."""
    for difficulty in _DIFFICULTIES:
        threading.Thread(target=_refill, args=(difficulty,), daemon=True).start()
