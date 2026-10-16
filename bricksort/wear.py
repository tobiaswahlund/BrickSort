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
DENT_RADIUS = (0.06, 0.15)  # in studs (a stud is 8 mm): a radius of about 0.5 to 1.2 mm
DENT_DEPTH = (0.01, 0.03)   # in studs: about 0.1 to 0.25 mm deep, like a tooth mark
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


def subdivide(verts, faces, max_edge=STUD / 3, rounds=3, near=None):
    """Split big triangles so a dent in a flat face has points to push in (near(point) -> bool: only
    edges whose middle is there; None: everywhere).

    Each long edge is split in the middle, and every triangle using that edge is split along with
    it (into 2, 3 or 4), so no corner ever sits in the middle of a neighbour's edge. Such a corner
    (a "T-junction") breaks the smooth shading of curved surfaces into stripes."""
    V = [np.asarray(v, float) for v in verts]
    index = {tuple(v): i for i, v in enumerate(V)}
    faces = [tuple(f) for f in np.asarray(faces)]

    def mid(p, q, mids):
        key = (min(p, q), max(p, q))
        if key not in mids:
            m = (V[p] + V[q]) / 2
            mids[key] = index.setdefault(tuple(m), len(V))
            if mids[key] == len(V):
                V.append(m)
        return mids[key]

    for _ in range(rounds):
        mids, out, changed = {}, [], False
        for a, b, c in faces:
            long = [np.linalg.norm(V[p] - V[q]) > max_edge and (near is None or near((V[p] + V[q]) / 2))
                    for p, q in ((a, b), (b, c), (c, a))]
            k = sum(long)
            if k == 0:
                out.append((a, b, c))
                continue
            changed = True
            # turn the triangle so its long edges come first: (a,b) long, then (b,c), then (c,a)
            while not long[0] or (k == 2 and not long[1]):
                a, b, c = b, c, a
                long = long[1:] + long[:1]
            if k == 1:
                ab = mid(a, b, mids)
                out += [(a, ab, c), (ab, b, c)]
            elif k == 2:
                ab, bc = mid(a, b, mids), mid(b, c, mids)
                out += [(ab, b, bc), (a, ab, bc), (a, bc, c)]
            else:
                ab, bc, ca = mid(a, b, mids), mid(b, c, mids), mid(c, a, mids)
                out += [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]
        faces = out
        if not changed or len(faces) > 120000:
            break
    return np.array(V), np.asarray(faces, np.int32)


def dents(verts, faces, rng, count):
    """Press `count` small dents (like tooth or impact marks) into the shape: (verts, faces).
    Only the surface around each dent is split into small triangles, so the rest of the piece keeps
    its own smooth shading."""
    if count <= 0:
        return verts, faces
    fn = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
    area = np.linalg.norm(fn, axis=1)
    picks = rng.choice(len(faces), size=count, p=area / area.sum())
    marks = []
    for k in picks:   # a random point on a face (bigger faces are hit more often), pushed in along it
        w = rng.dirichlet(np.ones(3))
        marks.append((w @ verts[faces[k]], fn[k] / (area[k] + 1e-12),
                      rng.uniform(*DENT_RADIUS) * STUD, rng.uniform(*DENT_DEPTH) * STUD))
    reach = STUD / 3
    v, f = subdivide(verts, faces, near=lambda p: any(np.linalg.norm(p - c) < r + reach for c, _, r, _ in marks))
    v = v.copy()
    for c, n, radius, depth in marks:
        d = np.linalg.norm(v - c, axis=1)
        hit = d < radius
        v[hit] -= n * (depth * (1 - (d[hit] / radius) ** 2))[:, None]
    return v, f


def shading(verts, faces, crease=35):
    """(verts, faces, normals) for smooth shading: round surfaces shade smoothly, while edges sharper
    than `crease` degrees stay sharp. A corner shared by faces on both sides of a sharp edge gets one
    copy per side, each with its own direction, so a box's edges don't shade darker."""
    fn = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
    unit = fn / (np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12)
    # each face counts by its angle at the corner, so how a side was cut into triangles doesn't matter
    angle = np.zeros(faces.shape)
    for c in range(3):
        e1 = verts[faces[:, (c + 1) % 3]] - verts[faces[:, c]]
        e2 = verts[faces[:, (c + 2) % 3]] - verts[faces[:, c]]
        cosang = (e1 * e2).sum(1) / (np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) + 1e-12)
        angle[:, c] = np.arccos(np.clip(cosang, -1, 1))
    cos = np.cos(np.radians(crease))
    by_vertex = [[] for _ in range(len(verts))]
    for k, face in enumerate(faces):
        for corner, v in enumerate(face):
            by_vertex[v].append((k, corner))
    new_verts, normals, new_faces = [], [], faces.copy()
    for v, uses in enumerate(by_vertex):
        groups = []   # faces around this corner that meet at a gentle angle: [summed normal, uses]
        for k, corner in uses:
            for g in groups:
                if unit[k] @ (g[0] / (np.linalg.norm(g[0]) + 1e-12)) >= cos:
                    g[0] = g[0] + unit[k] * angle[k, corner]
                    g[1].append((k, corner))
                    break
            else:
                groups.append([unit[k] * angle[k, corner], [(k, corner)]])
        for total, members in groups:
            for k, corner in members:
                new_faces[k, corner] = len(new_verts)
            new_verts.append(verts[v])
            normals.append(total / (np.linalg.norm(total) + 1e-12))
    return np.array(new_verts), new_faces, np.array(normals)


def texcoords(verts, normals):
    """Wrap the texture around the piece like a box (each point uses its main facing direction)."""
    axis = np.abs(normals).argmax(1)
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
