"""BrickSort: one window for every part of the project.

Run:  python -m bricksort.app   (or double-click the BrickSort shortcut, or BrickSort.bat)

Pick something in the menu and it opens in this same window, with "◀ Menu" at the top to go
back. Each part still runs as its own program (so a heavy one can't freeze the menu, and its
memory is given back when you leave it); it's only shown inside this window (ui.py: BRICKSORT_INSIDE).
"◀ Menu" closes it the way its own close button would, so it saves first, or asks.

To open quickly, a helper program waits in the background with everything loaded (PyTorch, MuJoCo
and every part's code: that's most of the waiting), and becomes whatever you pick next. A new
helper is got ready when you're back in the menu.
"""
import importlib
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from . import config
from .ui import ASSETS, MUTED, make_copyable, show_inside, use_logo

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
         "Score the model on your test pieces (my_photos/_test)."),
    ]),
]
LOG = config.BIG_DIR / "app_log.txt"   # what the programs opened from the menu print when something goes wrong
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        use_logo(self)
        self.title("BrickSort")
        self.minsize(560, 0)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.child = None          # the program shown now (a subprocess.Popen), or None
        self.screen = None         # the frame shown under the bar: the menu, a program, or the test
        self.menu_size = None
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

        # the bar above a program: back to the menu, and what's open
        self.bar = ttk.Frame(self, padding=(8, 6))
        self.back_btn = ttk.Button(self.bar, text="◀ Menu", command=self.back)
        self.back_btn.pack(side="left")
        self.bar_logo = ImageTk.PhotoImage(Image.open(ASSETS / "logo.png").resize((22, 22), Image.LANCZOS))
        ttk.Label(self.bar, image=self.bar_logo).pack(side="left", padx=(12, 4))
        self.bar_title = ttk.Label(self.bar, text="", font=("Segoe UI", 11, "bold"))
        self.bar_title.pack(side="left")
        self.bar_note = ttk.Label(self.bar, text="", foreground=MUTED)
        self.bar_note.pack(side="left", padx=12)

        self.menu = self._make_menu()
        self.helper = None         # a program waiting with everything loaded (see warm_helper)
        self.show_menu()

    # ------------------------------------------------------------------ the menu
    def _make_menu(self):
        m = ttk.Frame(self, padding=(16, 14))
        m.columnconfigure(0, weight=1)
        head = ttk.Frame(m)
        head.grid(row=0, column=0, sticky="we", pady=(0, 10))
        self._logo_small = ImageTk.PhotoImage(Image.open(ASSETS / "logo.png").resize((72, 72), Image.LANCZOS))
        ttk.Label(head, image=self._logo_small).pack(side="left", padx=(0, 12))
        words = ttk.Frame(head)
        words.pack(side="left", fill="x", expand=True)
        ttk.Label(words, text="BrickSort", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(words, text="Recognise LEGO pieces from a camera picture and sort them.",
                  foreground=MUTED).pack(anchor="w")
        row = 1
        for section, tools in TOOLS:
            box = ttk.LabelFrame(m, text=section, padding=(10, 6))
            box.grid(row=row, column=0, sticky="we", pady=4)
            box.columnconfigure(1, weight=1)
            for k, (name, args, what) in enumerate(tools):
                command = (lambda: self.test_accuracy()) if args is None else (lambda n=name, a=args: self.open(n, a))
                ttk.Button(box, text=name, width=20, command=command).grid(row=k, column=0, sticky="w", pady=3)
                ttk.Label(box, text=what, foreground=MUTED, wraplength=380, justify="left").grid(
                    row=k, column=1, sticky="w", padx=(10, 0))
            row += 1
        foot = ttk.Frame(m)
        foot.grid(row=row, column=0, sticky="we", pady=(10, 0))
        ttk.Button(foot, text="Open my photos", command=lambda: self.folder(config.MY_PHOTOS)).pack(side="left")
        ttk.Button(foot, text="Open data folder", command=lambda: self.folder(config.BIG_DIR)).pack(
            side="left", padx=6)
        ttk.Button(foot, text="How to use", command=lambda: self.folder(config.PROJECT_DIR / "docs" / "USAGE.md")).pack(
            side="left")
        return m

    def _show(self, frame, title=None):
        """Show one screen: the menu (no bar), or something with the bar above it."""
        if self.screen is not None and self.screen is not frame:
            self.screen.grid_forget()
            if self.screen is not self.menu:
                self.screen.destroy()
        self.screen = frame
        if title is None:
            self.bar.grid_forget()
            frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
            self.title("BrickSort")
        else:
            self.bar.grid(row=0, column=0, sticky="we")
            frame.grid(row=1, column=0, sticky="nsew")
            self.bar_title.configure(text=title)
            self.title(f"BrickSort – {title}")

    def show_menu(self):
        self._show(self.menu)
        self.after(1500, self._get_helper_ready)
        self.back_btn.configure(state="normal")
        self.bar_note.configure(text="")
        if self.menu_size:   # back to the size the menu had
            self.geometry(self.menu_size)

    def _grow(self):
        """The programs need more room than the menu: make the window big (unless it already is)."""
        self.update_idletasks()
        if self.screen is self.menu:
            self.menu_size = f"{self.winfo_width()}x{self.winfo_height()}"
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = max(self.winfo_width(), min(1400, int(sw * 0.9))), max(self.winfo_height(), min(920, int(sh * 0.85)))
        x, y = max(0, min(self.winfo_x(), sw - w)), max(0, min(self.winfo_y(), sh - h - 40))
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ------------------------------------------------------------------ a program, inside this window
    def open(self, name, args):
        if self.child is not None:
            return
        self._grow()
        holder = tk.Frame(self, container=True, background="#f0f0f0")
        self._show(holder, name)
        self.update_idletasks()
        LOG.parent.mkdir(parents=True, exist_ok=True)
        log = open(LOG, "a", encoding="utf-8")
        log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M')} {name}\n")
        log.flush()
        helper, self.helper = self.helper, None
        if helper is not None and helper.poll() is None:   # the helper becomes this program
            helper.stdin.write(" ".join(["run", hex(holder.winfo_id()), *args]) + "\n")
            helper.stdin.flush()
            self.child = helper
        else:
            self.child = subprocess.Popen(
                [sys.executable, "-m", *args], cwd=config.PROJECT_DIR, stdin=subprocess.PIPE,
                stdout=log, stderr=log, text=True, creationflags=NO_WINDOW,
                env={**os.environ, "BRICKSORT_INSIDE": hex(holder.winfo_id()), "PYTHONIOENCODING": "utf-8"})
        log.close()
        self.child_name = name
        self.bar_note.configure(text="Opening … (it can take a few seconds)")
        self.after(6000, lambda: self.bar_note.configure(text="") if self.child else None)
        self._watch_child()

    def _watch_child(self):
        if self.child is None:
            return
        code = self.child.poll()
        if code is None:
            self.after(400, self._watch_child)
            return
        name, self.child = self.child_name, None
        if self._quitting:
            self.destroy()
            return
        self.show_menu()
        if code != 0:
            messagebox.showwarning(
                f"{name} stopped", f"{name} stopped with an error. What it printed is at the end of\n{LOG}",
                parent=self)

    _quitting = False

    def _ask_child_to_close(self):
        try:
            self.child.stdin.write("close\n")
            self.child.stdin.flush()
        except (OSError, ValueError):   # it's already gone
            pass

    def back(self):
        if self.child is None:
            self.show_menu()
            return
        self.bar_note.configure(text="Closing …")
        self._ask_child_to_close()   # it saves, or asks first (and may stay open); _watch_child sees it go

    def _get_helper_ready(self):
        if self.child is not None or (self.helper is not None and self.helper.poll() is None):
            return
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as log:
            self.helper = subprocess.Popen(
                [sys.executable, "-m", "bricksort.app", "--helper"], cwd=config.PROJECT_DIR, stdin=subprocess.PIPE,
                stdout=log, stderr=log, text=True, creationflags=NO_WINDOW,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    def destroy(self):
        if self.helper is not None and self.helper.poll() is None:
            self.helper.kill()   # it was only waiting
        super().destroy()

    def quit_app(self):
        if self.child is None:
            self.destroy()
            return
        self._quitting = True
        self._ask_child_to_close()
        self.after(15000, lambda: setattr(self, "_quitting", False))   # it asked and you said no: stay

    # ------------------------------------------------------------------ test accuracy, in this window
    def test_accuracy(self):
        if self.child is not None:
            return
        self._grow()
        frame = ttk.Frame(self, padding=8)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        box = tk.Text(frame, wrap="word", font=("Consolas", 10), padx=8, pady=6)
        box.grid(row=0, column=0, sticky="nsew")
        make_copyable(box)
        results = config.PROJECT_DIR / "results" / "RESULTS.md"
        ttk.Button(frame, text="Open the results file", command=lambda: self.folder(results)).grid(
            row=1, column=0, sticky="e", pady=(6, 0))
        self._show(frame, "Test accuracy")
        self.bar_note.configure(text="Testing the model on my_photos/_test …")

        def add(line):
            if box.winfo_exists():
                box.insert("end", line)
                box.see("end")

        def finished(code):
            if box.winfo_exists():
                self.bar_note.configure(text="Done." if code == 0 else
                                        f"Stopped with an error (code {code}); see above.")

        def run():
            p = subprocess.Popen([sys.executable, "-m", "bricksort.evaluate"], cwd=config.PROJECT_DIR,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                 creationflags=NO_WINDOW)
            for line in p.stdout:
                self.after(0, add, line)
            code = p.wait()
            self.after(0, finished, code)
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    def folder(self, path):
        """Open a folder (made if it isn't there yet) or a file, the way Windows would."""
        if not path.suffix:
            path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def make_shortcut():
    """BrickSort.lnk in the project folder: opens this menu, and shows the logo in File Explorer
    (a .bat file always shows Windows' own icon, a shortcut can have any). Made by setup.bat; it
    holds this computer's paths, so it stays out of git."""
    if sys.platform != "win32":
        return
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    link = config.PROJECT_DIR / "BrickSort.lnk"
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}'); "
              f"$s.TargetPath = '{pythonw}'; $s.Arguments = '-m bricksort.app'; "
              f"$s.WorkingDirectory = '{config.PROJECT_DIR}'; $s.IconLocation = '{ASSETS / 'logo.ico'}'; "
              "$s.Description = 'BrickSort'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, creationflags=NO_WINDOW)
    print("Made", link)


def warm_helper():
    """(--helper) Load everything the parts need, then wait for the menu to say which part to be:
    "run <window id> <module> [arguments]". Becomes that part, shown inside the menu's window."""
    from . import colour_review, conveyor_demo, cut, demo, training_app  # noqa: F401  (the slow part)
    line = sys.stdin.readline().split()
    if len(line) < 3 or line[0] != "run":
        return   # the menu closed
    show_inside(line[1])
    sys.argv = [line[2], *line[3:]]
    importlib.import_module(line[2]).run()   # every part starts with run(), reading sys.argv


def run():
    if "--shortcut" in sys.argv:
        make_shortcut()
        return
    if "--helper" in sys.argv:
        warm_helper()
        return
    App().mainloop()


if __name__ == "__main__":
    run()
