"""Which bin a piece goes to (bricksort/sorter/rules.py), with rules and part facts passed in."""
import pytest

from bricksort.sorter import rules as r

PROPS = {
    "3001": {"category": "bricks", "name": "Brick 2 x 4", "flat": False, "length": 4, "width": 2, "height": 3},
    "3023": {"category": "plates", "name": "Plate 1 x 2", "flat": True, "length": 2, "width": 1, "height": 1},
    "3008": {"category": "bricks", "name": "Brick 1 x 8", "flat": False, "length": 8, "width": 1, "height": 3},
    "3626c": {"category": "minifig heads", "name": "Minifig Head", "flat": False},
}
RULES = {
    "confidence_needed": 0.9,
    "not_lego_bin": "Not Lego",
    "rest_bin": "Rest",
    "bins": [
        {"name": "Heads", "when": {"category": "minifig heads"}},
        {"name": "Flat black", "when": {"color": ["Black"], "flat": True}},
        {"name": "Long", "when": {"min_length": 6}},
        {"name": "Red", "when": {"color": ["Red"]}},
        {"name": "Other", "when": {}},
    ],
}


def choose(part, part_conf=0.99, colour="Red", colour_conf=0.99, n=1, rules=RULES, **kw):
    return r.choose_bin(rules, PROPS, part, part_conf, colour, colour_conf, n, **kw)[0]


def test_sure_piece_goes_to_first_matching_bin():
    assert choose("3001", colour="Red") == "Red"
    assert choose("3626c", colour="Red") == "Heads"   # Heads comes before Red
    assert choose("3008", colour="Red") == "Long"     # Long comes before Red


def test_other_colour_skips_a_colour_bin():
    assert choose("3001", colour="Blue") == "Other"
    assert choose("3023", colour="Black") == "Flat black"
    assert choose("3001", colour="Black") == "Other"  # black, but not flat


def test_several_objects_or_unsure_part_go_to_rest():
    assert choose("3001", n=2) == "Rest"
    assert choose("3001", part_conf=0.5) == "Rest"
    assert choose("multiple", part_conf=0.99) == "Rest"


def test_unsure_colour_never_guesses_a_colour_bin():
    # it would fit the Red bin, but the colour isn't certain: rest bin, not a wrong bin
    assert choose("3001", colour="Red", colour_conf=0.5) == "Rest"


def test_not_lego_needs_to_be_sure():
    assert choose("not_lego", part_conf=0.95) == "Not Lego"
    assert choose("not_lego", part_conf=0.6) == "Rest"


def test_bin_with_its_own_lower_confidence():
    easy = {"name": "Easy", "when": {"part": ["3001"]}, "confidence": 0.5}
    rules = {**RULES, "bins": [easy] + RULES["bins"]}
    assert choose("3001", part_conf=0.6, rules=rules) == "Easy"
    assert choose("3023", part_conf=0.6, rules=rules) == "Rest"   # the other bins still need 0.9


def test_unknown_part_sorted_by_a_clear_category():
    rules = {**RULES, "bins": [{"name": "Heads", "when": {"category": "minifig heads"}},
                               {"name": "Other", "when": {}}]}
    got = choose("9999", part_conf=0.2, rules=rules, category="Minifig Heads", category_conf=0.95)
    assert got == "Heads"


def test_look_alike_colours_count_as_the_same():
    rules = {**RULES, "bins": [{"name": "Grey", "when": {"color": ["Light Bluish Gray"]}}]}
    assert choose("3001", colour="Light Gray", rules=rules) == "Grey"


def test_printed_condition_needs_a_sure_answer():
    rules = {**RULES, "bins": [{"name": "Printed", "when": {"printed": True}}, {"name": "Other", "when": {}}]}
    assert choose("3001", rules=rules, printed=0.97) == "Printed"
    assert choose("3001", rules=rules, printed=0.02) == "Other"
    assert choose("3001", rules=rules, printed=0.6) == "Rest"   # not sure either way


def test_unknown_condition_is_an_error():
    with pytest.raises(ValueError):
        r.matches({"colour_typo": "Red"}, "3001", "Red", PROPS)


def test_describe_in_plain_words():
    assert r.describe({}) == "any other LEGO piece"
    assert r.describe({"color": ["Black"], "flat": True}) == "Black, flat"
    assert r.describe({"min_length": 6}) == "at least 6 studs long"


def test_bin_names_end_with_not_lego_and_rest():
    assert r.bin_names(RULES)[-2:] == ["Not Lego", "Rest"]
