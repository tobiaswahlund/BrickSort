"""The 3D wear on training pieces (bricksort/wear.py): splitting triangles, dents and smooth shading."""
from collections import Counter

import numpy as np

from bricksort import wear

# a closed box, 4 x 2 studs and a brick high, as triangles
CORNERS = np.array([[x, y, z] for x in (0, 0.32) for y in (0, 0.16) for z in (0, 0.096)], float)
QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
FACES = np.array([t for a, b, c, d in QUADS for t in ((a, b, c), (a, c, d))], np.int32)


def area(v, f):
    return 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1).sum()


def open_edges(f):
    count = Counter((min(p, q), max(p, q)) for a, b, c in f for p, q in ((a, b), (b, c), (c, a)))
    return sum(1 for n in count.values() if n != 2)


def test_subdivide_keeps_the_shape_closed():
    v, f = wear.subdivide(CORNERS, FACES)
    assert len(f) > len(FACES)
    assert np.isclose(area(v, f), area(CORNERS, FACES))
    assert open_edges(f) == 0        # no corner in the middle of a neighbour's edge (no stripes)


def test_subdivide_only_near_a_point():
    v_all, f_all = wear.subdivide(CORNERS, FACES)
    v, f = wear.subdivide(CORNERS, FACES, near=lambda p: np.linalg.norm(p - CORNERS[0]) < 0.1)
    assert len(FACES) < len(f) < len(f_all)
    assert open_edges(f) == 0


def test_dents_push_in_and_keep_the_shape_closed():
    v, f = wear.dents(CORNERS, FACES, np.random.default_rng(1), 2)
    assert open_edges(f) == 0
    assert area(v, f) >= area(CORNERS, FACES) * 0.99
    assert np.all(v >= CORNERS.min(0) - 1e-9) and np.all(v <= CORNERS.max(0) + 1e-9)   # in, not out
    same = wear.dents(CORNERS, FACES, np.random.default_rng(1), 0)
    assert same[0] is CORNERS


def test_shading_keeps_box_edges_sharp():
    v, f, n = wear.shading(CORNERS, FACES)
    assert len(v) == 8 * 3            # every box corner: one copy for each of its three sides
    assert np.allclose(np.linalg.norm(n, axis=1), 1)
    for face in f:                    # each face's corners all point the way the face does
        fn = np.cross(v[face[1]] - v[face[0]], v[face[2]] - v[face[0]])
        fn /= np.linalg.norm(fn)
        assert np.allclose(n[face], fn)


def test_shading_smooths_a_round_surface():
    k = 24   # a tube of 24 flat sides: 15 degrees apart, so shaded as one smooth surface
    ring = [(np.cos(a), np.sin(a)) for a in np.linspace(0, 2 * np.pi, k, endpoint=False)]
    v = np.array([(x, y, z) for z in (0, 1) for x, y in ring])
    f = np.array([t for i in range(k) for t in ((i, (i + 1) % k, k + (i + 1) % k), (i, k + (i + 1) % k, k + i))])
    v2, _, n = wear.shading(v, f)
    assert len(v2) == len(v)          # nothing split
    assert np.allclose(n[:, :2], v[:, :2], atol=0.02)   # each point faces straight out from the middle


def test_texcoords_follow_the_facing_side():
    v, f, n = wear.shading(CORNERS, FACES)
    uv = wear.texcoords(v, n)
    assert uv.shape == (len(v), 2)
    top = np.isclose(n[:, 2], 1)
    assert np.allclose(uv[top], v[top][:, :2] / wear.TEX_SPAN)
