"""Everything the website's live sorting machine needs: the parts (3D models), their colours, the
belt and the lamps. The website runs the same MuJoCo physics as the desktop app's virtual sorting
machine (conveyor.py) and draws the camera picture live in the browser.

Run:  python -m bricksort.export_parts3d _site/machine _site/model/labels.json
      (the GitHub Pages build does this, after export_web; see .github/workflows/pages.yml)

Writes to <out>:
  parts/<id>.bin      one small file per part (format below)
  parts/index.json    {part number as guessed: file name}, for the 3D view of a guess
  catalogue.json      the parts that can go on the belt (every part the model knows, plus a random
                      choice of other LEGO parts), with name, category, known or not, and the colours
                      each is really made in; the colour table; the machine (camera, belt, lamps)
  belt.png            the belt's surface (2 x 2 copies: one tile is 2 x span long, as on the desktop)

A guessed number LDraw doesn't have (3062 for 3062b, say) is looked up without its letter, or with
a, b or c.

The .bin file (little-endian): uint32 vertex count, uint32 triangle count, float32 scale, then the
corners as int16 x, y, z (times scale = millimetres, +Z up, centred), padded to 4 bytes, then the
triangles as uint16 corner numbers (uint32 when there are 65536 corners or more), outward = CCW.
"""
import json
import random
import re
import sys
from pathlib import Path

import numpy as np

from .ldraw import SCALE, Library

MAX_TRIANGLES = 60000   # more detailed than this: skipped (as on the desktop's virtual belt)
MAX_PIECE = 1.4         # longest piece that fits on the belt, in world units (140 mm; conveyor.MAX_PIECE)
MAX_EXTRA = 2500        # other LEGO parts (the model doesn't know them) picked at random for the belt
BELT = "Green, matte"   # the website's belt (stands out from most LEGO colours)


def ldraw_name(lib, pid):
    """The LDraw file for a guessed part number, or None."""
    base = re.sub(r"[a-z]+$", "", pid)
    for cand in (pid, base, base + "a", base + "b", base + "c"):
        if cand and lib.has_part(cand):
            return cand
    return None


def encode(verts, faces):
    """One part's mesh as the website's .bin (see the top of this file). verts in world units."""
    mm = np.asarray(verts, np.float64) * (0.4 / SCALE)
    scale = max(float(np.abs(mm).max()), 1e-6) / 32767
    pos = np.round(mm / scale).astype("<i2").tobytes()
    pos += b"\0" * (-len(pos) % 4)
    idx = np.asarray(faces).astype("<u2" if len(verts) < 65536 else "<u4").tobytes()
    head = np.array([len(verts), len(faces)], "<u4").tobytes() + np.array([scale], "<f4").tobytes()
    return head + pos + idx


