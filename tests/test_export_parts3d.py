"""The website's 3D part files (bricksort/export_parts3d.py), on a tiny hand-made library zip."""
import json
import struct
import zipfile

import numpy as np

from bricksort import export_parts3d, ldraw

# a 20 x 20 LDraw-unit square (8 x 8 mm), as two triangles
SQUARE = "0 Square\n0 BFC CERTIFY CCW\n4 16 0 0 0 20 0 0 20 0 20 0 0 20\n"


def _lib(tmp_path):
    z = tmp_path / "complete.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("ldraw/parts/3062b.dat", SQUARE)
        f.writestr("ldraw/parts/3001.dat", SQUARE)
    return ldraw.Library(z)


def _read(data):
    nv, nf = struct.unpack_from("<II", data)
    (scale,) = struct.unpack_from("<f", data, 8)
    pos = np.frombuffer(data, "<i2", nv * 3, 12).reshape(-1, 3) * scale
    start = 12 + nv * 6 + (-(nv * 6) % 4)
    faces = np.frombuffer(data, "<u2", nf * 3, start).reshape(-1, 3)
    assert len(data) == start + nf * 6
    return pos, faces


def test_files_and_index(tmp_path):
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"parts": [{"id": "3001"}, {"id": "3062"}, {"id": "not_lego"}, {"id": "99999"}]}))
    sim = tmp_path / "sim.json"
    sim.write_text(json.dumps({"pieces": [{"part": "3062b"}, {"part": "3001"}]}))
    out = tmp_path / "parts"
    index = export_parts3d.export(out, labels, sim, lib=_lib(tmp_path))
    # 3062 isn't in LDraw by that number: it gets 3062b's model; unknown numbers are left out
    assert index == {"3001": "3001.bin", "3062": "3062b.bin", "3062b": "3062b.bin"}
    assert json.loads((out / "index.json").read_text()) == index
    pos, faces = _read((out / "3001.bin").read_bytes())
    assert faces.shape == (2, 3) and len(pos) == 4
    assert np.allclose(np.ptp(pos, 0), [8, 8, 0], atol=0.01)   # 20 LDraw units = 8 mm, flat, +Z up
    assert np.allclose(pos.mean(0), 0, atol=0.01)              # centred
