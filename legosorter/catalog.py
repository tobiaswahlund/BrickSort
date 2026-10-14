"""Download the free Rebrickable tables + LDraw library and pick the parts to learn.

Run:  python -m legosorter.catalog [how_many_parts]
"""
import csv
import gzip
import io
import json
import re
import sys
import urllib.request
from collections import Counter

from . import config
from .junk import NOT_LEGO

# Rebrickable categories that aren't plain, solid pieces we can sort by shape
SKIP_CATEGORY_WORDS = ("sticker", "minifig", "duplo", "non-lego", "string", "flex",
                       "baseplate", "technic panels", "mechanical", "electronics",
                       "znap", "clikits", "belville", "scala", "quatro", "modulex",
                       "large buildable", "hinges, ")


def download(name, dest):
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {name} ...", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(config.URLS[name], headers={"User-Agent": "LegoSorter/0.1"})
    # timeout: give up on a stalled connection instead of hanging forever (seconds per read)
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    return dest


def read_csv(name):
    path = download(name, config.DOWNLOADS / f"{name}.csv.gz")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def colors(include_trans=False):
    """Rebrickable colors as {id: (name, (r,g,b))}. Solid colours only, unless include_trans
    (needed when you label photos of see-through pieces like Trans-Clear windscreens)."""
    out = {}
    for row in read_csv("colors"):
        if int(row["id"]) < 0 or (not include_trans and row.get("is_trans") in ("True", "t", "1")):
            continue
        rgb = row["rgb"]
        out[int(row["id"])] = (row["name"], tuple(int(rgb[i:i + 2], 16) for i in (0, 2, 4)))
    return out


# Rebrickable relationship types that mean "practically the same piece"
TWIN_TYPES = {"M": "mold variant", "A": "alternate"}


def twins():
    """{part: [(other part, kind)]} for mold variants / alternates (e.g. 30360 <-> 93168).

    Your labels stay the exact part number; this is only used to show look-alikes
    next to a guess and to put near-twins in the same sorting bin.
    """
    out = {}
    for row in read_csv("part_relationships"):
        kind = TWIN_TYPES.get(row["rel_type"])
        if kind:
            a, b = row["child_part_num"], row["parent_part_num"]
            out.setdefault(a, []).append((b, kind))
            out.setdefault(b, []).append((a, kind))
    return out


_bases = None


def base_part(part_num):
    """Printed/patterned version -> the plain part (e.g. a printed head -> plain head).

    We sort by shape and plastic colour only, so prints are treated as their base part.
    """
    global _bases
    if _bases is None:
        _bases = {r["child_part_num"]: r["parent_part_num"] for r in read_csv("part_relationships")
                  if r["rel_type"] in ("P", "T")}
    seen = set()
    while part_num in _bases and part_num not in seen:
        seen.add(part_num)
        part_num = _bases[part_num]
    # Not listed? Printed parts are named <base>pr0123 / pat / px, so strip that
    part_num = re.sub(r"(pr|pat|px)\d.*$", "", part_num) or part_num
    # Same shape as a part that has a 3D model (your choice): learn them as that part
    for pattern, model in MODEL_ALIASES:
        if re.fullmatch(pattern, part_num):
            return model
    return part_num


# Parts without their own LDraw 3D model that have the same shape as one that does.
# 970cNN = minifig hips and legs in colour NN (Rebrickable numbers the colours), all one shape.
MODEL_ALIASES = [
    (r"4079b", "4079"),        # Seat 2 x 2 with centre sprue mark -> Seat 2 x 2
    (r"970c\d+", "970c00"),    # Minifig hips and legs (any colour) -> hips and legs
    # mould variants that look the same from outside (found in the photo folders)
    (r"30237b", "30237"),      # Brick 1 x 2 with vertical clip, open O clip
    (r"30361c", "30361a"),     # Robot body 2 x 2 x 2 with axle holder
    (r"57909b", "57909"),      # Technic brick 2 x 2 with ball, 6 holes in ball
    (r"98560", "3684"),        # Slope 75 2 x 2 x 3, solid studs
    (r"35328", "21849"),       # Windscreen 8 x 4 x 2, hollow studs
    (r"3245", "3245b"),        # Brick 1 x 2 x 2
    (r"35336(_4176)?", "4176"),  # Windscreen 2 x 6 x 2, thin top (+ the folder holding both versions)
]


