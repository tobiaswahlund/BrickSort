"""Facts about each part that bin rules can use, worked out from the data we already have.

- name, category, look-alike group: from Rebrickable
- length/width in studs, height in plates, flat or not: measured on the LDraw 3D model

Measured once and cached in part_properties.json. Add a new property here and
it becomes usable in bins.json.
"""
import json

from .. import catalog, config
from ..junk import NOT_LEGO
from ..ldraw import SCALE

CACHE = config.PROJECT_DIR / "part_properties.json"
LDU_PER_STUD, LDU_PER_PLATE = 20, 8


def measure(lib, part_id):
    verts, _ = lib.part_mesh(part_id)
    ext = (verts.max(0) - verts.min(0)) / SCALE  # back to LDraw units
    length, width = sorted(map(float, ext[:2]), reverse=True)
    height = float(ext[2])
    return {
        "length": round(length / LDU_PER_STUD * 2) / 2,   # studs, to the nearest half
        "width": round(width / LDU_PER_STUD * 2) / 2,
        "height": round(height / LDU_PER_PLATE, 1),        # plates, including any studs on top
        # plates and tiles: one plate thick (+ studs). Bricks are 3 plates.
        "flat": bool(height <= LDU_PER_PLATE + 4.5),
    }


def load_all(lib=None):
    """{part_id: {name, category, group, length, width, height, flat}}"""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    bins = catalog.sort_groups(catalog.twins())
    changed = False
    out = {}
    for p in catalog.load_parts():
        pid = p["id"]
        # an empty entry is a failed measurement from an older version: try again
        # (custom and photos-only pieces have no 3D model, so nothing to measure)
        if not cache.get(pid) and pid != NOT_LEGO and not p.get("custom") and not p.get("photos_only"):
            if lib is None:
                from ..ldraw import Library
                lib = Library()
            try:
                cache[pid] = measure(lib, pid)
                changed = True
            except Exception as e:
                # not cached, so it's tried again next time (e.g. after the 3D library is updated);
                # until then size and "flat" rules can't match this part
                print(f"Could not measure part {pid} ({type(e).__name__}: {e}); size rules will skip it.")
                if pid in cache:
                    del cache[pid]
                    changed = True
        out[pid] = {"name": p["name"], "category": p.get("category", ""), "group": bins.get(pid, pid),
                    "tags": p.get("tags", []), **cache.get(pid, {})}
    if changed:
        CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return out
