"""BrickSort: one window to open every part of the project.

Run:  python -m bricksort.app   (or double-click "BrickSort.bat", or bricksort-app)

Each button opens that program in its own window, exactly as its own .bat file would, so they can
run side by side and closing this menu doesn't close them. Test accuracy shows its result here.
"""
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from . import config
from .ui import ASSETS, MUTED, make_copyable, use_logo

# (section, [(button, module and arguments, what it does)])
TOOLS = [
    ("Try it", [
        ("Demo", ["bricksort.demo"],
         "Drop a virtual piece and see what the model thinks it is. Correct it when it's wrong."),
        ("Sorting machine", ["bricksort.conveyor_demo"],
         "The virtual sorting machine: pieces on a belt, sorted into bins by your rules."),
    ]),
    ("Your own photos", [
        ("Cut out pieces", ["bricksort.cut"],
         "One picture per piece from photos of several pieces, for training (my_photos/_to_cut)."),
        ("Cut out test pieces", ["bricksort.cut", "--test"],
         "The same for the honest test, without the model's guesses (my_photos/_to_cut_test)."),
        ("Check colours", ["bricksort.colour_review"],
         "Look through photos by colour and fix the ones in the wrong colour."),
    ]),
    ("The model", [
        ("Model training", ["bricksort.training_app"],
         "Make the training pictures, set up your machine, and train."),
        ("Test accuracy", None,
         "Score the model on your test pieces (my_photos/_test). The result is shown here."),
    ]),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        use_logo(self)
        self.title("BrickSort")
        self.configure(padx=16, pady=14)
        self.minsize(520, 0)
        self.columnconfigure(0, weight=1)

        head = ttk.Frame(self)
        head.grid(row=0, column=0, sticky="we", pady=(0, 10))
        logo = Image.open(ASSETS / "logo.png").resize((72, 72), Image.LANCZOS)
        self._logo_small = ImageTk.PhotoImage(logo)
        ttk.Label(head, image=self._logo_small).pack(side="left", padx=(0, 12))
        words = ttk.Frame(head)
        words.pack(side="left", fill="x", expand=True)
        ttk.Label(words, text="BrickSort", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(words, text="Recognise LEGO pieces from a camera picture and sort them.",
                  foreground=MUTED).pack(anchor="w")

        row = 1
        for section, tools in TOOLS:
            box = ttk.LabelFrame(self, text=section, padding=(10, 6))
            box.grid(row=row, column=0, sticky="we", pady=4)
            box.columnconfigure(1, weight=1)
            for k, (name, args, what) in enumerate(tools):
                command = self.test_accuracy if args is None else (lambda n=name, a=args: self.open(n, a))
                ttk.Button(box, text=name, width=20, command=command).grid(row=k, column=0, sticky="w", pady=3)
                ttk.Label(box, text=what, foreground=MUTED, wraplength=380, justify="left").grid(
                    row=k, column=1, sticky="w", padx=(10, 0))
            row += 1

        foot = ttk.Frame(self)
        foot.grid(row=row, column=0, sticky="we", pady=(10, 0))
        ttk.Button(foot, text="Open my photos", command=lambda: self.folder(config.MY_PHOTOS)).pack(side="left")
        ttk.Button(foot, text="Open data folder", command=lambda: self.folder(config.BIG_DIR)).pack(
            side="left", padx=6)
        ttk.Button(foot, text="How to use", command=lambda: self.folder(config.PROJECT_DIR / "docs" / "USAGE.md")).pack(
            side="left")
        self.status = ttk.Label(self, text="", foreground=MUTED)
        self.status.grid(row=row + 1, column=0, sticky="w", pady=(8, 0))

    def open(self, name, args):
        """Start a program in its own window (and its own process: this menu can be closed)."""
        subprocess.Popen([sys.executable, "-m", *args], cwd=config.PROJECT_DIR,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.status.configure(text=f"Opening {name} … (it can take a few seconds)")
        self.after(8000, lambda: self.status.configure(text=""))

    def folder(self, path):
        """Open a folder (made if it isn't there yet) or a file, the way Windows would."""
        if not path.suffix:
            path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])

    def test_accuracy(self):
        """Run the honest test and show what it prints, in a window of its own."""
        win = tk.Toplevel(self)
        win.title("BrickSort – test accuracy")
        win.geometry("760x460")
        box = tk.Text(win, wrap="word", font=("Consolas", 10), padx=8, pady=6)
        box.pack(fill="both", expand=True)
        make_copyable(box)
        bar = ttk.Frame(win, padding=6)
        bar.pack(fill="x")
        results = config.PROJECT_DIR / "results" / "RESULTS.md"
        note = ttk.Label(bar, text="Testing the model on my_photos/_test …", foreground=MUTED)
        note.pack(side="left")
        ttk.Button(bar, text="Open the results file", command=lambda: self.folder(results)).pack(side="right")

        def add(line):
            box.insert("end", line)
            box.see("end")

        def run():
            p = subprocess.Popen([sys.executable, "-m", "bricksort.evaluate"], cwd=config.PROJECT_DIR,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in p.stdout:
                self.after(0, add, line)
            code = p.wait()
            done = "Done." if code == 0 else f"Stopped with an error (code {code}); see above."
            self.after(0, lambda: note.configure(text=done))
        threading.Thread(target=run, daemon=True).start()


def run():
    App().mainloop()


if __name__ == "__main__":
    run()
