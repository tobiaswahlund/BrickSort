"""Brickognize as the model: an online service that recognises LEGO parts from a photo
(brickognize.com, api.brickognize.com). Chosen in the BrickSort menu instead of your own model.

It answers the same questions as your model (part, colour, category) so every window can use it,
with these differences:
  - every piece is sent over the internet, so it needs a connection and takes about a second;
  - it can't be retrained, so the windows hide correcting and retraining while it's chosen;
  - its part numbers come from BrickLink (almost always the same as Rebrickable's), its colours are
    matched to Rebrickable's by name, and its category is Rebrickable's category of that part;
  - it doesn't say whether a piece is printed, and has no "several pieces" or "not LEGO" answer.
If it can't be reached, the answer is "?" with 0% (so the sorter puts the piece in the rest bin).
No published terms or limits were found (2026-10); it's used here gently, one piece at a time.
"""
import io
import json
import urllib.request
import uuid

from PIL import Image

from . import catalog

URL = "https://api.brickognize.com/predict/parts/?predict_color=true&top_k_items=5&top_k_colors=3"
NOTHING = ("?", 0.0)


class BrickognizeRecognizer:
    remote = True            # the windows use this to hide correcting and retraining
    knows_printed = False
    classes = None           # it knows (nearly) every part; there's no list to show
    info = {"name": "Brickognize (online)"}

    def __init__(self, timeout=10):
        self.timeout = timeout
        self._colour_ids = {n.lower(): cid for cid, (n, _) in catalog.colors(include_trans=True).items()}
        self._categories = None

    def _category_of(self, pid):
        if self._categories is None:   # Rebrickable's categories, read once
            cats = {r["id"]: r["name"].lower() for r in catalog.read_csv("part_categories")}
            self._categories = {r["part_num"]: cats.get(r["part_cat_id"], "") for r in catalog.read_csv("parts")}
        return self._categories.get(pid, "")

    def _ask(self, image):
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "JPEG", quality=92)
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"query_image\"; filename=\"piece.jpg\"\r\n"
                "Content-Type: image/jpeg\r\n\r\n").encode() + buf.getvalue() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(URL, data=body, method="POST", headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "BrickSort",
            "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def predict(self, image, top=5, top_colors=3, top_categories=3):
        from .model import Prediction
        if not isinstance(image, Image.Image):
            image = Image.fromarray(image)
        try:
            answer = self._ask(image)
        except (OSError, ValueError) as e:   # no connection, timeout, an error page...
            self.last_error = str(e)
            return Prediction([NOTHING], [(-1, 0.0)], [("", 0.0)])
        self.last_error = None
        items = [i for i in answer.get("items", []) if i.get("type", "part") == "part"][:top]
        parts = [(str(i["id"]), float(i["score"])) for i in items] or [NOTHING]
        colours = [(self._colour_ids.get(c["name"].lower(), -1), float(c["score"]))
                   for c in answer.get("colors", [])][:top_colors] or [(-1, 0.0)]
        cats = {}
        for pid, score in parts:
            cat = self._category_of(pid)
            if cat:
                cats[cat] = max(cats.get(cat, 0.0), score)
        categories = sorted(cats.items(), key=lambda t: -t[1])[:top_categories] or [("", 0.0)]
        return Prediction(parts, colours, categories, printed=None)
