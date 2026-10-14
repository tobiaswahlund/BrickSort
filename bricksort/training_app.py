"""Model training: make the training pictures, train the model, and look at the pictures, in one window.

Run:  python -m bricksort.training_app   (or double-click "Model training.bat")

Start runs two steps, each in its own background process so the window stays usable:
  1. python -m bricksort.render <pictures per part>   (only makes pictures that are missing)
  2. python -m bricksort.train <rounds>               (saves its progress after every round)
Pause stops the running step. Start again carries on: pictures already made are kept, and a stopped
training continues from the last finished round. The right side shows the training pictures
(the ones being made now, or all of them) so you can check they look right.
"""
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

from . import belts, config, machine_setup
from .ui import MUTED, make_copyable
from .watch import TrainingPictures

CHECKPOINT = config.MODEL_DIR / "training_in_progress.pt"   # same file as train.CHECKPOINT
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

RENDER_LINE = re.compile(r"^\[(\d+)/(\d+)\] (\S+)")
PROGRESS_LINE = re.compile(r"progress (\d+)/(\d+) \(round (\d+)/(\d+)\)")
ROUND_LINE = re.compile(r"^Round (\d+)/(\d+): loss ([\d.]+), simulated test: part right first guess (\d+)%, "
                        r"within top 5 (\d+)%, colour (\d+)%, category (\d+)% \((\d+)s\)")


