"""Which pictures training uses (bricksort/sampling.py)."""
from pathlib import Path

from bricksort.sampling import TEST_CAP, Balanced, split_real


def photos(part, n, prefix="p", colour=5):
    return [(Path(f"{prefix}{part}_{i}.jpg"), part, colour, "", 0) for i in range(n)]


def names(items):
    return {it[0] for it in items}


def test_split_keeps_about_one_in_five_photos_for_the_test():
    test, train = split_real(photos("3001", 20))
    assert len(test) == 4
    assert len(train) == 16
    assert not names(test) & names(train)


def test_split_is_the_same_every_time():
    items = photos("3001", 30) + photos("3023", 12)
    assert names(split_real(items)[0]) == names(split_real(list(reversed(items)))[0])


def test_split_never_tests_on_renders_or_parts_with_few_photos():
    test, train = split_real(photos("3001", 10, prefix="d02_") + photos("3023", 2))
    assert test == []
    assert len(train) == 12


def test_split_caps_test_photos_per_part():
    test, _ = split_real(photos("3001", 1000))
    assert len(test) == TEST_CAP


def test_balanced_uses_every_simulated_picture_and_is_repeatable():
    sim = [(Path(f"s{i}.png"), "3001", None, "", 0) for i in range(6)]
    s = Balanced(sim + photos("3001", 3), n_sim=len(sim))
    s.set_epoch(1)
    first = list(s)
    assert len(first) == len(s)
    assert set(range(len(sim))) <= set(first)
    s.set_epoch(1)
    assert list(s) == first           # same round number, same pictures: a stopped training carries on
    s.set_epoch(2)
    assert list(s) != first


def test_balanced_takes_colours_in_turn():
    items = photos("3001", 500, prefix="r", colour=5) + photos("3001", 1, prefix="b", colour=1)
    s = Balanced(items, n_sim=0)
    chosen = list(s)
    assert len(chosen) < len(items)        # capped: not every red photo fits in one round...
    assert len(items) - 1 in chosen        # ...but the one blue photo is never crowded out
