"""In-memory per-game hint session state.

Tracks which chunks have already been served (so a session never repeats a hint) and how
revealing a hint is allowed to be as more get requested (the specificity ceiling rises
every 2 hints -- see footy_quiz.hints.retrieval for what specificity 1-3 means). Lives in
the API process's memory for now, not persisted -- a restart loses in-progress sessions,
a known prototype-stage limitation, not a bug to fix here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import duckdb

from footy_quiz.hints import store

# A fixed set of angles steers retrieval toward a *topic*, not a specific pre-written
# fact -- the content itself still comes from genuine similarity search against the
# player's real Wikipedia chunks each time. This just spreads repeated hints across
# different parts of their life/career instead of clustering on whatever one topic
# happens to dominate their article.
HINT_ANGLES = [
    "an interesting fact about this player's youth or early career",
    "a notable achievement, award, or record held by this player",
    "something about this player's personality, style of play, or reputation",
    "a memorable match moment or transfer in this player's career",
    "a fact about this player's life off the pitch",
]


@dataclass
class HintSessionState:
    player_id: int
    served_chunk_indices: set[int] = field(default_factory=set)
    hints_given: int = 0

    def specificity_ceiling(self) -> int:
        """1-3, rising every 2 hints: hints 1-2 stay vague, 3-4 allow medium
        specificity, 5+ allow anything eligible (still never contains_name)."""
        return min(3, (self.hints_given // 2) + 1)

    def next_angle(self) -> str:
        return HINT_ANGLES[self.hints_given % len(HINT_ANGLES)]


def get_next_hint(
    con: duckdb.DuckDBPyConnection, state: HintSessionState
) -> Optional[tuple[int, str]]:
    """(chunk_index, text) for the next hint, or None if no eligible chunk remains (all
    servable chunks already served, or nothing passes the current specificity ceiling)."""
    results = store.retrieve(
        con,
        state.player_id,
        state.next_angle(),
        k=1,
        max_specificity=state.specificity_ceiling(),
        exclude_chunk_indices=state.served_chunk_indices,
    )
    if not results:
        return None

    chunk_index, text, _distance = results[0]
    state.served_chunk_indices.add(chunk_index)
    state.hints_given += 1
    return chunk_index, text