def _minutes(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


class TrainingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BrickSort – model training")
        self.configure(padx=10, pady=10)
        self.proc, self.running, self.queue = None, False, queue.Queue()
        self._build()
        self._show_resume_note()
        self.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self._read_model_info, daemon=True).start()
        self.after(200, self._pump)

    # ------------------------------------------------------------------ layout
    def _build(self):
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 8))
        self.start_btn = ttk.Button(bar, text="▶ Start training", command=self.start)
        self.start_btn.pack(side="left")
        self.pause_btn = ttk.Button(bar, text="⏸ Pause", command=self.pause, state="disabled")
        self.pause_btn.pack(side="left", padx=6)
        ttk.Button(bar, text="Open data folder", command=lambda: os.startfile(config.BIG_DIR)).pack(side="right")
        ttk.Button(bar, text="Open model folder", command=self._open_models).pack(side="right", padx=6)

        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew")
        tabs = ttk.Notebook(left)
        tabs.pack(fill="x")
        train_tab, setup_tab = ttk.Frame(tabs, padding=6), ttk.Frame(tabs, padding=6)
        tabs.add(train_tab, text="Training")
        tabs.add(setup_tab, text="Machine setup")
        self._build_setup(setup_tab)
        settings = ttk.LabelFrame(train_tab, text="Settings")
        settings.pack(fill="x")
        self.per_part = tk.IntVar(value=100)
        self.rounds = tk.IntVar(value=10)
        self.make_pictures = tk.BooleanVar(value=True)
        self.inputs = []
        for r, (label, var, lo, hi, step) in enumerate((("Pictures per part", self.per_part, 10, 1000, 10),
                                                        ("Training rounds", self.rounds, 1, 100, 1))):
            ttk.Label(settings, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=3)
            sb = ttk.Spinbox(settings, textvariable=var, from_=lo, to=hi, increment=step, width=7)
            sb.grid(row=r, column=1, sticky="w", pady=3)
            self.inputs.append(sb)
        cb = ttk.Checkbutton(settings, text="Make missing training pictures first", variable=self.make_pictures)
        cb.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(3, 6))
        self.inputs.append(cb)
        self.resume_note = ttk.Label(settings, text="", foreground="#a05a00", wraplength=420)
        self.resume_note.grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))

        model = ttk.LabelFrame(train_tab, text="Current model")
        model.pack(fill="x", pady=(8, 0))
        self.model_text = ttk.Label(model, text="Reading the model …", wraplength=440, justify="left")
        self.model_text.pack(anchor="w", padx=8, pady=6)

        prog = ttk.LabelFrame(train_tab, text="Progress")
        prog.pack(fill="x", pady=(8, 0))
        self.step_text = ttk.Label(prog, text="Not running.")
        self.step_text.pack(anchor="w", padx=8, pady=(6, 2))
        self.bar = ttk.Progressbar(prog, maximum=1000, length=420)
        self.bar.pack(fill="x", padx=8)
        self.eta_text = ttk.Label(prog, text="", foreground=MUTED)
        self.eta_text.pack(anchor="w", padx=8, pady=(2, 6))

        rounds = ttk.LabelFrame(train_tab, text="Rounds (tested on simulated pictures it didn't train on)")
        rounds.pack(fill="x", pady=(8, 0))
        cols = ("loss", "part", "top5", "colour", "category", "time")
        self.table = ttk.Treeview(rounds, columns=cols, height=5, selectmode="none")
        self.table.heading("#0", text="Round")
        self.table.column("#0", width=60, stretch=False)
        for c, title in zip(cols, ("Loss", "Part", "Top 5", "Colour", "Category", "Time")):
            self.table.heading(c, text=title)
            self.table.column(c, width=62, anchor="e")
        self.table.pack(fill="x", padx=8, pady=6)
        self.real_text = ttk.Label(rounds, text="", wraplength=440, justify="left")
        self.real_text.pack(anchor="w", padx=8, pady=(0, 6))

        logf = ttk.LabelFrame(left, text="Log")
        logf.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(logf, height=8, width=60, state="disabled", font=("Consolas", 9), wrap="word",
                           relief="flat")
        make_copyable(self.log)
        sb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=6)
        self.log.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)

        pictures = ttk.LabelFrame(self, text="Training pictures")
        pictures.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        self.viewer = TrainingPictures(pictures)
        self.viewer.pack(fill="both", expand=True, padx=8, pady=6)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

    # ------------------------------------------------------------------ machine setup
    def _build_setup(self, outer):
        s = machine_setup.load()
        tab = ttk.Frame(outer)
        tab.grid(row=0, column=0, sticky="nw")
        self.look_frame = ttk.Frame(outer)
        self.look_frame.grid(row=0, column=1, sticky="nw", padx=(10, 0))
        ttk.Label(tab, text="Make the training pictures look like your own machine. Save, then make the "
                            "training pictures again and train.", wraplength=440, foreground=MUTED
                  ).pack(anchor="w", pady=(0, 6))
        self.sv = {}   # setting name -> tk variable

        belt = ttk.LabelFrame(tab, text="Belt")
        belt.pack(fill="x")
        self.sv["belt"] = tk.StringVar(value=s["belt"])
        self.belt_box = ttk.Combobox(belt, textvariable=self.sv["belt"], values=belts.available(), state="readonly",
                                     width=28)
        self.belt_box.grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Button(belt, text="Use a photo of my belt…", command=self._own_belt_photo
                   ).grid(row=0, column=1, sticky="w", pady=4)
        self.sv["own_belt_mm"] = tk.IntVar(value=s["own_belt_mm"])
        ttk.Label(belt, text="Width of belt the photo shows (mm)").grid(row=1, column=0, sticky="w", padx=8)
        ttk.Spinbox(belt, textvariable=self.sv["own_belt_mm"], from_=10, to=500, increment=5, width=6
                    ).grid(row=1, column=1, sticky="w")
        self.sv["all_belts_in_training"] = tk.BooleanVar(value=s["all_belts_in_training"])
        ttk.Checkbutton(belt, text="Train on all belts, not only mine (copes better with changes)",
                        variable=self.sv["all_belts_in_training"]).grid(row=2, column=0, columnspan=2, sticky="w",
                                                                       padx=8, pady=(2, 6))

        cam = ttk.LabelFrame(tab, text="Camera and lamps (mm, measured from the belt)")
        cam.pack(fill="x", pady=(8, 0))
        rows = (("camera_height_mm", "Camera height", 100, 600, 10),
                ("lamps", "Number of lamps", 1, 5, 1),
                ("lamp_height_mm", "Lamp height", 100, 1000, 10),
                ("lamp_side_mm", "Lamps to the side of the camera", 0, 500, 10))
        for r, (key, label, lo, hi, step) in enumerate(rows):
            self.sv[key] = tk.IntVar(value=int(s[key]))
            ttk.Label(cam, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=2)
            ttk.Spinbox(cam, textvariable=self.sv[key], from_=lo, to=hi, increment=step, width=6
                        ).grid(row=r, column=1, sticky="w", pady=2)
        ttk.Label(cam, text="210 mm sees the whole 150 mm wide belt; lower sees less of it.", foreground=MUTED
                  ).grid(row=len(rows), column=0, columnspan=3, sticky="w", padx=8)
        for r, (key, label, lo, hi, show) in enumerate((
                ("brightness", "Brightness", 0.3, 2.0, lambda v: f"{v:.0%}"),
                ("warmth", "Light colour (white to warm)", 0.0, 1.0, lambda v: f"{v:.0%} warm"),
                ("machine_share", "Pictures like my machine", 0, 100, lambda v: f"{v:.0f}%")), start=len(rows) + 1):
            self.sv[key] = tk.DoubleVar(value=float(s[key]))
            text = tk.StringVar(value=show(float(s[key])))
            ttk.Label(cam, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=2)
            ttk.Scale(cam, from_=lo, to=hi, variable=self.sv[key], length=150,
                      command=lambda v, t=text, f=show: t.set(f(float(v)))).grid(row=r, column=1, sticky="w")
            ttk.Label(cam, textvariable=text, width=10).grid(row=r, column=2, sticky="w", padx=4)

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Preview pictures", command=self._preview).pack(side="left")
        ttk.Button(buttons, text="Built-in values", command=self._setup_defaults).pack(side="left", padx=6)
        ttk.Button(buttons, text="Save", command=self._save_setup).pack(side="right")
        self.setup_note = ttk.Label(tab, text="", foreground=MUTED, wraplength=440)
        self.setup_note.pack(anchor="w", pady=(4, 0))
        again = ttk.LabelFrame(tab, text="After changing the set-up")
        again.pack(fill="x", pady=(8, 0))
        ttk.Label(again, text="The training pictures made so far show the old set-up. Make them all again, then "
                              "train (this takes some hours).", wraplength=420).pack(anchor="w", padx=8, pady=(4, 2))
        self.remake_btn = ttk.Button(again, text="Make all training pictures again…", command=self._remake)
        self.remake_btn.pack(anchor="w", padx=8, pady=(0, 6))
        self._build_look(self.look_frame, s)

    def _build_look(self, frame, s):
        """Plastic look learned from your photos, and a 3D preview of a piece with all the settings."""
        box = ttk.LabelFrame(frame, text="Plastic look (learned from your photos)")
        box.pack(fill="x")
        self.sv["real_gloss"] = tk.BooleanVar(value=s["real_gloss"])
        ttk.Checkbutton(box, text="Shine like my photos", variable=self.sv["real_gloss"],
                        command=self._update_look).pack(anchor="w", padx=8, pady=(4, 0))
        self.look_text = ttk.Label(box, text="", foreground=MUTED, wraplength=290, justify="left")
        self.look_text.pack(anchor="w", padx=8, pady=(2, 0))
        ttk.Button(box, text="Learn from my photos", command=self._learn_look).pack(anchor="w", padx=8, pady=6)
        self._show_learned()

        pv = ttk.LabelFrame(frame, text="Preview (drag to turn, scroll to zoom)")
        pv.pack(fill="x", pady=(8, 0))
        self.look_holder = ttk.Frame(pv, width=280, height=280)
        self.look_holder.pack(padx=8, pady=6)
        self.look_holder.pack_propagate(False)
        ttk.Label(self.look_holder, text="Press Update to see a piece\nwith these settings.", foreground=MUTED,
                  justify="center").place(relx=0.5, rely=0.5, anchor="center")
        row = ttk.Frame(pv)
        row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Button(row, text="Update", command=self._update_look).pack(side="left")
        ttk.Button(row, text="Another piece", command=lambda: self._update_look(new_piece=True)).pack(side="left",
                                                                                                    padx=6)
        self.look_piece = None

    def _show_learned(self):
        from . import plastic_look
        got = plastic_look.learned()
        if not got:
            self.look_text.configure(text="Not learned yet: press Learn from my photos (about a minute).")
            return
        self.look_text.configure(text=f"Learned {got['learned']} from {got['photos']} photos: highlights cover "
                                      f"{got['photo_highlights']:.1%} of a piece (renders: "
                                      f"{got['render_highlights']:.1%} with the learned shine).")

    def _learn_look(self):
        if getattr(self, "_learning", False):
            return
        self._learning = True
        self.look_text.configure(text="Learning from your photos … (about a minute)")

        def work():
            from . import plastic_look
            try:
                plastic_look.learn(600, log=lambda t: self.queue.put(("line", t)))
            except Exception as e:
                self.queue.put(("line", f"Learning failed: {e.__class__.__name__}: {e}"))
            self.queue.put(("learned", None))

        threading.Thread(target=work, daemon=True).start()

    def _update_look(self, new_piece=False):
        """Rebuild the 3D preview with the settings as they are in the tab (not saved)."""
        import numpy as np
        from . import catalog
        from .viewer import LookPreview
        machine_setup.use(self._setup_values())
        try:
            if getattr(self, "lib", None) is None:
                from .ldraw import Library
                self.lib = Library()
            if self.look_piece is None or new_piece:
                rng = np.random.default_rng()
                choices = ["3001", "3003", "3039", "3062b", "2420", "3020", "4070", "3040", "3665", "6141"]
                table = catalog.colors()
                names = ["Red", "Blue", "Yellow", "Green", "Orange", "Medium Azure", "Lime", "Dark Bluish Gray"]
                cols = [rgb for n, rgb in table.values() if n in names]
                self.look_piece = (choices[rng.integers(len(choices))], cols[rng.integers(len(cols))])
            if not hasattr(self, "look_view"):
                for w in self.look_holder.winfo_children():
                    w.destroy()
                self.look_view = LookPreview(self.look_holder, self.lib, size=280)
                self.look_view.pack()
            self.look_view.show(*self.look_piece)
        except Exception as e:
            self.write(f"Preview failed: {e.__class__.__name__}: {e}")
        finally:
            machine_setup.load_saved()

    def _setup_values(self):
        """The set-up as typed in the tab, checked and kept within sensible limits."""
        out = {}
        for key, var in self.sv.items():
            try:
                v = var.get()
            except tk.TclError:          # not a number: keep the saved value
                v = machine_setup.load()[key]
            if key in machine_setup.LIMITS:
                lo, hi = machine_setup.LIMITS[key]
                v = min(max(v, lo), hi)
                v = int(round(v)) if isinstance(machine_setup.DEFAULTS[key], int) else round(float(v), 2)
            out[key] = v
        return out

    def _own_belt_photo(self):
        path = filedialog.askopenfilename(parent=self, title="A photo of your belt, taken from straight above",
                                          filetypes=[("Pictures", "*.png *.jpg *.jpeg *.bmp *.webp")])
        if not path:
            return
        machine_setup.set_own_belt(path)
        self.belt_box.configure(values=belts.available())
        self.sv["belt"].set(machine_setup.OWN_BELT)
        self.setup_note.configure(text="Belt photo added (a copy, without the photo's hidden camera and location "
                                       "data). Set how wide a piece of belt it shows, then Preview.")

    def _setup_defaults(self):
        for key, var in self.sv.items():
            var.set(machine_setup.DEFAULTS[key])
        self.setup_note.configure(text="Built-in values filled in (not saved yet).")

    def _save_setup(self):
        machine_setup.save(self._setup_values())
        self.setup_note.configure(text="Saved. New training pictures use it; the sorting machine uses it the next "
                                       "time it starts.")

    def _preview(self):
        """Six pictures of a random known part with the set-up as it is in the tab (not saved)."""
        if getattr(self, "_previewing", False):
            return
        self._previewing = True
        machine_setup.use(self._setup_values())
        self.setup_note.configure(text="Making preview pictures …")

        def work():
            try:
                import numpy as np
                from . import catalog, render
                if getattr(self, "lib", None) is None:
                    from .ldraw import Library
                    self.lib = Library()
                rng = np.random.default_rng()
                parts = [p for p in catalog.load_parts() if not p.get("custom") and not p.get("photos_only")
                         and p["id"] not in ("not_lego", "multiple")]
                for _ in range(10):   # some parts have no 3D model: try another
                    part = parts[rng.integers(len(parts))]
                    try:
                        pics = render.preview(self.lib, part, catalog.colors(include_trans=True), 6, rng)
                        break
                    except ValueError:
                        continue
                self.queue.put(("preview", (part, pics)))
            except Exception as e:
                self.queue.put(("preview", (None, f"{e.__class__.__name__}: {e}")))
            finally:
                machine_setup.use(machine_setup.load_saved())

        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, part, pics):
        self._previewing = False
        if part is None:
            self.setup_note.configure(text=f"Couldn't make a preview ({pics}).")
            return
        self.setup_note.configure(text="")
        win = tk.Toplevel(self)
        win.title(f"Preview: {part['id']} {part['name']}")
        win.configure(padx=8, pady=8)
        win.images = []
        for k, img in enumerate(pics):
            photo = ImageTk.PhotoImage(img.resize((200, 200)))
            win.images.append(photo)
            ttk.Label(win, image=photo).grid(row=k // 3, column=k % 3, padx=3, pady=3)
        ttk.Label(win, text="Taken like your machine's camera, with the set-up as it is in the tab.",
                  foreground=MUTED).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _remake(self):
        if self.running:
            messagebox.showinfo("Training is running", "Pause the training first.", parent=self)
            return
        folders = [d for d in (config.RENDERS, config.CATEGORY_RENDERS) if d.exists()]
        n = sum(1 for d in folders for _ in d.glob("*/*.png"))
        if not messagebox.askyesno(
                "Make all training pictures again",
                f"Delete all {n:,} training pictures, so the next Start makes them again with the saved machine "
                "set-up?\n\nThey can't be brought back, but they can always be made again (that takes some "
                "hours). Your own photos and corrections are not touched.", parent=self):
            return
        self._save_setup()
        for d in folders:
            shutil.rmtree(d, ignore_errors=True)
        self.make_pictures.set(True)
        self.write(f"Deleted {n:,} training pictures. Press Start to make them again with the machine set-up, "
                   "then train.")
        self.viewer.all_files = None

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _open_models(self):
        config.MODEL_DIR.mkdir(exist_ok=True)
        os.startfile(config.MODEL_DIR)

    def _show_resume_note(self):
        if CHECKPOINT.exists():
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(CHECKPOINT.stat().st_mtime))
            self.resume_note.configure(text=f"A stopped training (last saved {when}) carries on where it stopped; "
                                            "its number of rounds was set when it began.")
            self.start_btn.configure(text="▶ Continue training")
        else:
            self.resume_note.configure(text="")
            self.start_btn.configure(text="▶ Start training")

    def _read_model_info(self):
        """Runs in the background (loading torch takes a few seconds)."""
        if not config.MODEL_FILE.exists():
            self.queue.put(("model", "No trained model yet. Press Start to train the first one."))
            return
        try:
            import torch
            ckpt = torch.load(config.MODEL_FILE, map_location="cpu", weights_only=True)
            i = ckpt.get("info", {})
            text = (f"Trained {i.get('trained', '?')}, knows {len(ckpt['classes'])} parts.\n"
                    f"Simulated test: part right {i.get('top1', 0):.0%} (top 5 {i.get('top5', 0):.0%}), "
                    f"colour {i.get('color', 0):.0%}.")
            if i.get("real_test_n"):
                text += (f"\nYour {i['real_test_n']} set-aside photos: part right {i['real_top1']:.0%}, "
                         f"colour {i['real_color']:.0%} (same kind of photos as it trained on, so optimistic).")
        except Exception as e:
            text = f"Couldn't read the model file ({e.__class__.__name__})."
        self.queue.put(("model", text))

    # ------------------------------------------------------------------ running
    def start(self):
        if self.running:
            return
        try:
            per_part, rounds = int(self.per_part.get()), int(self.rounds.get())
            if per_part < 1 or rounds < 1:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showwarning("Check the settings", "Pictures per part and rounds must be whole numbers above 0.",
                                   parent=self)
            return
        steps = []
        if self.make_pictures.get():
            steps.append(("Making training pictures", ["-m", "bricksort.render", str(per_part)]))
        steps.append(("Training", ["-m", "bricksort.train", str(rounds)]))
        self.running = True
        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal")
        for w in self.inputs:
            w.configure(state="disabled")
        for item in self.table.get_children():
            self.table.delete(item)
        self.real_text.configure(text="")
        self.write(f"--- {time.strftime('%H:%M')} started")
        threading.Thread(target=self._run_steps, args=(steps,), daemon=True).start()

    def _run_steps(self, steps):
        """Background thread: run the steps one after the other, passing their output on."""
        ok = True
        for name, args in steps:
            self.queue.put(("step", name))
            self.proc = subprocess.Popen(
                [sys.executable, *args], cwd=config.PROJECT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
            for line in self.proc.stdout:
                self.queue.put(("line", line.rstrip()))
            code = self.proc.wait()
            if not self.running:          # paused
                ok = False
                break
            if code != 0:
                self.queue.put(("line", f"{name} stopped with an error (code {code}); see above."))
                ok = False
                break
        self.proc = None
        self.queue.put(("done", ok))

    def pause(self):
        """Stop the running step (and the helper processes it started). Nothing finished is lost."""
        if not self.running:
            return
        self.running = False
        self.pause_btn.configure(state="disabled")
        self.step_text.configure(text="Pausing …")
        proc = self.proc
        if proc and proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=NO_WINDOW)

    def _pump(self):
        try:
            while True:
                kind, value = self.queue.get_nowait()
                if kind == "line":
                    self._line(value)
                elif kind == "step":
                    self.stage, self.stage_t0 = value, time.time()
                    self.step_text.configure(text=value + " …")
                    self.bar.configure(value=0)
                    self.eta_text.configure(text="")
                elif kind == "model":
                    self.model_text.configure(text=value)
                elif kind == "preview":
                    self._show_preview(*value)
                elif kind == "learned":
                    self._learning = False
                    self._show_learned()
                    self._update_look()
                elif kind == "done":
                    self._finished(value)
        except queue.Empty:
            pass
        self.after(200, self._pump)

    def _progress(self, fraction, text):
        self.bar.configure(value=int(1000 * fraction))
        self.step_text.configure(text=text)
        spent = time.time() - self.stage_t0
        if 0.02 < fraction < 1:
            self.eta_text.configure(text=f"{_minutes(spent)} so far, about {_minutes(spent / fraction - spent)} left")

    def _line(self, line):
        m = RENDER_LINE.match(line)
        if m:   # one part's pictures done (one line per part: too many for the log)
            k, n, part = int(m.group(1)), int(m.group(2)), m.group(3)
            self._progress(k / n, f"Making training pictures: part {k} of {n} ({part})")
            return
        m = PROGRESS_LINE.search(line)
        if m:
            b, nb, r, nr = map(int, m.groups())
            self._progress(((r - 1) + b / nb) / nr, f"Training: round {r} of {nr}")
            return
        m = ROUND_LINE.match(line)
        if m:
            r, nr, loss, part, top5, colour, cat, secs = m.groups()
            self.table.insert("", "end", text=f"{r}/{nr}", values=(loss, f"{part}%", f"{top5}%", f"{colour}%",
                                                                   f"{cat}%", _minutes(int(secs))))
        if line.startswith("On your"):
            self.real_text.configure(text=line)
        self.write(line)

    def _finished(self, ok):
        self.running = False
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        for w in self.inputs:
            w.configure(state="normal")
        self._show_resume_note()
        if ok:
            self.bar.configure(value=1000)
            self.step_text.configure(text="Done: the demo and the sorting machine now use the new model.")
            self.eta_text.configure(text="")
            self.write(f"--- {time.strftime('%H:%M')} finished")
            self.bell()
            threading.Thread(target=self._read_model_info, daemon=True).start()
        else:
            self.step_text.configure(text="Paused. Press Start to carry on where it stopped.")
            self.eta_text.configure(text="")
            self.write(f"--- {time.strftime('%H:%M')} paused")

    def close(self):
        if self.running:
            if not messagebox.askyesno("Training is running", "Pause the training and close?\n"
                                       "Nothing finished is lost; Start carries on later.", parent=self):
                return
            self.pause()
        self.destroy()


def run():
    TrainingApp().mainloop()


if __name__ == "__main__":
    run()
