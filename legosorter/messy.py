"""Make a clean rendered picture look more like a real photo.

Every picture gets a random mix of: a different table/tray surface, worn or
dirty plastic, a slight colour cast and exposure change, out-of-focus or
shaky-hand blur, sensor noise and JPEG compression. The model then learns to
ignore those things and focus on the shape and the plastic's colour.
"""
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _smooth_noise(rng, h, w, scale):
    """Blotchy noise in 0..1 (cheap: small random grid, upscaled)."""
    small = rng.random((max(2, h // scale), max(2, w // scale)))
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(img, dtype=np.float32) / 255


def background(rng, h, w):
    """A random surface: plain, wood, speckled tabletop, cloth or a gradient."""
    base = rng.uniform(0.15, 0.95, 3)
    base = 0.5 * base + 0.5 * base.mean()   # muted colours, not neon
    if rng.random() < 0.5:  # mostly greyish/beige surfaces, like real tables and trays
        base = np.full(3, rng.uniform(0.3, 0.95)) + rng.uniform(-0.08, 0.08, 3)
    if rng.random() < 0.15:  # like the sorting machine's belt
        base = np.array([0.47, 0.69, 0.55]) * rng.uniform(0.85, 1.15)
    kind = rng.choice(["plain", "plain", "wood", "speckle", "cloth", "gradient"])
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if kind == "wood":
        a = rng.uniform(0, np.pi)
        u = xx * np.cos(a) + yy * np.sin(a)
        warp = _smooth_noise(rng, h, w, 40) * rng.uniform(5, 30)
        rings = 0.5 + 0.5 * np.sin((u + warp) / rng.uniform(2, 8))
        pattern = 0.85 + 0.25 * rings * _smooth_noise(rng, h, w, 6)
    elif kind == "speckle":
        pattern = 0.9 + 0.2 * (rng.random((h, w)) > 0.97) * rng.uniform(-1, 1) + 0.1 * _smooth_noise(rng, h, w, 30)
    elif kind == "cloth":
        pattern = 0.9 + 0.1 * np.sin(xx * rng.uniform(1, 2)) * np.sin(yy * rng.uniform(1, 2)) \
            + 0.1 * _smooth_noise(rng, h, w, 20)
    elif kind == "gradient":
        a = rng.uniform(0, 2 * np.pi)
        pattern = 0.8 + 0.4 * ((xx * np.cos(a) + yy * np.sin(a)) / max(h, w) + 0.5) / 1.5
    else:
        pattern = 0.95 + 0.1 * _smooth_noise(rng, h, w, 60)
    return np.clip(base[None, None, :] * pattern[..., None], 0, 1)


def wear(img, mask, rng):
    """Scratches, scuffs and specks of dirt on the part."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        return img
    pil = Image.fromarray(img)
    overlay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    size = max(x1 - x0, y1 - y0)
    for _ in range(rng.integers(0, 12)):  # scratches: thin light or dark lines
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        a, length = rng.uniform(0, np.pi), rng.uniform(0.05, 0.3) * size
        shade = 255 if rng.random() < 0.6 else 0
        draw.line([(x, y), (x + length * np.cos(a), y + length * np.sin(a))],
                  fill=(shade, shade, shade, int(rng.uniform(25, 90))), width=1)
    for _ in range(rng.integers(0, 25)):  # dirt and dust specks
        x, y, rad = rng.uniform(x0, x1), rng.uniform(y0, y1), rng.uniform(0.5, 2.5)
        tone = int(rng.uniform(30, 120))
        draw.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(tone, tone - 10, tone - 20, int(rng.uniform(60, 160))))
    if rng.random() < 0.3:  # a scuffed, duller area
        x, y, rad = rng.uniform(x0, x1), rng.uniform(y0, y1), rng.uniform(0.05, 0.2) * size
        draw.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(200, 200, 200, int(rng.uniform(10, 25))))
    worn = Image.alpha_composite(pil.convert("RGBA"), overlay.filter(ImageFilter.GaussianBlur(0.4))).convert("RGB")
    out = np.asarray(worn).copy()
    out[~mask] = img[~mask]
    return out


def photo_effects(img, mask, rng, replace_background=False, painted_wear=False):
    """Apply the messy treatment to a rendered picture (H,W,3 uint8). The surface itself is
    now part of the 3D world (real shadows), so replacing the background is optional."""
    f = img.astype(np.float32) / 255
    # 1. (optional) new background, keeping the rendered shadows: background = surface x shading
    bg = ~mask
    if replace_background and bg.any():
        lum = f.mean(2)
        level = np.median(lum[bg]) + 1e-3
        shade = np.clip(lum / level, 0.3, 1.15)[..., None]
        surf = background(rng, *mask.shape)
        f[bg] = (surf * shade)[bg]
    out = (np.clip(f, 0, 1) * 255).astype(np.uint8)
    # 2. (old way, off now) wear and dirt painted on the picture; wear is now on the 3D piece itself
    if painted_wear:
        out = wear(out, mask, rng)
    f = out.astype(np.float32) / 255
    # 3. Exposure, contrast and colour cast (kept mild so colours stay recognisable)
    f = f * rng.uniform(0.88, 1.12) * rng.uniform(0.95, 1.05, 3)[None, None, :]
    f = np.clip(f, 0, 1) ** rng.uniform(0.88, 1.12)
    f = (f - 0.5) * rng.uniform(0.92, 1.08) + 0.5
    # 4. Sensor noise
    f = f + rng.normal(0, rng.uniform(0, 0.03), f.shape)
    pil = Image.fromarray((np.clip(f, 0, 1) * 255).astype(np.uint8))
    # 5. Out of focus, or a little camera shake
    r = rng.random()
    if r < 0.4:
        pil = pil.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.8)))
    elif r < 0.55:  # shake: smear along a line, sideways or up-down
        kernel = np.zeros((5, 5))
        if rng.random() < 0.5:
            kernel[2, :] = 1
        else:
            kernel[:, 2] = 1
        pil = pil.filter(ImageFilter.Kernel((5, 5), kernel.ravel().tolist(), scale=5))
    # 6. JPEG compression, like a phone or webcam
    buf = io.BytesIO()
    pil.save(buf, "JPEG", quality=int(rng.integers(35, 95)))
    return np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
