"""Check the colours of the Dataset_01 photos, one piece at a time.

Run:  python -m bricksort.colour_review   (or double-click "Check colours.bat")

For each piece:
  1. Pick colours: a sample of its photos (a few of every guessed colour) and buttons for the
     colours it could be. Press every colour you can see, then "Done, continue".
  2. One colour at a time: the photos that could be that colour are shown. Click photos to mark
     them (Shift-click marks everything from the last photo you clicked to this one), then either "✔ The marked ones ARE <colour>" (the unmarked ones are not) or
     "✘ The marked ones are NOT <colour>" (the unmarked ones are). Repeat for each colour.
  3. When every photo has a colour, the photos are moved to my_photos/<part>/<colour>/.
Pieces with a print: give them the colour of the plastic and press "Marked ones are printed";
they go to my_photos/<part>/<colour>/printed/.
You can go back and forth between pieces at any time; all choices are saved.
"""
import copy
import json
import random
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from . import catalog, config
from .cut import autocomplete, wide_dropdown
from .render import real_colors
from .ui import Label

SOURCE = config.PROJECT_DIR / "_check" / "dataset_01_colours"
STATE = SOURCE / "_review_progress.json"
NOT_SPECIFIED = "colour_not_specified"
PRINTED = "printed"   # my_photos/<part>/<colour>/printed/: plastic colour <colour>, with a print on it
DELETED = config.PROJECT_DIR / "_check" / "_deleted"   # thrown-away photos (empty it yourself when sure)
THUMB = 112
COLS = 9


def _candidates(folder_name):
    """Colours a photo could be, from the folder the guessing put it in."""
    if folder_name.startswith("_check - "):
        return [c.strip() for c in folder_name[len("_check - "):].split(" or ")]
    if folder_name == NOT_SPECIFIED:
        return []
    return [folder_name]


