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
from .ui import Label

COLS, ROWS, SIZE = 6, 3, 150


def _names():
    names = {}
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
        self.info = Label(self, text="Waiting for new pictures …", font=("Segoe UI", 11))
        self.info.grid(row=0, column=0, columnspan=COLS, sticky="w", pady=(0, 6))
        self.cells = []
        for i in range(COLS * ROWS):
            img = Label(self)
            cap = Label(self, text="", wraplength=SIZE, justify="center", font=("Segoe UI", 8))
            img.grid(row=1 + (i // COLS) * 2, column=i % COLS, padx=3)
            cap.grid(row=2 + (i // COLS) * 2, column=i % COLS, padx=3, sticky="n")
            self.cells.append((img, cap))
        self.dirs = {}  # folder -> last modified time, to find the active ones quickly
        self.refresh()

    def _newest(self, n):
        files = []
        for root in (config.RENDERS, config.CATEGORY_RENDERS):
            if not root.exists():
                continue
            for d in root.iterdir():
                m = d.stat().st_mtime
                if d.is_dir() and m >= self.dirs.get(d, 0):
                    self.dirs[d] = m
        # look inside the most recently changed folders only
        for d in sorted(self.dirs, key=self.dirs.get, reverse=True)[:8]:
            files += [(p.stat().st_mtime, p) for p in d.glob("*.png")]
        return [p for _, p in sorted(files, reverse=True)[:n]]

    def refresh(self):
        try:
            files = self._newest(COLS * ROWS)
            for (img_label, cap), path in zip(self.cells, files):
                img = ImageTk.PhotoImage(Image.open(path).resize((SIZE, SIZE)))
                img_label.configure(image=img)
                img_label.image = img
                m = re.search(r"_c(\d+)", path.stem)
                colour = self.colors.get(int(m.group(1)), "") if m else ""
                part = path.parent.name
                cap.configure(text=f"{part} {colour}\n{self.names.get(part, '')[:40]}")
            total = sum(1 for root in (config.RENDERS, config.CATEGORY_RENDERS) if root.exists()
                        for _ in root.glob("*/*.png"))
            self.info.configure(text=f"{total:,} training pictures so far. Newest first.")
        except Exception as e:  # a picture being written right now can't be opened yet
            self.info.configure(text=f"(skipped a picture still being written: {e.__class__.__name__})")
        self.after(1000, self.refresh)


if __name__ == "__main__":
    Watch().mainloop()
