"""Subtle wear on the 3D pieces themselves (instead of painting smudges on the picture).

What real used Lego looks like (from sellers' condition guides and collector forums):
  - hairline scratches and scuffs are by far the most common; they look slightly lighter
  - dust specks
  - a slight loss of shine ("cloudy"), on well-played parts
  - small dents / tooth marks, much rarer
  - yellowing of old white, light grey and blue parts (UV / ageing of the plastic)

Each piece gets a random wear level: mostly like-new or lightly played, sometimes medium.
Dents are pressed into the 3D shape; scratches and dust are a texture wrapped on the piece,
so they're lit and shaded by the lamps like the rest of the plastic.

The amounts are kept in WEAR_LEVELS so they can be tuned to match your real photos.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

STUD = 0.08            # one stud in world units
TEX = 512              # wear texture size (pixels)
TEX_SPAN = 0.32        # world units covered by one copy of the texture (4 studs)

# chance, scratches, dust specks, dents, how much shine is lost
WEAR_LEVELS = {
    "like new": dict(p=0.45, scratches=(0, 4), dust=(0, 15), dents=(0, 0), dull=(0.0, 0.1)),
    "light":    dict(p=0.38, scratches=(3, 12), dust=(10, 40), dents=(0, 1), dull=(0.05, 0.25)),
    "medium":   dict(p=0.17, scratches=(10, 30), dust=(25, 80), dents=(1, 3), dull=(0.2, 0.45)),
}
YELLOWING = 0.25       # share of white / light grey / blue pieces that are a bit yellowed
TEXTURE_BASE = 0.92    # the plastic colour is divided by this so scratches can be a little lighter


def pick_level(rng):
    names = list(WEAR_LEVELS)
    return names[rng.choice(len(names), p=[WEAR_LEVELS[n]["p"] for n in names])]


def _normals(verts, faces):
    n = np.zeros_like(verts)
    fn = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
    for k in range(3):
        np.add.at(n, faces[:, k], fn)
    return n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)


def subdivide(verts, faces, max_edge=STUD / 3, rounds=3):
    """Split big triangles so a dent in a flat face has points to push in."""
    verts = list(map(tuple, verts))
    for _ in range(rounds):
        index = {v: i for i, v in enumerate(verts)}
        new_faces, changed = [], False
        V = np.array(verts)
        for a, b, c in faces:
            edges = [np.linalg.norm(V[a] - V[b]), np.linalg.norm(V[b] - V[c]), np.linalg.norm(V[c] - V[a])]
            if max(edges) <= max_edge:
                new_faces.append((a, b, c))
                continue
            changed = True
            mids = []
            for p, q in ((a, b), (b, c), (c, a)):
                m = tuple((V[p] + V[q]) / 2)
                if m not in index:
                    index[m] = len(verts)
                    verts.append(m)
                mids.append(index[m])
            ab, bc, ca = mids
            new_faces += [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]
        faces = np.array(new_faces)
        if not changed or len(faces) > 120000:
            break
    return np.array(verts), np.asarray(faces, np.int32)


def dent(verts, faces, rng, count):
    """Press `count` small dents (like tooth or impact marks) into the shape."""
    if count <= 0:
        return verts
    verts = verts.copy()
    normals = _normals(verts, faces)
    for _ in range(count):
        c = rng.integers(len(verts))
        radius = rng.uniform(0.12, 0.3) * STUD
        depth = rng.uniform(0.04, 0.12) * STUD
        d = np.linalg.norm(verts - verts[c], axis=1)
        near = d < radius
        verts[near] -= normals[c] * (depth * (1 - (d[near] / radius) ** 2))[:, None]
    return verts


def texcoords(verts, faces):
    """Wrap the texture around the piece like a box (each point uses its main facing direction)."""
    n = _normals(verts, faces)
    axis = np.abs(n).argmax(1)
    uv = np.empty((len(verts), 2))
    for a, (i, j) in enumerate(((1, 2), (0, 2), (0, 1))):
        sel = axis == a
        uv[sel] = verts[sel][:, [i, j]] / TEX_SPAN
    return uv


def texture(rng, level, path):
    """Scratches (slightly lighter thin lines), scuffs and dust specks (darker), as a picture."""
    w = WEAR_LEVELS[level]
    base = int(255 * TEXTURE_BASE)
    img = Image.new("L", (TEX, TEX), base)
    draw = ImageDraw.Draw(img)
    for _ in range(rng.integers(*w["scratches"]) if w["scratches"][1] else 0):
        x, y = rng.uniform(0, TEX, 2)
        length, ang = rng.uniform(15, 120), rng.uniform(0, np.pi)
        # a hairline that may bend a little, like a real scratch
        pts = [(x, y)]
        for _ in range(4):
            ang += rng.normal(0, 0.15)
            x, y = x + np.cos(ang) * length / 4, y + np.sin(ang) * length / 4
            pts.append((x, y))
        draw.line(pts, fill=int(rng.uniform(base + 8, 255)), width=1)
    for _ in range(rng.integers(*w["dust"]) if w["dust"][1] else 0):
        x, y, r = *rng.uniform(0, TEX, 2), rng.uniform(0.6, 2.2)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=int(base * rng.uniform(0.6, 0.85)))
    if level != "like new" and rng.random() < 0.5:  # a scuffed patch
        x, y, r = *rng.uniform(0, TEX, 2), rng.uniform(15, 50)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=min(255, base + 6))
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    from . import plastic_look
    detail_rng = np.random.default_rng(rng.integers(1 << 31))   # drawn either way, so the switch changes nothing else
    if plastic_look.use_texture():   # real surface detail from your photos (machine setup)
        detail = plastic_look.surface_texture(detail_rng, TEX)
        a = np.asarray(img, np.float32) * (1 + plastic_look.TEXTURE_STRENGTH * (detail - 1))
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    Image.merge("RGB", [img] * 3).save(path)


def aged_colour(rgb, rng):
    """Old white / light grey / blue plastic sometimes turns a bit yellow."""
    r, g, b = rgb
    is_white_grey = min(rgb) > 140 and max(rgb) - min(rgb) < 30
    is_blue = b > r + 60 and b > g + 30
    if (is_white_grey or is_blue) and rng.random() < YELLOWING:
        k = rng.uniform(0.02, 0.08)
        return (r, g * (1 - k / 2), b * (1 - k * 1.6))
    return rgb


def dullness(level, rng):
    lo, hi = WEAR_LEVELS[level]["dull"]
    return rng.uniform(lo, hi)
