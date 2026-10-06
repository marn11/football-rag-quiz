"""Difficulty presets for target-player selection, centralized here so they're easy to
tune without hunting through footy_quiz/selection.py.

Each preset loosens what counts as a "strong teammate" connection and how many "rich"
clubs (clubs with enough strong-teammate connections) a player needs to qualify. A
player is assigned the STRICTEST preset they satisfy -- so e.g. Messi qualifies for
every preset but is only ever surfaced as "easy", never re-surfaced under "normal" etc.

- easy:    plenty of well-attested teammates across >=2 clubs -- today's marquee names.
- normal:  well-attested teammates, but only at one club worth of clue material.
- hard:    teammate connections exist but are thin (shared just 1 match, or the
           teammate themselves is lightly covered) -- still real, just weaker signal.
- extreme: virtually no bar at all -- even a player with a single appearance has
           *someone* they shared that one squad list with. Deliberately includes
           one-match cameos as the hardest possible riddles.
"""

DIFFICULTY_ORDER = ["easy", "normal", "hard", "extreme"]

DIFFICULTY_PRESETS = {
    "easy": dict(
        min_matches=6,
        min_shared_matches_for_strong_teammate=2,
        min_matches_for_strong_teammate=5,
        min_strong_teammates_per_rich_club=3,
        min_rich_clubs=2,
    ),
    "normal": dict(
        min_matches=6,
        min_shared_matches_for_strong_teammate=2,
        min_matches_for_strong_teammate=5,
        min_strong_teammates_per_rich_club=3,
        min_rich_clubs=1,
    ),
    "hard": dict(
        min_matches=3,
        min_shared_matches_for_strong_teammate=1,
        min_matches_for_strong_teammate=3,
        min_strong_teammates_per_rich_club=1,
        min_rich_clubs=1,
    ),
    "extreme": dict(
        min_matches=1,
        min_shared_matches_for_strong_teammate=1,
        min_matches_for_strong_teammate=1,
        min_strong_teammates_per_rich_club=1,
        min_rich_clubs=1,
    ),
}