class ColourReview(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BrickSort – check colours")
        self.configure(padx=8, pady=8)
        self.geometry("1150x860")
        self.table = catalog.colors(include_trans=True)
        self.rgb = {n: rgb for n, rgb in self.table.values()}
        self.names = {r["part_num"]: r["name"] for r in catalog.read_csv("parts")}
        self.parts = sorted(p.name for p in SOURCE.iterdir() if p.is_dir()) if SOURCE.exists() else []
        self.state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        self.thumbs = {}
        self.scanned = set()   # pieces already checked for newly added photos this time
        self._build()
        if not self.parts:
            messagebox.showinfo("Nothing to check", f"No photos found in {SOURCE}")
            self.destroy()
            return
        for p in self.parts:   # newly added photos on pieces you've already started
            if p in self.state:
                self.scanned.add(p)
                self._add_new_photos(p)
        first = next((i for i, p in enumerate(self.parts) if self.state.get(p, {}).get("stage") != "done"), 0)
        self.show_part(first)

    # ------------------------------------------------------------------ layout
    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Button(top, text="◀ Previous piece", command=lambda: self.show_part(self.i - 1)).pack(side="left")
        ttk.Button(top, text="Next piece ▶", command=lambda: self.show_part(self.i + 1)).pack(side="left", padx=4)
        self.jump = ttk.Combobox(top, width=44, state="readonly")
        self.jump.pack(side="left", padx=8)
        self.jump.bind("<<ComboboxSelected>>", lambda e: self.show_part(self.jump.current()))
        wide_dropdown(self.jump)
        self.progress = Label(top, text="", foreground="#666")
        self.progress.pack(side="left", padx=8)
        self.undo_btn = ttk.Button(top, text="↶ Undo", command=self.undo, state="disabled")
        self.undo_btn.pack(side="right")
        self.bind_all("<Control-z>", lambda e: self.undo())
        self.title_lbl = Label(self, text="", font=("Segoe UI", 13, "bold"))
        self.title_lbl.pack(anchor="w", pady=(6, 0))
        self.help = Label(self, text="", wraplength=1100, justify="left")
        self.help.pack(anchor="w", pady=(2, 6))
        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(holder, highlightthickness=0, bg="#f4f4f4")
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.grid_frame = tk.Frame(self.canvas, bg="#f4f4f4")
        self.grid_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.cols = COLS
        self.canvas.bind("<Configure>", lambda e: self._reflow())   # as many photos per row as fit
        self.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.bottom = ttk.Frame(self)
        self.bottom.pack(fill="x", pady=(8, 0))

    def _clear_bottom(self):
        for w in self.bottom.winfo_children():
            w.destroy()

    def _thumb(self, path):
        key = str(path)
        if key not in self.thumbs:
            if len(self.thumbs) > 3000:   # never keep thousands of pictures in memory (it used to crash)
                self.thumbs.clear()
            img = Image.open(path).convert("RGB")
            img.thumbnail((THUMB, THUMB))
            self.thumbs[key] = ImageTk.PhotoImage(img)
        return self.thumbs[key]

    def _show_grid(self, files, selectable=False, captions=None):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)
        self.marked = set()
        self.cells = {}
        self.order = list(files)
        self.last_clicked = None
        self.captions = captions or {}
        self.caption_lbls = {}
        for k, f in enumerate(files):
            cell = tk.Frame(self.grid_frame, bg="#f4f4f4", highlightthickness=4, highlightbackground="#f4f4f4")
            cell.grid(row=k // self.cols, column=k % self.cols, padx=2, pady=2)
            pic = tk.Label(cell, image=self._thumb(self.paths()[f]), bg="#f4f4f4",
                           cursor="hand2" if selectable else "")
            pic.pack()
            self.caption_lbls[f] = tk.Label(cell, text=self._caption(f), bg="#f4f4f4", font=("Segoe UI", 8))
            self.caption_lbls[f].pack()
            if selectable:
                for w in (cell, pic):
                    w.bind("<Button-1>", lambda e, f=f: self._click(f))
                    w.bind("<Shift-Button-1>", lambda e, f=f: self._shift_click(f))
            self.cells[f] = cell

    def _reflow(self):
        """Window resized: lay the photos out again with as many per row as now fit."""
        cols = max(1, (self.canvas.winfo_width() - 8) // (THUMB + 18))   # photo + frame + gap
        if cols == self.cols:
            return
        self.cols = cols
        for k, f in enumerate(getattr(self, "order", [])):
            if f in self.cells and self.cells[f].winfo_exists():
                self.cells[f].grid(row=k // cols, column=k % cols)

    # ------------------------------------------------------------------ undo
    def _remember(self):
        """Call before changing anything: keeps this piece's state so Undo can bring it back."""
        part = self.parts[self.i]
        self.undo_stack = getattr(self, "undo_stack", [])[-49:]   # the last 50 steps
        self.undo_stack.append((self.i, copy.deepcopy(self.state.get(part))))
        self.undo_btn.configure(state="normal")

    def undo(self):
        """Go back one step: the piece's choices as they were, and any photos that were moved
        (to my_photos, or to the deleted folder) put back where they were."""
        if not getattr(self, "undo_stack", None):
            return
        i, old = self.undo_stack.pop()
        part = self.parts[i]
        now = self.state.get(part) or {}
        for f, was in (old or {}).get("path", {}).items():
            where = now.get("path", {}).get(f) or str(DELETED / part / f)
            if where != was and Path(where).exists():
                Path(was).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(where, was)
        if old is None:
            self.state.pop(part, None)
        else:
            self.state[part] = old
        self.save()
        if not self.undo_stack:
            self.undo_btn.configure(state="disabled")
        self.show_part(i)

    def _caption(self, f):
        text = self.captions.get(f, "")
        if f in self.part_state().get("printed", []):
            text = (text + " · " if text else "") + "PRINTED"
        return text

    def set_printed(self, on):
        """Flag the marked photos as printed (or not). They still get the colour of the plastic."""
        self._remember()
        st = self.part_state()
        printed = set(st.get("printed", []))
        printed = printed | self.marked if on else printed - self.marked
        st["printed"] = sorted(printed)
        for f in list(self.marked):
            self._toggle(f)
            self.caption_lbls[f].configure(text=self._caption(f), fg="#b45309")
        if st["stage"] == "done":
            self._move_files()
        self.save()

    def _printed_buttons(self, parent=None):
        parent = parent or self.bottom
        ttk.Button(parent, text="🖨 Marked ones are printed", command=lambda: self.set_printed(True)
                   ).pack(side="left", padx=(12, 2))
        ttk.Button(parent, text="Not printed", command=lambda: self.set_printed(False)).pack(side="left")
        ttk.Button(parent, text="🗑 Delete marked", command=self.delete_marked).pack(side="left", padx=(12, 0))

    def delete_marked(self):
        """Throw the marked photos away: moved to _check/_deleted/<part>/ (so a mistake can be undone)."""
        if not self.marked:
            return
        self._remember()
        st = self.part_state()
        bin_dir = DELETED / self.parts[self.i]
        bin_dir.mkdir(parents=True, exist_ok=True)
        for f in list(self.marked):
            try:
                shutil.move(st["path"][f], bin_dir / f)
            except OSError:
                pass  # already gone
            for key in ("cand", "orig_cand", "colour", "path"):
                st.get(key, {}).pop(f, None)
            if f in st.get("printed", []):
                st["printed"].remove(f)
            self.cells[f].destroy()
            self.order.remove(f)
            self.marked.discard(f)
        if getattr(self, "current", None) and self.current[1] is not None:
            self.current = (self.current[0], [f for f in self.current[1] if f in st["path"]])
        self.mark_count.configure(text="0 marked")
        self.save()
        self.title_lbl.configure(text=f"{self.parts[self.i]}  {self.names.get(self.parts[self.i], '')}  "
                                      f"({len(st['cand'])} photos)")

    def _click(self, f):
        self._toggle(f)
        self.last_clicked = f

    def _shift_click(self, f):
        """Shift-click: mark every photo from the last one you clicked up to this one."""
        if self.last_clicked is None:
            return self._click(f)
        a, b = sorted((self.order.index(self.last_clicked), self.order.index(f)))
        for g in self.order[a:b + 1]:
            if g not in self.marked:
                self._toggle(g)
        self.last_clicked = f
        return "break"

    def _toggle(self, f):
        if f in self.marked:
            self.marked.discard(f)
            self.cells[f].configure(highlightbackground="#f4f4f4")
        else:
            self.marked.add(f)
            self.cells[f].configure(highlightbackground="#1a73e8")
        if getattr(self, "mark_count", None) is not None and self.mark_count.winfo_exists():
            self.mark_count.configure(text=f"{len(self.marked)} marked")

    # ------------------------------------------------------------------ data per piece
    def part_state(self):
        part = self.parts[self.i]
        if part not in self.state:
            cand, path = {}, {}
            for sub in (SOURCE / part).iterdir():
                if sub.is_dir():
                    for f in sub.iterdir():
                        if f.suffix.lower() in config.PHOTO_TYPES:
                            cand[f.name] = _candidates(sub.name)
                            path[f.name] = str(f)
            self.state[part] = {"stage": "pick", "selected": [], "cand": cand, "orig_cand": dict(cand),
                                "colour": {}, "path": path, "finished": []}
            self.scanned.add(part)
        elif part not in self.scanned:
            self.scanned.add(part)
            self._add_new_photos(part)
        return self.state[part]

    def _add_new_photos(self, part):
        """Photos added to the folder after you started this piece (e.g. from Dataset_02): add them
        without touching what you've already decided. A finished piece asks only about the new ones."""
        st = self.state[part]
        added = 0
        for sub in (SOURCE / part).iterdir() if (SOURCE / part).exists() else []:
            if sub.is_dir():
                for f in sub.iterdir():
                    if f.suffix.lower() in config.PHOTO_TYPES and f.name not in st["cand"]:
                        st["cand"][f.name] = _candidates(sub.name)
                        st.setdefault("orig_cand", {})[f.name] = _candidates(sub.name)
                        st["path"][f.name] = str(f)
                        added += 1
        if added and st["stage"] == "done":
            st["stage"], st["finished"] = "assign", []
        if added:
            self.save()

    def paths(self):
        return self.part_state()["path"]

    def save(self):
        STATE.write_text(json.dumps(self.state), encoding="utf-8")

    def _possible_colours(self):
        """Buttons: every colour the guesses mentioned, plus this part's most common real colours."""
        st = self.part_state()
        from collections import Counter
        seen = Counter(c for cs in st["cand"].values() for c in cs)
        ids, w = real_colors({"id": self.parts[self.i], "colors": []}, self.table)
        common = [self.table[c][0] for c, p in sorted(zip(ids, w), key=lambda t: -t[1])[:10]]
        out = [c for c, _ in seen.most_common()] + [c for c in common if c not in seen]
        return out + [c for c in st["selected"] if c not in out]

    # ------------------------------------------------------------------ pieces
    def show_part(self, i):
        if not self.parts:
            return
        self.save()
        new = max(0, min(i, len(self.parts) - 1))
        if new != getattr(self, "i", None):
            # a new piece: forget the previous piece's thumbnails. They used to pile up for every
            # piece looked at, until the program ran out of memory after a long session
            for w in self.grid_frame.winfo_children():
                w.destroy()
            self.thumbs.clear()
        self.i = new
        part = self.parts[self.i]
        st = self.part_state()
        done = sum(1 for p in self.parts if self.state.get(p, {}).get("stage") == "done")
        self.jump.configure(values=[f"{'✓ ' if self.state.get(p, {}).get('stage') == 'done' else ''}{p}  "
                                    f"{self.names.get(p, '')}" for p in self.parts])
        self.jump.current(self.i)
        self.progress.configure(text=f"Piece {self.i + 1} of {len(self.parts)} · {done} done")
        self.title_lbl.configure(text=f"{part}  {self.names.get(part, '')}  ({len(st['cand'])} photos)")
        {"pick": self.stage_pick, "assign": self.stage_assign, "done": self.stage_done}[st["stage"]]()

    # stage 1: which colours are there?
    def stage_pick(self):
        st = self.part_state()
        self.help.configure(text="1. Look at these photos and press every colour you can see "
                                 "(press again to unmark). Then press \"Done, continue\".")
        groups = {}
        for f, cs in st["cand"].items():
            groups.setdefault(" / ".join(cs) or "?", []).append(f)
        rng = random.Random(self.parts[self.i])
        sample = []
        for fs in groups.values():  # a few of every guessed colour...
            sample += rng.sample(fs, min(6, len(fs)))
        rest = [f for f in st["cand"] if f not in sample]
        sample += rng.sample(rest, min(max(0, 54 - len(sample)), len(rest)))  # ...topped up at random
        self._show_grid(sorted(sample, key=lambda f: " / ".join(st["cand"][f])), selectable=True)
        self._clear_bottom()
        buttons = ttk.Frame(self.bottom)
        buttons.pack(fill="x")
        self.colour_buttons = {}
        for k, name in enumerate(self._possible_colours()):
            self._colour_button(buttons, name, k)
        more = ttk.Frame(self.bottom)
        more.pack(fill="x", pady=4)
        ttk.Label(more, text="Another colour:").pack(side="left")
        names = catalog.color_choices()
        extra = ttk.Combobox(more, width=28, values=names)
        extra.pack(side="left", padx=4)
        wide_dropdown(extra)
        autocomplete(extra, names)

        def add():
            n = extra.get().strip()
            if n in self.rgb and n not in self.colour_buttons:
                self._colour_button(buttons, n, len(self.colour_buttons))
                self._press(n)
        ttk.Button(more, text="Add", command=add).pack(side="left")
        ttk.Button(more, text="Done, continue ▶", command=self.finish_pick).pack(side="right")
        self.mark_count = ttk.Label(more, text="0 marked")
        self.mark_count.pack(side="left", padx=(16, 0))
        ttk.Button(more, text="🗑 Delete marked", command=self.delete_marked).pack(side="left", padx=6)

    def _colour_button(self, parent, name, k):
        r, g, b = self.rgb.get(name, (128, 128, 128))
        fg = "white" if (0.3 * r + 0.59 * g + 0.11 * b) < 128 else "black"
        btn = tk.Button(parent, text=name, bg="#%02x%02x%02x" % (r, g, b), fg=fg, width=18, relief="raised", bd=3,
                        font=("Segoe UI", 9), command=lambda: self._press(name))
        btn.grid(row=k // 6, column=k % 6, padx=3, pady=3, sticky="we")
        self.colour_buttons[name] = btn
        if name in self.part_state()["selected"]:
            self._show_pressed(name, True)

    def _show_pressed(self, name, on):
        btn = self.colour_buttons[name]
        btn.configure(relief="sunken" if on else "raised", text=("✔ " if on else "") + name,
                      highlightthickness=3 if on else 0, highlightbackground="#1a73e8", bd=5 if on else 3)

    def _press(self, name):
        self._remember()
        sel = self.part_state()["selected"]
        if name in sel:
            sel.remove(name)
        else:
            sel.append(name)
        self._show_pressed(name, name in sel)
        self.save()

    def finish_pick(self):
        self._remember()
        st = self.part_state()
        if not st["selected"]:
            messagebox.showinfo("No colours", "Press at least one colour you can see.", parent=self)
            return
        # most likely colours first: those the guesses mention most
        from collections import Counter
        seen = Counter(c for cs in st["cand"].values() for c in cs)
        st["selected"].sort(key=lambda c: -seen.get(c, 0))
        st["stage"], st["finished"], st["colour"] = "assign", [], {}
        if len(st["selected"]) == 1:  # only one colour: that's it
            st["colour"] = {f: st["selected"][0] for f in st["cand"]}
            return self.finish_part()
        self.save()
        self.stage_assign()

    # stage 2: one colour at a time
    def _unassigned(self):
        st = self.part_state()
        return [f for f in st["cand"] if f not in st["colour"]]

    def _could_be(self, colour):
        st = self.part_state()
        sel = set(st["selected"])
        out = []
        for f in self._unassigned():
            cs = set(st["cand"][f]) & sel
            if not cs or colour in cs:  # unknown, or the guess includes this colour
                out.append(f)
        return out

    def _add_colour_row(self, done_stage=False):
        """'Add a colour' without losing what you've done on this piece."""
        row = ttk.Frame(self.bottom)
        row.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Label(row, text="Add a colour:").pack(side="left")
        names = catalog.color_choices()
        box = ttk.Combobox(row, width=28, values=names)
        box.pack(side="left", padx=4)
        wide_dropdown(box)
        autocomplete(box, names)
        ttk.Button(row, text="Add", command=lambda: self.add_colour(box.get().strip(), done_stage)).pack(side="left")
        ttk.Label(row, text="(keeps everything you've already decided on this piece)", foreground="#666"
                  ).pack(side="left", padx=6)

    def add_colour(self, name, done_stage=False):
        st = self.part_state()
        if name not in self.rgb:
            messagebox.showinfo("Colour", f"'{name}' isn't one of the colour names.", parent=self)
            return
        self._remember()
        if done_stage:  # finished piece: look through all its photos for the new colour
            st["recheck"] = name
            st["stage"] = "assign"
            self.save()
            return self.stage_assign()
        if name in st["selected"]:
            return
        st["selected"].append(name)  # asked about after the colours already chosen
        for f in self._unassigned():
            if st["cand"][f] and name not in st["cand"][f]:
                st["cand"][f].append(name)
        self.save()
        self.help.configure(text=self.help.cget("text") + f"   (Added {name}: it comes after the other colours.)")

    def stage_assign(self):
        st = self.part_state()
        if st.get("recheck"):  # a colour added to a finished piece: which photos are it?
            colour = st["recheck"]
            shown = list(st["cand"])
            self.help.configure(text=f"Added colour {colour}: mark the photos that are {colour}. "
                                     f"The others keep the colour they already have.")
            self._assign_view(colour, shown)
            return
        left = self._unassigned()
        if not left:
            return self.finish_part()
        remaining = [c for c in st["selected"] if c not in st.get("finished", [])]
        if not remaining:  # every colour asked once; ask again about what's left, all colours possible
            st["finished"] = []
            for f in left:
                st["cand"][f] = []
            remaining = list(st["selected"])
        colour = remaining[0]
        shown = self._could_be(colour)
        if not shown:
            st.setdefault("finished", []).append(colour)
            return self.stage_assign()
        if len(remaining) == 1:  # the last colour: everything left could only be this one
            shown = left
        k = st["selected"].index(colour) + 1
        self.help.configure(text=f"2. Colour {k} of {len(st['selected'])}: {colour}. These {len(shown)} photos could be "
                                 f"{colour} ({len(left)} photos still without a colour). Click photos to mark them, "
                                 f"then press one of the buttons.")
        self._assign_view(colour, shown)

    def _assign_view(self, colour, shown):
        self._show_grid(shown, selectable=True)
        self.current = (colour, shown)
        self._clear_bottom()
        self._add_colour_row()
        row1, row2 = ttk.Frame(self.bottom), ttk.Frame(self.bottom)  # two rows, so nothing falls off the edge
        row1.pack(fill="x")
        row2.pack(fill="x", pady=(6, 0))
        r, g, b = self.rgb.get(colour, (128, 128, 128))
        tk.Label(row1, text="   ", bg="#%02x%02x%02x" % (r, g, b), relief="solid", bd=1).pack(side="left")
        tk.Button(row1, text=f"✔  The marked ones ARE {colour}", bg="#2e7d32", fg="white",
                  font=("Segoe UI", 10, "bold"), command=lambda: self.answer(True)).pack(side="left", padx=6)
        tk.Button(row1, text=f"✘  The marked ones are NOT {colour}", bg="#c62828", fg="white",
                  font=("Segoe UI", 10, "bold"), command=lambda: self.answer(False)).pack(side="left", padx=6)
        self.mark_count = ttk.Label(row1, text="0 marked")
        self.mark_count.pack(side="left", padx=8)
        ttk.Button(row1, text="Leave the rest as 'not specified'", command=self.rest_unknown).pack(side="right")
        ttk.Button(row1, text="◀ Back to choosing colours", command=self.back_to_pick).pack(side="right", padx=4)
        ttk.Button(row2, text="Mark all", command=lambda: [self._toggle(f) for f in self.order if f not in self.marked]
                   ).pack(side="left")
        ttk.Button(row2, text="Clear marks", command=lambda: [self._toggle(f) for f in list(self.marked)]
                   ).pack(side="left", padx=4)
        self._printed_buttons(row2)

    def answer(self, marked_are):
        self._remember()
        st = self.part_state()
        colour, shown = self.current
        yes = [f for f in shown if (f in self.marked) == marked_are]
        no = [f for f in shown if (f in self.marked) != marked_are]
        if st.get("recheck"):  # added to a finished piece: only the 'yes' photos change colour
            for f in yes:
                st["colour"][f] = colour
            if colour not in st["selected"]:
                st["selected"].append(colour)
            st["recheck"] = None
            return self.finish_part()
        for f in yes:
            st["colour"][f] = colour
        for f in no:  # not this colour: don't show them under it again
            st["cand"][f] = [c for c in (st["cand"][f] or st["selected"]) if c != colour]
        st.setdefault("finished", []).append(colour)
        self.save()
        self.stage_assign()

    def rest_unknown(self):
        self._remember()
        st = self.part_state()
        for f in self._unassigned():
            st["colour"][f] = NOT_SPECIFIED
        self.finish_part()

    def back_to_pick(self):
        self._remember()
        st = self.part_state()
        st.update(stage="pick", colour={}, finished=[], cand=dict(st.get("orig_cand", st["cand"])))
        self.save()
        self.stage_pick()

    # stage 3: done -> move the photos
    def _move_files(self):
        """my_photos/<part>/<colour>/, printed ones in a 'printed' folder inside it."""
        st = self.part_state()
        part = self.parts[self.i]
        printed = set(st.get("printed", []))
        for f, colour in st["colour"].items():
            dest = config.MY_PHOTOS / part / colour
            if f in printed:
                dest = dest / PRINTED
            dest.mkdir(parents=True, exist_ok=True)
            src = st["path"][f]
            target = dest / f
            if str(target) != src:
                shutil.move(src, target)
                st["path"][f] = str(target)

    def finish_part(self):
        st = self.part_state()
        self._move_files()
        st["stage"] = "done"
        self.save()
        self.show_part(self.i + 1 if self.i + 1 < len(self.parts) else self.i)

    def stage_done(self):
        st = self.part_state()
        from collections import Counter
        counts = Counter(st["colour"].values())
        self.help.configure(text="Done: these photos are in my_photos/" + self.parts[self.i] + "/<colour>/. "
                                 + ", ".join(f"{c}: {n}" for c, n in counts.most_common())
                                 + ". You can start this piece again if something is wrong, or click photos "
                                 "and mark them as printed.")
        self._show_grid(list(st["colour"]), selectable=True, captions=st["colour"])
        self._clear_bottom()
        self._add_colour_row(done_stage=True)
        ttk.Button(self.bottom, text="Start this piece again", command=self.back_to_pick).pack(side="left")
        self.mark_count = ttk.Label(self.bottom, text="0 marked")
        self.mark_count.pack(side="left", padx=8)
        self._printed_buttons()
        ttk.Button(self.bottom, text="Next piece ▶", command=lambda: self.show_part(self.i + 1)).pack(side="right")


def run():
    app = ColourReview()
    try:
        if app.winfo_exists():
            app.protocol("WM_DELETE_WINDOW", lambda: (app.save(), app.destroy()))
            app.mainloop()
    except tk.TclError:   # closed straight away (nothing to check)
        pass


if __name__ == "__main__":
    run()
