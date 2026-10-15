"""Turn an LDraw part file into a plain triangle mesh.

LDraw parts are text files that reference smaller shared pieces (studs,
tubes, edges...). We read them straight out of the downloaded zip, follow the
references, and flatten everything into one list of triangles with the
outward-facing winding (LDraw's "BFC" rules), in metres-ish world units.
"""
import zipfile

import numpy as np

from . import config

# LDraw: 1 unit = 0.4 mm, -Y is up. We scale 10x (one 1x1 brick ~ 8 cm) which
# keeps the physics engine comfortable, and rotate so +Z is up.
SCALE = 0.004
_TO_WORLD = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=float) * SCALE


class Library:
    def __init__(self, zip_path=config.LDRAW_ZIP):
        if not zip_path.exists():  # first run on a new computer: fetch the 3D part library once
            from .catalog import download
            download("ldraw", zip_path)
        self.zip = zipfile.ZipFile(zip_path)
        self.index = {}
        for name in self.zip.namelist():
            low = name.lower().replace("\\", "/")
            if not low.endswith(".dat"):
                continue
            # complete.zip has everything under "ldraw/"
            for prefix in ("ldraw/parts/", "ldraw/p/", "ldraw/models/"):
                if low.startswith(prefix):
                    rel = low[len(prefix):]
                    # Prefer normal-resolution primitives over 48/ and 8/ variants
                    self.index.setdefault(rel, name)
        self._cache = {}

    def has_part(self, part_num):
        return f"{part_num.lower()}.dat" in self.index

    def title(self, part_num):
        name = self.index.get(f"{part_num.lower()}.dat")
        if not name:
            return ""
        first = self.zip.read(name).decode("utf-8", "replace").splitlines()[0]
        return first[2:].strip() if first.startswith("0") else ""

    def _lines(self, ref):
        name = self.index.get(ref.lower().replace("\\", "/"))
        if name is None:
            return None
        return self.zip.read(name).decode("utf-8", "replace").splitlines()

    def triangles(self, ref):
        """Triangles (N,3,3) of a file in its own coordinates, CCW = outward."""
        key = ref.lower().replace("\\", "/")
        if key in self._cache:
            return self._cache[key]
        lines = self._lines(key)
        if lines is None:
            self._cache[key] = np.zeros((0, 3, 3))
            return self._cache[key]
        self._cache[key] = np.zeros((0, 3, 3))  # guard against self-reference

        out = []
        ccw = True
        invert_next = False
        for raw in lines:
            tok = raw.split()
            if not tok:
                continue
            kind = tok[0]
            if kind == "0":
                up = [t.upper() for t in tok[1:]]
                if up[:1] == ["BFC"]:
                    if "INVERTNEXT" in up:
                        invert_next = True
                    if "CW" in up:
                        ccw = False
                    if "CCW" in up:
                        ccw = True
                continue
            if kind == "1" and len(tok) >= 15:
                v = [float(x) for x in tok[2:14]]
                pos = np.array(v[0:3])
                mat = np.array(v[3:12]).reshape(3, 3)
                child = self.triangles(" ".join(tok[14:]))
                if len(child):
                    tris = child @ mat.T + pos
                    if (np.linalg.det(mat) < 0) != invert_next:
                        tris = tris[:, ::-1, :]
                    out.append(tris)
                invert_next = False
                continue
            if kind == "3" and len(tok) >= 11:
                p = np.array([float(x) for x in tok[2:11]]).reshape(1, 3, 3)
                out.append(p if ccw else p[:, ::-1, :])
            elif kind == "4" and len(tok) >= 14:
                q = np.array([float(x) for x in tok[2:14]]).reshape(4, 3)
                t = np.stack([q[[0, 1, 2]], q[[0, 2, 3]]])
                out.append(t if ccw else t[:, ::-1, :])
            invert_next = False if kind in "1234" else invert_next

        tris = np.concatenate(out) if out else np.zeros((0, 3, 3))
        self._cache[key] = tris
        return tris

    def part_mesh(self, part_num):
        """(vertices (V,3), faces (F,3)) in world units, centred on the part."""
        tris = self.triangles(f"{part_num}.dat") @ _TO_WORLD.T
        if len(tris) == 0:
            raise ValueError(f"No geometry for part {part_num}")
        verts = tris.reshape(-1, 3)
        verts = verts - (verts.min(0) + verts.max(0)) / 2
        # Merge identical corners so the mesh is connected (nicer shading)
        rounded = np.round(verts, 7)
        uniq, inverse = np.unique(rounded, axis=0, return_inverse=True)
        faces = inverse.reshape(-1, 3)
        good = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
        return uniq.astype(np.float64), faces[good].astype(np.int32)
