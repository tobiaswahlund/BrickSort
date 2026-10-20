"""Camera test: the first real-world step. A real webcam looks down at a surface; you put pieces under
it by hand, and BrickSort finds them (red boxes) and says what they are and which bin they'd go to.
The same finding, cropping, recognising and bin choice as the sorting machine, only without a belt.

Run:  python -m bricksort.camera_test   (or Camera test in the BrickSort menu)

1. Point the camera straight down at a plain surface (ideally the belt you'll use), about 20 cm up.
2. Learn the empty surface: nothing under the camera, then press the button.
3. Measure: put a known piece (a 2x4 brick, or choose another; studs up, lined up with the picture's
   edges) under it and press the button. Now BrickSort knows how many pixels are one millimetre.
   Area: only a rectangle or circle of the picture can be looked at (drag it on the picture), e.g. just
   the belt; the rest is ignored.
4. Colours: put a white piece under it and press the button, so the camera's colour tint under your
   light is taken out (a white piece should look white to the model).
5. Put pieces under the camera, a few cm apart, and press Take picture (or Space). Pieces that would go
   to the rest bin are kept: Review rest bin says what they really were, for the next training.
   (Or tick "By itself": then a piece is recognised once it lies still, and nothing is kept.)
Settings are kept in real_machine.json (camera, pixels per mm, area, colour correction).
"""
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from . import catalog, config
from .ldraw import Library
from .sorter import area as area_mod
from .sorter import properties
from .sorter import rules as rules_mod
from .sorter.detector import Detector, crop
from .ui import MUTED, ImageBox, Label, use_logo

SETTINGS = config.PROJECT_DIR / "real_machine.json"
DEFAULTS = {"camera": 0, "px_per_mm": None, "width": 1280, "height": 720}
MM_PER_STUD = 8.0
# pieces to measure with: rectangular, so the longest side seen from above is easy to know
MEASURE_WITH = ("3001", "3003", "3010", "3009", "3008", "3020", "3666", "3460", "3795")
STILL_FRAMES = 6          # a piece is recognised once it has stayed put this many pictures


def load_settings():
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(s):
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


def correct_colours(picture, gains):
    """The picture with the camera's colour tint taken out (gains from white_balance); unchanged if none."""
    if not gains:
        return picture
    a = np.asarray(picture, np.float32) * np.asarray(gains, np.float32)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def find_cameras(n=4):
    """Indexes of the cameras that give a picture."""
    import cv2
    found = []
    for i in range(n):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened() and cap.read()[0]:
            found.append(i)
        cap.release()
    return found


class Camera:
    """Reads pictures from a webcam in the background, so the window always has the newest one."""

    def __init__(self, index, width, height):
        import cv2
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)   # DirectShow: opens in a second on Windows
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.latest, self.running = None, self.cap.isOpened()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while self.running:
            ok, img = self.cap.read()
            if ok:
                self.latest = self.cv2.cvtColor(img, self.cv2.COLOR_BGR2RGB)
            else:
                time.sleep(0.05)

    def close(self):
        self.running = False
        time.sleep(0.1)
        self.cap.release()