# Colours that look (nearly) the same: counted as one colour when guessing and sorting.
# Mostly LEGO's old and new versions of a colour. The first name is the one shown.
COLOUR_TWINS = [
    ["Light Bluish Gray", "Light Gray"],
    ["Dark Bluish Gray", "Dark Gray"],
    ["Very Light Bluish Gray", "Very Light Gray"],
    ["White", "Milky White"],
    ["Light Aqua", "Aqua"],
    ["Lavender", "Light Violet"],
    ["Yellowish Green", "Light Lime"],
]
_TWIN_NAME = {n.lower(): g[0] for g in COLOUR_TWINS for n in g}


def same_colour(name):
    """The name a colour is counted as: 'Light Gray' -> 'Light Bluish Gray' (see COLOUR_TWINS)."""
    return _TWIN_NAME.get((name or "").lower(), name)


def same_colour_ids(table):
    """{colour id: id it's counted as} for the colour table (id -> (name, rgb))."""
    by_name = {n: cid for cid, (n, _) in table.items()}
    return {cid: by_name.get(same_colour(n), cid) for cid, (n, _) in table.items()}


def same_piece(a, b):
    """Same piece, ignoring the version letter/suffix: 12002 and 12002b, 3062a and 3062b count as the same."""
    if a == b:
        return True
    ma, mb = re.match(r"\d+", a or ""), re.match(r"\d+", b or "")
    return bool(ma and mb and ma.group() == mb.group())


def sort_groups(twin_map):
    """{part: bin name}: near-twins share a bin, named after the lowest part number in the group."""
    group = {}
    for start in twin_map:
        if start in group:
            continue
        members, todo = set(), [start]
        while todo:
            p = todo.pop()
            if p not in members:
                members.add(p)
                todo += [o for o, _ in twin_map.get(p, [])]
        name = min(members, key=lambda s: (len(s), s))
        group.update({m: name for m in members})
    return group


SEPARATOR = "───────────────"


