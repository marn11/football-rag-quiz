"""Tunable thresholds for target-player selection, centralized here so they're easy to
adjust without hunting through footy_quiz/selection.py."""

# A player needs at least this many squad-list appearances to be considered as a target at all.
MIN_MATCHES_FOR_TARGET = 6

# A club counts as "rich" (good clue material) if the player has at least this many
# strong teammates there.
MIN_STRONG_TEAMMATES_PER_RICH_CLUB = 3

# A teammate only counts toward a club's "strong teammate" count if the pair shared at
# least this many matches together...
MIN_SHARED_MATCHES_FOR_STRONG_TEAMMATE = 2

# ...and the teammate themselves has at least this many matches in the dataset -- a
# teammate who's themselves a one-match cameo doesn't make a good clue.
MIN_MATCHES_FOR_STRONG_TEAMMATE = 5
