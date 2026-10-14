"""Random non-Lego objects (pebbles, beads, coins, screws-ish rods, blobs).

Used to teach the model a "not_lego" class, and as things that sneak onto the
virtual conveyor belt. Real photos of non-Lego things go in my_photos/not_lego/.
"""
import numpy as np

NOT_LEGO = "not_lego"


def random_mesh(rng, size=0.08):
    """(verts, faces) of a random lumpy shape, roughly `size` across."""
    n_lat, n_lon = 14, 24
    lat = np.linspace(0, np.pi, n_lat)
    lon = np.linspace(0, 2 * np.pi, n_lon, endpoint=False)
    th, ph = np.meshgrid(lat, lon, indexing="ij")
    dirs = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1)

    kind = rng.choice(["pebble", "coin", "rod", "bead", "blob"])
    radii = {"pebble": rng.uniform(0.5, 1.0, 3), "coin": [1, 1, rng.uniform(0.08, 0.2)],
             "rod": [rng.uniform(0.15, 0.3), rng.uniform(0.15, 0.3), 1.0], "bead": [1, 1, 1],
             "blob": rng.uniform(0.4, 1.0, 3)}[kind]
    bump = {"pebble": 0.12, "coin": 0.02, "rod": 0.03, "bead": 0.0, "blob": 0.35}[kind]
    # smooth random bumps from a few random waves
    r = np.ones(th.shape)
    for _ in range(4):
        k = rng.normal(size=3) * rng.uniform(1, 4)
        r += bump * np.sin(dirs @ k + rng.uniform(0, 2 * np.pi)) / 4
    verts = dirs * r[..., None] * np.asarray(radii) * size / 2

    faces = []
    idx = lambda i, j: i * n_lon + (j % n_lon)
    for i in range(n_lat - 1):
        for j in range(n_lon):
            a, b, c, d = idx(i, j), idx(i, j + 1), idx(i + 1, j), idx(i + 1, j + 1)
            faces += [[a, c, b], [b, c, d]]
    verts = verts.reshape(-1, 3)
    # merge the duplicated pole vertices
    uniq, inv = np.unique(np.round(verts, 7), axis=0, return_inverse=True)
    faces = inv.ravel()[np.array(faces)]
    good = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return uniq.astype(np.float64), faces[good].astype(np.int32)


def random_color(rng):
    """Anything: dull stone, metal, wood, bright plastic."""
    pick = rng.random()
    if pick < 0.4:
        g = rng.uniform(60, 200)
        return tuple(np.clip(g + rng.uniform(-20, 20, 3), 0, 255).astype(int))
    if pick < 0.6:
        return tuple(np.clip(np.array([150, 100, 55]) * rng.uniform(0.6, 1.3) + rng.uniform(-15, 15, 3), 0, 255).astype(int))
    return tuple(rng.integers(0, 256, 3))
