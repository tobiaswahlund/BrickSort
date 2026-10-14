"""Notice objects on the belt by comparing each camera picture with the empty belt.

Works the same on the virtual belt and a real one: anything that looks different
from the bare belt (and isn't just a shadow) is an object. Touching pieces show
up as one bigger object; separate pieces as several.
"""
from dataclasses import dataclass
from collections import deque

import numpy as np

STEP = 4  # analyse every 4th pixel: plenty for finding objects, and fast


@dataclass
class Blob:
    x0: int
    y0: int
    x1: int
    y1: int
    area: int          # in full-resolution pixels (approx.)
    cx: float
    cy: float
    bits: tuple = ()   # sizes of separate bits merged into this object (empty = one bit)

    @property
    def long_side(self):
        return max(self.x1 - self.x0, self.y1 - self.y0)


def _blocks(img):
    """Average over STEP x STEP blocks (a smaller, smoother picture)."""
    img = np.asarray(img, np.float32)
    h, w = img.shape[0] // STEP * STEP, img.shape[1] // STEP * STEP
    return img[:h, :w].reshape(h // STEP, STEP, w // STEP, STEP, -1).mean((1, 3))


class Detector:
    def __init__(self, threshold=28, min_area=120, merge_gap=20):
        self.threshold = threshold
        self.min_area = min_area
        self.merge_gap = merge_gap  # join bits closer than this (pixels); 0 = never
        self.background = None      # average look of the empty belt (full size)
        self.noise = None           # how much the empty belt itself varies (texture, belt moving)
        self._seen = []

    def learn_background(self, frame):
        """Call with pictures of the empty belt, ideally at different belt positions: a textured
        belt looks a bit different everywhere, and that variation must not count as an object."""
        self._seen.append(_blocks(frame))
        stack = np.stack(self._seen)
        self._bg_small = stack.mean(0)                                   # average empty belt
        self.noise = stack.std(0).max(2) if len(self._seen) > 2 else None  # its natural variation
        self.background = frame.astype(np.float32)

    def mask(self, frame):
        f = _blocks(frame)  # average over little blocks: smooths out the belt's fine texture
        b = getattr(self, "_bg_small", None)
        if b is None or b.shape != f.shape:
            b = _blocks(self.background)
        diff = np.abs(f - b).max(2)
        # A shadow is the belt, only darker, with the same colour balance: not an object
        lum_f, lum_b = f.mean(2) + 1, b.mean(2) + 1
        ratio = lum_f / lum_b
        chroma = np.abs(f / lum_f[..., None] - b / lum_b[..., None]).max(2)
        shadow = (ratio > 0.35) & (ratio < 0.97) & (chroma < 0.12)
        limit = self.threshold
        if self.noise is not None and self.noise.shape == diff.shape:
            limit = np.maximum(limit, 3 * self.noise + 10)  # where the belt itself varies, be stricter
        m = (diff > limit) & ~shadow
        # tidy up: drop lonely pixels (needs 2+ neighbours)
        n = np.zeros(m.shape, np.int32)
        p = np.pad(m, 1)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    n += p[1 + dy:p.shape[0] - 1 + dy, 1 + dx:p.shape[1] - 1 + dx]
        m = m & (n >= 2)
        # close small gaps (a dark groove or highlight can split one piece in two)
        p = np.pad(m, 1)
        grown = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                grown |= p[1 + dy:p.shape[0] - 1 + dy, 1 + dx:p.shape[1] - 1 + dx]
        return grown

    def find(self, frame):
        """List of Blobs (objects) in the picture."""
        if self.background is None:
            self.learn_background(frame)
            return []
        m = self.mask(frame)
        labels = connected_components(m)
        blobs = []
        for lab in np.unique(labels[m]):
            ys, xs = np.nonzero(labels == lab)
            area = len(xs) * STEP * STEP
            if area < self.min_area:
                continue
            blobs.append(Blob(int(xs.min() * STEP), int(ys.min() * STEP), int(xs.max() * STEP + STEP),
                              int(ys.max() * STEP + STEP), area, float(xs.mean() * STEP), float(ys.mean() * STEP)))
        return merge_close(blobs, self.merge_gap) if self.merge_gap else blobs


def connected_components(m):
    """Label touching (8-connected) pixels of a mask with the same number, using whole-array
    steps (fast in numpy): every pixel repeatedly takes the smallest label among its neighbours."""
    h, w = m.shape
    big = h * w + 1
    labels = np.where(m, np.arange(h * w).reshape(h, w), big)
    while True:
        p = np.pad(labels, 1, constant_values=big)
        smallest = labels
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                smallest = np.minimum(smallest, p[dy:dy + h, dx:dx + w])
        smallest = np.where(m, smallest, big)
        # jump straight to the label's own label (speeds up long chains a lot)
        flat = smallest.ravel()
        inside = flat < big
        flat[inside] = np.minimum(flat[inside], flat[flat[inside]])
        if np.array_equal(smallest, labels):
            return labels
        labels = smallest


def merge_close(blobs, gap=8):
    """Bits whose boxes (almost) overlap are one object: one piece split by a dark groove,
    or pieces touching each other (the recognizer and size check deal with those)."""
    blobs = list(blobs)
    merged = True
    while merged:
        merged = False
        for i in range(len(blobs)):
            for j in range(i + 1, len(blobs)):
                a, b = blobs[i], blobs[j]
                if a.x0 - gap <= b.x1 and b.x0 - gap <= a.x1 and a.y0 - gap <= b.y1 and b.y0 - gap <= a.y1:
                    area = a.area + b.area
                    blobs[i] = Blob(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1), area,
                                    (a.cx * a.area + b.cx * b.area) / area, (a.cy * a.area + b.cy * b.area) / area,
                                    (a.bits or (a.area,)) + (b.bits or (b.area,)))
                    del blobs[j]
                    merged = True
                    break
            if merged:
                break
    return blobs


def merge_all(blobs):
    """One object covering all these blobs (their sizes kept as separate bits)."""
    area = sum(b.area for b in blobs)
    return Blob(min(b.x0 for b in blobs), min(b.y0 for b in blobs), max(b.x1 for b in blobs),
                max(b.y1 for b in blobs), area, sum(b.cx * b.area for b in blobs) / area,
                sum(b.cy * b.area for b in blobs) / area, sum(((b.bits or (b.area,)) for b in blobs), ()))


def crop(frame, blob, size=224, margin=0.15):
    """Square picture around one object, for the recognizer."""
    from PIL import Image
    cx, cy = (blob.x0 + blob.x1) / 2, (blob.y0 + blob.y1) / 2
    half = blob.long_side / 2 * (1 + margin) + 6
    pad = int(half) + 2
    big = np.pad(frame, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    box = (int(cx - half) + pad, int(cy - half) + pad, int(cx + half) + pad, int(cy + half) + pad)
    return Image.fromarray(big).crop(box).resize((size, size), Image.LANCZOS)
