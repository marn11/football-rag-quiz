"""Public contract: the riddle engine's full surface, importable directly from footy_quiz.

The API layer (checkpoint 13) and nothing else should call these; internals
(footy_quiz.graph, footy_quiz.media's HTTP plumbing, footy_quiz.ingest, ...) are
implementation details reached only through here. footy_quiz.hints (the RAG pipeline)
is a separate, parallel public surface -- it's imported directly, not re-exported here,
since its functions take a live duckdb connection rather than managing their own.
"""

from footy_quiz.answers import AnswerResult, autocomplete_candidates, check_answer
from footy_quiz.riddle import Clue, Riddle, get_riddle
from footy_quiz.selection import PlayerCandidate, list_candidate_target_players

__all__ = [
    "AnswerResult",
    "check_answer",
    "autocomplete_candidates",
    "Clue",
    "Riddle",
    "get_riddle",
    "PlayerCandidate",
    "list_candidate_target_players",
]
