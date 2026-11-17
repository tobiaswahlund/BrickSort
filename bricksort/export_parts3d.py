"""3D models of parts for the website's sorting machine, so a guess can be shown as a piece you spin.

Run:  python -m bricksort.export_parts3d _site/parts _site/model/labels.json web/sim/sim.json
      (the GitHub Pages build does this, after export_web; see .github/workflows/pages.yml)

Writes one small file per part, <out>/<id>.bin, for every part the model knows (labels.json) and
every piece on the website's belt (sim.json), plus <out>/index.json: {part id as guessed: file name}.
A guessed number LDraw doesn't have (3062 for 3062b, say) is looked up without its letter, or with a, b or c.

The file (little-endian): uint32 vertex count, uint32 triangle count, float32 scale, then the corners
as int16 x, y, z (times scale = millimetres, +Z up, centred), padded to 4 bytes, then the triangles
as uint16 corner numbers (uint32 when there are 65536 corners or more), outward = counter-clockwise.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

from .ldraw import SCALE, Library

MAX_TRIANGLES = 60000   # more detailed than this: skipped (as on the virtual belt)


def ldraw_name(lib, pid):
    """The LDraw file for a guessed part number, or None."""
    base = re.sub(r"[a-z]+$", "", pid)
    for cand in (pid, base, base + "a", base + "b", base + "c"):
        if cand and lib.has_part(cand):
            return cand
    return None


def encode(verts, faces):
    """One part's mesh as the website's .bin (see the top of this file)."""
    mm = np.asarray(verts, np.float64) * (0.4 / SCALE)
    scale = max(float(np.abs(mm).max()), 1e-6) / 32767
    pos = np.round(mm / scale).astype("<i2").tobytes()
    pos += b"\0" * (-len(pos) % 4)
    idx = np.asarray(faces).astype("<u2" if len(verts) < 65536 else "<u4").tobytes()
    head = np.array([len(verts), len(faces)], "<u4").tobytes() + np.array([scale], "<f4").tobytes()
    return head + pos + idx


def export(out, labels_file, sim_file, lib=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ids = []
    if labels_file and Path(labels_file).exists():
        ids += [p["id"] for p in json.loads(Path(labels_file).read_text(encoding="utf-8"))["parts"]]
    if sim_file and Path(sim_file).exists():
        ids += [p["part"] for p in json.loads(Path(sim_file).read_text(encoding="utf-8"))["pieces"]]
    ids = list(dict.fromkeys(i for i in ids if i not in ("not_lego", "multiple")))
    lib = lib or Library()
    index, made, size = {}, {}, 0
    for pid in ids:
        name = ldraw_name(lib, pid)
        if name is None:
            continue
        if name not in made:
            try:
                v, f = lib.part_mesh(name)
            except Exception:
                made[name] = None
                continue
            if len(f) > MAX_TRIANGLES:
                made[name] = None
                continue
            data = encode(v, f)
            (out / f"{name}.bin").write_bytes(data)
            size += len(data)
            made[name] = f"{name}.bin"
        if made[name]:
            index[pid] = made[name]
    (out / "index.json").write_text(json.dumps(index), encoding="utf-8")
    print(f"Wrote 3D models of {len(index)} of {len(ids)} parts to {out} ({size / 1e6:.1f} MB)")
    return index


if __name__ == "__main__":
    export(*(sys.argv[1:4] + [None] * (3 - len(sys.argv[1:4]))))
