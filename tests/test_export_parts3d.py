"""The website's live sorting machine files (bricksort/export_parts3d.py), on a tiny hand-made LDraw zip."""
import json
import struct
import zipfile

import numpy as np

from bricksort import export_parts3d, ldraw

# a 20 x 20 LDraw-unit square (8 x 8 mm), as two triangles
SQUARE = "0 Square\n0 BFC CERTIFY CCW\n4 16 0 0 0 20 0 0 20 0 20 0 0 20\n"
# 400 LDraw units = 160 mm long: too long for the belt, but fine for the 3D view of a guess
LONG = "0 Long\n0 BFC CERTIFY CCW\n4 16 0 0 0 400 0 0 400 0 20 0 0 20\n"
COLOURS = {4: ("Red", (201, 26, 9)), 1: ("Blue", (0, 85, 191)), 47: ("Trans-Clear", (252, 252, 252))}


def _lib(tmp_path):
    z = tmp_path / "complete.zip"
    with zipfile.ZipFile(z, "w") as f:
        for name, text in (("3062b", SQUARE), ("3001", SQUARE), ("3005", SQUARE), ("3008", LONG)):
            f.writestr(f"ldraw/parts/{name}.dat", text)
    return ldraw.Library(z)


def _read(data):
    nv, nf = struct.unpack_from("<II", data)
    (scale,) = struct.unpack_from("<f", data, 8)
    pos = np.frombuffer(data, "<i2", nv * 3, 12).reshape(-1, 3) * scale
    start = 12 + nv * 6 + (-(nv * 6) % 4)
    faces = np.frombuffer(data, "<u2", nf * 3, start).reshape(-1, 3)
    assert len(data) == start + nf * 6
    return pos, faces


def test_catalogue_and_models(tmp_path):
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"parts": [{"id": "3001", "name": "Brick 2 x 4", "category": "bricks"},
                                            {"id": "3062", "name": "Round brick", "category": "bricks round"},
                                            {"id": "3008", "name": "Brick 1 x 8", "category": "bricks"},
                                            {"id": "not_lego"}, {"id": "99999"}]}))
    others = [{"id": "3005", "name": "Brick 1 x 1", "category": "bricks"}, {"id": "3001", "name": "", "category": ""}]
    colours = {"3001": ([4, 1], [0.6, 0.4]), "3062": ([47], [1.0]), "3008": ([4], [1.0]), "3005": ([1, 999], [0.5, 0.5])}
    out = tmp_path / "machine"
    cat = export_parts3d.export(out, labels, lib=_lib(tmp_path), others=others, colour_table=COLOURS,
                                colours_of=lambda p: colours[p["id"]], settings={"camera_height": 2.1})
    # 3062 isn't in LDraw by that number: it uses 3062b's model. 3008 is too long for the belt but
    # can still be shown in 3D; 99999 has no model; 3001 isn't added twice.
    index = json.loads((out / "parts" / "index.json").read_text())
    assert index == {"3001": "3001.bin", "3062": "3062b.bin", "3008": "3008.bin", "3005": "3005.bin"}
    assert [(p["id"], p["known"]) for p in cat["parts"]] == [("3001", True), ("3062", True), ("3005", False)]
    assert cat["parts"][0]["colours"] == [[4, 0.6], [1, 0.4]]
    assert cat["parts"][2]["colours"] == [[1, 0.5]]            # colours not in the table are left out
    assert cat["colours"] == {"1": ["Blue", [0, 85, 191]], "4": ["Red", [201, 26, 9]],
                              "47": ["Trans-Clear", [252, 252, 252]]}
    assert json.loads((out / "catalogue.json").read_text()) == cat
    pos, faces = _read((out / "parts" / "3001.bin").read_bytes())
    assert faces.shape == (2, 3) and len(pos) == 4
    assert np.allclose(np.ptp(pos, 0), [8, 8, 0], atol=0.01)   # 20 LDraw units = 8 mm, flat, +Z up
    assert np.allclose(pos.mean(0), 0, atol=0.01)              # centred


def test_machine_settings_match_the_desktop():
    m = export_parts3d.machine_settings()
    assert m["belt_half_len"] == 2.0 and m["belt_half_width"] == 0.75 and m["fovy"] == 45.0
    assert m["camera_height"] == 2.1 and m["machine_camera"] == 720 and len(m["lamps"]) == 3
