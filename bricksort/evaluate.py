"""The honest accuracy test: score a model on photos of pieces it has never seen.

Run:  python -m bricksort.evaluate [model file]      (default: model/lego_model.pt)

The test pieces are in my_photos/_test/<part>/<colour>/ (made with "Cut out test pieces.bat", labelled
without seeing the model's guesses). Training never uses folders starting with _, so these photos
stay unseen however often the model is retrained.

Each picture counts as one piece. To use several photos of the same piece, name them with a shared
start and two underscores (piece07__a.jpg, piece07__b.jpg): they then count as one piece, scored by
the share of its photos that are right, because photos of one piece aren't independent.

Writes results/results.json and results/RESULTS.md (a table for the README).
"""
import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import catalog, config

RESULTS = config.PROJECT_DIR / "results"


def wilson(right, n, z=1.96):
    """95% range for a success rate measured on n pieces (Wilson score interval)."""
    if n == 0:
        return 0.0, 0.0
    p = right / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def test_photos(root=None):
    """[(path, part, colour name or None)] for every test photo."""
    root = root or config.TEST_DIR
    out = []
    if not root.exists():
        return out
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        part = catalog.folder_part(folder.name)   # printed version -> plain part; not_lego
        if not part:
            continue
        for f in sorted(folder.rglob("*")):
            if f.suffix.lower() in config.PHOTO_TYPES:
                colour = f.parent.name if f.parent != folder else None
                out.append((f, part, colour))
    return out


def _piece_of(path):
    stem = path.stem
    return f"{path.parent}/{stem.split('__')[0]}" if "__" in stem else str(path)


def _categories():
    names = {r["id"]: r["name"].lower() for r in catalog.read_csv("part_categories")}
    return {r["part_num"]: names.get(r["part_cat_id"], "") for r in catalog.read_csv("parts")}


def evaluate(model_file=None, log=print):
    from .model import Recognizer
    from .train import load_square
    model_file = Path(model_file or config.MODEL_FILE)
    rec = Recognizer(model_file)
    colours = {cid: name for cid, (name, _) in catalog.colors(include_trans=True).items()}
    category_of = _categories()
    photos = test_photos()
    if not photos:
        log(f"No test photos in {config.TEST_DIR}. Make them with 'Cut out test pieces.bat'.")
        return None

    def knows(part):
        return any(catalog.same_piece(part, c) for c in rec.classes)

    per_piece = defaultdict(list)   # piece -> [(known, top1, top5, colour right or None, category right, guess)]
    for k, (path, part, colour) in enumerate(photos, 1):
        pred = rec.predict(load_square(path))
        ids = [p for p, _ in pred.parts]
        known = knows(part)
        top1 = bool(ids) and catalog.same_piece(ids[0], part)
        top5 = any(catalog.same_piece(i, part) for i in ids[:5])
        guessed_colour = colours.get(pred.colors[0][0], "?") if pred.colors else "?"
        colour_ok = None if colour is None else catalog.same_colour(guessed_colour) == catalog.same_colour(colour)
        cat = category_of.get(part, "")
        cat_ok = None if not cat else bool(pred.categories) and pred.categories[0][0] == cat   # None: not scored
        per_piece[_piece_of(path)].append((known, top1, top5, colour_ok, cat_ok, (part, ids[0] if ids else "?")))
        if k % 25 == 0:
            log(f"  {k}/{len(photos)} photos")

    def rate(rows, i):
        """Share right over pieces: each piece counts once (the share of its photos that are right)."""
        scored = [[r[i] for r in rs if r[i] is not None] for rs in rows]
        scored = [s for s in scored if s]
        if not scored:
            return None
        right = sum(sum(s) / len(s) for s in scored)
        lo, hi = wilson(right, len(scored))
        return {"right": right / len(scored), "pieces": len(scored), "low": lo, "high": hi}

    pieces = list(per_piece.values())
    known_pieces = [rs for rs in pieces if rs[0][0]]
    unknown_pieces = [rs for rs in pieces if not rs[0][0]]
    confused = Counter(r[5] for rs in known_pieces for r in rs if not r[1])
    result = {
        "model": model_file.name,
        "model_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
        "tested": time.strftime("%Y-%m-%d %H:%M"),
        "photos": len(photos),
        "pieces": len(pieces),
        "known_pieces": len(known_pieces),
        "part_first_guess": rate(known_pieces, 1),
        "part_top5": rate(known_pieces, 2),
        "colour": rate(known_pieces, 3),
        "colour_all_pieces": rate(pieces, 3),
        "category_unknown_parts": rate(unknown_pieces, 4),
        "most_confused": [{"real": a, "guessed": b, "photos": n} for (a, b), n in confused.most_common(10)],
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (RESULTS / "RESULTS.md").write_text(markdown(result), encoding="utf-8")
    log(markdown(result))
    return result


def _pct(r):
    if not r:
        return "–", "–"
    return f"{r['right']:.0%}", f"{r['low']:.0%}–{r['high']:.0%}"


def markdown(r):
    rows = [("Part, first guess", r["part_first_guess"]), ("Part, within top 5", r["part_top5"]),
            ("Colour", r["colour"]), ("Category of parts it doesn't know", r["category_unknown_parts"])]
    lines = [f"Tested {r['tested']} on {r['pieces']} pieces ({r['photos']} photos), "
             f"never seen in training. {r['known_pieces']} of {r['pieces']} pieces are parts the model knows; "
             "the part scores are on those.", "",
             "| | Right | 95% range | Pieces |", "|---|---|---|---|"]
    for name, x in rows:
        right, rng = _pct(x)
        lines.append(f"| {name} | {right} | {rng} | {x['pieces'] if x else 0} |")
    if r["most_confused"]:
        lines += ["", "Most confused (real → guessed): " + ", ".join(
            f"{c['real']} → {c['guessed']} ({c['photos']})" for c in r["most_confused"])]
    lines += ["", f"Model: `{r['model']}` (sha256 {r['model_sha256'][:12]}…)."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")   # a Windows console can't show every character
    evaluate(sys.argv[1] if len(sys.argv) > 1 else None)
