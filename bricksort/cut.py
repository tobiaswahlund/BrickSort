"""Cut a photo with several pieces into one picture per piece.

Put photos in my_photos/_to_cut/ (pieces spread out on a plain surface, not touching).
Run:  python -m bricksort.cut   (or double-click "Cut out pieces.bat")

For each photo the pieces are found automatically and shown with numbered boxes.
- Drag on the photo to add a box the finder missed; drag a box's edge or corner to resize it;
  right-click a box to remove it.
- The model's guess for part and colour is filled in; fix what's wrong
  (clear the part number to skip a piece).
- "Save pieces, next photo" files each piece in my_photos/<part>/<colour>/ and
  moves the photo to my_photos/_to_cut/done/.
- Unfinished photos keep their boxes and typed answers (my_photos/_to_cut/progress/):
  saved when you go to another photo, close the window, or press "Save draft".
"""
import json
import sys
import re
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, simpledialog, ttk

import numpy as np
from PIL import Image, ImageOps, ImageTk

from . import catalog, config, custom
from .ui import Label
from .sorter.detector import Detector

TO_CUT = config.MY_PHOTOS / "_to_cut"
TO_CUT_TEST = config.MY_PHOTOS / "_to_cut_test"   # photos for the honest test (python -m bricksort.cut --test)
VIEW = 760  # longest side of the photo on screen


def wide_dropdown(combo):
    """Make the opened list wide enough to show the longest option in full."""
    font = tkfont.nametofont("TkDefaultFont")

    def resize():
        try:
            popdown = combo.tk.eval(f"ttk::combobox::PopdownWindow {combo}")
            need = max((font.measure(str(v)) for v in combo.cget("values")), default=0) + 40
            w, h = combo.tk.call("winfo", "width", popdown), combo.tk.call("winfo", "height", popdown)
            x, y = combo.tk.call("winfo", "rootx", popdown), combo.tk.call("winfo", "rooty", popdown)
            if need > int(w):
                combo.tk.call("wm", "geometry", popdown, f"{need}x{h}+{x}+{y}")
        except tk.TclError:
            pass

    combo.configure(postcommand=lambda: combo.after(1, resize))  # after Tk has placed the list


def autocomplete(combo, values):
    """Typing suggests matching options: the rest of the best match is filled in (press Tab or
    Enter to accept, keep typing to change it), and the dropdown shows only matching options."""
    combo._ac_values = [v for v in values if not v.startswith("─")]  # can be swapped later

    def on_key(e):
        if e.keysym in ("Up", "Down", "Left", "Right", "Return", "Tab", "Escape", "Shift_L", "Shift_R",
                        "Control_L", "Control_R"):
            return
        values = combo._ac_values
        typed = combo.get()
        if combo.selection_present():  # don't count the suggested (selected) part as typed
            typed = typed[:combo.index("sel.first")]
        low = typed.lower()
        starts = [v for v in values if v.lower().startswith(low)]
        contains = [v for v in values if low in v.lower() and v not in starts]
        combo.configure(values=(starts + contains) if typed else values)
        if typed and starts and e.keysym != "BackSpace":
            combo.delete(0, "end")
            combo.insert(0, starts[0])
            combo.selection_range(len(typed), "end")
            combo.icursor(len(typed))

    def accept(_):
        combo.selection_clear()
        combo.icursor("end")

    combo.bind("<KeyRelease>", on_key, add="+")
    combo.bind("<Tab>", accept, add="+")
    combo.bind("<Return>", accept, add="+")


MULTIPLE_KINDS = ["Stuck", "Not touching"]


class _Value:
    """Stands in for an entry box when restoring saved progress."""

    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


UNKNOWN_VERSION = "Unknown version"


