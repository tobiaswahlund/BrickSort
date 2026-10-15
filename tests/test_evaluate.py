"""The accuracy test's maths and bookkeeping (bricksort/evaluate.py)."""
from pathlib import Path

import pytest

from bricksort import evaluate


def test_wilson_interval():
    assert evaluate.wilson(0, 0) == (0.0, 0.0)
    lo, hi = evaluate.wilson(0, 10)        # 0 of 10 right: could still be up to ~28%
    assert lo == 0.0
    assert hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = evaluate.wilson(50, 100)      # symmetric around 50%
    assert lo == pytest.approx(1 - hi)
    assert lo < 0.5 < hi


def test_interval_narrows_with_more_pieces():
    small = evaluate.wilson(8, 10)
    big = evaluate.wilson(80, 100)
    assert big[1] - big[0] < small[1] - small[0]


def test_photos_of_one_piece_count_once():
    a = evaluate._piece_of(Path("t/3001/Red/piece07__a.jpg"))
    b = evaluate._piece_of(Path("t/3001/Red/piece07__b.jpg"))
    c = evaluate._piece_of(Path("t/3001/Red/piece08.jpg"))
    assert a == b
    assert a != c


def test_test_photos_reads_part_and_colour(tmp_path, no_downloads):
    (tmp_path / "3001" / "Red").mkdir(parents=True)
    (tmp_path / "3001" / "Red" / "a.jpg").write_bytes(b"")
    (tmp_path / "3023").mkdir()
    (tmp_path / "3023" / "b.jpg").write_bytes(b"")
    (tmp_path / "_skip").mkdir()
    (tmp_path / "_skip" / "c.jpg").write_bytes(b"")
    got = sorted((p.name, part, colour) for p, part, colour in evaluate.test_photos(tmp_path))
    assert got == [("a.jpg", "3001", "Red"), ("b.jpg", "3023", None)]
