"""FastAPI service for "guess the player" mode.

A thin HTTP layer over the footy_quiz riddle engine (deterministic clues/answers) and
footy_quiz.hints (live RAG hint pipeline) -- no game logic lives here beyond picking a
random target and wiring requests through to those modules. Game state (target player
id, hint session) lives in footy_quiz.api.game.GAMES, an in-memory dict -- see that
module's docstring for the persistence caveat.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

import footy_quiz
from footy_quiz import media, riddle
from footy_quiz.api import pregen, schemas
from footy_quiz.api.game import GAMES, GameState, new_game_id
from footy_quiz.db import connect
from footy_quiz.hints import llm_hint, store
from footy_quiz.hints.session import HintSessionState, get_next_hint

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the embedding model on the main thread at startup, not lazily inside a
    # request's threadpool worker -- loading torch/tokenizers for the first time off
    # the main thread crashed the server outright (no Python traceback, just an exit)
    # the first time a hint request triggered it mid-request.
    store._get_model()
    pregen.warm_all()
    yield


app = FastAPI(title="Footy Quiz -- Guess the Player", lifespan=lifespan)


def _clue_to_schema(c: riddle.Clue) -> schemas.ClueOut:
    return schemas.ClueOut(
        team_name=c.team_name,
        team_crest_url=c.team_crest_url,
        teammate_display_name=c.teammate_display_name,
        teammate_photo_url=c.teammate_photo_url,
        competition_name=c.competition_name,
        season_name=c.season_name,
        season_start_year=c.season_start_year,
        text=c.text,
    )


def _get_game_or_404(game_id: str) -> GameState:
    game = GAMES.get(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    return game


def _prewarm_hint_corpus(player_id: int) -> None:
    """Runs after the response is sent (see BackgroundTasks below) -- fetching +
    chunking + embedding a player's Wikipedia page is the single slowest part of
    starting a game, and nothing about seeing the riddle actually needs it done yet;
    it only needs to be ready by the time "Get Hint" is clicked, a few seconds later
    at minimum. Needs its own connection: the request's cursor is already closed by
    the time this runs."""
    con = connect(read_only=False)
    try:
        store.ensure_player_chunks(con, player_id)
    except Exception:
        logger.exception("Failed to pre-warm hint corpus for player %s", player_id)
    finally:
        con.close()


@app.post("/api/games", response_model=schemas.StartGameResponse)
def start_game(background_tasks: BackgroundTasks, difficulty: str = "normal") -> schemas.StartGameResponse:
    # Usually instant: pops an already-generated riddle for this difficulty out of
    # footy_quiz.api.pregen's pool (built in the background while the *previous* game
    # was being played), which also kicks off generating the next one right away. Only
    # pays the full synchronous cost (candidate selection + crest/photo resolution) on a
    # genuine cold start, e.g. right after server startup before warm_all() finishes.
    generated_riddle = pregen.get_riddle_for(difficulty)
    if generated_riddle is None:
        raise HTTPException(status_code=400, detail=f"no candidates for difficulty={difficulty!r}")
    target_player_id = generated_riddle.target_player_id

    game_id = new_game_id()
    GAMES[game_id] = GameState(
        game_id=game_id,
        target_player_id=target_player_id,
        difficulty=generated_riddle.difficulty,
        hint_state=HintSessionState(player_id=target_player_id),
    )

    background_tasks.add_task(_prewarm_hint_corpus, target_player_id)

    return schemas.StartGameResponse(
        game_id=game_id,
        difficulty=generated_riddle.difficulty,
        clues=[_clue_to_schema(c) for c in generated_riddle.clues],
    )


@app.post("/api/games/{game_id}/hint", response_model=schemas.HintResponse)
def get_hint(game_id: str) -> schemas.HintResponse:
    game = _get_game_or_404(game_id)

    con = connect(read_only=False)
    try:
        result = get_next_hint(con, game.hint_state)
        if result is None:
            return schemas.HintResponse(
                hint_number=game.hint_state.hints_given, hint_text=llm_hint.NO_HINTS_LEFT_MESSAGE
            )

        _chunk_index, raw_text = result
        player_name, player_nickname = con.execute(
            "SELECT player_name, player_nickname FROM players WHERE player_id = ?",
            [game.target_player_id],
        ).fetchone()
    finally:
        con.close()

    phrased = llm_hint.phrase_hint([raw_text], player_name, player_nickname, game.hint_state.hints_given)
    return schemas.HintResponse(hint_number=game.hint_state.hints_given, hint_text=phrased)


@app.post("/api/games/{game_id}/guess", response_model=schemas.GuessResponse)
def submit_guess(game_id: str, body: schemas.GuessRequest) -> schemas.GuessResponse:
    game = _get_game_or_404(game_id)
    result = footy_quiz.check_answer(game.target_player_id, body.guess)

    if result.correct:
        game.solved = True
        return schemas.GuessResponse(correct=True, message=f"Correct! It was {result.matched_name}.")
    return schemas.GuessResponse(correct=False, message="Not quite -- try another guess or request a hint.")


@app.post("/api/games/{game_id}/reveal", response_model=schemas.RevealResponse)
def reveal(game_id: str) -> schemas.RevealResponse:
    game = _get_game_or_404(game_id)
    game.solved = True
    con = connect()
    try:
        name, photo_url = con.execute(
            "SELECT COALESCE(player_nickname, player_name), photo_url FROM players WHERE player_id = ?",
            [game.target_player_id],
        ).fetchone()
        # Same priority as clue cards: transfermarkt's own photo, Wikidata's as fallback.
        photo_url = photo_url or media.get_or_fetch_player_photo(con, game.target_player_id)
    finally:
        con.close()
    return schemas.RevealResponse(player_name=name, photo_url=photo_url)


@app.get("/api/players/autocomplete", response_model=list[schemas.AutocompleteResult])
def autocomplete(prefix: str, limit: int = 10) -> list[schemas.AutocompleteResult]:
    results = footy_quiz.autocomplete_candidates(prefix, limit=limit)
    return [schemas.AutocompleteResult(**r) for r in results]


class _RevalidatingStaticFiles(StaticFiles):
    # Without a Cache-Control header, browsers heuristically cache app.js/style.css and
    # keep serving stale copies after a change. no-cache still uses the ETag (cheap 304s),
    # it just forces the revalidation.
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Registered last so the explicit /api/* routes above are matched first -- anything else
# (/, /app.js, /style.css) falls through to the static frontend (checkpoint 14).
app.mount("/", _RevalidatingStaticFiles(directory=WEB_DIR, html=True), name="static")