class CameraTest(tk.Tk):
    def __init__(self):
        super().__init__()
        use_logo(self)
        self.title("BrickSort – camera test")
        self.configure(padx=10, pady=10)
        self.geometry("1280x800")
        self.settings = load_settings()
        self.detector = None
        self.learning = None         # pictures of the empty surface, while learning it (None: not learning)
        self.tracks = {}             # id -> {"box", "still", "result", "busy"}
        self.next_id = 0
        self.done = queue.Queue()     # (track id, result) from the recognising thread
        self.camera = None
        self.recognizer = None
        self.colors = catalog.colors(include_trans=True)
        self.color_names = {cid: n for cid, (n, _) in self.colors.items()}
        self.names = {p["id"]: p["name"] for p in catalog.load_parts()}
        self.rules = rules_mod.load()
        self.lib = Library()
        self.props = properties.load_all(self.lib)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self._load_model, daemon=True).start()
        self.after(100, self._open_camera)

    # ------------------------------------------------------------------ layout
    def _build(self):
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 8))
        ttk.Label(bar, text="Camera").pack(side="left")
        self.cam_choice = ttk.Combobox(bar, width=6, state="readonly")
        self.cam_choice.pack(side="left", padx=(4, 12))
        self.cam_choice.bind("<<ComboboxSelected>>", lambda e: self._switch_camera())
        self.learn_btn = ttk.Button(bar, text="1. Learn the empty surface", command=self.learn)
        self.learn_btn.pack(side="left")
        self.measure_btn = ttk.Button(bar, text="2. Measure with", command=self.measure)
        self.measure_btn.pack(side="left", padx=(6, 2))
        self.measure_part = ttk.Combobox(bar, width=26, values=[self._measure_label(p) for p in MEASURE_WITH])
        self.measure_part.set(self._measure_label("3001"))
        self.measure_part.pack(side="left", padx=(0, 6))
        ttk.Label(bar, text="Area").pack(side="left", padx=(6, 2))
        self.area_choice = ttk.Combobox(bar, width=14, state="readonly", values=list(area_mod.SHAPES))
        shape = (self.settings.get("area") or {}).get("shape")
        self.area_choice.set({"rect": "Rectangle", "circle": "Circle"}.get(shape, "Whole picture"))
        self.area_choice.pack(side="left", padx=(0, 6))
        self.area_choice.bind("<<ComboboxSelected>>", lambda e: self._area_chosen())
        ttk.Button(bar, text="3. Colours with a white piece", command=self.white_balance).pack(side="left", padx=(0, 6))
        self.scale_text = ttk.Label(bar, text="", foreground=MUTED)
        self.scale_text.pack(side="right")

        # taking the picture: with the button (or Space), or by itself once a piece lies still
        shoot = ttk.Frame(self)
        shoot.grid(row=2, column=0, columnspan=2, sticky="we", pady=(8, 0))
        ttk.Button(shoot, text="📷 Take picture  (Space)", command=self.take_picture).pack(side="left")
        self.auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(shoot, text="By itself when a piece lies still", variable=self.auto).pack(side="left",
                                                                                                 padx=10)
        ttk.Button(shoot, text="Clear the list", command=self.forget).pack(side="left")
        self.review_btn = ttk.Button(shoot, text="Review rest bin…", command=self.review_rest)
        self.review_btn.pack(side="right")
        self.model_text = ttk.Label(shoot, text="", foreground=MUTED)
        self.model_text.pack(side="right", padx=10)
        self.bind("<space>", lambda e: self.take_picture())

        view = ttk.LabelFrame(self, text="Camera (red box = piece found)")
        view.grid(row=1, column=0, sticky="nsew")
        self.view = ImageBox(view, 800, 450)
        self.view.pack(fill="both", expand=True, padx=8, pady=6)
        self.picker = area_mod.AreaPicker(self.view, self._area_drawn)

        side = ttk.LabelFrame(self, text="Pieces recognised")
        side.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        self.list = ttk.Frame(side)
        self.list.pack(fill="both", expand=True, padx=8, pady=6)
        self.status = Label(self, text="Opening the camera …", foreground=MUTED, wraplength=1100, justify="left")
        self.status.grid(row=3, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=1, minsize=330)
        self.rowconfigure(1, weight=1)
        self._show_scale()

    def _show_scale(self):
        k = self.settings.get("px_per_mm")
        self.scale_text.configure(text=f"{k:.2f} pixels per mm" if k else "Not measured yet")

    # ------------------------------------------------------------------ camera
    def _load_model(self):
        from .model import is_remote, load_recognizer
        self.recognizer = load_recognizer()   # your model, or Brickognize (chosen in the BrickSort menu)
        self.remote = is_remote(self.recognizer)
        self.done.put(("model", None))   # tell the window (from its own thread) which model it is

    def _open_camera(self):
        found = find_cameras()
        if not found:
            self.status.configure(text="No camera found. Plug in a webcam and open the camera test again.")
            return
        self.cam_choice.configure(values=[str(i) for i in found])
        index = self.settings["camera"] if self.settings["camera"] in found else found[0]
        self.cam_choice.set(str(index))
        self._switch_camera()
        self._tick()

    def _switch_camera(self):
        if self.camera:
            self.camera.close()
        self.settings["camera"] = int(self.cam_choice.get())
        save_settings(self.settings)
        self.camera = Camera(self.settings["camera"], self.settings["width"], self.settings["height"])
        self.detector = None
        self.forget()
        self.status.configure(text="Point the camera straight down at a plain surface with nothing on it, "
                                   "then press 1. Learn the empty surface.")

    def learn(self):
        """Collect pictures of the empty surface for a moment (see _tick)."""
        self.learning = []
        self.detector = None
        self.forget()
        self.status.configure(text="Learning the empty surface: keep it clear for a moment …")

    def _measure_label(self, pid):
        p = self.props.get(pid, {})
        return f"{pid}  {p.get('name', '')} ({p.get('length', 0) * MM_PER_STUD:g} mm)" if p else pid

    def measure(self):
        pid = self.measure_part.get().split()[0] if self.measure_part.get().split() else ""
        length = self.props.get(pid, {}).get("length")
        if not length:
            self.status.configure(text=f"I don't know how long {pid or 'that piece'} is. Choose one from the list, "
                                       "or type the number of a rectangular brick or plate.")
            return
        boxes = [t["box"] for t in self.tracks.values()]
        if self.detector is None or len(boxes) != 1:
            self.status.configure(text=f"To measure: learn the empty surface first, then put exactly one {pid} "
                                       "under the camera, studs up and lined up with the picture's edges.")
            return
        long_px = self._exact_length(self.camera.latest, boxes[0])
        self.settings["px_per_mm"] = long_px / (length * MM_PER_STUD)
        save_settings(self.settings)
        self._show_scale()
        self.status.configure(text=f"Measured: {self.settings['px_per_mm']:.2f} pixels per mm "
                                   f"({pid} is {length * MM_PER_STUD:g} mm and was {long_px} pixels long). Saved.")

    def _exact_length(self, frame, b):
        """The piece's longest side in pixels, to the pixel: the finder's box is a little bigger than the
        piece (it works on 4x4 blocks and closes small gaps), so look again at every pixel in it."""
        pad = 8
        y0, y1 = max(0, b.y0 - pad), min(frame.shape[0], b.y1 + pad)
        x0, x1 = max(0, b.x0 - pad), min(frame.shape[1], b.x1 + pad)
        diff = np.abs(frame[y0:y1, x0:x1].astype(np.float32)
                      - self.detector.background[y0:y1, x0:x1]).max(2)
        ys, xs = np.nonzero(diff > self.detector.threshold)
        if len(xs) < 20:
            return max(b.x1 - b.x0, b.y1 - b.y0)
        lo_x, hi_x = np.percentile(xs, [0.5, 99.5])   # a stray noisy pixel doesn't stretch it
        lo_y, hi_y = np.percentile(ys, [0.5, 99.5])
        return int(round(max(hi_x - lo_x, hi_y - lo_y))) + 1

    def white_balance(self):
        """A white piece should look white: from how it looks now, work out how much to turn each colour
        channel up or down (the camera's colour tint under this light), and correct every piece with it."""
        boxes = [t["box"] for t in self.tracks.values()]
        frame = self.camera.latest if self.camera else None
        if self.detector is None or len(boxes) != 1 or frame is None:
            self.status.configure(text="For the colours: learn the empty surface first, then put exactly one white "
                                       "piece under the camera and press 3. again.")
            return
        b = boxes[0]
        part = frame[b.y0:b.y1, b.x0:b.x1].astype(np.float32)
        diff = np.abs(part - self.detector.background[b.y0:b.y1, b.x0:b.x1]).max(2)
        px = part[diff > self.detector.threshold]
        if len(px) < 50:
            self.status.configure(text="Couldn't see the white piece clearly. Try again.")
            return
        bright = px[px.sum(1) >= np.percentile(px.sum(1), 50)]   # its lit top, not its shadowed sides
        mean = bright.mean(0)
        gains = np.clip(mean.mean() / np.maximum(mean, 1), 0.5, 2.0)
        self.settings["colour_gains"] = [round(float(g), 3) for g in gains]
        save_settings(self.settings)
        self.forget()
        r, g, bl = self.settings["colour_gains"]
        self.status.configure(text=f"Colours set: red x{r:.2f}, green x{g:.2f}, blue x{bl:.2f} "
                                   "(the camera's tint is taken out before the model looks). Saved.")

    # ------------------------------------------------------------------ the area to look at
    def _area_chosen(self):
        shape = area_mod.SHAPES[self.area_choice.get()]
        if shape is None:
            self._area_drawn(None)
            return
        self.picker.begin(shape)
        self.status.configure(text=f"Drag on the picture to draw the {self.area_choice.get().lower()}: "
                                   "only what's inside it is looked at.")

    def _area_drawn(self, area):
        self.settings["area"] = area
        save_settings(self.settings)
        self._apply_area()
        self.forget()
        self.status.configure(text="Looking at the whole picture." if area is None else
                              "Area set: only pieces inside it are found.")

    def _apply_area(self):
        frame = self.camera.latest if self.camera else None
        if self.detector is not None and frame is not None:
            h, w = frame.shape[:2]
            self.detector.set_area(area_mod.mask(self.settings.get("area"), w, h))

    def forget(self):
        self.tracks = {}
        for w in self.list.winfo_children():
            w.destroy()

    # ------------------------------------------------------------------ every picture
    def _tick(self):
        frame = self.camera.latest if self.camera else None
        if frame is not None:
            if self.detector is None and self.learning is not None and len(self.learning) < 20:
                self.learning.append(frame)
                if len(self.learning) == 20:
                    self.detector = Detector()
                    for f in self.learning:
                        self.detector.learn_background(f)
                    self.learning = None
                    self._apply_area()
                    self.status.configure(text="Learned. Now put pieces under the camera, a few cm apart, and press Take picture "
                                               "(Space). Measure once with a known piece (button 2) so sizes are known.")
            while not self.done.empty():
                tid, result = self.done.get()
                if tid == "model":
                    self._show_model()
                else:
                    self._got(tid, result)
            blobs = self.detector.find(frame) if self.detector else []
            self._follow(blobs, frame)
            self._draw(frame)
        self.after(100, self._tick)

    def _follow(self, blobs, frame):
        """Match the objects to the ones seen before; recognise each once it has lain still."""
        seen = set()
        for b in blobs:
            best, dist = None, 40.0
            for tid, t in self.tracks.items():
                d = np.hypot(b.cx - t["box"].cx, b.cy - t["box"].cy)
                if tid not in seen and d < dist:
                    best, dist = tid, d
            if best is None:
                best = self.next_id
                self.next_id += 1
                self.tracks[best] = {"box": b, "still": 0, "result": None, "busy": False}
            t = self.tracks[best]
            moved = abs(b.cx - t["box"].cx) + abs(b.cy - t["box"].cy) > 6
            t["still"] = 0 if moved else t["still"] + 1
            if moved:
                t["result"] = None   # it was moved: look again once it lies still
            t["box"] = b
            seen.add(best)
            if (self.auto.get() and t["still"] >= STILL_FRAMES and t["result"] is None and not t["busy"]
                    and self.recognizer):
                t["busy"] = True
                threading.Thread(target=self._recognise, args=(best, frame, b), daemon=True).start()
        for tid in [t for t in self.tracks if t not in seen]:   # taken away
            del self.tracks[tid]
        self._show_list()

    def take_picture(self):
        """Look at every piece under the camera now (each gets a fresh answer), and keep the pictures."""
        frame = self.camera.latest if self.camera else None
        if self.detector is None or frame is None:
            self.status.configure(text="Learn the empty surface first (button 1).")
            return
        if self.recognizer is None:
            self.status.configure(text="The model is still loading: try again in a moment.")
            return
        if not self.tracks:
            self.status.configure(text="No pieces found under the camera.")
            return
        for tid, t in self.tracks.items():
            if not t["busy"]:
                t["busy"], t["result"] = True, None
                threading.Thread(target=self._recognise, args=(tid, frame, t["box"], True), daemon=True).start()
        self.status.configure(text=f"Picture taken: {len(self.tracks)} pieces. The ones that would go to the rest "
                                   "bin are kept for Review rest bin.")

    def _show_model(self):
        if self.remote:
            self.review_btn.pack_forget()
            self.model_text.configure(text="Model: Brickognize (online)")
        else:
            self.model_text.configure(text="Model: yours" if self.recognizer else "No model yet")

    def review_rest(self):
        """The Demo's review window on the rest-bin pictures: say what each piece really was. Those answers
        are saved as real photos and used the next time the model is trained."""
        import subprocess
        import sys
        subprocess.Popen([sys.executable, "-m", "bricksort.demo", "--rest", "--real"], cwd=config.PROJECT_DIR)

    def _keep(self, picture, pred, bin_name, reason):
        """Save the picture and the guesses where Review rest bin / Spot check look (as the machine does)."""
        folder = config.REST_LOG if bin_name == self.rules["rest_bin"] else config.SORTED_LOG
        folder.mkdir(exist_ok=True)
        stem = time.strftime("%Y%m%d-%H%M%S") + f"-cam{self.next_id:04d}-{threading.get_ident() % 10000:04d}"
        picture.save(folder / f"{stem}.png")
        info = {"bin": bin_name, "reason": reason, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "real": True,
                "parts": pred.parts, "colors": pred.colors, "categories": pred.categories, "printed": pred.printed}
        (folder / f"{stem}.json").write_text(json.dumps(info), encoding="utf-8")

    def _recognise(self, tid, frame, blob, keep=False):
        picture = correct_colours(crop(frame, blob), self.settings.get("colour_gains"))
        pred = self.recognizer.predict(picture)
        part, p_conf = pred.parts[0]
        cid, c_conf = pred.colors[0]
        category, g_conf = pred.categories[0] if pred.categories else ("", 0.0)
        colour = self.color_names.get(cid, "?")
        bin_name, reason = rules_mod.choose_bin(self.rules, self.props, part, p_conf, colour, c_conf, 1,
                                                category, g_conf, pred.printed)
        k = self.settings.get("px_per_mm")
        size = f"{self._exact_length(frame, blob) / k:.0f} mm long" if k else ""
        result = {"part": part, "p": p_conf, "colour": colour, "c": c_conf, "bin": bin_name, "reason": reason,
                  "picture": picture, "size": size, "next": pred.parts[1:3],
                  "rgb": tuple(self.colors.get(cid, ("", (200, 200, 200)))[1]),
                  "next_colours": [(self.color_names.get(c, "?"), q) for c, q in pred.colors[1:3]]}
        if keep and not getattr(self, "remote", False):   # Brickognize can't learn from it: nothing to keep
            self._keep(picture, pred, bin_name, reason)
        self.done.put((tid, result))   # picked up by _tick (Tk is only touched from its own thread)

    def _got(self, tid, result):
        if tid in self.tracks:
            self.tracks[tid]["result"] = result
            self.tracks[tid]["busy"] = False
            self._show_list(force=True)

    def _show_list(self, force=False):
        shown = [(tid, t["result"]) for tid, t in sorted(self.tracks.items()) if t["result"]]
        key = [(tid, id(r)) for tid, r in shown]
        if not force and key == getattr(self, "_listed", None):
            return
        self._listed = key
        for w in self.list.winfo_children():
            w.destroy()
        if not shown:
            ttk.Label(self.list, text="Nothing recognised yet." if self.detector else "", foreground=MUTED).pack(
                anchor="w")
        for n, (_, r) in enumerate(shown, 1):
            row = ttk.Frame(self.list)
            row.pack(fill="x", pady=3)
            img = ImageTk.PhotoImage(r["picture"].resize((72, 72)))
            pic = ttk.Label(row, image=img)
            pic.image = img
            pic.pack(side="left")
            text = (f"{n}. {r['part']}  {self.names.get(r['part'], '')} ({r['p']:.0%})\n"
                    + "".join(f"   or {p}  {self.names.get(p, '')} ({q:.0%})\n" for p, q in r["next"])
                    + f"{r['colour']} ({r['c']:.0%})"
                    + "".join(f", or {c} ({q:.0%})" for c, q in r["next_colours"])
                    + (f"\n{r['size']}" if r["size"] else "") + f"\nBin: {r['bin']}")
            ttk.Label(row, text=text, wraplength=240, justify="left").pack(side="left", padx=6)

    def _draw(self, frame):
        img = area_mod.draw(Image.fromarray(frame), self.picker.drawing() or self.settings.get("area"))
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arialbd.ttf", 28)
            small = ImageFont.truetype("arialbd.ttf", 20)
        except OSError:
            font = small = ImageFont.load_default()
        for t in self.tracks.values():
            b, r = t["box"], t["result"]
            if r is None:   # not recognised yet: a plain grey box
                d.rectangle((b.x0, b.y0, b.x1, b.y1), outline=(200, 200, 200), width=2)
                continue
            # like Brickognize: the box in the colour it thinks the piece is, with the part and colour on a tag
            rgb = r["rgb"]
            d.rectangle((b.x0 - 1, b.y0 - 1, b.x1 + 1, b.y1 + 1), outline=(255, 255, 255), width=1)
            d.rectangle((b.x0, b.y0, b.x1, b.y1), outline=rgb, width=4)
            label = f"{'several pieces' if r['part'] == 'multiple' else r['part']}  {r['colour']}"
            x0, y0, x1, y1 = d.textbbox((0, 0), label, font=small)
            w, h = x1 - x0 + 12, y1 - y0 + 8
            top = b.y0 - h if b.y0 - h >= 0 else b.y1          # above the box, or below it at the top edge
            d.rectangle((b.x0, top, b.x0 + w, top + h), fill=rgb)
            dark = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 150   # dark text on light colours
            d.text((b.x0 + 6, top + 4 - y0), label, fill=(20, 20, 20) if dark else (255, 255, 255), font=small)
        if self.detector is None:
            d.text((12, 10), "Learning the empty surface …" if self.learning is not None else
                   "Press 1. Learn the empty surface", fill=(255, 255, 255), font=font)
        self.view.set(img)

    def close(self):
        if self.camera:
            self.camera.close()
        self.destroy()


def run():
    CameraTest().mainloop()


if __name__ == "__main__":
    run()