def conveyor_constants():
    """The virtual sorting machine's sizes, read from sorter/conveyor.py itself (importing it would
    need MuJoCo, which the website build doesn't install)."""
    import ast
    tree = ast.parse((Path(__file__).parent / "sorter" / "conveyor.py").read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            names = node.targets[0]
            names = [n.id for n in names.elts] if isinstance(names, ast.Tuple) else [getattr(names, "id", None)]
            try:
                values = ast.literal_eval(node.value)
            except ValueError:
                continue
            values = values if len(names) > 1 else [values]
            out.update({n: v for n, v in zip(names, values) if n})
    return out


def machine_settings():
    """The desktop's built-in sorting machine (default machine setup), for the website."""
    from . import belts, machine_setup
    conveyor = type("Conveyor", (), conveyor_constants())
    machine_setup.use(dict(machine_setup.DEFAULTS))   # the built-in machine, not this computer's set-up
    bl = conveyor.BELT_HALF_LEN
    belt = belts.spec(BELT)
    return {
        "belt_half_len": bl, "belt_half_width": conveyor.BELT_HALF_WIDTH, "belt_slide": conveyor.BELT_SLIDE,
        "camera_height": machine_setup.camera_height(), "fovy": conveyor.FOVY, "machine_camera": conveyor.CAM_RES,
        "speed": 0.22, "spacing_min": conveyor.SPACING_MIN, "spacing_extra": conveyor.SPACING_EXTRA,
        "pool": conveyor.POOL - 2, "refresh_after": conveyor.REFRESH_AFTER,
        "belt": {"name": BELT, "span": belt["span"], "specular": belt["specular"], "shininess": belt["shininess"],
                 "rgb": list(belt["rgb"])},
        "lamps": [{"pos": [round(float(v), 4) for v in p], "power": round(float(power), 4),
                   "rgb": [round(float(v), 4) for v in c]}
                  for p, power, c in machine_setup.lamps(spread=bl * 0.6)],
    }


def belt_tile(out):
    """belt.png: the belt picture as 2 x 2 copies (as conveyor._tile does)."""
    from PIL import Image

    from . import belts
    img = Image.open(belts.path(BELT)).convert("RGB")
    w, h = img.size
    tile = Image.new("RGB", (2 * w, 2 * h))
    for x, y in ((0, 0), (w, 0), (0, h), (w, h)):
        tile.paste(img, (x, y))
    tile.save(out / "belt.png")


def export(out, labels_file, lib=None, others=None, colours_of=None, colour_table=None, settings=None,
           max_extra=MAX_EXTRA, seed=7):
    """others: [{id, name, category}] of other LEGO parts (default: catalog.all_lego_parts);
    colours_of(part) -> (colour ids, weights) (default: catalog.real_colors);
    colour_table: {id: (name, rgb)} (default: catalog.colors(include_trans=True))."""
    from . import catalog
    out = Path(out)
    (out / "parts").mkdir(parents=True, exist_ok=True)
    lib = lib or Library()
    labels = json.loads(Path(labels_file).read_text(encoding="utf-8")) if labels_file else {"parts": []}
    known = [p for p in labels["parts"] if p["id"] not in (catalog.NOT_LEGO, catalog.MULTIPLE)]
    known_ids = {p["id"] for p in known}
    if others is None:
        others = catalog.all_lego_parts(lib)
    if colour_table is None:
        colour_table = catalog.colors(include_trans=True)
    if colours_of is None:
        def colours_of(p):
            return catalog.real_colors(p, colour_table)
    extra = [p for p in others if p["id"] not in known_ids]
    random.Random(seed).shuffle(extra)

    files, index, size = {}, {}, 0

    def model_file(pid, belt=False):
        """The part's .bin (made once); None if there's no usable model (or, for the belt, it's too big)."""
        nonlocal size
        name = ldraw_name(lib, pid)
        if name is None:
            return None
        if name not in files:
            files[name] = None
            try:
                v, f = lib.part_mesh(name)
            except Exception:
                return None
            if len(f) <= MAX_TRIANGLES:
                data = encode(v, f)
                (out / "parts" / f"{name}.bin").write_bytes(data)
                size += len(data)
                files[name] = (f"{name}.bin", float((v.max(0) - v.min(0)).max()))
        if files[name] is None or (belt and files[name][1] > MAX_PIECE):
            return None
        return files[name][0]

    belt_parts, used_colours = [], set()

    def add(p, is_known):
        file = model_file(p["id"])
        if file:
            index[p["id"]] = file
        if not file or not model_file(p["id"], belt=True):
            return False
        ids, w = colours_of(p)
        colours = [[int(c), round(float(x), 4)] for c, x in zip(ids, w) if c in colour_table]
        if not colours:
            return False
        used_colours.update(c for c, _ in colours)
        belt_parts.append({"id": p["id"], "name": p.get("name", ""), "category": p.get("category", ""),
                           "known": is_known, "file": file, "colours": colours})
        return True

    for p in known:
        add(p, True)
    n_extra = 0
    for p in extra:
        if n_extra >= max_extra:
            break
        n_extra += add(p, False)

    (out / "parts" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    catalogue = {"parts": belt_parts,
                 "colours": {str(c): [colour_table[c][0], list(colour_table[c][1])] for c in sorted(used_colours)},
                 "machine": settings if settings is not None else machine_settings()}
    (out / "catalogue.json").write_text(json.dumps(catalogue), encoding="utf-8")
    if settings is None:
        belt_tile(out)
    n_known = sum(p["known"] for p in belt_parts)
    print(f"Wrote {len(belt_parts)} belt parts ({n_known} the model knows) and 3D models of {len(index)} "
          f"part numbers to {out} ({size / 1e6:.1f} MB)")
    return catalogue


if __name__ == "__main__":
    export(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
