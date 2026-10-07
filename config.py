"""Difficulty presets for target-player selection, centralized here so they're easy to
tune without hunting through footy_quiz/selection.py.

Each preset loosens what counts as a "strong teammate" connection, how many "rich" clubs
(clubs with enough strong-teammate connections) a player needs, and how many distinct
"qualifying" clubs (any club with even one solid teammate connection, rich or not) they
need overall. A player is assigned the STRICTEST preset they satisfy -- so e.g. Messi
qualifies for every preset but is only ever surfaced as "easy", never re-surfaced under
"normal" etc.

min_qualifying_clubs exists specifically to avoid a thin, repetitive riddle: without it,
a player who spent years at exactly one club (and nowhere else in this dataset) could
still be selected, and the only way to fill 3 clues would be 3 different teammates from
that SAME club in different seasons -- a riddle that reads as "this person was at Eibar
for a while" three times over, not an interesting career trajectory. Requiring a second
(not necessarily "rich") club pushes those thin, single-club careers down to "extreme",
the one tier explicitly meant to allow them.

- easy:    plenty of well-attested teammates across >=2 clubs -- today's marquee names.
- normal:  one well-attested club, but still requires a second club with at least some
           connection, so the riddle isn't just one club repeated.
- hard:    teammate connections exist but are thin (shared just 1 match, or the
           teammate themselves is lightly covered) -- still real, just weaker signal,
           still requires that second club.
- extreme: virtually no bar at all -- even a player with a single appearance has
           *someone* they shared that one squad list with. The only tier that allows a
           genuinely single-club (or single-match) career -- deliberately the hardest,
           most obscure riddles.
"""

DIFFICULTY_ORDER = ["easy", "normal", "hard", "extreme"]

DIFFICULTY_PRESETS = {
    "easy": dict(
        min_matches=6,
        min_shared_matches_for_strong_teammate=2,
        min_matches_for_strong_teammate=5,
        min_strong_teammates_per_rich_club=3,
        min_rich_clubs=2,
        min_qualifying_clubs=2,
    ),
    "normal": dict(
        min_matches=6,
        min_shared_matches_for_strong_teammate=2,
        min_matches_for_strong_teammate=5,
        min_strong_teammates_per_rich_club=3,
        min_rich_clubs=1,
        min_qualifying_clubs=2,
    ),
    "hard": dict(
        min_matches=3,
        min_shared_matches_for_strong_teammate=1,
        min_matches_for_strong_teammate=3,
        min_strong_teammates_per_rich_club=1,
        min_rich_clubs=1,
        min_qualifying_clubs=2,
    ),
    "extreme": dict(
        min_matches=1,
        min_shared_matches_for_strong_teammate=1,
        min_matches_for_strong_teammate=1,
        min_strong_teammates_per_rich_club=1,
        min_rich_clubs=1,
        min_qualifying_clubs=1,
    ),
}