class PartChooser:
    """Part number box, plus a second dropdown for its version when it has several (3062a / 3062b).
    get() gives the number to save under."""

    def __init__(self, row, line2, cutter):
        self.cutter, self.on_change, self.shown_for = cutter, None, None
        self.number = ttk.Combobox(row, width=10, values=cutter.numbers)
        self.number.pack(side="left", padx=4)
        wide_dropdown(self.number)
        self.version = ttk.Combobox(line2, width=34, state="readonly")
        wide_dropdown(self.version)
        for seq in ("<KeyRelease>", "<<ComboboxSelected>>"):
            self.number.bind(seq, lambda e: self._changed(), add="+")
        self.version.bind("<<ComboboxSelected>>", lambda e: self._fire())

    def widgets(self):
        return self.number, self.version

    def _fire(self):
        if self.on_change:
            self.on_change()

    def _changed(self):
        n = self.number.get().strip()
        found = self.cutter.variants(n)
        key = re.match(r"\d*", n).group()
        if not found:
            self.version.pack_forget()
            self.shown_for = None
        elif key != self.shown_for:   # a new number: offer its versions
            names = self.cutter.rebrickable
            self.version.configure(values=[UNKNOWN_VERSION] + [f"{v}  {names.get(v, '')}" for v in found])
            exact = next((v for v in found if v == n.lower()), None)
            self.version.set(f"{exact}  {names.get(exact, '')}" if exact else UNKNOWN_VERSION)
            self.version.pack(side="top", anchor="w", pady=(0, 2), before=self.version.master.winfo_children()[0])
            self.shown_for = key
        self._fire()

    def get(self):
        n = self.number.get().strip()
        if self.shown_for is None or "+" in n:
            return n
        v = self.version.get()
        return self.cutter.default_version(n) if v == UNKNOWN_VERSION else v.split()[0]

    def set(self, pid):
        """Show a full number: the base number in the first box, the version in the second."""
        pid = (pid or "").strip()
        found = self.cutter.variants(pid)
        self.number.set(re.match(r"\d*", pid).group() if found else pid)
        self.shown_for = None
        self._changed()
        if found and pid.lower() in found:
            self.version.set(f"{pid.lower()}  {self.cutter.rebrickable.get(pid.lower(), '')}")


