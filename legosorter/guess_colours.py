"""Guess the colour of single-piece photos on a white background (Dataset_01), for you to check.

Run:  python -m legosorter.guess_colours
Moves Dataset_01/<category>/<part>/*.jpg to _check/dataset_01_colours/<part>/<guessed colour>/.
Look through those folders and drag any photo with a wrong colour into the right colour folder
(make one if needed; Rebrickable colour names), or use the review window
(python -m legosorter.colour_review, "Check colours.bat"), which moves checked pieces into my_photos.

How the guess works: two independent guesses, both limited to colours this exact part was
really made in (Rebrickable's set lists):
  1. measuring: the photo is white-balanced on its background, the piece's own pixels are
     taken (median of its 'core'), and the closest colour is picked;
  2. the trained model's colour answer.
If they agree the photo goes to <part>/<colour>/; if not, to <part>/_check - A or B/.
"""
import re
import shutil
import sys
from collections import Counter

import numpy as np
from PIL import Image

from . import catalog, config
from .render import real_colors

OUT = config.PROJECT_DIR / "_check" / "dataset_01_colours"


def _lab(rgb):
    """RGB (0..255) -> CIE Lab, so 'closest colour' matches how different colours look to us."""
    c = np.asarray(rgb, float) / 255
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.2126, 0.0193], [0.3576, 0.7152, 0.1192], [0.1805, 0.0722, 0.9505]])
    xyz = xyz / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def piece_colour(path):
    """The piece's colour: white-balanced against the background (the photo's edges are mostly
    background), then the median of the pixels that clearly differ from the background."""
    img = np.asarray(Image.open(path).convert("RGB").resize((96, 96)), float)
    border = np.concatenate([img[:4].reshape(-1, 3), img[-4:].reshape(-1, 3),
                             img[:, :4].reshape(-1, 3), img[:, -4:].reshape(-1, 3)])
    bg = np.median(border, 0)
    img = np.clip(img * (235 / np.maximum(bg, 1)), 0, 255)   # the background becomes neutral white
    lab = _lab(img)
    dist = np.linalg.norm(lab - _lab(np.array([235.0, 235, 235])), axis=-1)
    sel = dist > 14
    if sel.sum() < 150:   # hardly anything differs from the background: a white piece
        return (240, 240, 240)
    # Edge pixels are a blend of piece and background: use the pixels that differ most
    # from the background (the piece's 'core'), but not the darkest ones (shadows, holes).
    d = dist[sel]
    piece = img[sel]
    core = piece[d >= np.percentile(d, 50)]
    core = core[core.mean(1) >= np.percentile(core.mean(1), 20)]
    return tuple(np.median(core, 0))


_model = None


def guess_with_model(path, part, table):
    """The trained model's colour answer (it's right ~88% on your real photos), limited to colours
    this part really comes in; the pixel-measuring guess is used if the model has no opinion."""
    global _model
    if _model is None:
        from .model import Recognizer
        _model = Recognizer()
    from .train import load_square
    import torch
    img = load_square(path)
    x = __import__("legosorter.model", fromlist=["eval_transform"]).eval_transform(img).unsqueeze(0).to(_model.dev)
    with torch.no_grad():
        probs = torch.softmax(_model.net(x)[1], 1)[0].cpu().numpy()
    ids, w = real_colors({"id": part, "colors": []}, table)
    allowed = {c: p for c, p in zip(ids, w) if p >= 0.005}
    scored = [(probs[i] * (0.2 + allowed[c]), c) for i, c in enumerate(_model.color_classes) if c in allowed]
    if scored and max(scored)[0] > 0.02:
        return table[max(scored)[1]][0]
    return guess(path, part, table)


def guess(path, part, table):
    rgb = piece_colour(path)
    ids, w = real_colors({"id": part, "colors": []}, table)
    keep = [(c, p) for c, p in zip(ids, w) if p >= 0.01 and not table[c][0].startswith("Trans")]
    cand, prior = zip(*keep) if keep else (ids, w)
    d = np.linalg.norm(_lab([table[c][1] for c in cand]) - _lab(rgb), axis=1)
    score = d - 4 * np.log(np.asarray(prior) + 1e-3)   # common colours of this part win close calls
    return table[cand[int(np.argmin(score))]][0]


def main(root=None):
    root = root or config.PROJECT_DIR / "Dataset_01"
    table = catalog.colors(include_trans=True)
    total, per_colour = 0, Counter()
    for part_dir in sorted(p for cat in root.iterdir() if cat.is_dir() for p in cat.iterdir() if p.is_dir()):
        part = catalog.folder_part(re.split(r"[_ ]", part_dir.name)[0])
        if not part:
            continue
        for f in sorted(part_dir.iterdir()):
            if f.suffix.lower() not in config.PHOTO_TYPES:
                continue
            try:
                a, b = guess(f, part, table), guess_with_model(f, part, table)
                # both ways agree: probably right. Otherwise a folder that says which two it could be.
                colour = a if a == b else f"_check - {a} or {b}"
            except Exception:
                colour = "colour_not_specified"
            dest = OUT / part / colour
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest / f.name))
            total += 1
            per_colour[colour] += 1
        print(f"{part}: done ({total} photos)", flush=True)
    print(f"Moved {total} photos to {OUT}. Most common guesses: {per_colour.most_common(12)}")


if __name__ == "__main__":
    main(*(sys.argv[1:2] and [config.PROJECT_DIR / sys.argv[1]]))
