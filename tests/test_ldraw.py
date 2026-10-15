"""Reading LDraw part files (bricksort/ldraw.py), on a tiny hand-made library zip."""
import zipfile

import numpy as np
import pytest

from bricksort import ldraw

# A "part" made of one quad of its own plus a reference to a shared triangle, placed 10 units
# higher and mirrored (a mirroring matrix flips the winding, as LDraw's BFC rules say).
PART = """0 Test Square
0 BFC CERTIFY CCW
4 16 0 0 0 20 0 0 20 0 20 0 0 20
1 16 0 -10 0 1 0 0 0 1 0 0 0 1 tri.dat
1 16 0 -10 0 -1 0 0 0 1 0 0 0 1 tri.dat
"""
TRI = """0 Shared triangle
0 BFC CERTIFY CCW
3 16 0 0 0 1 0 0 0 0 1
"""


@pytest.fixture
def lib(tmp_path):
    z = tmp_path / "complete.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("ldraw/parts/test.dat", PART)
        f.writestr("ldraw/p/tri.dat", TRI)
    return ldraw.Library(z)


def test_finds_parts_and_titles(lib):
    assert lib.has_part("test")
    assert lib.has_part("TEST")
    assert not lib.has_part("3001")
    assert lib.title("test") == "Test Square"


def test_quads_become_two_triangles_and_references_are_followed(lib):
    tris = lib.triangles("test.dat")
    assert tris.shape == (4, 3, 3)   # quad = 2 triangles, plus the referenced triangle twice
    np.testing.assert_allclose(tris[2], [[0, -10, 0], [1, -10, 0], [0, -10, 1]])   # moved 10 units


def test_mirrored_reference_keeps_faces_pointing_out(lib):
    tris = lib.triangles("test.dat")
    normal = lambda t: np.cross(t[1] - t[0], t[2] - t[0])   # noqa: E731
    plain, mirrored = tris[2], tris[3]
    # mirrored in x, then the winding is flipped back: the face still points the same way (here: -y)
    assert np.sign(normal(plain)[1]) == np.sign(normal(mirrored)[1])


def test_part_mesh_is_centred_and_z_up(lib):
    verts, faces = lib.part_mesh("test")
    np.testing.assert_allclose((verts.min(0) + verts.max(0)) / 2, 0, atol=1e-12)
    # LDraw's -y (up) becomes +z. The square is 20 x 20 LDraw units, 10 below the triangles,
    # and the mirrored triangle reaches 1 unit past its edge (x = -1)
    size = verts.max(0) - verts.min(0)
    np.testing.assert_allclose(size, np.array([21, 20, 10]) * ldraw.SCALE)
    assert faces.max() < len(verts)


def test_missing_reference_is_skipped_not_fatal(tmp_path):
    z = tmp_path / "complete.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("ldraw/parts/odd.dat", "0 Odd\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 missing.dat\n3 16 0 0 0 1 0 0 0 0 1\n")
    assert ldraw.Library(z).triangles("odd.dat").shape == (1, 3, 3)
