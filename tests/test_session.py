"""Tests footy_quiz.hints.session's logic with store.retrieve mocked out -- this is about
session bookkeeping (no-repeats, ceiling progression, angle rotation), not retrieval
quality, which is already covered in test_hints_store.py.
"""

from footy_quiz.hints import session as session_module
from footy_quiz.hints.session import HINT_ANGLES, HintSessionState, get_next_hint


def test_specificity_ceiling_rises_every_two_hints():
    state = HintSessionState(player_id=1)
    expected = [1, 1, 2, 2, 3, 3, 3, 3]  # caps at 3
    actual = []
    for i in range(8):
        state.hints_given = i
        actual.append(state.specificity_ceiling())
    assert actual == expected


def test_next_angle_cycles_through_all_angles_then_wraps():
    state = HintSessionState(player_id=1)
    seen = [state.next_angle()]
    state.hints_given = 1
    seen.append(state.next_angle())
    state.hints_given = len(HINT_ANGLES)  # should wrap back to the first angle
    seen.append(state.next_angle())
    assert seen[0] == HINT_ANGLES[0]
    assert seen[1] == HINT_ANGLES[1]
    assert seen[2] == HINT_ANGLES[0]


def test_get_next_hint_marks_chunk_served_and_increments_count(monkeypatch):
    calls = []

    def fake_retrieve(con, player_id, query, k, max_specificity, exclude_chunk_indices):
        calls.append(
            dict(query=query, max_specificity=max_specificity, excluded=set(exclude_chunk_indices))
        )
        return [(len(calls) - 1, f"chunk text {len(calls) - 1}", 0.1)]

    monkeypatch.setattr(session_module.store, "retrieve", fake_retrieve)

    state = HintSessionState(player_id=1)
    chunk_index, text = get_next_hint(None, state)
    assert chunk_index == 0
    assert state.hints_given == 1
    assert state.served_chunk_indices == {0}

    chunk_index, text = get_next_hint(None, state)
    assert chunk_index == 1
    assert state.hints_given == 2
    assert state.served_chunk_indices == {0, 1}

    # the second call must have excluded the chunk served by the first
    assert calls[1]["excluded"] == {0}
    # and used a different angle than the first call
    assert calls[0]["query"] != calls[1]["query"]


def test_get_next_hint_returns_none_without_incrementing_when_nothing_eligible(monkeypatch):
    monkeypatch.setattr(
        session_module.store, "retrieve", lambda *a, **k: []
    )
    state = HintSessionState(player_id=1)
    result = get_next_hint(None, state)
    assert result is None
    assert state.hints_given == 0
    assert state.served_chunk_indices == set()


def test_six_simulated_hints_have_no_repeats(monkeypatch):
    # Mimics scripts/simulate_hints.py's scenario with a fake but realistic retrieve().
    pool = {i: f"fact number {i}" for i in range(10)}

    def fake_retrieve(con, player_id, query, k, max_specificity, exclude_chunk_indices):
        for idx, text in pool.items():
            if idx not in exclude_chunk_indices:
                return [(idx, text, 0.1)]
        return []

    monkeypatch.setattr(session_module.store, "retrieve", fake_retrieve)

    state = HintSessionState(player_id=1)
    served = []
    for _ in range(6):
        result = get_next_hint(None, state)
        assert result is not None
        served.append(result[0])

    assert len(served) == len(set(served))  # no repeats
    assert state.hints_given == 6
