"""Real machine: the sorting machine with a real webcam, belt and chute (an Arduino over USB).

Run:  python -m bricksort.real_machine   (or Real machine in the BrickSort menu)

The same sorting logic as the virtual machine (sorter/machine.py); only the camera, belt and chute
are real (sorter/hardware.py). Without an Arduino it still runs with the camera alone ("no Arduino"):
slide pieces under the camera by hand in the belt's direction and see what it would decide.

Set up once, in this order:
  1. Camera test: point the camera down at the belt and measure with a 2x4 brick (pixels per mm).
  2. Here: choose the Arduino's port, press Connect, and try "Run the belt" and "Turn the chute".
  3. Measure the distance from the middle of the camera picture to where pieces fall off the belt,
     and the belt speed you'll use.
  4. Learn the empty belt (nothing on it, belt running), then Start sorting.
Settings are kept in real_machine.json, the bins in bins.json (Edit bins in the sorting machine).
"""
import time
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageFont

from . import catalog, config
from .camera_test import Camera as LiveFeed
from .camera_test import find_cameras, load_settings, save_settings
from .ldraw import Library
from .sorter import area as area_mod
from .sorter import hardware, properties
from .sorter import rules as rules_mod
from .sorter.machine import Machine
from .ui import MUTED, ImageBox, Label, make_copyable, use_logo

NO_ARDUINO = "No Arduino (camera only)"
MACHINE_DEFAULTS = {"port": NO_ARDUINO, "speed_mm_s": 40.0, "camera_to_end_mm": 250.0, "belt_direction": 1,
                    "chute_lead_s": 0.4}


class WebcamFeed(hardware.Camera):
    """The live webcam picture as the sorting logic's camera."""

    def __init__(self, feed, px_per_mm, belt_direction):
        self.feed, self.px_per_mm, self.belt_direction = feed, px_per_mm, belt_direction

    def frame(self):
        return self.feed.latest


class HandMoved(hardware.Belt, hardware.Diverter):
    """No Arduino: nothing moves by itself and no chute turns; the decisions are only shown."""

    def __init__(self, speed_mm_s, camera_to_end_mm):
        self.speed_mm_s, self.camera_to_end_mm = speed_mm_s, camera_to_end_mm

    def send(self, bin_name, arrive_at):
        pass

    def close(self):
        pass


def list_ports():
    try:
        from serial.tools import list_ports as lp
        return [f"{p.device}  {p.description}" for p in lp.comports()]
    except ImportError:
        return []


