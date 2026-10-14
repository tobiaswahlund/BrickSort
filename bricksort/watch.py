"""Watch the training pictures as they're being made (a separate window; doesn't slow anything down).

Run:  python -m bricksort.watch
Every second it shows the newest pictures in the renders folders, with part name and colour.
"""
import json
import re
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from . import config

COLS, ROWS, SIZE = 6, 3, 150


def _names():
    names = {"multiple": "Several pieces", "not_lego": "Not LEGO"}
    for f in (config.PARTS_FILE, config.CATEGORY_PARTS_FILE):
        if f.exists():
            names.update({p["id"]: p["name"] for p in json.loads(f.read_text(encoding="utf-8"))})
    return names


def _colors():
    try:
        from .catalog import colors
        return {cid: n for cid, (n, _) in colors().items()}
    except Exception:
        return {}


class Watch(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BrickSort – training pictures being made")
        self.configure(padx=8, pady=8)
        self.names, self.colors = _names(), _colors()
        self.info = ttk.Label(self, text="Waiting for new pictures …", font=("Segoe UI", 11))
        self.info.pack(anchor="w", pady=(0, 6))
        self.board = ttk.Frame(self, width=COLS * (SIZE + 6), height=ROWS * (SIZE + 40))
        self.board.pack(fill="both", expand=True)
        self.board.grid_propagate(False)   # the window decides the board's size, not the pictures in it
        self.cells, self.shape = [], None
        # as many pictures as fit: a bigger window shows more of them
        self.board.bind("<Configure>", lambda e: self._layout())
        self.dirs = {}  # folder -> last modified time, to find the active ones quickly
        self._layout()
        self.refresh()

    def _layout(self):
        w, h = self.board.winfo_width(), self.board.winfo_height()
        if w < 50:
            w, h = COLS * (SIZE + 6), ROWS * (SIZE + 40)
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
            img = ttk.Label(self.board)
            cap = ttk.Label(self.board, text="", wraplength=SIZE, justify="center", font=("Segoe UI", 8))
            img.grid(row=(i // cols) * 2, column=i % cols, padx=3)
            cap.grid(row=(i // cols) * 2 + 1, column=i % cols, padx=3, sticky="n")
            self.cells.append((img, cap))

    def _run_start(self):
        """When the latest Train.bat run started making pictures (0 if never)."""
        try:
            return float(config.RENDER_RUN.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0.0

    def _newest(self, n):
        files = []
        for root in (config.RENDERS, config.CATEGORY_RENDERS):
            if not root.exists():
                continue
            for d in root.iterdir():
                m = d.stat().st_mtime
                if d.is_dir() and m >= self.dirs.get(d, 0):
                    self.dirs[d] = m
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
        try:
            start = self._run_start()
            if start != getattr(self, "start", None):   # a new run: start over
                self.start, self.ticks = start, 0
                for img_label, cap in self.cells:
                    img_label.configure(image="")
                    cap.configure(text="")
            files = self._newest(len(self.cells))
            for (img_label, cap), path in zip(self.cells, files):
                img = ImageTk.PhotoImage(Image.open(path).resize((SIZE, SIZE)))
                img_label.configure(image=img)
                img_label.image = img
                m = re.search(r"_c(\d+)", path.stem)
                colour = self.colors.get(int(m.group(1)), "") if m else ""
                part = path.parent.name
                cap.configure(text=f"{part} {colour}\n{self.names.get(part, '')[:40]}")
            # counting takes a moment, so only every 10 seconds
            self.ticks += 1
            if self.ticks % 10 == 1:
                self.total = self._count_this_run()
            self.info.configure(text=f"{self.total:,} new training pictures in this run. Newest first." if files
                                else "No new training pictures yet. They appear here while Train.bat makes them.")
        except Exception as e:  # a picture being written right now can't be opened yet
            self.info.configure(text=f"(skipped a picture still being written: {e.__class__.__name__})")
        self.after(1000, self.refresh)


def run():
    Watch().mainloop()


if __name__ == "__main__":
    run()
