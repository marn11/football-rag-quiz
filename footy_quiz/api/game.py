"""In-memory game session storage, keyed by game_id.

No persistence across restarts -- a process restart loses in-progress games. Fine for a
single-process prototype; a real multi-worker deployment would move this to something
shared (Redis, a DB table), not module-level process memory.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from footy_quiz.hints.session import HintSessionState


@dataclass
class GameState:
    game_id: str
    target_player_id: int
    difficulty: str
    hint_state: HintSessionState
    solved: bool = False


GAMES: dict[str, GameState] = {}


def new_game_id() -> str:
    return uuid.uuid4().hex