class RealMachine(tk.Tk):
    def __init__(self):
        super().__init__()
        use_logo(self)
        self.title("BrickSort – real machine")
        self.configure(padx=10, pady=10)
        self.geometry("1300x820")
        self.settings = {**MACHINE_DEFAULTS, **load_settings()}
        self.feed, self.link, self.machine = None, None, None
        self.running = False
        self.learning = None
        self.counts = {}
        self.colors = catalog.colors(include_trans=True)
        self.color_names = {cid: n for cid, (n, _) in self.colors.items()}
        self.lib = Library()
        self.props = properties.load_all(self.lib)
        self.recognizer = None
        if config.MODEL_FILE.exists():
            from .model import Recognizer
            self.recognizer = Recognizer()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self._open_camera)

    # ------------------------------------------------------------------ layout
    def _build(self):
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew")
        view = ttk.LabelFrame(left, text="Camera (red box = piece found; the line is where it's photographed)")
        view.pack(fill="both", expand=True)
        self.view = ImageBox(view, 820, 460)
        self.view.pack(fill="both", expand=True, padx=8, pady=6)
        self.picker = area_mod.AreaPicker(self.view, self._area_drawn)
        log_box = ttk.LabelFrame(left, text="What it decided")
        log_box.pack(fill="x", pady=(8, 0))
        self.log = tk.Text(log_box, height=8, state="disabled", font=("Consolas", 9), wrap="word", relief="flat")
        make_copyable(self.log)
        self.log.pack(fill="x", padx=8, pady=6)

        side = ttk.Frame(self)
        side.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        conn = ttk.LabelFrame(side, text="Machine", padding=8)
        conn.pack(fill="x")
        ttk.Label(conn, text="Camera").grid(row=0, column=0, sticky="w")
        self.cam_choice = ttk.Combobox(conn, width=8, state="readonly")
        self.cam_choice.grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(conn, text="Arduino").grid(row=1, column=0, sticky="w")
        self.port = ttk.Combobox(conn, width=30, state="readonly", values=[NO_ARDUINO, *list_ports()])
        self.port.set(self.settings["port"] if self.settings["port"] in self.port["values"] else NO_ARDUINO)
        self.port.grid(row=1, column=1, sticky="we", pady=2)
        self.connect_btn = ttk.Button(conn, text="Connect", command=self.connect)
        self.connect_btn.grid(row=2, column=1, sticky="w", pady=(2, 0))
        self.vars = {}
        rows = [("speed_mm_s", "Belt speed (mm/s)"), ("camera_to_end_mm", "Camera middle → chute (mm)"),
                ("chute_lead_s", "Turn the chute early (s)")]
        for k, (key, text) in enumerate(rows, start=3):
            ttk.Label(conn, text=text).grid(row=k, column=0, sticky="w")
            self.vars[key] = tk.StringVar(value=f"{self.settings[key]:g}")
            ttk.Entry(conn, textvariable=self.vars[key], width=10).grid(row=k, column=1, sticky="w", pady=2)
        ttk.Label(conn, text="Belt moves").grid(row=6, column=0, sticky="w")
        self.direction = ttk.Combobox(conn, width=16, state="readonly", values=["left to right", "right to left"])
        self.direction.set("left to right" if self.settings["belt_direction"] > 0 else "right to left")
        self.direction.grid(row=6, column=1, sticky="w", pady=2)
        ttk.Label(conn, text="Look at").grid(row=8, column=0, sticky="w")
        self.area_choice = ttk.Combobox(conn, width=16, state="readonly", values=list(area_mod.SHAPES))
        shape = (self.settings.get("area") or {}).get("shape")
        self.area_choice.set({"rect": "Rectangle", "circle": "Circle"}.get(shape, "Whole picture"))
        self.area_choice.grid(row=8, column=1, sticky="w", pady=2)
        self.area_choice.bind("<<ComboboxSelected>>", lambda e: self._area_chosen())
        k = self.settings.get("px_per_mm")
        self.scale_text = Label(conn, text=f"Camera: {k:.2f} pixels per mm (from the camera test)" if k else
                                "Not measured: do 2. Measure in the camera test first.", foreground=MUTED,
                                wraplength=300)
        self.scale_text.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

        test = ttk.LabelFrame(side, text="Try the parts", padding=8)
        test.pack(fill="x", pady=(8, 0))
        ttk.Button(test, text="Run the belt 3 s", command=self.try_belt).grid(row=0, column=0, sticky="w")
        self.bin_choice = ttk.Combobox(test, width=18, state="readonly")
        self.bin_choice.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(test, text="Turn the chute", command=self.try_chute).grid(row=1, column=1, sticky="w",
                                                                            padx=6, pady=(6, 0))

        run = ttk.LabelFrame(side, text="Sorting", padding=8)
        run.pack(fill="x", pady=(8, 0))
        ttk.Button(run, text="Learn the empty belt", command=self.learn).pack(fill="x")
        self.go_btn = ttk.Button(run, text="▶ Start sorting", command=self.toggle)
        self.go_btn.pack(fill="x", pady=(6, 0))
        self.counts_text = Label(run, text="", foreground=MUTED, wraplength=300, justify="left")
        self.counts_text.pack(anchor="w", pady=(6, 0))
        self.status = Label(self, text="Opening the camera …", foreground=MUTED, wraplength=1200, justify="left")
        self.status.grid(row=1, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rules = rules_mod.load()
        self.bin_choice.configure(values=rules_mod.bin_names(self.rules))
        self.bin_choice.current(0)

    # ------------------------------------------------------------------ settings and parts
    def _read_settings(self):
        try:
            for key, var in self.vars.items():
                self.settings[key] = float(var.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning("Check the numbers", "Belt speed, distance and time must be numbers.", parent=self)
            return False
        self.settings["belt_direction"] = 1 if self.direction.get() == "left to right" else -1
        self.settings["port"] = self.port.get()
        save_settings(self.settings)
        return True

    def _open_camera(self):
        found = find_cameras()
        if not found:
            self.status.configure(text="No camera found. Plug in the webcam and open Real machine again.")
            return
        self.cam_choice.configure(values=[str(i) for i in found])
        index = self.settings["camera"] if self.settings["camera"] in found else found[0]
        self.cam_choice.set(str(index))
        self.feed = LiveFeed(index, self.settings["width"], self.settings["height"])
        self.status.configure(text="Camera on. Choose the Arduino and press Connect (or run with the camera only), "
                                   "then Learn the empty belt.")
        self._tick()

    def connect(self):
        if not self._read_settings():
            return
        if self.link:
            self.link.close()
            self.link = None
        port = self.port.get()
        if port == NO_ARDUINO:
            self.write("No Arduino: decisions are only shown. Slide pieces under the camera by hand, "
                       f"{self.direction.get()}.")
            return
        try:
            self.link = hardware.SerialMachine(port.split()[0], bins=rules_mod.bin_names(self.rules),
                                               speed_mm_s=self.settings["speed_mm_s"],
                                               camera_to_end_mm=self.settings["camera_to_end_mm"],
                                               chute_lead_s=self.settings["chute_lead_s"])
        except Exception as e:   # wrong port, no board, no permission...
            self.write(f"Couldn't connect on {port}: {e}")
            return
        self.write("Connected: the Arduino answers." if self.link.ping() else
                   "The port opened, but the Arduino doesn't answer. Is bricksort_machine.ino uploaded to it?")

    def try_belt(self):
        if not self.link:
            self.write("Connect the Arduino first.")
            return
        if self._read_settings():
            self.link.speed_mm_s = self.settings["speed_mm_s"]
            self.link.start()
            self.after(3000, self.link.stop)
            self.write(f"Belt running at {self.settings['speed_mm_s']:g} mm/s for 3 seconds.")

    def try_chute(self):
        if not self.link:
            self.write("Connect the Arduino first.")
            return
        answer = self.link.turn_to(self.bin_choice.current())
        self.write(f"Chute to bin {self.bin_choice.current() + 1} ({self.bin_choice.get()}): {answer or 'no answer'}")

    # ------------------------------------------------------------------ sorting
    def learn(self):
        if self.feed is None:
            return
        self.learning = []
        self.machine = None
        self.write("Learning the empty belt: keep it clear (let it run if it's connected) …")
        if self.link:
            self.link.start()

    def _make_machine(self, frames):
        if not self._read_settings():
            return
        k = self.settings.get("px_per_mm") or 4.0
        camera = WebcamFeed(self.feed, k, self.settings["belt_direction"])
        belt = self.link or HandMoved(self.settings["speed_mm_s"], self.settings["camera_to_end_mm"])
        if self.link:
            self.link.speed_mm_s = self.settings["speed_mm_s"]
            self.link.camera_to_end_mm = self.settings["camera_to_end_mm"]
            self.link.chute_lead_s = self.settings["chute_lead_s"]
        self.rules = rules_mod.load()
        self.machine = Machine(camera, belt, belt, self.recognizer, self.color_names, self.props,
                               hardware.Clock(), self.rules)
        self.machine.calibrate(frames)
        self._apply_area()
        self.counts = {}
        self.write("Learned the empty belt. Press Start sorting.")
        if self.link and not self.running:
            self.link.stop()

    def _area_chosen(self):
        shape = area_mod.SHAPES[self.area_choice.get()]
        if shape is None:
            self._area_drawn(None)
        else:
            self.picker.begin(shape)
            self.write(f"Drag on the picture to draw the {self.area_choice.get().lower()}: only what's inside "
                       "it is looked at (e.g. just the belt).")

    def _area_drawn(self, area):
        self.settings["area"] = area
        save_settings(self.settings)
        self._apply_area()
        self.write("Looking at the whole picture." if area is None else "Area set: only pieces inside it count.")

    def _apply_area(self):
        frame = self.feed.latest if self.feed else None
        if self.machine is not None and frame is not None:
            h, w = frame.shape[:2]
            self.machine.detector.set_area(area_mod.mask(self.settings.get("area"), w, h))

    def toggle(self):
        if self.machine is None:
            self.write("Learn the empty belt first.")
            return
        self.running = not self.running
        self.go_btn.configure(text="■ Stop" if self.running else "▶ Start sorting")
        if self.link:
            (self.link.start if self.running else self.link.stop)()
        self.write("Sorting." if self.running else "Stopped.")

    def _tick(self):
        frame = self.feed.latest if self.feed else None
        blobs = []
        if frame is not None:
            if self.learning is not None:
                self.learning.append(frame)
                if len(self.learning) >= 24:
                    frames, self.learning = self.learning, None
                    self._make_machine(frames)
            elif self.machine and self.running:
                blobs, decisions = self.machine.step(frame)
                for d in decisions:
                    self.counts[d.bin] = self.counts.get(d.bin, 0) + 1
                    self.write(f"{time.strftime('%H:%M:%S')}  {d.part or '?'} {d.color}  →  {d.bin}  ({d.reason})")
                if decisions:
                    self.counts_text.configure(text="\n".join(f"{b}: {n}" for b, n in sorted(self.counts.items())))
            elif self.machine:
                blobs = self.machine.detector.find(frame)
            self._draw(frame, blobs)
        self.after(50, self._tick)

    def _draw(self, frame, blobs):
        img = area_mod.draw(Image.fromarray(frame), self.picker.drawing() or self.settings.get("area"))
        d = ImageDraw.Draw(img)
        w, h = img.size
        d.line((w // 2, 0, w // 2, h), fill=(255, 255, 255), width=1)
        for b in blobs:
            d.rectangle((b.x0, b.y0, b.x1, b.y1), outline=(220, 30, 30), width=3)
        if self.learning is not None:
            try:
                font = ImageFont.truetype("arialbd.ttf", 28)
            except OSError:
                font = ImageFont.load_default()
            d.text((12, 10), "Learning the empty belt …", fill=(255, 255, 255), font=font)
        self.view.set(img)

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status.configure(text=text)

    def close(self):
        self.running = False
        if self.link:
            self.link.close()
        if self.feed:
            self.feed.close()
        self.destroy()


def run():
    RealMachine().mainloop()


if __name__ == "__main__":
    run()
