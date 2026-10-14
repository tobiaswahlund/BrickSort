"""Look through the training pictures, to check they look right (lighting, angles, blur and smudges,
backgrounds, the look of the plastic). A separate window; it doesn't slow the training down.

Run:  python -m bricksort.watch   (the "Model training.bat" window has this viewer built in)

Two views:
- "Being made now": the newest pictures of the current training run, refreshed every second.
- "All training pictures": every simulated picture the next training will use (the parts in
  parts.json and category_parts.json), page by page, for one part or all, in order or shuffled.
Click a picture to see it big (arrow keys for the next one). A bad one can be taken out of the
training: it's moved to <data folder>/rejected_renders/, and the next training run makes a new one.
"""
import json
import random
import re
import shutil
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from . import config
from .ui import MUTED, ImageBox

SIZE = 150
LIVE, ALL = "Being made now", "All training pictures"
ALL_PARTS = "All parts"
REJECTED = config.BIG_DIR / "rejected_renders"


def _parts():
    """{id: name} for every piece the next training uses, and which renders folder it's in."""
    names, folders = {"multiple": "Several pieces", "not_lego": "Not LEGO"}, {}
    for f, root in ((config.PARTS_FILE, config.RENDERS), (config.CATEGORY_PARTS_FILE, config.CATEGORY_RENDERS)):
        if f.exists():
            for p in json.loads(f.read_text(encoding="utf-8")):
                names[p["id"]] = p["name"]
                folders[p["id"]] = root / p["id"]
    folders.setdefault("multiple", config.RENDERS / "multiple")
    return names, folders


def _colors():
    try:
        from .catalog import colors
        return {cid: n for cid, (n, _) in colors(include_trans=True).items()}
    except Exception:
        return {}


