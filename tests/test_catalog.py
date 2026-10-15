"""Matching part numbers and colours (bricksort/catalog.py)."""
from bricksort import catalog


def test_same_piece_ignores_the_version_letter():
    assert catalog.same_piece("3062a", "3062b")
    assert catalog.same_piece("12002", "12002b")
    assert not catalog.same_piece("3001", "3002")
    assert not catalog.same_piece("", "3001")


def test_same_colour_joins_old_and_new_greys():
    assert catalog.same_colour("Light Gray") == "Light Bluish Gray"
    assert catalog.same_colour("dark gray") == "Dark Bluish Gray"
    assert catalog.same_colour("Red") == "Red"


def test_folder_part(no_downloads):
    assert catalog.folder_part("3001") == "3001"
    assert catalog.folder_part("3626cpr0001") == "3626c"     # printed -> plain part
    assert catalog.folder_part("970c03") == "970c00"         # hips and legs in any colour -> one shape
    assert catalog.folder_part("_not_lego") == catalog.NOT_LEGO
    assert catalog.folder_part("_multiple") == catalog.MULTIPLE
    assert catalog.folder_part("_test") is None              # the test set is never a part folder
    assert catalog.folder_part("_to_cut") is None
    assert catalog.folder_part("unknown") is None
