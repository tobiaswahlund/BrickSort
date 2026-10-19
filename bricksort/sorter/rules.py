"""Which bin does a piece go to? Read from bins.json, which you can edit.

Each bin has a name and a "when" with any of these conditions (all must match):

  "part":        ["3001", "3626c"]     these part numbers (look-alikes count too)
  "category":    "minifig heads"       Rebrickable category contains this text (or a list of texts)
  "name":        "slope"               part name contains this text (or a list)
  "tag":         "helmet"              one of your own tags (custom pieces, custom_parts.json)
  "color":       ["Black", "Red"]      Rebrickable colour names
  "flat":        true / false          plates and tiles are flat; bricks aren't
  "printed":     true / false          the piece has a print on it (the model's printed yes/no answer)
  "min_length", "max_length"           longest side, in studs
  "min_width",  "max_width"            shortest side, in studs
  "min_height", "max_height"           height in plates (a brick is 3 plates, plus studs ~3.5)

Bins are checked top to bottom; the first match wins. "when": {} matches everything.
Pieces the camera or model isn't sure about go to the rest bin instead.
"""
import json

from .. import catalog, config

RULES_FILE = config.PROJECT_DIR / "bins.json"

DEFAULT = {
    "confidence_needed": 0.85,   # tested: about 0% wrong in real bins, 60% of pieces sorted (2026-10-19)
    "not_lego_bin": "Not Lego",
    "rest_bin": "Rest",
    "bins": [
        {"name": "Minifig heads", "when": {"category": "minifig heads"}},
        {"name": "Minifig handheld", "when": {"category": ["minifig accessories", "minifig shields, weapons"]}},
        {"name": "Flat black", "when": {"color": ["Black"], "flat": True}},
        {"name": "Technic", "when": {"category": "technic"}},
        {"name": "Long pieces", "when": {"min_length": 6}},
        {"name": "Red", "when": {"color": ["Red", "Dark Red"]}},
        {"name": "Other Lego", "when": {}},
    ],
}


def load():
    if not RULES_FILE.exists():
        RULES_FILE.write_text(json.dumps(DEFAULT, indent=2), encoding="utf-8")
    rules = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    for key, value in DEFAULT.items():
        rules.setdefault(key, value)
    return rules


def bin_names(rules):
    return [b["name"] for b in rules["bins"]] + [rules["not_lego_bin"], rules["rest_bin"]]


def _texts(v):
    return [v.lower()] if isinstance(v, str) else [x.lower() for x in v]


def describe(when):
    """A bin's "when" in plain words, e.g. {"color": ["Black"], "flat": True} -> "Black, flat"."""
    if not when:
        return "any other LEGO piece"
    one_of = lambda v: v if isinstance(v, str) else " or ".join(map(str, v))
    words = {
        "part": lambda v: f"part {one_of(v)}",
        "category": lambda v: f"category: {one_of(v)}",
        "name": lambda v: f"name contains {one_of(v)}",
        "tag": lambda v: f"tag: {one_of(v)}",
        "color": one_of,
        "flat": lambda v: "flat" if v else "not flat",
        "printed": lambda v: "printed" if v else "not printed",
        "min_length": lambda v: f"at least {v} studs long",
        "max_length": lambda v: f"at most {v} studs long",
        "min_width": lambda v: f"at least {v} studs wide",
        "max_width": lambda v: f"at most {v} studs wide",
        "min_height": lambda v: f"at least {v} plates high",
        "max_height": lambda v: f"at most {v} plates high",
    }
    return ", ".join(words.get(k, lambda v, k=k: f"{k}: {v}")(v) for k, v in when.items())


def matches(when, part_id, color_name, props, printed=None):
    """printed: the model's chance (0..1) that the piece has a print; None if unknown."""
    p = props.get(part_id, {})
    for key, want in when.items():
        if key == "printed":
            if printed is None or (printed >= 0.5) != bool(want):
                return False
        elif key == "part":
            ids = {str(x) for x in (want if isinstance(want, list) else [want])}
            if part_id not in ids and p.get("group") not in ids:
                return False
        elif key == "tag":  # your own tags on custom pieces, e.g. "helmet"
            if not set(_texts(want)) & {t.lower() for t in p.get("tags", [])}:
                return False
        elif key in ("category", "name"):
            have = p.get(key, "").lower()
            if not any(t in have for t in _texts(want)):
                return False
        elif key == "color":  # look-alike colours (Light Gray / Light Bluish Gray) count as the same
            if catalog.same_colour(color_name or "").lower() not in {catalog.same_colour(t).lower() for t in _texts(want)}:
                return False
        elif key == "flat":
            if p.get("flat") is None or bool(p["flat"]) != bool(want):
                return False
        elif key.startswith(("min_", "max_")):
            value = p.get(key[4:])
            if value is None:
                return False
            if key.startswith("min_") and value < want or key.startswith("max_") and value > want:
                return False
        else:
            raise ValueError(f"bins.json: unknown condition '{key}'")
    return True