def color_choices(top=25):
    """Colour names for dropdowns: the most used colours first (by how many pieces Rebrickable
    lists in each), then a line, then all the others A–Z. Transparent colours included."""
    cache = config.BIG_DIR / "color_popularity.json"
    if cache.exists():
        counts = {int(k): v for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
    else:
        counts = Counter()
        for row in read_csv("inventory_parts"):
            counts[int(row["color_id"])] += int(row["quantity"])
        cache.write_text(json.dumps(counts), encoding="utf-8")
    table = colors(include_trans=True)
    ranked = sorted(table, key=lambda c: -counts.get(c, 0))
    first = [table[c][0] for c in ranked[:top]]
    rest = sorted(table[c][0] for c in ranked[top:])
    return ["Unknown"] + first + [SEPARATOR] + rest


def _norm(name):
    return re.sub(r"[\s_\-]+", " ", name).strip().lower()


def color_by_name(table=None):
    """{normalised colour name: colour id}, for reading my_photos/<part>/<colour>/ folders."""
    table = table or colors(include_trans=True)
    return {_norm(name): cid for cid, (name, _) in table.items()}


def find_color(folder_name, by_name):
    """Colour id of a folder name. Two-colour combos ("White + Light Bluish Gray") count as the first colour."""
    return by_name.get(_norm(folder_name.split("+")[0]))


def build(top_n=config.TOP_N):
    from .ldraw import Library
    download("ldraw", config.LDRAW_ZIP)
    lib = Library()

    cats = {r["id"]: r["name"].lower() for r in read_csv("part_categories")}
    parts = {r["part_num"]: r for r in read_csv("parts")}

    print("Counting how common each part is ...", flush=True)
    count = Counter()
    color_count = {}
    for row in read_csv("inventory_parts"):
        q = int(row["quantity"])
        count[row["part_num"]] += q
        color_count.setdefault(row["part_num"], Counter())[int(row["color_id"])] += q

    chosen = []
    for part_num, _ in count.most_common():
        p = parts.get(part_num)
        if not p:
            continue
        cat = cats.get(p["part_cat_id"], "")
        if any(w in cat for w in SKIP_CATEGORY_WORDS):
            continue
        if re.search(r"(pr|pat|px)\d", part_num):
            continue  # printed variants: same shape as the plain part
        if not lib.has_part(part_num):
            continue
        try:
            v, f = lib.part_mesh(part_num)
        except ValueError:
            continue
        if len(f) < 4:
            continue
        common_colors = [c for c, _ in color_count[part_num].most_common(6)]
        chosen.append({"id": part_num, "name": p["name"], "category": cat,
                       "colors": common_colors})
        print(f"  {len(chosen):3d}. {part_num:10s} {p['name']}", flush=True)
        if len(chosen) >= top_n:
            break

    save_parts(chosen)
    print(f"Saved {len(chosen)} parts to {config.PARTS_FILE}")
    return chosen


# Categories that aren't loose system pieces a sorter would see
NO_CATEGORY_WORDS = ("sticker", "duplo", "non-buildable", "modulex", "belville", "clikits", "pen & watch",
                     "electronics", "ho scale", "non-system", "znap", "string", "large buildable",
                     "baseplates", "gear parts", "other", "minifigs", "minidoll")


def build_category_set(per_category=25, lib=None):
    """Extra parts, labelled only with their Rebrickable category, so the model learns what
    e.g. 'minifig accessories' look like in general, not only the parts it knows by number."""
    from .ldraw import Library
    lib = lib or Library()
    known = {p["id"] for p in json.loads(config.PARTS_FILE.read_text(encoding="utf-8"))}
    names, cats, part_colors = _rebrickable_info()
    by_cat = {}
    popular = sorted(part_colors, key=lambda p: -sum(part_colors[p].values()))
    for pid in popular:
        if pid not in names or pid in known or re.search(r"(pr|pat|px)\d", pid):
            continue
        cat = cats.get(names[pid][1], "")
        if not cat or any(w in cat for w in NO_CATEGORY_WORDS):
            continue
        if len(by_cat.setdefault(cat, [])) >= per_category or not lib.has_part(pid):
            continue
        try:
            v, f = lib.part_mesh(pid)
        except ValueError:
            continue
        if len(f) < 4 or (v.max(0) - v.min(0)).max() > 2.0:
            continue
        by_cat[cat].append({"id": pid, "name": names[pid][0], "category": cat,
                            "colors": [c for c, _ in part_colors[pid].most_common(6)]})
    extra = [p for ps in by_cat.values() for p in ps]
    config.CATEGORY_PARTS_FILE.write_text(json.dumps(extra, indent=1), encoding="utf-8")
    print(f"{len(extra)} extra parts in {len(by_cat)} categories saved to {config.CATEGORY_PARTS_FILE}")
    return extra


def all_lego_parts(lib=None):
    """Every plain Lego part that has an LDraw 3D model (for 'All pieces' on the virtual belt).
    Worked out once and saved in LegoSorterData/all_parts.json."""
    cache = config.BIG_DIR / "all_parts.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    from .ldraw import Library
    lib = lib or Library()
    names, cats, part_colors = _rebrickable_info()
    out = []
    for pid, (name, cat_id) in names.items():
        cat = cats.get(cat_id, "")
        if any(w in cat for w in NO_CATEGORY_WORDS) or re.search(r"(pr|pat|px)\d", pid):
            continue
        if not lib.has_part(pid):
            continue
        out.append({"id": pid, "name": name, "category": cat,
                    "colors": [c for c, _ in part_colors.get(pid, Counter()).most_common(6)]})
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def load_category_parts():
    f = config.CATEGORY_PARTS_FILE
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


MULTIPLE = "multiple"
SPECIAL = {NOT_LEGO: "Not a Lego piece", MULTIPLE: "Several pieces (touching or stuck)"}


def folder_part(name):
    """Which part a photo folder is for: my_photos/_not_lego, my_photos/_multiple, or a part number.
    Other folders starting with _ (like _to_cut) and 'unknown' aren't parts."""
    n = name.strip().lower()
    if n.lstrip("_") in (NOT_LEGO, "not lego", "notlego"):
        return NOT_LEGO
    if n.lstrip("_") == MULTIPLE:
        return MULTIPLE
    if n.startswith("_") or n == "unknown":
        return None
    if n.startswith("combo-"):
        from .custom import normalize
        return normalize(name.strip())
    return base_part(name.strip())


def _has_photos(folder):
    return folder.exists() and any(p.suffix.lower() in config.PHOTO_TYPES for p in folder.rglob("*"))


def load_parts():
    """Every piece the model learns: parts.json + your custom pieces and combos (custom_parts.json)
    + 'several pieces' once there are photos of that."""
    from . import custom
    parts = json.loads(config.PARTS_FILE.read_text(encoding="utf-8"))
    ids = {p["id"] for p in parts}
    for c in custom.load():
        if c["id"] not in ids:
            parts.append({**c, "colors": c.get("colors", []), "custom": True})
            ids.add(c["id"])
    if MULTIPLE not in ids and (_has_photos(config.MY_PHOTOS / "_multiple") or _has_photos(config.MY_PHOTOS / MULTIPLE)
                                or _has_photos(config.CORRECTIONS / MULTIPLE)):
        parts.append({"id": MULTIPLE, "name": SPECIAL[MULTIPLE], "category": "several pieces", "colors": [],
                      "custom": True})
    return parts


def save_parts(parts):
    """Write parts.json (custom pieces live in custom_parts.json, so they're left out here)."""
    plain = [p for p in parts if not p.get("custom")]
    config.PARTS_FILE.write_text(json.dumps(plain, indent=1), encoding="utf-8")


def _rebrickable_info():
    """Name + category of every part, and which colours each part is most often made in."""
    names = {r["part_num"]: (r["name"], r["part_cat_id"]) for r in read_csv("parts")}
    cats = {r["id"]: r["name"].lower() for r in read_csv("part_categories")}
    part_colors = {}
    for row in read_csv("inventory_parts"):
        part_colors.setdefault(row["part_num"], Counter())[int(row["color_id"])] += int(row["quantity"])
    return names, cats, part_colors


def add_parts_from_folders(lib, log=print):
    """Parts you've photographed (my_photos/<id>) or corrected that the model doesn't know yet get added."""
    parts = load_parts()
    if not any(p["id"] == NOT_LEGO for p in parts):  # the "this isn't Lego at all" class
        parts.append({"id": NOT_LEGO, "name": "Not a Lego piece", "category": "not lego", "colors": []})
        save_parts(parts)
    known = {p["id"] for p in parts}
    added = []
    for root in (config.MY_PHOTOS, config.CORRECTIONS):
        if not root.exists():
            continue
        for folder in sorted(root.iterdir()):
            pid = folder_part(folder.name) if folder.is_dir() else None
            if pid is None or pid in known:
                continue
            entry = {"id": pid, "name": "", "category": "added by you", "colors": []}
            if not lib.has_part(pid):  # no 3D model: learned from the photos alone (no renders)
                if not _has_photos(folder):
                    continue
                entry["photos_only"] = True
                log(f"  Folder '{folder.name}': no 3D model, so it's learned from your photos only.")
            parts.append(entry)
            known.add(pid)
            added.append(pid)

    # Fill in Rebrickable's name, category and usual colours for parts you added
    todo = [p for p in parts if p.get("category") == "added by you"]
    if todo:
        names, cats, part_colors = _rebrickable_info()
        for p in todo:
            name, cat = names.get(p["id"], (None, None))
            p["name"] = name or p["name"] or lib.title(p["id"]) or p["id"]
            p["category"] = cats.get(cat, "not on Rebrickable")
            p["colors"] = [c for c, _ in part_colors.get(p["id"], Counter()).most_common(6)]
        save_parts(parts)
    if added:
        log(f"Added {len(added)} parts from your folders: {', '.join(added)}")
    return parts


if __name__ == "__main__":
    if sys.argv[1:2] == ["categories"]:
        build_category_set(int(sys.argv[2]) if len(sys.argv) > 2 else 25)
    else:
        build(int(sys.argv[1]) if len(sys.argv) > 1 else config.TOP_N)