def find_pieces(img):
    """Boxes (x0, y0, x1, y1) in the photo's own pixels, for things that differ from the surface."""
    small = img.copy()
    small.thumbnail((640, 640))
    a = np.asarray(small)
    h, w = a.shape[:2]
    # The surface the pieces lie on: the most common colour in the middle part of the photo
    mid = a[h // 4:3 * h // 4, w // 4:3 * w // 4].reshape(-1, 3)
    q = mid // 40
    keys, counts = np.unique(q, axis=0, return_counts=True)
    surface = np.median(mid[(q == keys[counts.argmax()]).all(1)], 0)
    # Light changes across a table, so follow the surface colour area by area,
    # using only surface-like pixels in each area (pieces don't count)
    cell = 40
    gh, gw = -(-h // cell), -(-w // cell)
    grid = np.empty((gh, gw, 3), np.float32)
    for i in range(gh):
        for j in range(gw):
            px = a[i * cell:(i + 1) * cell, j * cell:(j + 1) * cell].reshape(-1, 3).astype(np.float32)
            like = px[np.abs(px - surface).max(1) < 70]
            grid[i, j] = np.median(like, 0) if len(like) > 50 else surface
    bg = np.asarray(Image.fromarray(grid.clip(0, 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32)
    det = Detector(threshold=40, min_area=120, merge_gap=0)  # pieces in a photo may lie close together
    det.background = bg
    k = img.width / w
    boxes = []
    for b in det.find(a):
        touches_edge = b.x0 <= 4 or b.y0 <= 4 or b.x1 >= w - 4 or b.y1 >= h - 4
        too_big = (b.x1 - b.x0) * (b.y1 - b.y0) > 0.2 * w * h
        if touches_edge or too_big:
            continue  # things around the table (keyboard, clothes...), not a piece
        boxes.append([int(b.x0 * k), int(b.y0 * k), int(b.x1 * k), int(b.y1 * k)])
    return boxes


def square_crop(img, box, margin=0.05):
    """Exactly what's inside the box (plus a hair of margin), made square by filling the
    sides with the surface colour, so no neighbouring pieces sneak into the picture."""
    x0, y0, x1, y1 = box
    mx, my = (x1 - x0) * margin, (y1 - y0) * margin
    piece = img.crop((int(x0 - mx), int(y0 - my), int(x1 + mx), int(y1 + my)))
    a = np.asarray(piece)
    edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])  # the box's border is mostly surface
    side = max(piece.size)
    square = Image.new("RGB", (side, side), tuple(int(v) for v in np.median(edge, 0)))
    square.paste(piece, ((side - piece.width) // 2, (side - piece.height) // 2))
    return square


class Cutter(tk.Tk):
    """test=True: pieces for the honest accuracy test (Phase 4). Photos come from my_photos/_to_cut_test/,
    the model's guesses are never shown (so the answers can't lean towards them), and pieces are saved in
    my_photos/_test/<part>/<colour>/, which training never uses."""

    def __init__(self, test=False):
        super().__init__()
        self.test = test
        self.to_cut = TO_CUT_TEST if test else TO_CUT
        self.title("BrickSort – cut out TEST pieces (blind: no guesses shown)" if test else "BrickSort – cut out pieces")
        self.configure(padx=10, pady=10)
        parts = catalog.load_parts()
        self.part_ids = [p["id"] for p in parts]  # suggestions; any other number can be typed
        self.rebrickable = {r["part_num"]: r["name"] for r in catalog.read_csv("parts")}
        self.custom_names = {p["id"]: p["name"] for p in parts if p.get("custom")}
        # part numbers grouped by their digits: 3062 -> [3062b, 3062a] (known to the model first;
        # printed versions like 3062bpr0001 are left out, they're saved as the plain part anyway)
        known = set(self.part_ids)
        self._versions = {}
        for pid in self.rebrickable:
            m = re.fullmatch(r"(\d+)([a-z]\d*)?", pid)
            if m:
                self._versions.setdefault(m.group(1), []).append(pid)
        for base, ids in self._versions.items():
            ids.sort(key=lambda p: (p not in known, p))
        # the number box offers each piece once (3062, not 3062a and 3062b); exact numbers can still be typed
        bases = []
        for pid in self.part_ids:
            m = re.fullmatch(r"(\d+)([a-z]\d*)?", pid)
            b = m.group(1) if m and len(self._versions.get(m.group(1), [])) > 1 else pid
            if b not in bases:
                bases.append(b)
        self.numbers = bases
        colors = catalog.colors(include_trans=True)
        self.color_names = catalog.color_choices()  # most used colours first
        self.color_by_id = {cid: n for cid, (n, _) in colors.items()}
        self.recognizer = None
        if config.MODEL_FILE.exists() and not test:   # a test is labelled blind: no model at all
            from .model import Recognizer
            self.recognizer = Recognizer()
        self.guesses = {}
        self.scale = 1.0
        # the photo fills whatever room the window gives it (it's redrawn when the window changes size)
        photo_box = ttk.LabelFrame(self, text="Photo (drag to add a box, drag an edge to resize, right-click to remove)")
        photo_box.grid(row=0, column=0, sticky="nsew")
        self.canvas = tk.Canvas(photo_box, width=VIEW, height=VIEW, bg="#ddd", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=6)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._remove)
        self.canvas.bind("<Configure>", lambda e: self._fit())
        pieces = ttk.LabelFrame(self, text="Pieces")
        pieces.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.info = Label(pieces, text="", wraplength=430, justify="left")
        self.info.pack(anchor="w", padx=8, pady=(6, 4))
        holder = ttk.Frame(pieces)
        holder.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self.rows_canvas = tk.Canvas(holder, width=430, height=300, highlightthickness=0)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.rows_canvas.yview)
        self.rows = ttk.Frame(self.rows_canvas)
        self.rows.bind("<Configure>", lambda e: self.rows_canvas.configure(scrollregion=self.rows_canvas.bbox("all")))
        self.rows_canvas.create_window((0, 0), window=self.rows, anchor="nw")
        self.rows_canvas.configure(yscrollcommand=scroll.set)
        self.rows_canvas.bind("<MouseWheel>", self._wheel)
        self.rows.bind("<MouseWheel>", self._wheel)
        self.rows_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 0))
        ttk.Button(bar, text="Save pieces, next photo ▶", command=self.save).pack(side="right")
        ttk.Button(bar, text="Skip ▶", command=lambda: self.go(+1)).pack(side="right", padx=6)
        ttk.Button(bar, text="◀ Back", command=lambda: self.go(-1)).pack(side="right")
        ttk.Button(bar, text="Save draft", command=self.save_draft).pack(side="left")
        self.status = Label(bar, text="", foreground="#666")
        self.status.pack(side="left", padx=8)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.path = None
        self.go(0)

    # ---------- unfinished work is kept per photo, in _to_cut/progress/ ----------
    def _draft_file(self, path):
        return self.to_cut / "progress" / (path.name + ".json")

    def save_draft(self):
        """Remember the boxes and what's typed for this photo, to pick up later."""
        if not self.path:
            return
        f = self._draft_file(self.path)
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps([{"box": box, "part": p.get(), "color": c.get()} for box, p, c in self.fields]),
                     encoding="utf-8")
        self.status.configure(text=f"Progress saved ({time.strftime('%H:%M:%S')})")

    def close(self):
        self.save_draft()
        self.destroy()

    def _photos(self):
        return [p for p in sorted(self.to_cut.glob("*")) if p.suffix.lower() in config.PHOTO_TYPES]

    def go(self, step):
        """Show the previous (-1) / next (+1) photo, keeping the progress on this one."""
        photos = self._photos()
        if not photos:
            messagebox.showinfo("All done", f"No more photos in my_photos/{self.to_cut.name}.")
            self.destroy()
            return
        if self.path:
            self.save_draft()
        i = photos.index(self.path) if self.path in photos else 0
        self.show(photos[(i + step) % len(photos)], len(photos))

    def show(self, path, n_photos):
        self.path = path
        self.img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        self._fit(draw=False)
        draft = self._draft_file(path)
        if draft.exists():  # pick up where you left off
            saved = json.loads(draft.read_text(encoding="utf-8"))
            self.boxes = [d["box"] for d in saved]
            self.fields = [(box, _Value(d["part"]), _Value(d["color"])) for box, d in zip(self.boxes, saved)]
            how = f"continuing your saved progress: {len(self.boxes)} pieces"
        else:
            self.boxes = find_pieces(self.img)
            self.fields = []
            how = f"found {len(self.boxes)} pieces"
        self.status.configure(text="")
        test = ("TEST PIECES: type the part and colour yourself; the model's guesses are hidden on purpose. "
                "Pieces it doesn't know are fine: keep them.\n") if self.test else ""
        self.info.configure(text=test + f"{path.name}: {how} ({n_photos} photos in {self.to_cut.name}).\n"
                                 "Drag on the photo to add a missed piece. Drag a box's edge or corner to resize it. "
                                 "Right-click a box to remove it.")
        self._redraw()

    def _fit(self, draw=True):
        """Scale the photo to the room the canvas has (boxes are kept in the photo's own pixels)."""
        if getattr(self, "img", None) is None:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 50 or h < 50:   # not laid out yet
            w = h = VIEW
        scale = min(w / self.img.width, h / self.img.height)
        if draw and abs(scale - self.scale) < 1e-3 and getattr(self, "tk_img", None):
            return
        self.scale = scale
        shown = self.img.resize((max(1, int(self.img.width * scale)), max(1, int(self.img.height * scale))))
        self.tk_img = ImageTk.PhotoImage(shown)
        if draw:
            self._draw_photo()

    def _draw_photo(self):
        c = self.canvas
        c.delete("all")
        c.create_image(0, 0, image=self.tk_img, anchor="nw")
        self._draw_boxes()

    def _redraw(self):
        self._draw_photo()
        # keep what was typed for boxes that still exist
        old = {id(box): (p.get(), col.get()) for box, p, col in self.fields}
        for w in self.rows.winfo_children():
            w.destroy()
        self.fields = []
        for i, box in enumerate(self.boxes):
            row = ttk.Frame(self.rows)
            row.pack(fill="x", pady=2)
            thumb = ImageTk.PhotoImage(square_crop(self.img, box).resize((64, 64)))
            lbl = Label(row, image=thumb)
            lbl.image = thumb
            lbl.pack(side="left")
            Label(row, text=f"{i + 1}.", width=3).pack(side="left")
            line2 = ttk.Frame(self.rows)   # under the row: the version dropdown (if any) and the name
            line2.pack(fill="x", padx=(70, 0))
            name = Label(line2, text="", foreground="#666", wraplength=380)
            part = PartChooser(row, line2, self)
            col = ttk.Combobox(row, width=22, values=self.color_names)
            col.pack(side="left", padx=(4, 0))
            wide_dropdown(col)
            autocomplete(col, self.color_names)
            name.pack(side="top", anchor="w")
            guess = self._guess(box)
            if id(box) in old:
                part.set(old[id(box)][0])
                col.set(old[id(box)][1])
            elif guess:  # pre-fill the model's guess; just fix it if it's wrong
                part.set(guess[0])
                col.set(guess[1])
            else:
                col.set("Unknown")
            if guess:
                Label(row, text=f"model: {guess[2]:.0%}", foreground="#666").pack(side="left", padx=4)
            # any number can be typed; show what Rebrickable calls it
            part.on_change = lambda p=part, n=name, c=col: (self._name(p, n), self._colour_mode(p, c))
            part.on_change()
            # the mouse wheel scrolls the list, never the dropdown values
            for w in (row, line2, col, lbl, name, *part.widgets(), *row.winfo_children()):
                w.bind("<MouseWheel>", self._wheel)
            self.fields.append((box, part, col))

    # ---------- part numbers and their versions (3062 -> 3062a, 3062b) ----------
    def variants(self, number):
        """All versions of a part number that Rebrickable has, the ones the model knows first.
        '3062' and '3062b' both give ['3062b', '3062a']; a number without versions gives []."""
        m = re.fullmatch(r"(\d+)([a-z]\d*)?", number.strip().lower())
        if not m:
            return []
        found = self._versions.get(m.group(1), [])
        return found if len(found) > 1 else []

    def default_version(self, number):
        """'Unknown version': saved as the version the model knows (it treats versions as the same piece)."""
        found = self.variants(number)
        return found[0] if found else number

    def _colour_mode(self, part, col):
        """For 'multiple' the second box asks whether the pieces are stuck together or just touching."""
        multiple = catalog.folder_part(part.get().strip() or "x") == catalog.MULTIPLE
        options = MULTIPLE_KINDS if multiple else self.color_names
        if list(col.cget("values")) != list(options):
            col.configure(values=options)
            col._ac_values = list(options)
            if multiple and col.get() not in MULTIPLE_KINDS:
                col.set(MULTIPLE_KINDS[0])
            elif not multiple and col.get() in MULTIPLE_KINDS:
                col.set("Unknown")

    def _wheel(self, e):
        self.rows_canvas.yview_scroll(int(-e.delta / 120), "units")
        return "break"

    def _combo(self, ids):
        """Register e.g. 3937+6134 as one piece of your own (custom_parts.json), once."""
        cid = custom.combo_id(ids)
        if cid not in self.custom_names:
            cat_names = {r["id"]: r["name"].lower() for r in catalog.read_csv("part_categories")}
            cats = {r["part_num"]: cat_names.get(r["part_cat_id"], "") for r in catalog.read_csv("parts")}
            custom.add({"id": cid, "kind": "combo", "parts": ids, "tags": ["combo"],
                        "name": " + ".join(self.rebrickable.get(i, i) for i in ids) + " (together)",
                        "category": next((cats[i] for i in ids if cats.get(i)), "")})
            self.custom_names[cid] = cid
        return cid

    def _unknown_number(self, pid, picture):
        """A number Rebrickable doesn't know: fix a typo, make it a custom piece, or leave it for now.
        Returns the number to save under, or None to skip this piece for now."""
        win = tk.Toplevel(self)
        win.title("Number not on Rebrickable")
        win.configure(padx=12, pady=12)
        win.transient(self)
        thumb = ImageTk.PhotoImage(picture.resize((120, 120)))
        Label(win, image=thumb).grid(row=0, column=0, rowspan=4, padx=(0, 10))
        Label(win, text="This number isn't on Rebrickable. Misspelled? Fix it here:").grid(row=0, column=1, sticky="w")
        number = tk.StringVar(value=pid)
        entry = ttk.Entry(win, textvariable=number, width=24)
        entry.grid(row=1, column=1, sticky="w", pady=4)
        hint = Label(win, text="", foreground="#666", wraplength=320)
        hint.grid(row=2, column=1, sticky="w")

        def check(_=None):
            n = number.get().strip()
            hint.configure(text=self.rebrickable.get(n) or self.custom_names.get(n) or "Still not on Rebrickable")
        entry.bind("<KeyRelease>", check)
        check()
        result = {"pid": None}

        def use():
            result["pid"] = number.get().strip()
            win.destroy()

        def make_custom():
            n = number.get().strip()
            win.destroy()
            result["pid"] = n if self._make_custom(n) else None

        buttons = ttk.Frame(win)
        buttons.grid(row=3, column=1, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="Use this number", command=use).pack(side="left")
        if not self.test:   # a test piece never changes what the model learns
            ttk.Button(buttons, text="Make it a custom piece…", command=make_custom).pack(side="left", padx=6)
        ttk.Button(buttons, text="Not now", command=win.destroy).pack(side="left")
        entry.focus_set()
        entry.select_range(0, "end")
        win.grab_set()
        self.wait_window(win)
        return result["pid"] or None

    def _make_custom(self, pid):
        """Make pid one of your own custom pieces. Returns True if made."""
        name = simpledialog.askstring("New custom piece", f"Name for {pid} (e.g. Minifig helmet, printed, third-party):",
                                      parent=self)
        if not name:
            return False
        category = simpledialog.askstring("New custom piece", "Category (e.g. minifig headwear):",
                                          parent=self) or ""
        tags = simpledialog.askstring("New custom piece", "Your own tags, comma separated (e.g. helmet):", parent=self) or ""
        custom.add({"id": pid, "kind": "custom", "name": name, "category": category, "tags": tags.split(",")})
        self.custom_names[pid] = name
        return True

    def _name(self, part, label):
        pid = part.get().strip()
        if "+" in pid:  # several parts that belong together, e.g. 3937+6134
            ids = [x.strip() for x in pid.split("+") if x.strip()]
            label.configure(text="Treated as ONE piece: " + " + ".join(self.rebrickable.get(i, i) for i in ids)
                                 + ". Colour: write the colours with + too, main part first, e.g. White + Light Bluish Gray")
        elif not pid:
            label.configure(text="(skipped)")
        elif pid in self.rebrickable:
            unsure = isinstance(part, PartChooser) and part.shown_for and part.version.get() == UNKNOWN_VERSION
            label.configure(text=f"Version unknown: saved as {pid}, which the model treats as the same piece"
                            if unsure else self.rebrickable[pid])
        elif pid in self.custom_names:
            label.configure(text=self.custom_names[pid] + " (your own piece)")
        else:
            label.configure(text="Not on Rebrickable: when you save, you can make it a custom piece")

    def _guess(self, box):
        """The model's (part, colour, how sure) for one piece, or None without a model."""
        if self.recognizer is None:
            return None
        key = tuple(box)
        if key not in self.guesses:
            pred = self.recognizer.predict(square_crop(self.img, box).resize((config.IMAGE_SIZE,) * 2))
            part, p = pred.parts[0]
            self.guesses[key] = (part if part not in ("not_lego", "multiple") else "",
                                 self.color_by_id.get(pred.colors[0][0], "Unknown"), p)
        return self.guesses[key]

    def _grab_edge(self, x, y, near=8):
        """(box index, which edges) if (x, y) is on the edge or corner of a box, else None."""
        s = self.scale
        for i, (x0, y0, x1, y1) in enumerate(self.boxes):
            X0, Y0, X1, Y1 = x0 * s, y0 * s, x1 * s, y1 * s
            if not (X0 - near <= x <= X1 + near and Y0 - near <= y <= Y1 + near):
                continue
            edges = {k for k, hit in (("x0", abs(x - X0) < near), ("x1", abs(x - X1) < near),
                                      ("y0", abs(y - Y0) < near), ("y1", abs(y - Y1) < near)) if hit}
            if edges:
                return i, edges
        return None

    def _press(self, e):
        self.start = (e.x, e.y)
        self.resizing = self._grab_edge(e.x, e.y)  # drag an edge or corner to resize a box
        if self.resizing is None:                    # otherwise draw a new box
            self.rubber = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#22e", width=2)

    def _drag(self, e):
        if self.resizing:
            i, edges = self.resizing
            box, s = self.boxes[i], self.scale
            for k in edges:
                idx = {"x0": 0, "y0": 1, "x1": 2, "y1": 3}[k]
                box[idx] = int((e.x if k[0] == "x" else e.y) / s)
            self._draw_boxes()
        else:
            self.canvas.coords(self.rubber, *self.start, e.x, e.y)

    def _release(self, e):
        if self.resizing:
            i, _ = self.resizing
            x0, y0, x1, y1 = self.boxes[i]
            self.boxes[i] = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
            self.guesses.pop(tuple(self.boxes[i]), None)
            self.resizing = None
            self._redraw()
            return
        (x0, y0), s = self.start, self.scale
        x0, x1 = sorted((x0, e.x))
        y0, y1 = sorted((y0, e.y))
        if x1 - x0 > 8 and y1 - y0 > 8:
            self.boxes.append([int(x0 / s), int(y0 / s), int(x1 / s), int(y1 / s)])
        self._redraw()

    def _draw_boxes(self):
        c, s = self.canvas, self.scale
        c.delete("box")
        for i, (x0, y0, x1, y1) in enumerate(self.boxes, 1):
            c.create_rectangle(x0 * s, y0 * s, x1 * s, y1 * s, outline="#e22", width=2, tags="box")
            c.create_text(x0 * s + 4, y0 * s + 2, text=str(i), anchor="nw", fill="#e22",
                          font=("Segoe UI", 12, "bold"), tags="box")

    def _remove(self, e):
        s = self.scale
        self.boxes = [b for b in self.boxes if not (b[0] * s <= e.x <= b[2] * s and b[1] * s <= e.y <= b[3] * s)]
        self._redraw()

    def save(self):
        saved, saved_boxes, held = 0, [], False
        for i, (box, part, col) in enumerate(self.fields, 1):
            pid = part.get().strip()
            if not pid:
                continue
            if "+" in pid:  # several parts that belong together: one combo piece
                pid = self._combo([catalog.base_part(x.strip()) for x in pid.split("+") if x.strip()])
            else:
                pid = catalog.folder_part(pid) or pid  # printed version -> plain part
                if pid not in self.rebrickable and pid not in self.custom_names and pid not in catalog.SPECIAL:
                    pid = self._unknown_number(pid, square_crop(self.img, box))
                    if pid is None:  # "Not now": keep this piece (and the photo) for later
                        held = True
                        continue
                    part.set(pid)
            colour = col.get().strip()
            if colour == catalog.SEPARATOR:
                colour = "Unknown"
            if self.test:   # the honest test: my_photos/_test/<part>/<colour>/ (no colour folder if unknown)
                folder = config.TEST_DIR / pid
                if colour and colour not in ("Unknown", *MULTIPLE_KINDS):
                    folder = folder / colour
            elif pid == catalog.MULTIPLE:  # my_photos/_multiple/Stuck or /Not_touching
                folder = config.MY_PHOTOS / "_multiple" / ("Stuck" if colour == "Stuck" else "Not_touching")
            elif colour in ("", "Unknown") and pid not in catalog.SPECIAL and "+" not in part.get():
                # colour not known yet: into Check colours' folder, where you give it its colour later
                from .colour_review import NOT_SPECIFIED, SOURCE
                folder = SOURCE / pid / NOT_SPECIFIED
            else:
                folder = config.MY_PHOTOS / pid
                if colour and colour != "Unknown":
                    folder = folder / colour
            folder.mkdir(parents=True, exist_ok=True)
            square_crop(self.img, box).save(folder / f"{self.path.stem}_{i}.jpg", quality=92)
            saved += 1
            saved_boxes.append(box)
        if held:  # some pieces still need a number: the saved ones leave the list, the photo stays
            self.boxes = [b for b in self.boxes if not any(b is s for s in saved_boxes)]
            self._redraw()
            self.save_draft()
            self.status.configure(text=f"Saved {saved} pieces. The rest stay here until you fix their numbers.")
            return
        done = self.to_cut / "done"
        done.mkdir(exist_ok=True)
        self._draft_file(self.path).unlink(missing_ok=True)
        photos = self._photos()
        i = photos.index(self.path)
        self.path.rename(done / self.path.name)
        self.path = None
        rest = self._photos()
        if not rest:
            messagebox.showinfo("All done", f"Saved {saved} pieces. No more photos in my_photos/{self.to_cut.name}.")
            self.destroy()
            return
        self.show(rest[min(i, len(rest) - 1)], len(rest))
        self.status.configure(text=f"Saved {saved} pieces from the last photo.")


def run():
    app = Cutter(test="--test" in sys.argv)
    try:
        app.mainloop()
    except tk.TclError:   # closed straight away (no photos to cut)
        pass


if __name__ == "__main__":
    run()