class TrainingPictures(ttk.Frame):
    """The picture viewer: part of the Model training window, or a window of its own (Watch)."""

    def __init__(self, master):
        super().__init__(master)
        self.names, self.folders = _parts()
        self.colors = _colors()
        self.dirs = {}       # folder -> last modified time, to find the active ones quickly
        self.all_files = None
        self.page = 0

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        self.mode = tk.StringVar(value=LIVE)
        for m in (LIVE, ALL):
            ttk.Radiobutton(bar, text=m, value=m, variable=self.mode, command=self._mode_changed).pack(side="left")
        self.browse = ttk.Frame(bar)   # only shown for "All training pictures"
        ttk.Label(self.browse, text="Part").pack(side="left", padx=(16, 4))
        self.part = ttk.Combobox(self.browse, width=40, state="readonly",
                                 values=[ALL_PARTS] + [f"{p}  {self.names.get(p, '')}" for p in sorted(self.folders)])
        self.part.set(ALL_PARTS)
        self.part.pack(side="left")
        self.part.bind("<<ComboboxSelected>>", lambda e: self._load_all())
        self.shuffled = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.browse, text="Shuffle", variable=self.shuffled, command=self._load_all
                        ).pack(side="left", padx=8)
        ttk.Button(self.browse, text="◀", width=3, command=lambda: self._turn(-1)).pack(side="left")
        self.page_text = ttk.Label(self.browse, text="", width=14, anchor="center")
        self.page_text.pack(side="left")
        ttk.Button(self.browse, text="▶", width=3, command=lambda: self._turn(+1)).pack(side="left")

        self.info = ttk.Label(self, text="", font=("Segoe UI", 10))
        self.info.pack(anchor="w", pady=(0, 6))
        self.board = ttk.Frame(self, width=6 * (SIZE + 6), height=3 * (SIZE + 40))
        self.board.pack(fill="both", expand=True)
        self.board.grid_propagate(False)   # the window decides the board's size, not the pictures in it
        self.cells, self.shape, self.shown = [], None, []
        # as many pictures as fit: a bigger window shows more of them
        self.board.bind("<Configure>", lambda e: self._layout())
        ttk.Label(self, text="Click a picture to see it big. PageUp/PageDown turn the page.", foreground=MUTED
                  ).pack(anchor="w", pady=(6, 0))
        top = self.winfo_toplevel()
        top.bind("<Next>", lambda e: self._turn(+1), add="+")
        top.bind("<Prior>", lambda e: self._turn(-1), add="+")
        self._layout()
        self.refresh()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        w, h = self.board.winfo_width(), self.board.winfo_height()
        if w < 50:
            w, h = 6 * (SIZE + 6), 3 * (SIZE + 40)
        shape = (max(1, w // (SIZE + 6)), max(1, h // (SIZE + 40)))
        if shape == self.shape:
            return
        self.shape = shape
        for img, cap in self.cells:
            img.destroy()
            cap.destroy()
        cols, rows = shape
        self.cells = []
        for i in range(cols * rows):
            img = ttk.Label(self.board, cursor="hand2")
            cap = ttk.Label(self.board, text="", wraplength=SIZE, justify="center", font=("Segoe UI", 8))
            img.grid(row=(i // cols) * 2, column=i % cols, padx=3)
            cap.grid(row=(i // cols) * 2 + 1, column=i % cols, padx=3, sticky="n")
            img.bind("<Button-1>", lambda e, i=i: self._open(i))
            self.cells.append((img, cap))
        if self.mode.get() == ALL:
            self._show_page()

    def _caption(self, path):
        m = re.search(r"_c(\d+)", path.stem)
        colour = self.colors.get(int(m.group(1)), "") if m else ""
        part = path.parent.name
        return f"{part} {colour}\n{self.names.get(part, '')[:40]}"

    def _fill(self, files):
        self.shown = list(files)
        for k, (img_label, cap) in enumerate(self.cells):
            if k < len(files):
                try:
                    img = ImageTk.PhotoImage(Image.open(files[k]).resize((SIZE, SIZE)))
                except OSError:   # being written right now: next time
                    continue
                img_label.configure(image=img)
                img_label.image = img
                cap.configure(text=self._caption(files[k]))
            else:
                img_label.configure(image="")
                img_label.image = None
                cap.configure(text="")

    # ------------------------------------------------------------------ "being made now"
    def _run_start(self):
        """When the latest training run started making pictures (0 if never)."""
        try:
            return float(config.RENDER_RUN.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0.0

    def _scan_dirs(self):
        for root in (config.RENDERS, config.CATEGORY_RENDERS):
            if root.exists():
                for d in root.iterdir():
                    if d.is_dir():
                        m = d.stat().st_mtime
                        if m >= self.dirs.get(d, 0):
                            self.dirs[d] = m

    def _newest(self, n):
        self._scan_dirs()
        files = []
        # look inside the most recently changed folders only, and only at pictures from this run
        for d in sorted(self.dirs, key=self.dirs.get, reverse=True)[:8]:
            if self.dirs[d] >= self.start:
                files += [(m, p) for p in d.glob("*.png") if (m := p.stat().st_mtime) >= self.start]
        return [p for _, p in sorted(files, reverse=True)[:n]]

    def _count_this_run(self):
        """Pictures made since this run started (folders untouched since then can be skipped)."""
        return sum(1 for d, m in self.dirs.items() if m >= self.start
                   for p in d.glob("*.png") if p.stat().st_mtime >= self.start)

    def refresh(self):
        if self.mode.get() == LIVE:
            start = self._run_start()
            if start != getattr(self, "start", None):   # a new run: start over
                self.start, self.ticks = start, 0
                self._fill([])
            try:
                files = self._newest(len(self.cells))
                self._fill(files)
                self.ticks += 1
                if self.ticks % 10 == 1:   # counting takes a moment, so only every 10 seconds
                    self.total = self._count_this_run()
                self.info.configure(text=f"{self.total:,} new training pictures in this run. Newest first."
                                    if files else "No new training pictures yet. They appear here while "
                                                  "a training run makes them.")
            except OSError:   # a folder changed while looking
                pass
        self.after(1000, self.refresh)

    # ------------------------------------------------------------------ "all training pictures"
    def _mode_changed(self):
        if self.mode.get() == ALL:
            self.browse.pack(side="left")
            self._load_all()
        else:
            self.browse.pack_forget()
            self.start = None   # refresh() fills the live view again

    def _load_all(self):
        self.info.configure(text="Looking through the pictures …")
        self.update_idletasks()
        choice = self.part.get()
        ids = sorted(self.folders) if choice == ALL_PARTS else [choice.split()[0]]
        files = []
        for pid in ids:
            d = self.folders[pid]
            if d.is_dir():
                files += sorted(d.glob("*.png"))
        if self.shuffled.get():
            random.Random(len(files)).shuffle(files)
        self.all_files, self.page = files, 0
        with_pictures = len({f.parent.name for f in files})
        self.info.configure(text=f"{len(files):,} pictures the next training will use"
                                 + (f", for {with_pictures} parts." if choice == ALL_PARTS else "."))
        self._show_page()

    def _per_page(self):
        return max(1, len(self.cells))

    def _show_page(self):
        if self.all_files is None:
            return
        n = self._per_page()
        pages = max(1, -(-len(self.all_files) // n))
        self.page = max(0, min(self.page, pages - 1))
        self._fill(self.all_files[self.page * n:(self.page + 1) * n])
        self.page_text.configure(text=f"page {self.page + 1} of {pages:,}")

    def _turn(self, step):
        if self.mode.get() == ALL:
            self.page += step
            self._show_page()

    # ------------------------------------------------------------------ one picture, big
    def _open(self, k):
        if k < len(self.shown):
            BigPicture(self, self.shown, k)

    def reject(self, path):
        """Take a picture out of the training. Kept in rejected_renders/<part>/, not deleted."""
        dest = REJECTED / path.parent.name
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), dest / path.name)
        if self.all_files is not None and path in self.all_files:
            self.all_files.remove(path)
            self._show_page()


class BigPicture(tk.Toplevel):
    def __init__(self, app, files, k):
        super().__init__(app)
        self.app, self.files, self.k = app, list(files), k
        self.geometry("620x700")
        self.box = ImageBox(self, 560, 560)
        self.box.pack(fill="both", expand=True, padx=8, pady=8)
        self.caption = ttk.Label(self, text="", justify="center")
        self.caption.pack()
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=8)
        ttk.Button(bar, text="◀ Previous", command=lambda: self.go(-1)).pack(side="left")
        ttk.Button(bar, text="Next ▶", command=lambda: self.go(+1)).pack(side="left", padx=6)
        ttk.Button(bar, text="Take out of training", command=self.reject).pack(side="right")
        self.bind("<Left>", lambda e: self.go(-1))
        self.bind("<Right>", lambda e: self.go(+1))
        self.bind("<Delete>", lambda e: self.reject())
        self.bind("<Escape>", lambda e: self.destroy())
        self.show()

    def show(self):
        if not self.files:
            self.destroy()
            return
        self.k %= len(self.files)
        path = self.files[self.k]
        try:
            self.box.set(Image.open(path).convert("RGB"))
        except OSError:
            pass
        self.title(f"{path.parent.name}/{path.name}")
        self.caption.configure(text=self.app._caption(path) + f"\n{self.k + 1} of {len(self.files)}")

    def go(self, step):
        self.k += step
        self.show()

    def reject(self):
        if not self.files:
            return
        path = self.files.pop(self.k)
        self.app.reject(path)
        self.show()


class Watch(tk.Tk):
    """The viewer on its own (the Model training window has it built in)."""

    def __init__(self):
        super().__init__()
        self.title("BrickSort – training pictures")
        self.configure(padx=8, pady=8)
        self.view = TrainingPictures(self)
        self.view.pack(fill="both", expand=True)


def run():
    Watch().mainloop()


if __name__ == "__main__":
    run()
