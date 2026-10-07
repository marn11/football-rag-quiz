"""Request/response bodies for the FastAPI service.

ClueOut deliberately excludes team_id/teammate_player_id/competition_id/season_id --
internal numeric ids the frontend doesn't need -- and obviously excludes anything about
the TARGET player (name, id): a clue reveals the teammate, never the mystery player.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ClueOut(BaseModel):
    team_name: str
    team_crest_url: Optional[str]
    teammate_display_name: str
    teammate_photo_url: Optional[str]
    competition_name: str
    season_name: str
    season_start_year: int
    text: str


class StartGameResponse(BaseModel):
    game_id: str
    difficulty: str
    clues: list[ClueOut]


class HintResponse(BaseModel):
    hint_number: int
    hint_text: str


class GuessRequest(BaseModel):
    guess: str


class GuessResponse(BaseModel):
    correct: bool
    message: str


class RevealResponse(BaseModel):
    player_name: str


class AutocompleteResult(BaseModel):
    player_id: int
    player_name: str
    player_nickname: Optional[str]
