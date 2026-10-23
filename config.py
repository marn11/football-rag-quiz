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

min_popularity_views is a real-world fame gate, separate from all the above: the underlying
dataset's coverage density (how thoroughly a player's matches/teammates are logged) and actual
public recognizability are only loosely correlated -- a competently-covered journeyman
can rack up the same structural "rich club" stats as a genuine star. Measured via trailing
12-month en.wikipedia pageviews (footy_quiz.media.get_or_fetch_player_popularity, computed
once by scripts/build_popularity.py, never live per-request -- see that module). Calibration
sample (13-month window): Messi ~9.47M, Di Maria ~1.21M, Rapinoe ~499k, Dante ~173k,
Kehrer ~115k, vs. a true nobody like a lower-league squad filler at ~23 -- a >1000x gap
between "recognizable pro" and "nobody's heard of them", which is what min_popularity_views
is tuned against, not against finer distinctions of fame within "recognizable". A player who
clears a band's structural bar but not its popularity bar falls through to the next band
down (same mechanism as any other unmet threshold) -- never excluded outright. hard/extreme
have no popularity bar at all: thin/obscure is already their entire premise.

- easy:    plenty of well-attested teammates across >=2 clubs, AND a genuine global-fame
           pageview count -- today's marquee names.
- normal:  one well-attested club, but still requires a second club with at least some
           connection, so the riddle isn't just one club repeated; popularity bar is much
           lower than "easy" -- just enough to exclude true nobodies, not just non-stars.
- hard:    teammate connections exist but are thin (shared just 1 match, or the
           teammate themselves is lightly covered) -- still real, just weaker signal,
           still requires that second club. No popularity bar.
- extreme: virtually no bar at all -- even a player with a single appearance has
           *someone* they shared that one squad list with. The only tier that allows a
           genuinely single-club (or single-match) career -- deliberately the hardest,
           most obscure riddles. No popularity bar.
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
        min_popularity_views=400_000,
    ),
    "normal": dict(
        min_matches=6,
        min_shared_matches_for_strong_teammate=2,
        min_matches_for_strong_teammate=5,
        min_strong_teammates_per_rich_club=3,
        min_rich_clubs=1,
        min_qualifying_clubs=2,
        min_popularity_views=8_000,
    ),
    "hard": dict(
        min_matches=3,
        min_shared_matches_for_strong_teammate=1,
        min_matches_for_strong_teammate=3,
        min_strong_teammates_per_rich_club=1,
        min_rich_clubs=1,
        min_qualifying_clubs=2,
        min_popularity_views=0,
    ),
    "extreme": dict(
        min_matches=1,
        min_shared_matches_for_strong_teammate=1,
        min_matches_for_strong_teammate=1,
        min_strong_teammates_per_rich_club=1,
        min_rich_clubs=1,
        min_qualifying_clubs=1,
        min_popularity_views=0,
    ),
}
