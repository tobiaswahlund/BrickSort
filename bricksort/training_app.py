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
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import config
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
        settings = ttk.LabelFrame(left, text="Settings")
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

        model = ttk.LabelFrame(left, text="Current model")
        model.pack(fill="x", pady=(8, 0))
        self.model_text = ttk.Label(model, text="Reading the model …", wraplength=440, justify="left")
        self.model_text.pack(anchor="w", padx=8, pady=6)

        prog = ttk.LabelFrame(left, text="Progress")
        prog.pack(fill="x", pady=(8, 0))
        self.step_text = ttk.Label(prog, text="Not running.")
        self.step_text.pack(anchor="w", padx=8, pady=(6, 2))
        self.bar = ttk.Progressbar(prog, maximum=1000, length=420)
        self.bar.pack(fill="x", padx=8)
        self.eta_text = ttk.Label(prog, text="", foreground=MUTED)
        self.eta_text.pack(anchor="w", padx=8, pady=(2, 6))

        rounds = ttk.LabelFrame(left, text="Rounds (tested on simulated pictures it didn't train on)")
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
