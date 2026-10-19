"""Camera test: the first real-world step. A real webcam looks down at a surface; you put pieces under
it by hand, and BrickSort finds them (red boxes) and says what they are and which bin they'd go to.
The same finding, cropping, recognising and bin choice as the sorting machine, only without a belt.

Run:  python -m bricksort.camera_test   (or Camera test in the BrickSort menu)

1. Point the camera straight down at a plain surface (ideally the belt you'll use), about 20 cm up.
2. Learn the empty surface: nothing under the camera, then press the button.
3. Measure: put a 2x4 brick (studs up, lined up with the picture's edges) under it and press the
   button. Now BrickSort knows how many pixels are one millimetre (it checks piece sizes with that).
4. Put pieces under the camera, a few cm apart. Once a piece lies still, it's recognised.
Settings are kept in real_machine.json (camera, pixels per mm).
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
from .sorter import properties
from .sorter import rules as rules_mod
from .sorter.detector import Detector, crop
from .ui import MUTED, ImageBox, Label, use_logo

SETTINGS = config.PROJECT_DIR / "real_machine.json"
DEFAULTS = {"camera": 0, "px_per_mm": None, "width": 1280, "height": 720}
BRICK_2X4_MM = 32.0       # a 2x4 brick seen from above: 32 x 16 mm
STILL_FRAMES = 6          # a piece is recognised once it has stayed put this many pictures


def load_settings():
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(s):
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


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
        self.measure_btn = ttk.Button(bar, text="2. Measure with a 2x4 brick", command=self.measure)
        self.measure_btn.pack(side="left", padx=6)
        ttk.Button(bar, text="Forget the pieces", command=self.forget).pack(side="left")
        self.scale_text = ttk.Label(bar, text="", foreground=MUTED)
        self.scale_text.pack(side="right")

        view = ttk.LabelFrame(self, text="Camera (red box = piece found)")
        view.grid(row=1, column=0, sticky="nsew")
        self.view = ImageBox(view, 800, 450)
        self.view.pack(fill="both", expand=True, padx=8, pady=6)

        side = ttk.LabelFrame(self, text="Pieces recognised")
        side.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        self.list = ttk.Frame(side)
        self.list.pack(fill="both", expand=True, padx=8, pady=6)
        self.status = Label(self, text="Opening the camera …", foreground=MUTED, wraplength=1100, justify="left")
        self.status.grid(row=2, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=1, minsize=330)
        self.rowconfigure(1, weight=1)
        self._show_scale()

    def _show_scale(self):
        k = self.settings.get("px_per_mm")
        self.scale_text.configure(text=f"{k:.2f} pixels per mm" if k else "Not measured yet")

    # ------------------------------------------------------------------ camera
    def _load_model(self):
        if config.MODEL_FILE.exists():
            from .model import Recognizer
            self.recognizer = Recognizer()

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

    def measure(self):
        boxes = [t["box"] for t in self.tracks.values()]
        if self.detector is None or len(boxes) != 1:
            self.status.configure(text="To measure: learn the empty surface first, then put exactly one 2x4 brick "
                                       "under the camera, studs up and lined up with the picture's edges.")
            return
        b = boxes[0]
        long_px = max(b.x1 - b.x0, b.y1 - b.y0)
        self.settings["px_per_mm"] = long_px / BRICK_2X4_MM
        save_settings(self.settings)
        self._show_scale()
        self.status.configure(text=f"Measured: {self.settings['px_per_mm']:.2f} pixels per mm "
                                   f"(the brick was {long_px} pixels long). Saved.")

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
                    self.status.configure(text="Learned. Now put pieces under the camera, a few cm apart. "
                                               "Measure once with a 2x4 brick (button 2) so sizes are known.")
            while not self.done.empty():
                self._got(*self.done.get())
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
            if t["still"] >= STILL_FRAMES and t["result"] is None and not t["busy"] and self.recognizer:
                t["busy"] = True
                threading.Thread(target=self._recognise, args=(best, crop(frame, b), b), daemon=True).start()
        for tid in [t for t in self.tracks if t not in seen]:   # taken away
            del self.tracks[tid]
        self._show_list()

    def _recognise(self, tid, picture, blob):
        pred = self.recognizer.predict(picture)
        part, p_conf = pred.parts[0]
        cid, c_conf = pred.colors[0]
        category, g_conf = pred.categories[0] if pred.categories else ("", 0.0)
        colour = self.color_names.get(cid, "?")
        bin_name, reason = rules_mod.choose_bin(self.rules, self.props, part, p_conf, colour, c_conf, 1,
                                                category, g_conf, pred.printed)
        k = self.settings.get("px_per_mm")
        size = f"{blob.long_side / k:.0f} mm long" if k else ""
        result = {"part": part, "p": p_conf, "colour": colour, "c": c_conf, "bin": bin_name, "reason": reason,
                  "picture": picture, "size": size}
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
            text = (f"{n}. {r['part']}  {self.names.get(r['part'], '')}\n"
                    f"{r['colour']} · part {r['p']:.0%}, colour {r['c']:.0%}"
                    + (f" · {r['size']}" if r["size"] else "") + f"\nBin: {r['bin']}")
            ttk.Label(row, text=text, wraplength=240, justify="left").pack(side="left", padx=6)

    def _draw(self, frame):
        img = Image.fromarray(frame)
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arialbd.ttf", 28)
        except OSError:
            font = ImageFont.load_default()
        numbers = {tid: n for n, tid in enumerate((t for t in sorted(self.tracks) if self.tracks[t]["result"]), 1)}
        for tid, t in self.tracks.items():
            b = t["box"]
            colour = (220, 30, 30) if t["result"] else (240, 160, 40)   # orange: still deciding
            d.rectangle((b.x0, b.y0, b.x1, b.y1), outline=colour, width=3)
            if tid in numbers:
                d.text((b.x0 + 6, b.y0 + 2), str(numbers[tid]), fill=colour, font=font)
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
