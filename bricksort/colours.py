"""Group LEGO's ~270 colour names into main colours (Red, Blue, ...) for choosing them in lists.

family("Dark Bluish Gray") -> "Gray", shade("Dark Bluish Gray") -> "Dark".
The main colour comes from the last colour word in the name ("Reddish Brown" is a brown,
"Yellowish Green" a green). Transparent, metallic and other special finishes, and colours of other
LEGO product lines (Duplo, Modulex, ...), get groups of their own.
"""
import colorsys

FAMILIES = ["Black", "White", "Gray", "Red", "Orange", "Yellow", "Green", "Blue", "Purple", "Pink", "Brown",
            "Tan and beige", "Transparent", "Metallic and special", "Other product lines"]
SHADES = ["Light", "Medium", "Dark"]

WORDS = {
    "black": "Black", "white": "White", "milky": "White", "gray": "Gray", "grey": "Gray",
    "red": "Red", "rust": "Red", "terracotta": "Red",
    "orange": "Orange", "coral": "Orange",
    "yellow": "Yellow", "lemon": "Yellow", "curry": "Yellow",
    "green": "Green", "lime": "Green", "olive": "Green",
    "blue": "Blue", "azure": "Blue", "aqua": "Blue", "turquoise": "Blue", "cyan": "Blue", "teal": "Blue",
    "purple": "Purple", "violet": "Purple", "lavender": "Purple", "lilac": "Purple",
    "pink": "Pink", "magenta": "Pink", "salmon": "Pink", "rose": "Pink",
    "brown": "Brown", "umber": "Brown", "sienna": "Brown",
    "tan": "Tan and beige", "nougat": "Tan and beige", "beige": "Tan and beige", "buff": "Tan and beige",
}
SPECIAL = ("chrome", "metallic", "metal", "pearl", "copper", "gold", "silver", "glitter", "speckle", "glow",
           "two-tone", "titanium", "flat ")
OTHER_LINES = ("duplo", "modulex", "ho ", "fabuland", "clikits", "vintage")
LIGHT = ("light", "very", "pastel", "pale", "sky", "bright light")
DARK = ("dark", "earth")


def _base_family(name, rgb=None):
    words = name.lower().replace("-", " ").split()
    for w in reversed(words):
        if w in WORDS:
            return WORDS[w]
    if rgb is None:
        return "Other"
    h, light, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    if s < 0.15:
        return "Black" if light < 0.2 else "White" if light > 0.85 else "Gray"
    hue = h * 360
    for limit, fam in ((15, "Red"), (45, "Orange"), (70, "Yellow"), (170, "Green"), (260, "Blue"),
                       (300, "Purple"), (345, "Pink"), (360, "Red")):
        if hue < limit:
            return fam
    return "Red"


def family(name, rgb=None):
    low = name.lower()
    if low.startswith(OTHER_LINES):
        return "Other product lines"
    if "trans" in low:
        return "Transparent"
    if any(s in low for s in SPECIAL):
        return "Metallic and special"
    return _base_family(name, rgb)


def subgroup(name, rgb=None):
    """Second level: for transparent colours their main colour, otherwise Light / Medium / Dark."""
    low = name.lower()
    if family(name, rgb) == "Transparent":
        rest = low.replace("glitter", "").replace("opal", "").replace("trans", "")
        return "Clear" if "clear" in rest else _base_family(rest, rgb)
    if any(w in low for w in DARK):
        return "Dark"
    if any(w in low.split() or low.startswith(w) for w in LIGHT):
        return "Light"
    return "Medium"


def grouped(colour_table, order=None):
    """{family: {subgroup or "": [colour names]}} for {id: (name, rgb)}. Families with only a few
    colours aren't split further (subgroup ""). order: names in the order to list them (most used first)."""
    rank = {n: i for i, n in enumerate(order or [])}
    rgb = {n: c for n, c in colour_table.values() if not n.startswith("[")}
    out = {}
    for name in sorted(rgb, key=lambda n: (rank.get(n, len(rank)), n)):
        out.setdefault(family(name, rgb[name]), []).append(name)
    result = {}
    for fam in FAMILIES + sorted(set(out) - set(FAMILIES)):
        names = out.get(fam, [])
        if not names:
            continue
        if len(names) <= 8 or fam in ("Metallic and special", "Other product lines"):
            result[fam] = {"": names}
        else:
            subs = {}
            for n in names:
                subs.setdefault(subgroup(n, rgb[n]), []).append(n)
            keys = [s for s in SHADES if s in subs] + sorted(set(subs) - set(SHADES))
            result[fam] = {s: subs[s] for s in keys}
    return result
