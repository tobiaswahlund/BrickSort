"""The part of the camera picture to look at: a rectangle or a circle; the rest is ignored.

Useful when the camera sees more than the belt (its edges, the frame, the table): only pieces inside
the area are found. Kept as fractions of the picture (0..1), so it fits any camera resolution:
  {"shape": "rect" | "circle", "box": [x0, y0, x1, y1]}   (a circle fills its box as an ellipse)
None means the whole picture.
"""
import numpy as np
from PIL import Image, ImageDraw

SHAPES = {"Whole picture": None, "Rectangle": "rect", "Circle": "circle"}


def mask(area, width, height):
    """(height, width) True inside the area, or None for the whole picture."""
    if not area or area.get("shape") not in ("rect", "circle"):
        return None
    x0, y0, x1, y1 = area["box"]
    x0, x1 = sorted((x0 * width, x1 * width))
    y0, y1 = sorted((y0 * height, y1 * height))
    ys, xs = np.mgrid[0:height, 0:width]
    if area["shape"] == "rect":
        return (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, max((x1 - x0) / 2, 1), max((y1 - y0) / 2, 1)
    return ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 <= 1


def draw(img, area, dim=0.45):
    """The picture with everything outside the area darkened and the area outlined."""
    if not area or area.get("shape") not in ("rect", "circle"):
        return img
    w, h = img.size
    x0, y0, x1, y1 = area["box"]
    box = (min(x0, x1) * w, min(y0, y1) * h, max(x0, x1) * w, max(y0, y1) * h)
    keep = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(keep)
    (d.rectangle if area["shape"] == "rect" else d.ellipse)(box, fill=255)
    out = Image.composite(img, Image.eval(img, lambda v: int(v * dim)), keep)
    d = ImageDraw.Draw(out)
    (d.rectangle if area["shape"] == "rect" else d.ellipse)(box, outline=(80, 200, 255), width=3)
    return out


class AreaPicker:
    """Drag on an ImageBox to draw the area. on_done(area) is called when the mouse is let go."""

    def __init__(self, image_box, on_done):
        self.box, self.on_done = image_box, on_done
        self.shape, self.start, self.current = None, None, None
        image_box.bind_image("<ButtonPress-1>", self._press)
        image_box.bind_image("<B1-Motion>", self._move)
        image_box.bind_image("<ButtonRelease-1>", self._release)

    def begin(self, shape):
        """Start drawing a 'rect' or 'circle' with the next drag."""
        self.shape, self.start, self.current = shape, None, None

    def drawing(self):
        """The area being drawn right now (to show it), or None."""
        if self.shape and self.start and self.current:
            return {"shape": self.shape, "box": [*self.start, *self.current]}
        return None

    def _fraction(self, e):
        w, h = self.box._shown_size or (1, 1)
        return min(max(e.x / w, 0.0), 1.0), min(max(e.y / h, 0.0), 1.0)

    def _press(self, e):
        if self.shape:
            self.start = self.current = self._fraction(e)

    def _move(self, e):
        if self.shape and self.start:
            self.current = self._fraction(e)

    def _release(self, e):
        if not (self.shape and self.start):
            return
        self.current = self._fraction(e)
        area = self.drawing()
        self.shape = self.start = self.current = None
        x0, y0, x1, y1 = area["box"]
        if abs(x1 - x0) > 0.02 and abs(y1 - y0) > 0.02:   # not just a click
            area["box"] = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
            self.on_done(area)
