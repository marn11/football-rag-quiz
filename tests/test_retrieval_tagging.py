from footy_quiz.hints.retrieval import contains_name, extract_aka_nickname, specificity


def test_extract_aka_nickname_from_opening_sentence():
    opening = 'Lionel Andrés "Leo" Messi (born 24 June 1987) is an Argentine footballer.'
    assert extract_aka_nickname(opening) == "Leo"


def test_extract_aka_nickname_none_when_absent():
    assert extract_aka_nickname("Sergio Ramos García (born 1986) is a Spanish footballer.") is None


def test_contains_name_catches_prose_only_nickname_via_aka():
    # "Leo" never appears in the stored player_name/player_nickname fields -- only in
    # the Wikipedia prose itself -- so it must be passed in explicitly as `aka`.
    assert contains_name("'Leo' developed a passion for the sport.", "Lionel Messi", "Lionel Messi", aka="Leo")
    assert not contains_name("'Leo' developed a passion for the sport.", "Lionel Messi", "Lionel Messi")


def test_contains_name_detects_full_name_token():
    assert contains_name("Messi scored twice that night.", "Lionel Messi", "Messi")


def test_contains_name_detects_nickname_only():
    assert contains_name("He is often compared to Pele.", "Edson Arantes do Nascimento", "Pele")


def test_contains_name_false_when_no_token_present():
    assert not contains_name("He was born in a small town.", "Lionel Messi", "Messi")


def test_contains_name_ignores_short_particle_tokens():
    # "Di" alone shouldn't cause false positives against unrelated text containing "di".
    assert not contains_name(
        "He played a different role that season.", "Angel Di Maria", "Di Maria"
    )


def test_specificity_vague_sentence_is_tier_one():
    assert specificity("He is known for his composure in front of goal.") == 1


def test_specificity_year_and_two_names_is_tier_three():
    text = "In 2019 he scored past Manuel Neuer in the Champions League semi-final."
    assert specificity(text) == 3


def test_specificity_quote_bumps_tier():
    assert specificity('He once said, "I just want to play football."') >= 2
