"""Finding pieces on the belt (bricksort/sorter/detector.py), on made-up camera pictures."""
import numpy as np

from bricksort.sorter.detector import Detector, connected_components, crop, merge_close, Blob

H, W = 240, 320


def belt(seed=0):
    """An empty dark-green belt with a little camera noise."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), (40, 90, 50), np.float32) + rng.normal(0, 2, (H, W, 3))
    return np.clip(img, 0, 255).astype(np.uint8)


def ready_detector():
    d = Detector()
    for k in range(4):
        d.learn_background(belt(k))
    return d


def test_empty_belt_has_no_objects():
    assert ready_detector().find(belt(9)) == []


def test_two_separate_pieces_are_two_objects():
    frame = belt(9)
    frame[40:80, 40:100] = (200, 30, 30)      # a red brick
    frame[150:200, 220:260] = (230, 230, 230)  # a white one
    blobs = sorted(ready_detector().find(frame), key=lambda b: b.x0)
    assert len(blobs) == 2
    red, white = blobs
    assert abs(red.x0 - 40) <= 8 and abs(red.x1 - 100) <= 8
    assert abs(white.cy - 175) <= 6


def test_a_shadow_is_not_an_object():
    frame = belt(9).astype(np.float32)
    frame[60:140, 60:200] *= 0.6               # the belt, just darker: a shadow
    assert ready_detector().find(frame.astype(np.uint8)) == []


def test_pieces_close_together_count_as_one():
    frame = belt(9)
    frame[50:100, 50:90] = (200, 30, 30)
    frame[50:100, 94:130] = (30, 30, 200)      # 4 px apart: seen as one object
    assert len(ready_detector().find(frame)) == 1
    frame = belt(9)
    frame[50:100, 50:90] = (200, 30, 30)
    frame[50:100, 114:150] = (30, 30, 200)     # 24 px apart: two bits, joined as one object...
    blobs = ready_detector().find(frame)
    assert len(blobs) == 1
    assert len(blobs[0].bits) == 2             # ...that remembers it was two bits (the sorter's size check)


def test_connected_components_labels_separate_regions():
    m = np.zeros((6, 6), bool)
    m[0:2, 0:2] = True
    m[4:6, 3:6] = True
    m[2, 2] = True                             # touches the first region diagonally
    labels = connected_components(m)
    assert len(np.unique(labels[m])) == 2
    assert labels[2, 2] == labels[0, 0]


def test_merge_close_and_crop():
    a = Blob(0, 0, 10, 10, 100, 5, 5)
    b = Blob(30, 30, 40, 40, 100, 35, 35)
    assert len(merge_close([a, b], gap=5)) == 2
    assert len(merge_close([a, b], gap=25)) == 1
    pic = crop(belt(), Blob(100, 100, 140, 120, 800, 120, 110), size=64)
    assert pic.size == (64, 64)
