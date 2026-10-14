"""Virtual sorting machine: pieces ride a conveyor belt under a camera and get sorted into bins.

Run:  python -m bricksort.conveyor_demo
Bins are set in bins.json (button "Edit bins…").
"""
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from . import catalog, config
from .demo import reference_image
from .viewer import PartViewer
from .ldraw import Library
from .ui import ImageBox, Label, make_copyable
from .sorter import properties, rules as rules_mod
from .sorter.piece_picker import PiecePicker, load_choice
from .sorter.conveyor import (BELTS, DEFAULT_BELT, SPAWN_ALL, SPAWN_CHOSEN, SPAWN_TRAINED, ConveyorWorld, NoPieces,
                              SimBelt, SimCamera, SimClock, SimDiverter)
from .sorter.bin_editor import BinEditor
from .sorter.machine import Machine


def tkimg(img, w, h=None):
    if not isinstance(img, Image.Image):
        img = Image.fromarray(img)
    size = (w, h or w)
    return ImageTk.PhotoImage(img if img.size == size else img.resize(size, Image.BILINEAR))


class ConveyorDemo(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BrickSort – sorting machine (simulation)")
        self.configure(padx=10, pady=10)
        self.lib = Library()
        self.colors = catalog.colors(include_trans=True)
        self.color_names = {cid: n for cid, (n, _) in self.colors.items()}
        self.parts = catalog.load_parts()
        self.names = {p["id"]: p["name"] for p in self.parts}
        self.props = properties.load_all(self.lib)
        self.all_parts = catalog.all_lego_parts(self.lib)   # for "All pieces" on the belt
        self.rng = np.random.default_rng()
        self.recognizer = None
        if config.MODEL_FILE.exists():
            from .model import Recognizer
            self.recognizer = Recognizer()
        self.running = False
        self.tick_no = 0
        self._build_ui()
        self.setup()

    # ---------------------------------------------------------- set-up
    def setup(self):
        """(Re)build the world and the machine from the current bins.json."""
        if getattr(self, "world", None):
            self.world.close()
        self.rules = rules_mod.load()
        self.rules["confidence_needed"] = self.sure.get() / 100   # the slider, not bins.json
        self.bins = rules_mod.bin_names(self.rules)
        try:
            self.world = ConveyorWorld(self.lib, self.parts, self.colors, self.bins, self.rng,
                                       all_parts=self.all_parts, spawn_mode=self.spawn_mode.get(),
                                       belt=self.belt.get(), chosen=self.chosen)
        except NoPieces as e:
            messagebox.showwarning("Can't use these pieces", f"{e}\n\nGoing back to the pieces the model knows.",
                                   parent=self)
            self.spawn_mode.set(SPAWN_TRAINED)
            self._mode_shown = SPAWN_TRAINED
            self.change_chosen.grid_remove()
            self.world = ConveyorWorld(self.lib, self.parts, self.colors, self.bins, self.rng,
                                       all_parts=self.all_parts, spawn_mode=SPAWN_TRAINED, belt=self.belt.get())
        self.world.junk_chance = self.junk.get() / 100
        self.world.pair_chance = self.pairs.get() / 100
        self.clock = SimClock(self.world)
        self.camera = SimCamera(self.world)
        self.diverter = SimDiverter(self.world, self.rules["rest_bin"])
        self.machine = Machine(self.camera, SimBelt(self.world), self.diverter, self.recognizer,
                               self.color_names, self.props, self.clock, self.rules)
        self.machine.calibrate(self.world.empty_belt_frames())
        self.counts = {b: 0 for b in self.bins}
        self.score = {"sorted": 0, "right": 0, "rest": 0, "wrong": 0}
        self.acc = {"known": 0, "part": 0, "color": 0, "both": 0, "unknown": 0, "category": 0, "not_lego": 0,
                    "not_lego_right": 0}
        self._show_accuracy()
        self.score_text.configure(text="No pieces sorted yet.")
        self._fill_bins()
        self.cam_frame, self.blobs = None, []
        self._draw()
        self._show_status()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}
        # ---- toolbar: run controls on the left, the other windows on the right
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 8))
        self.go = ttk.Button(bar, text="▶ Start", width=10, command=self.toggle)
        self.go.pack(side="left")
        ttk.Button(bar, text="↺ Reset", command=self.reset).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Spot check…", command=lambda: self._review("--spot")).pack(side="right")
        ttk.Button(bar, text="Review rest bin…", command=lambda: self._review("--rest")).pack(side="right", padx=6)
        ttk.Button(bar, text="Edit bins…", command=self.edit_bins).pack(side="right")

        # ---- left: the machine, the camera and the last piece
        # (the machine and camera pictures grow and shrink with the window)
        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew")
        over = ttk.LabelFrame(left, text="Machine")
        over.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.overview = ImageBox(over, 640, 360)
        self.overview.pack(fill="both", expand=True, **pad)
        cam_box = ttk.LabelFrame(left, text="Camera (red box = piece found)")
        cam_box.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.cam_view = ImageBox(cam_box, 300, 300)
        self.cam_view.pack(fill="both", expand=True, **pad)
        last = ttk.LabelFrame(left, text="Last piece")
        last.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(8, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=3)
        left.rowconfigure(1, weight=2)
        pics = ttk.Frame(last)
        pics.pack(anchor="w", **pad)
        ttk.Label(pics, text="Photo").grid(row=0, column=0, sticky="w")
        ttk.Label(pics, text="Best guess (drag to turn)").grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.last_pic = Label(pics)
        self.last_pic.grid(row=1, column=0, sticky="n")
        self.guess_pics = pics
        self.guess_pic = Label(pics)  # becomes a 3D view of the model's best guess (drag to spin)
        self.guess_pic.grid(row=1, column=1, padx=(8, 0))
        self.guess_name = Label(pics, text="", wraplength=160, justify="left")
        self.guess_name.grid(row=2, column=1, sticky="nw", padx=(8, 0))
        self.last_text = Label(last, text="Start the machine to see the pieces it recognises.",
                               wraplength=330, justify="left")
        self.last_text.pack(anchor="w", padx=8, pady=(0, 8))

        # ---- right: settings, bins, results
        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        settings = ttk.LabelFrame(right, text="Settings")
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)
        self.settings = settings
        # speed 1 = one simulated second per real second; from 0.1 up to 2 (20x the slowest)
        self.speed = tk.DoubleVar(value=1.0)
        self.speed_text = tk.StringVar(value="1.0×")
        self.junk, self.junk_text = tk.IntVar(value=0), tk.StringVar(value="0%")
        self.pairs, self.pairs_text = tk.IntVar(value=0), tk.StringVar(value="0%")
        # how sure the model must be before a piece goes in a bin (else the rest bin); 0 = always its best guess
        self.sure = tk.IntVar(value=round(rules_mod.load()["confidence_needed"] * 100))
        self.sure_text = tk.StringVar(value=f"{self.sure.get()}%")
        for i, (label, var, shown, lo, hi, tip) in enumerate((
                ("Speed", self.speed, self.speed_text, 0.1, 2, ""),
                ("Non-LEGO objects", self.junk, self.junk_text, 0, 50, "share of objects that aren't LEGO"),
                ("Pieces touching", self.pairs, self.pairs_text, 0, 50, "share of pieces dropped onto another"),
                ("Confidence needed", self.sure, self.sure_text, 0, 100, "less sure than this: rest bin"))):
            ttk.Label(settings, text=label).grid(row=i, column=0, sticky="w", padx=(8, 4), pady=2)
            ttk.Scale(settings, from_=lo, to=hi, variable=var, command=self._sliders).grid(row=i, column=1, sticky="we")
            ttk.Label(settings, textvariable=shown, width=5, anchor="e").grid(row=i, column=2, padx=(4, 8))
        self._steps_due = 0.0
        ttk.Label(settings, text="Pieces").grid(row=4, column=0, sticky="w", padx=(8, 4), pady=(6, 2))
        self.spawn_mode = tk.StringVar(value=SPAWN_TRAINED)
        mode = ttk.Combobox(settings, textvariable=self.spawn_mode, values=[SPAWN_TRAINED, SPAWN_ALL, SPAWN_CHOSEN],
                            state="readonly", width=34)
        mode.grid(row=4, column=1, columnspan=2, sticky="we", padx=(0, 8), pady=(6, 2))
        mode.bind("<<ComboboxSelected>>", lambda e: self._spawn_mode_changed())  # new batch of pieces from that set
        self.chosen = load_choice()
        self._mode_shown = SPAWN_TRAINED
        self.change_chosen = ttk.Button(settings, text="Change chosen pieces…", command=self._pick_pieces)
        ttk.Label(settings, text="Belt").grid(row=6, column=0, sticky="w", padx=(8, 4), pady=(2, 8))
        self.belt = tk.StringVar(value=DEFAULT_BELT)
        belt = ttk.Combobox(settings, textvariable=self.belt, values=list(BELTS), state="readonly", width=34)
        belt.grid(row=6, column=1, columnspan=2, sticky="we", padx=(0, 8), pady=(2, 8))
        belt.bind("<<ComboboxSelected>>", lambda e: self._rebuild("Belt changed"))

        bins = ttk.LabelFrame(right, text="Bins")
        bins.pack(fill="x", pady=(8, 0))
        self.bin_table = ttk.Treeview(bins, columns=("count", "rule"), height=9, selectmode="none")
        self.bin_table.heading("#0", text="Bin", anchor="w")
        self.bin_table.heading("count", text="Pieces", anchor="e")
        self.bin_table.heading("rule", text="Gets", anchor="w")
        self.bin_table.column("#0", width=130, stretch=False)
        self.bin_table.column("count", width=55, anchor="e", stretch=False)
        self.bin_table.column("rule", width=290)
        self.bin_table.pack(fill="x", **pad)

        results = ttk.LabelFrame(right, text="Results")
        results.pack(fill="both", expand=True, pady=(8, 0))
        self.score_text = Label(results, text="No pieces sorted yet.", wraplength=340, justify="left")
        self.score_text.pack(anchor="w", padx=8, pady=(6, 4))
        ttk.Label(results, text="Recognition (checked against the real piece):").pack(anchor="w", padx=8)
        self.acc_text = Label(results, text="Nothing checked yet.", wraplength=340, justify="left")
        self.acc_text.pack(anchor="w", padx=8, pady=(0, 8))

        # ---- bottom: the log, along the whole width so long reasons fit on one line
        bottom = ttk.LabelFrame(self, text="Log")
        bottom.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=4)   # extra height mostly goes to the pictures...
        self.rowconfigure(2, weight=1)   # ...and some to the log
        self.log = tk.Text(bottom, height=7, width=60, state="disabled", font=("Consolas", 9), wrap="word",
                           relief="flat")
        make_copyable(self.log)  # select + Ctrl+C, or right-click > Copy
        log_scroll = ttk.Scrollbar(bottom, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        ttk.Button(bottom, text="Clear", command=self.clear_log).pack(side="right", anchor="n", padx=(0, 8), pady=6)
        log_scroll.pack(side="right", fill="y", pady=6)
        self.log.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)

        self.status = ttk.Label(self, text="", anchor="w", foreground="#555")
        self.status.grid(row=3, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.bind("<space>", self._space)   # Space = start / pause
        if not config.MODEL_FILE.exists():
            self.write("No trained model yet: everything will go to the rest bin.")

    def _space(self, e):
        # a focused button already reacts to Space itself, and the log uses it for typing nothing
        if not isinstance(e.widget, (ttk.Button, ttk.Combobox, tk.Text)):
            self.toggle()

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def reset(self):
        """Empty the belt and the bins, set the counters to zero and pick a new set of pieces."""
        self._rebuild("Reset")

    def _rebuild(self, why):
        self.setup()
        self.write(f"{why}: empty belt, counters set to zero.")

    def _show_status(self):
        state = "Running" if self.running else "Paused – press Start or Space"
        self.status.configure(text=f"{state}   ·   {self.clock.now():.0f} s simulated   ·   "
                                   f"{self.score['sorted']} pieces sorted   ·   belt: {self.belt.get()}")

    def _review(self, flag):
        """Open the review window (the same one as in the drop demo) on the saved pictures."""
        if self.running:
            self.toggle()
        subprocess.Popen([sys.executable, "-m", "bricksort.demo", flag], cwd=config.PROJECT_DIR)

    def _spawn_mode_changed(self):
        if self.spawn_mode.get() == SPAWN_CHOSEN:
            return self._pick_pieces()
        self.change_chosen.grid_remove()
        self._mode_shown = self.spawn_mode.get()
        self.setup()

    def _pick_pieces(self):
        """The 'Pieces I choose' window; afterwards a button to change the choice again."""
        if self.running:
            self.toggle()
        pieces = {p["id"]: p for p in self.all_parts}
        pieces.update({p["id"]: p for p in self.world.candidates})
        picker = PiecePicker(self, list(pieces.values()), self.world.known)
        if picker.chosen:  # Done, with at least one piece
            self.chosen = picker.chosen
            self.spawn_mode.set(SPAWN_CHOSEN)
            self.change_chosen.configure(text=f"Change chosen pieces ({len(self.chosen)})…")
            self.change_chosen.grid(row=5, column=1, columnspan=2, sticky="we", padx=(0, 8), pady=2)
            self._mode_shown = SPAWN_CHOSEN
            self.setup()
            self.write(f"The belt now only gets the {len(self.chosen)} pieces you chose.")
        else:  # closed without choosing: keep what it was
            self.spawn_mode.set(self._mode_shown)
            if picker.chosen is not None:
                self.write("No pieces ticked, so the belt keeps the pieces it had.")

    def _sliders(self, _=None):
        for var in (self.junk, self.pairs, self.sure):
            var.set(int(float(var.get())))
        if getattr(self, "rules", None):  # the machine uses this same dict, so it takes effect right away
            self.rules["confidence_needed"] = self.sure.get() / 100
        self.speed.set(max(0.1, round(float(self.speed.get()), 1)))
        self.speed_text.set(f"{self.speed.get():.1f}×")
        for var, text in ((self.junk, self.junk_text), (self.pairs, self.pairs_text), (self.sure, self.sure_text)):
            text.set(f"{var.get()}%")
        if getattr(self, "world", None):
            self.world.junk_chance = self.junk.get() / 100
            self.world.pair_chance = self.pairs.get() / 100

    def _fill_bins(self):
        t = self.bin_table
        t.delete(*t.get_children())
        for i, b in enumerate(self.bins):
            bin_ = next((x for x in self.rules["bins"] if x["name"] == b), None)
            rule = bin_["when"] if bin_ else None
            if rule is not None:
                desc = rules_mod.describe(rule)
                if "confidence" in bin_:
                    desc += f" (needs {bin_['confidence']:.0%})"
            elif b == self.rules["not_lego_bin"]:
                desc = "things that aren't LEGO"
            else:
                desc = "unsure, or several pieces at once"
            t.insert("", "end", iid=str(i), text=f"{i + 1}. {b}", values=(0, desc))
        t.configure(height=len(self.bins))

    def _count(self, b):
        """Add one piece to bin b in the table."""
        i = self.bins.index(b) if b in self.bins else len(self.bins) - 1
        self.counts[b] = self.counts.get(b, 0) + 1
        self.bin_table.set(str(i), "count", self.counts[b])

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------------------------------------------------------- running
    def toggle(self):
        self.running = not self.running
        self.go.configure(text="⏸ Pause" if self.running else "▶ Start")
        self._show_status()
        if self.running:
            self._last_tick = time.perf_counter()
            self.tick()

    def tick(self):
        if not self.running:
            return
        # Speed 1 = one simulated second per real second (the old slowest speed);
        # 0.1 = ten times slower, 5 = five times faster.
        now = time.perf_counter()
        real = min(now - getattr(self, "_last_tick", now), 0.2)
        self._last_tick = now
        self._steps_due += max(0.1, float(self.speed.get())) * real / self.world.model.opt.timestep
        steps = int(self._steps_due)
        self._steps_due -= steps
        frame = None
        while steps > 0:
            chunk = min(steps, 66)  # a camera picture at least every 0.13 simulated seconds
            steps -= chunk
            self.world.maybe_spawn()
            for slot, b, truth in self.world.step(self.diverter, n=chunk):
                self._arrived(b, truth)
            frame = self.camera.frame()
            blobs, decisions = self.machine.step(frame)
            for d in decisions:
                self._decided(d)
        if frame is not None:
            self.cam_frame, self.blobs = frame, blobs  # (not "self.frame": Tk windows already have a frame())
            self._draw()
            self._show_status()
        self.after(15, self.tick)

    def _check(self, d):
        """Compare the model's guess with what's really on the belt (only possible in the simulation)."""
        truth = self.world.piece_at(d.x_px, d.y_px)
        if truth is None or not d.guesses:
            return ""
        part, color, category, known = truth
        a = self.acc
        if part == "not_lego":
            a["not_lego"] += 1
            ok = d.part == "not_lego"
            a["not_lego_right"] += ok
            return "  ✓ correctly not Lego" if ok else f"  ✗ it was a non-Lego object (guessed {d.part})"
        if known:
            a["known"] += 1
            p_ok, c_ok = catalog.same_piece(d.part, part), catalog.same_colour(d.color) == catalog.same_colour(color)
            a["part"] += p_ok
            a["color"] += c_ok
            a["both"] += p_ok and c_ok
            if p_ok and c_ok:
                return "  ✓ right"
            wrong = [f"part was {part}" if not p_ok else "", f"colour was {color}" if not c_ok else ""]
            return "  ✗ " + ", ".join(w for w in wrong if w)
        a["unknown"] += 1
        g_ok = d.category == category
        a["category"] += g_ok
        return (f"  ✓ unknown part {part}, category right" if g_ok
                else f"  ✗ unknown part {part} ({category}), guessed category {d.category}")

    def _show_accuracy(self):
        a = self.acc
        pct = lambda x, n: f"{x}/{n} ({x / n:.0%})" if n else "–"
        if not (a["known"] or a["unknown"] or a["not_lego"]):
            self.acc_text.configure(text="Nothing checked yet.")
            return
        lines = [f"Known pieces: part {pct(a['part'], a['known'])}, colour {pct(a['color'], a['known'])}, "
                 f"both {pct(a['both'], a['known'])}"]
        if a["unknown"]:
            lines.append(f"Other pieces: category {pct(a['category'], a['unknown'])}")
        if a["not_lego"]:
            lines.append(f"Non-LEGO objects spotted: {pct(a['not_lego_right'], a['not_lego'])}")
        self.acc_text.configure(text="\n".join(lines))

    def edit_bins(self):
        if self.running:
            self.toggle()
        if BinEditor(self, self.parts).saved:
            self.setup()
            self.write("Bins updated.")

    def _decided(self, d):
        verdict = self._check(d)
        self._show_accuracy()
        self.write(f"{self.clock.now():6.1f}s  → {d.bin:14s} {d.reason}{verdict}")
        # building a 3D view takes a moment: at high speed the pictures refresh at most twice a second
        now = time.perf_counter()
        if now - getattr(self, "_last_viewer", 0) < 0.5 and float(self.speed.get()) > 1:
            return
        self._last_viewer = now
        self._set(self.last_pic, tkimg(d.picture, 160))
        self._last_verdict = verdict
        self.guess_pic.destroy()
        if d.guesses:
            best = d.guesses[0][0]
            rgb = next((c for n, c in self.colors.values() if n == d.color), (160, 165, 169))
            self.guess_pic = PartViewer(self.guess_pics, self.lib, best, rgb=rgb, size=160,
                                        fallback=reference_image(best))
            if best in (catalog.MULTIPLE, "not_lego"):   # not a part: just say what it is
                self.guess_name.configure(text=self.names.get(best, best))
            else:
                self.guess_name.configure(text=f"{best} {self.names.get(best, '')}\nColour: {d.color}")
        else:
            self.guess_pic = Label(self.guess_pics)
            self.guess_name.configure(text="(no guess)")
        self.guess_pic.grid(row=1, column=1, padx=(8, 0))
        top = ", ".join(f"{p} {c:.0%}" for p, c in d.guesses[:3])
        self.last_text.configure(text=f"→ {d.bin}\n{d.reason}\nGuesses: {top}\n{verdict.strip()}")

    def _arrived(self, b, truth):
        self._count(b)
        part, color, category, known = truth
        if known or part == "not_lego":
            right_bin, _ = rules_mod.choose_bin(self.rules, self.props, part, 1.0, color, 1.0, 1)
        else:  # a rarer part the model only knows by category
            right_bin, _ = rules_mod.choose_bin(self.rules, self.props, part, -1.0, color, 1.0, 1, category, 1.0)
            part = f"{part} ({category})"
        s = self.score
        s["sorted"] += 1
        if b == right_bin:
            s["right"] += 1
        elif b == self.rules["rest_bin"]:
            s["rest"] += 1
        else:
            s["wrong"] += 1
            self.write(f"        ✗ a {part} {color} went to {b}, should be {right_bin}")
        pct = lambda x: f"{x} ({x / s['sorted']:.0%})"
        self.score_text.configure(text=f"{s['sorted']} pieces sorted\nRight bin: {pct(s['right'])}\n"
                                       f"Set aside in {self.rules['rest_bin']}: {pct(s['rest'])}\n"
                                       f"Wrong bin: {pct(s['wrong'])}")

    def _set(self, label, img):
        label.configure(image=img)
        label.image = img

    def _draw(self):
        self.tick_no += 1
        if self.tick_no % 2 == 0 or not self.running:
            self.overview.set(self.world.render("overview"))
        frame = getattr(self, "cam_frame", None)
        if frame is None:
            frame = self.camera.frame()
        img = Image.fromarray(frame)
        draw = ImageDraw.Draw(img)
        w = img.width
        draw.line([(w / 2, 0), (w / 2, img.height)], fill=(255, 255, 255), width=1)
        for b in getattr(self, "blobs", []):
            draw.rectangle([b.x0, b.y0, b.x1, b.y1], outline=(255, 40, 40), width=2)
        self.cam_view.set(img)


def run():
    ConveyorDemo().mainloop()


if __name__ == "__main__":
    run()
