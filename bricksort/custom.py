"""Your own pieces: things Rebrickable doesn't have, and pieces you want treated as one.

Stored in custom_parts.json (you can edit it, or use the buttons in the demo):

  {"id": "custom-0001", "kind": "custom", "name": "Minifig helmet, printed (third-party)",
   "category": "minifig headwear", "tags": ["helmet", "third-party"]}

  {"id": "combo-4592+4593", "kind": "combo", "parts": ["4592", "4593"],
   "name": "Hinge lever, assembled", "category": "hinges, arms and turntables", "tags": []}

They have no 3D model, so the model learns them from your photos only:
put photos in my_photos/<id>/<colour>/ like any other piece. The category
also teaches the model's category answer, and tags can be used in bins.json.
"""
import json

from . import config

FILE = config.PROJECT_DIR / "custom_parts.json"


def load():
    """Your custom pieces; a combo entered twice (e.g. 3680+3679 and 3679+3680) counts once."""
    items = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else []
    out, seen = [], set()
    for p in items:
        if p.get("kind") == "combo" or p["id"].startswith("combo-"):
            p = {**p, "id": normalize(p["id"])}
        if p["id"] not in seen:
            seen.add(p["id"])
            out.append(p)
    return out


def normalize(pid):
    """combo-3680+combo-3679 -> combo-3679+3680 (combos of combos are flattened, order doesn't matter)."""
    if not pid.startswith("combo-"):
        return pid
    parts = []
    for x in pid[len("combo-"):].split("+"):
        x = x.strip()
        parts += normalize(x)[len("combo-"):].split("+") if x.startswith("combo-") else [x]
    return combo_id(parts)


def save(items):
    FILE.write_text(json.dumps(items, indent=1), encoding="utf-8")


def next_id():
    used = {p["id"] for p in load()}
    n = 1
    while f"custom-{n:04d}" in used:
        n += 1
    return f"custom-{n:04d}"


def add(entry):
    items = [p for p in load() if p["id"] != entry["id"]]
    entry["category"] = entry.get("category", "").strip().lower()
    entry["tags"] = [t.strip().lower() for t in entry.get("tags", []) if t.strip()]
    items.append(entry)
    save(items)
    return entry


def combo_id(parts):
    flat = []
    for p in parts:
        p = p.strip()
        flat += p[len("combo-"):].split("+") if p.startswith("combo-") else [p]
    return "combo-" + "+".join(sorted(set(x.strip() for x in flat if x.strip())))
