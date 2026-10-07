"""Tests footy_quiz.hints.llm_hint with the Anthropic client mocked out -- no real API
calls (no cost, no network, deterministic). scripts/simulate_hints_llm.py is the
real-API eyeball check + the "force a bad key" fallback check, per checkpoint 12's verify
step.
"""

import httpx2
import pytest

import anthropic
from footy_quiz.hints import llm_hint

PLAYER_NAME = "Lionel Andrés Messi Cuccittini"
PLAYER_NICKNAME = "Lionel Messi"


class _FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = stop_reason


@pytest.fixture(autouse=True)
def _reset_client_singleton(monkeypatch):
    monkeypatch.setattr(llm_hint, "_client", None)


def test_phrase_hint_happy_path(monkeypatch):
    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                assert kwargs["model"] == "claude-haiku-4-5"
                assert PLAYER_NAME in kwargs["messages"][0]["content"]
                return _FakeResponse("He once scored a wonder goal as a teenager.")

    monkeypatch.setattr(llm_hint, "_get_client", lambda: FakeClient())
    result = llm_hint.phrase_hint(
        ["He scored an incredible solo goal at age 17."], PLAYER_NAME, PLAYER_NICKNAME, 1
    )
    assert result == "He once scored a wonder goal as a teenager."


def test_phrase_hint_empty_chunks_returns_no_hints_message():
    result = llm_hint.phrase_hint([], PLAYER_NAME, PLAYER_NICKNAME, 1)
    assert result == llm_hint.NO_HINTS_LEFT_MESSAGE


def test_phrase_hint_falls_back_on_rate_limit(monkeypatch):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx2.Response(429, request=req)

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise anthropic.RateLimitError("rate limited", response=resp, body=None)

    monkeypatch.setattr(llm_hint, "_get_client", lambda: FakeClient())
    result = llm_hint.phrase_hint(["Messi once scored a hat-trick."], PLAYER_NAME, PLAYER_NICKNAME, 1)
    assert result.startswith("Fun fact:")
    assert "Messi" not in result  # redacted even in the fallback path


def test_phrase_hint_falls_back_on_connection_error(monkeypatch):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise anthropic.APIConnectionError(request=req)

    monkeypatch.setattr(llm_hint, "_get_client", lambda: FakeClient())
    result = llm_hint.phrase_hint(["He grew up in a small town."], PLAYER_NAME, PLAYER_NICKNAME, 1)
    assert result == "Fun fact: He grew up in a small town."


def test_phrase_hint_falls_back_on_bad_api_key(monkeypatch):
    # AuthenticationError is a subclass of APIStatusError -- confirms a bad/invalid key
    # (401) is caught by the same fallback chain as rate limits and connection errors.
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx2.Response(401, request=req)

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise anthropic.AuthenticationError("invalid x-api-key", response=resp, body=None)

    monkeypatch.setattr(llm_hint, "_get_client", lambda: FakeClient())
    result = llm_hint.phrase_hint(["He grew up in a small town."], PLAYER_NAME, PLAYER_NICKNAME, 1)
    assert result == "Fun fact: He grew up in a small town."


def test_phrase_hint_falls_back_on_refusal(monkeypatch):
    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                return _FakeResponse("", stop_reason="refusal")

    monkeypatch.setattr(llm_hint, "_get_client", lambda: FakeClient())
    result = llm_hint.phrase_hint(["He grew up in a small town."], PLAYER_NAME, PLAYER_NICKNAME, 1)
    assert result == "Fun fact: He grew up in a small town."


def test_redact_replaces_all_name_tokens():
    text = "Messi and Lionel both refer to the same person."
    redacted = llm_hint._redact(text, PLAYER_NAME, PLAYER_NICKNAME)
    assert "Messi" not in redacted
    assert "Lionel" not in redacted
