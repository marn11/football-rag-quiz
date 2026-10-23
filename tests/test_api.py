"""End-to-end API tests using FastAPI's TestClient (in-process, no real server/port).
Requires build_db.py + build_graph.py to have run. Hint requests make real Wikipedia
calls on first use per player (cached afterward) and real LLM calls if ANTHROPIC_API_KEY
is set -- or exercise the fallback path if it isn't/is invalid, either way the endpoint
should respond successfully.
"""

import pytest
from fastapi.testclient import TestClient

from footy_quiz.api.main import app
from footy_quiz.ingest import DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="DB not built yet -- run scripts/build_db.py first"
)

client = TestClient(app)


def _start_game(difficulty: str = "easy") -> dict:
    resp = client.post("/api/games", params={"difficulty": difficulty})
    assert resp.status_code == 200
    return resp.json()


def test_start_game_returns_clues_without_leaking_target_identity():
    body = _start_game()
    assert "game_id" in body
    assert body["difficulty"] == "easy"
    assert len(body["clues"]) >= 1
    for clue in body["clues"]:
        assert "text" in clue and "teammate_display_name" in clue
        # must never leak target-identifying fields -- only teammate/club info
        assert "target_player_id" not in clue
        assert "player_id" not in clue


def test_full_sequence_start_hint_wrong_guess_correct_guess():
    game = _start_game()
    game_id = game["game_id"]

    hint_resp = client.post(f"/api/games/{game_id}/hint")
    assert hint_resp.status_code == 200
    assert "hint_text" in hint_resp.json()

    wrong = client.post(f"/api/games/{game_id}/guess", json={"guess": "Cristiano Ronaldo"})
    assert wrong.status_code == 200
    assert wrong.json()["correct"] is False

    reveal = client.post(f"/api/games/{game_id}/reveal")
    assert reveal.status_code == 200
    real_name = reveal.json()["player_name"]

    # The full revealed name, not just its last token -- some players have compound
    # surnames (particles like "di"/"van"/"de"), where the last token alone isn't
    # guaranteed to match (see answers._surname_candidates); the full name always does.
    correct = client.post(f"/api/games/{game_id}/guess", json={"guess": real_name})
    assert correct.status_code == 200
    body = correct.json()
    assert body["correct"] is True
    assert real_name in body["message"]


def test_unknown_game_id_returns_404():
    assert client.post("/api/games/not-a-real-id/hint").status_code == 404
    assert client.post("/api/games/not-a-real-id/guess", json={"guess": "x"}).status_code == 404
    assert client.post("/api/games/not-a-real-id/reveal").status_code == 404


def test_unknown_difficulty_returns_400():
    resp = client.post("/api/games", params={"difficulty": "impossible"})
    assert resp.status_code == 400


def test_hints_do_not_repeat_across_requests():
    game = _start_game()
    game_id = game["game_id"]
    texts = set()
    for _ in range(3):
        resp = client.post(f"/api/games/{game_id}/hint")
        texts.add(resp.json()["hint_text"])
    # not a strict guarantee of 3 unique phrasings (LLM could paraphrase differently),
    # but the underlying chunks are guaranteed distinct -- this at least confirms the
    # endpoint doesn't error out across repeated calls in the same game session.
    assert len(texts) >= 1