def uses_color(when):
    return "color" in when


def bin_need(rules, b):
    """How sure the model must be for this bin: its own "confidence", or the general one."""
    return b.get("confidence", rules["confidence_needed"])


def _by_category(rules, category, category_conf, color_name, color_conf):
    """Part number unsure, but the category is clear: only bins that ask for just a category
    (and maybe a colour) can be used, e.g. all minifig accessories in one bin.
    Bins are checked top to bottom, so a bin above it that the piece might belong in (one that asks
    about its shape, which isn't known without the part) means rest bin: the category bin could be
    the wrong one. E.g. a black Technic axle belongs in 'Flat black' if that comes before 'Technic'."""
    if not category:
        return None
    sure_colour = color_conf >= rules["confidence_needed"]
    for b in rules["bins"]:
        when = b["when"]
        need = bin_need(rules, b)
        if "category" not in when or set(when) - {"category", "color"}:
            if _might_match(when, category, color_name, sure_colour):
                return None
            continue
        if not any(t in category.lower() for t in _texts(when["category"])):
            continue
        if category_conf < need:
            continue
        if "color" in when:
            if color_conf < need:
                return rules["rest_bin"], f"a {category} piece, but only {color_conf:.0%} sure it's {color_name}"
            if catalog.same_colour(color_name or "").lower() not in {catalog.same_colour(t).lower() for t in _texts(when["color"])}:
                continue
        return b["name"], f"unknown part, but {category_conf:.0%} sure it's a {category} piece"
    return None


def _might_match(when, category, color_name, sure_colour):
    """Could a piece of this category (and colour, if sure) belong in a bin with these conditions?
    Conditions about the part itself (its shape, number, name...) can't be ruled out."""
    if "category" in when and not any(t in category.lower() for t in _texts(when["category"])):
        return False
    if "color" in when and sure_colour and catalog.same_colour(color_name or "").lower() not in {
            catalog.same_colour(t).lower() for t in _texts(when["color"])}:
        return False
    return True


def choose_bin(rules, props, part_id, part_conf, color_name, color_conf, n_objects,
               category=None, category_conf=0.0, printed=None):
    """Returns (bin name, reason). printed: chance (0..1) the piece has a print, None if unknown."""
    need = rules["confidence_needed"]
    if n_objects > 1:
        return rules["rest_bin"], f"{n_objects} objects seen at once"
    if part_id == "multiple":
        return rules["rest_bin"], f"looks like several pieces together ({part_conf:.0%} sure)"
    if part_id == "not_lego":
        if part_conf >= need:
            return rules["not_lego_bin"], f"not a Lego piece ({part_conf:.0%} sure)"
        return rules["rest_bin"], f"probably not Lego, but only {part_conf:.0%} sure"
    # a bin may ask for less than the general level, so the part check uses the lowest of them
    lowest = min([need] + [bin_need(rules, b) for b in rules["bins"]])
    if part_conf < lowest:
        by_cat = _by_category(rules, category, category_conf, color_name, color_conf)
        if by_cat:
            return by_cat
        return rules["rest_bin"], f"only {part_conf:.0%} sure it's {part_id} (needs {lowest:.0%})"
    for b in rules["bins"]:
        shape_rules = {k: v for k, v in b["when"].items() if k not in ("color", "printed")}
        if not matches(shape_rules, part_id, color_name, props):
            continue
        need = bin_need(rules, b)
        if uses_color(b["when"]) and not matches({"color": b["when"]["color"]}, part_id, color_name, props) \
                and color_conf >= min(need, rules["confidence_needed"]):
            continue   # clearly another colour: this bin is out, whatever it asks for
        if part_conf < need:   # it would go here, but this bin asks for more: set it aside, don't guess
            return rules["rest_bin"], f"only {part_conf:.0%} sure it's {part_id} ('{b['name']}' needs {need:.0%})"
        if "printed" in b["when"]:
            # same idea as colour: unsure whether there's a print -> rest bin, not a wrong bin
            if printed is None or need > max(printed, 1 - printed):
                sure = "unknown" if printed is None else f"{max(printed, 1 - printed):.0%}"
                return rules["rest_bin"], f"{part_id}, but not sure whether it has a print ({sure})"
            if not matches({"printed": b["when"]["printed"]}, part_id, color_name, props, printed):
                continue
        if uses_color(b["when"]):
            # The shape fits a colour bin: we must be sure of the colour either way,
            # or a black piece misread as grey would end up in the wrong bin
            if color_conf < need:
                return rules["rest_bin"], f"{part_id}, but only {color_conf:.0%} sure it's {color_name}"
            if not matches({"color": b["when"]["color"]}, part_id, color_name, props):
                continue
        return b["name"], f"{part_id} {color_name} ({part_conf:.0%} sure)"
    return rules["rest_bin"], f"{part_id} {color_name} matches no bin"
