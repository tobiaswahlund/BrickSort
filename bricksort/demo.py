"""The virtual demo: choose a piece, drop it, let the camera + model guess, then review.

Run:  python -m bricksort.demo
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import numpy as np
from PIL import Image, ImageTk

from . import catalog, config, custom, junk
from .ldraw import Library
from .ui import MUTED, ImageBox, Label, make_copyable
from .render import real_colors
from .cut import autocomplete, wide_dropdown
from .model import Prediction
from .viewer import PartViewer
from .scene import DropScene
from .train import load_square, photos_in

VIEW = 420  # size of the big 3D view on screen


def photo(img, size):
    if not isinstance(img, Image.Image):
        img = Image.fromarray(img)
    return ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))


ASSETS = Path(__file__).resolve().parent / "assets"


def reference_image(part_id):
    """The reference picture, or for your own pieces (no 3D model) one of your photos.
    'Several pieces' has its own picture (assets/multiple.png, rendered on the sorting machine's belt)."""
    if (ASSETS / f"{part_id}.png").exists():
        return Image.open(ASSETS / f"{part_id}.png")
    path = config.REFERENCE / f"{part_id}.png"
    if not path.exists():
        photos = [p for p in (config.MY_PHOTOS / part_id).rglob("*") if p.suffix.lower() in config.PHOTO_TYPES] \
            if (config.MY_PHOTOS / part_id).exists() else []
        if photos:
            return load_square(photos[0])
    return Image.open(path) if path.exists() else Image.new("RGB", (224, 224), (225, 225, 225))


def reference_photo(part_id, size):
    return photo(reference_image(part_id), size)


class Demo(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BrickSort – virtual demo")
        self.configure(padx=10, pady=10)
        self.lib = Library()
        self.parts = catalog.load_parts()
        self.by_id = {p["id"]: p for p in self.parts}
        self.colors = catalog.colors(include_trans=True)
        self.color_list = catalog.color_choices()  # "Unknown", most used colours, a line, the rest
        self.twins = catalog.twins()            # mold variants / alternates, from Rebrickable
        self.bins = catalog.sort_groups(self.twins)
        self.rng = np.random.default_rng()
        self.scene, self.scene_part = None, None
        self.recognizer = None
        self.tally = {"drops": 0, "first": 0, "top5": 0, "color": 0}
        self._keep = []  # Tk forgets images unless we hold on to them
        self._build()
        self.load_model()

    # ---------- layout ----------
    def _build(self):
        pad = {"padx": 8, "pady": 6}
        # ---- toolbar: the other tasks, so the left side is only about dropping a piece
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=3, sticky="we", pady=(0, 8))
        ttk.Button(bar, text="Open photo…", command=self.open_photo).pack(side="left")
        ttk.Button(bar, text="Sort unknown photos…", command=self.review_unknown).pack(side="left", padx=6)
        ttk.Button(bar, text="Review rest bin…", command=self.review_rest).pack(side="left")
        ttk.Button(bar, text="Spot check…", command=self.spot_check).pack(side="left", padx=6)
        self.retrain_btn = ttk.Button(bar, text="Retrain model", command=self.retrain)
        self.retrain_btn.pack(side="right")
        ttk.Button(bar, text="New custom piece…", command=self.new_custom_piece).pack(side="right", padx=6)

        # ---- left: choose a piece and drop it
        left = ttk.LabelFrame(self, text="Piece")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="Search by number or name").grid(row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._fill_list())
        ttk.Entry(left, textvariable=self.search).grid(row=1, column=0, sticky="we", padx=8, pady=(2, 4))
        lst = ttk.Frame(left)
        lst.grid(row=2, column=0, sticky="nsew", padx=8)
        # fixed-width font, so the part numbers and names line up in columns
        self.listbox = tk.Listbox(lst, width=44, height=14, exportselection=False, activestyle="none",
                                  font=("Consolas", 9))
        sb = ttk.Scrollbar(lst, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._show_preview())
        self.listbox.bind("<Double-Button-1>", lambda e: self.drop())
        self.preview = Label(left)
        self.preview.grid(row=3, column=0, pady=6)
        ttk.Label(left, text="Colour").grid(row=4, column=0, sticky="w", padx=8)
        self.color_choice = ttk.Combobox(left, state="readonly", width=38)
        wide_dropdown(self.color_choice)
        self.color_choice.grid(row=5, column=0, sticky="we", padx=8)
        self.color_choice.set("Random")
        btns = ttk.Frame(left)
        btns.grid(row=6, column=0, sticky="we", padx=8, pady=8)
        ttk.Button(btns, text="▼ Drop", command=self.drop).pack(side="left", expand=True, fill="x")
        ttk.Button(btns, text="Random piece", command=self.random_drop).pack(side="left", expand=True, fill="x",
                                                                          padx=(6, 0))

        # ---- right: the drop and what the camera saw (both grow with the window)
        world = ttk.LabelFrame(self, text="Simulation")
        world.grid(row=1, column=1, sticky="nsew")
        self.view = ImageBox(world, VIEW, VIEW)
        self.view.pack(fill="both", expand=True, **pad)
        cam = ttk.LabelFrame(self, text="Camera picture")
        cam.grid(row=1, column=2, sticky="nsew", padx=(8, 0))
        self.camera = ImageBox(cam, 224, 224)
        self.camera.pack(fill="both", expand=True, **pad)

        # ---- bottom: what happened
        bottom = ttk.LabelFrame(self, text="Log")
        bottom.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        self.log = tk.Text(bottom, height=6, width=60, state="disabled", font=("Consolas", 9), wrap="word",
                           relief="flat")
        make_copyable(self.log)  # select + Ctrl+C, or right-click > Copy
        log_sb = ttk.Scrollbar(bottom, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y", pady=6)
        self.log.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        self.status = Label(self, text="Choose a piece and press Drop (or double-click it).", foreground=MUTED,
                            wraplength=900, justify="left")
        self.status.grid(row=4, column=0, columnspan=3, sticky="we", pady=(6, 0))

        self.columnconfigure(1, weight=3)
        self.columnconfigure(2, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(3, weight=1)
        blank = Image.new("RGB", (VIEW, VIEW), (235, 235, 235))
        self.view.set(blank)
        self.camera.set(blank)
        self._fill_list()

    def _set(self, label, img):
        label.configure(image=img)
        label.image = img

    def _fill_list(self):
        q = self.search.get().lower().strip()
        self.listed = [p for p in self.parts if not q or q in p["id"].lower() or q in p["name"].lower()]
        self.listbox.delete(0, "end")
        for p in self.listed:
            self.listbox.insert("end", f"{p['id']:9s} {p['name']}")
        if self.listed:
            self.listbox.selection_set(0)
            self._show_preview()

    def _selected(self):
        sel = self.listbox.curselection()
        return self.listed[sel[0]] if sel and self.listed else None

    def _show_preview(self):
        part = self._selected()
        if not part:
            return
        self._set(self.preview, reference_photo(part["id"], 120))
        names = ["Random"] + [f"{self.colors[c][0]}" for c in part.get("colors", []) if c in self.colors]
        names += [n for n in self.color_list[1:] if n not in names]  # then the most used colours
        self.color_choice["values"] = names
        if self.color_choice.get() not in names:
            self.color_choice.set("Random")

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def load_model(self):
        if not config.MODEL_FILE.exists():
            self.recognizer = None
            self.write("No trained model yet – drops work, but there are no guesses until you train.")
            return
        from .model import Recognizer
        self.recognizer = Recognizer()
        i = self.recognizer.info
        self.write(f"Model loaded: knows {len(self.recognizer.classes)} parts, trained {i.get('trained', '?')}, "
                   f"on test pictures part right {i.get('top1', 0):.0%} (top 5: {i.get('top5', 0):.0%}), "
                   f"colour right {i.get('color', 0):.0%}. {i.get('real', 0)} real photos/corrections used.")
        if i.get("real_test_n"):
            self.write(f"On {i['real_test_n']} of your real photos it never trained on: part right "
                       f"{i['real_top1']:.0%} (top 5: {i['real_top5']:.0%}), colour right {i['real_color']:.0%}.")

    # ---------- dropping ----------
    def random_drop(self):
        self.search.set("")
        k = int(self.rng.integers(len(self.listed)))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(k)
        self.listbox.see(k)
        self._show_preview()
        self.drop()

    def _color(self, part):
        """Colour id chosen in the dropdown, or a random likely one."""
        name = self.color_choice.get()
        for cid, (n, _) in self.colors.items():
            if n == name:
                return cid
        ids, w = real_colors(part, self.colors)  # only colours this part really comes in
        return ids[self.rng.choice(len(ids), p=w)]

    def drop(self):
        part = self._selected()
        if not part:
            return
        if part.get("custom"):
            self.status.configure(text=f"{part['id']} is one of your own pieces: there's no 3D model to drop. "
                                       "Use 'Open a real photo…' instead.")
            return
        is_junk = part["id"] == junk.NOT_LEGO
        if self.scene_part != part["id"] or is_junk:  # a new random object each time for "not Lego"
            if self.scene:
                self.scene.close()
            self.status.configure(text=f"Loading 3D model of {part['id']} …")
            self.update()
            mesh = junk.random_mesh(self.rng, self.rng.uniform(0.05, 0.3)) if is_junk else self.lib.part_mesh(part["id"])
            self.scene = DropScene(*mesh)
            self.scene_part = part["id"]
        cid = self._color(part)
        self.scene.set_color(junk.random_color(self.rng) if is_junk else self.colors[cid][1],
                             transparent=not is_junk and self.colors[cid][0].startswith("Trans"))
        self.scene.randomize_look(self.rng)
        self.status.configure(text=f"Dropping {part['id']} {part['name']} in {self.colors[cid][0]} …")
        frames = self.scene.drop(self.rng, frame_every=12, camera="side")
        self._animate(frames, (part["id"], cid))

    def _animate(self, frames, truth):
        try:
            frame = next(frames)
        except StopIteration:
            self._photograph(truth)
            return
        self.view.set(frame)
        self.after(15, self._animate, frames, truth)

    def _photograph(self, truth):
        full, crop = self.scene.snapshot(config.IMAGE_SIZE, rng=self.rng)
        if crop is None:
            self.status.configure(text="The piece ended up out of the camera's view. Drop it again!")
            return
        self.camera.set(crop)
        self.status.configure(text="Camera took a picture. Asking the model …")
        self.update()
        self.review(crop, truth=truth)

    def open_photo(self):
        path = filedialog.askopenfilename(filetypes=[("Pictures", "*.png *.jpg *.jpeg *.bmp")])
        if not path:
            return
        img = load_square(path)
        self.camera.set(img)
        self.review(img, truth=None)

    def review_unknown(self, _skip=()):
        """Show each photo in my_photos/unknown; picking an ID moves it to my_photos/<ID>/."""
        todo = [p for p in photos_in(config.MY_PHOTOS / "unknown") if p not in _skip]
        if not todo:
            messagebox.showinfo("All done", "There are no more photos in my_photos/unknown.")
            return
        path = todo[0]
        img = load_square(path)
        self.camera.set(img)
        self.status.configure(text=f"{len(todo)} unknown photos left. Showing {path.name}.")
        win = self.review(img, truth=None, source=path)
        win.bind("<Destroy>", lambda e: e.widget is win and self.after(
            100, self.review_unknown, (*_skip, path) if path.exists() else _skip))

    def review_rest(self):
        """Go through the pieces the sorting machine put in the rest bin, and say what they were."""
        self.review_log(config.REST_LOG, spot_check=False)

    def spot_check(self):
        """Check pieces the machine did sort (least sure first): gives a real-world accuracy figure."""
        self.review_log(config.SORTED_LOG, spot_check=True)

    def review_log(self, folder, spot_check):
        todo = []
        for png in (folder.glob("*.png") if folder.exists() else []):
            meta_file = png.with_suffix(".json")
            meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
            todo.append((meta.get("parts", [["", 0]])[0][1] if spot_check else 0, png.name, png, meta))
        if not todo:
            messagebox.showinfo("All done", "Nothing left to check here.")
            return
        _, _, png, meta = min(todo)  # spot check: least sure first. Rest bin: oldest first
        meta_file = png.with_suffix(".json")
        crop = Image.open(png).convert("RGB")
        crop.load()
        self.camera.set(crop)
        if spot_check:
            self.status.configure(text=f"Spot check: {len(todo)} sorted pieces to check. The machine put this "
                                       f"one in '{meta.get('bin', '?')}'. If the first guess is right, click it.")
        else:
            self.status.configure(text=f"{len(todo)} rest-bin pieces to review. Why it went there: "
                                       f"{meta.get('reason', '?')} ({meta.get('time', '')})")
        pred = Prediction(meta["parts"], meta["colors"], meta.get("categories", [])) if "parts" in meta else None

        def done(part_id=None, color=None):
            png.unlink(missing_ok=True)
            meta_file.unlink(missing_ok=True)
            if spot_check and pred and part_id:
                self._record_spot_check(pred, part_id, color)

        def not_lego():
            self.save_correction(crop, junk.NOT_LEGO)
            done()
            win.destroy()

        def several():
            self.save_correction(crop, catalog.MULTIPLE)  # teaches "several pieces" -> rest bin
            done()
            win.destroy()

        win = self.review(crop, truth=None, pred=pred, on_saved=done,
                          extra=[("Not LEGO", not_lego), ("Several pieces", several)])
        # answered -> show the next one; "Skip" keeps it for later and stops
        win.bind("<Destroy>", lambda e: e.widget is win and not png.exists()
                 and self.after(100, self.review_log, folder, spot_check))

    def _record_spot_check(self, pred, part_id, color):
        """Keep score of spot checks: how often the machine was right in the real world."""
        f = config.PROJECT_DIR / "spot_check_results.json"
        s = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"checked": 0, "part_right": 0, "color_right": 0}
        s["checked"] += 1
        s["part_right"] += catalog.same_piece(pred.parts[0][0], catalog.base_part(part_id))  # 12002 = 12002b
        s["color_right"] += catalog.same_colour(self.color_name(pred.colors[0][0])) == catalog.same_colour(color)
        f.write_text(json.dumps(s), encoding="utf-8")
        self.write(f"Spot check so far: {s['checked']} checked, part right {s['part_right'] / s['checked']:.0%}, "
                   f"colour right {s['color_right'] / s['checked']:.0%}.")

    # ---------- review window ----------
    def review(self, crop, truth, source=None, pred=None, on_saved=None, extra=()):
        if pred is None and self.recognizer:
            pred = self.recognizer.predict(crop)
        guesses, color_guesses = (pred.parts, pred.colors) if pred else ([], [])
        if pred and pred.categories:
            self.write("Category guess: " + ", ".join(f"{g} {p:.0%}" for g, p in pred.categories))
        if truth:
            part_id, cid = truth
            t = self.tally
            t["drops"] += 1
            ids = [g for g, _ in guesses]
            t["first"] += bool(ids and catalog.same_piece(ids[0], part_id))   # 12002 counts for 12002b
            t["top5"] += any(catalog.same_piece(i, part_id) for i in ids)
            t["color"] += bool(color_guesses and catalog.same_colour(self.color_name(color_guesses[0][0]))
                               == catalog.same_colour(self.color_name(cid)))
            self.status.configure(text=f"This session: {t['drops']} drops. Part right on first guess {t['first']}, "
                                       f"within top 5 {t['top5']}. Colour right {t['color']}.")
        return ReviewWindow(self, crop, guesses, color_guesses, truth, source, on_saved, extra)

    def color_name(self, cid):
        return self.colors[cid][0] if cid in self.colors else "Unknown"

    def reload_parts(self):
        self.parts = catalog.load_parts()
        self.by_id = {p["id"]: p for p in self.parts}
        self._fill_list()

    def new_custom_piece(self):
        entry = CustomPieceForm(self).result
        if entry:
            self.write(f"Made custom piece {entry['id']} ({entry['name']}). Put its photos in "
                       f"my_photos/{entry['id']}/<colour>/ and press Retrain.")

    def treat_as_one(self, crop, color_name, window):
        """Several real parts that belong together (e.g. a hinge pair): learn them as one piece."""
        text = simpledialog.askstring("Treat as one piece", "Which part numbers are stuck together?\n"
                                      "Separate them with +, for example: 4592 + 4593", parent=window)
        if not text:
            return
        ids = [catalog.base_part(t.strip()) for t in text.replace(",", "+").split("+") if t.strip()]
        if len(ids) < 2:
            return
        cid = custom.combo_id(ids)
        if cid not in self.by_id:
            first = self.by_id.get(ids[0], {})
            names = " + ".join(self.by_id.get(i, {}).get("name", i) for i in ids)
            custom.add({"id": cid, "kind": "combo", "parts": ids, "name": f"{names} (together)",
                        "category": first.get("category", ""), "tags": ["combo"]})
            self.reload_parts()
            self.write(f"New combo piece {cid}: from the next retrain it's learned as one piece.")
        if self.save_correction(crop, cid, color_name):
            window.finish(cid, color_name)

    def save_correction(self, crop, part_id, color_name="Unknown", source=None):
        typed = part_id.strip()
        part_id = typed if typed in self.by_id else catalog.folder_part(typed) or typed
        if part_id != typed:
            self.write(f"{typed} is a printed version of {part_id}; saved as {part_id}.")
        if color_name == catalog.SEPARATOR:
            color_name = "Unknown"
        color_dir = () if color_name in ("", "Unknown") or part_id in catalog.SPECIAL else (color_name,)
        if part_id not in self.by_id and part_id not in catalog.SPECIAL:
            if not self.lib.has_part(part_id):
                if messagebox.askyesno("Unknown part", f"{part_id} isn't on Rebrickable/LDraw. Make it one of your "
                                       "own custom pieces (name, category and tags you choose)?"):
                    entry = CustomPieceForm(self, suggested_id=part_id).result
                    if not entry:
                        return False
                    part_id = entry["id"]
                elif not messagebox.askyesno("Unknown part", "Save the photo under that number anyway?"):
                    return False
            else:
                name = self.lib.title(part_id) or part_id
                entry = {"id": part_id, "name": name, "category": "added by you", "colors": []}
                self.parts.append(entry)
                self.by_id[part_id] = entry
                catalog.save_parts(self.parts)
                self._fill_list()
                self.write(f"Added new part {part_id} ({name}). It will be learned at the next retrain.")
        if source:  # one of your own photos: move it into its part (and colour) folder
            folder = config.MY_PHOTOS.joinpath(part_id, *color_dir)
            folder.mkdir(parents=True, exist_ok=True)
            source.rename(folder / source.name)
            self.write(f"Moved {source.name} to my_photos/{'/'.join((part_id, *color_dir))}/")
            return True
        folder = config.CORRECTIONS.joinpath(part_id, *color_dir)
        folder.mkdir(parents=True, exist_ok=True)
        crop.save(folder / f"{time.strftime('%Y%m%d-%H%M%S')}.png")
        n = sum(1 for _ in config.CORRECTIONS.rglob("*.png"))
        self.write(f"Saved as {part_id}, {color_name}. You have {n} confirmed pictures in total.")
        return True

    # ---------- retraining ----------
    def retrain(self):
        if getattr(self, "_training", False):
            return
        self._training = True
        self.write("Retraining: making pictures of any new parts, then training. This window stays usable.")
        q = queue.Queue()

        def run():
            for cmd in (["-m", "bricksort.render"], ["-m", "bricksort.train", "3"]):
                p = subprocess.Popen([sys.executable, *cmd], cwd=config.PROJECT_DIR, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                     bufsize=1, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in p.stdout:
                    if not line.startswith("["):  # skip the long per-part render listing
                        q.put(line)
                if p.wait() != 0:
                    q.put(f"Step {' '.join(cmd)} failed.\n")
                    break
            q.put(None)

        threading.Thread(target=run, daemon=True).start()

        def pump():
            try:
                while True:
                    line = q.get_nowait()
                    if line is None:
                        self._training = False
                        self.load_model()
                        return
                    self.write(line)
            except queue.Empty:
                pass
            self.after(200, pump)
        pump()


class ReviewWindow(tk.Toplevel):
    def __init__(self, app, crop, guesses, color_guesses, truth, source=None, on_saved=None, extra=()):
        super().__init__(app)
        self.app, self.crop, self.source, self.on_saved = app, crop, source, on_saved
        self.title("Check the guess")
        self.configure(padx=12, pady=12)
        self.transient(app)
        imgs = []

        top = ttk.Frame(self)
        top.pack(fill="x")
        seen = ttk.LabelFrame(top, text="Photo")
        seen.pack(side="left", anchor="n")
        imgs.append(photo(crop, 200))
        Label(seen, image=imgs[-1]).pack(padx=8, pady=6)
        info = ttk.LabelFrame(top, text="Colour")
        info.pack(side="left", padx=(8, 0), anchor="n", fill="y")
        info = ttk.Frame(info, padding=(8, 4))
        info.pack(fill="both")

        # Colour: the model's top guesses as swatches, plus a dropdown to correct it
        ttk.Label(info, text="The model's guesses (click to use):" if color_guesses else "Choose the colour:"
                  ).pack(anchor="w", pady=(0, 2))
        self.color = ttk.Combobox(info, width=28, values=app.color_list)
        wide_dropdown(self.color)
        autocomplete(self.color, app.color_list)
        for cid, p in color_guesses:
            rgb = app.colors.get(cid, ("", (128, 128, 128)))[1]
            line = ttk.Frame(info)
            line.pack(anchor="w")
            tk.Label(line, width=3, bg="#%02x%02x%02x" % rgb, relief="solid", bd=1).pack(side="left")
            ttk.Button(line, text=f"{app.color_name(cid)} ({p:.0%})",
                       command=lambda c=cid: self.color.set(app.color_name(c))).pack(side="left", padx=4)
        self.color.set(app.color_name(color_guesses[0][0]) if color_guesses else "Unknown")
        self.color.pack(anchor="w", pady=(4, 0))

        if truth:
            part_id, cid = truth
            self.reveal = Label(info, text="", wraplength=260)
            ttk.Button(info, text="Show which piece was dropped", command=lambda: self.reveal.configure(
                text=f"Dropped: {part_id} {app.by_id.get(part_id, {}).get('name', '')}, "
                     f"{app.color_name(cid)}")).pack(anchor="w", pady=(10, 2))
            self.reveal.pack(anchor="w")

        parts_box = ttk.LabelFrame(self, text="Part: select the right one (drag a piece to turn it, scroll to zoom)"
                                   if guesses else "Part: no trained model yet, so type the number below")
        parts_box.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(parts_box, padding=6)
        row.pack()
        guess_rgb = app.colors.get(color_guesses[0][0], (None, (160, 165, 169)))[1] if color_guesses else (160, 165, 169)
        for part_id, p in guesses:
            card = ttk.Frame(row, relief="groove", padding=6)
            card.pack(side="left", padx=4, anchor="n")
            # a 3D model of the guess, in the guessed colour, that you can spin around
            PartViewer(card, app.lib, part_id, rgb=guess_rgb, size=130, fallback=reference_image(part_id)).pack()
            Label(card, text=part_id, font=("Segoe UI", 11, "bold")).pack()
            name = app.by_id.get(part_id, {}).get("name", "")
            Label(card, text=name, wraplength=130, justify="center").pack()
            Label(card, text=f"{p:.0%} sure").pack()
            for other, kind in app.twins.get(part_id, [])[:3]:
                Label(card, text=f"Look-alike: {other} ({kind})", foreground="#a05a00").pack()
            if part_id in app.bins and app.bins[part_id] != part_id:
                Label(card, text=f"Sorts into bin {app.bins[part_id]}", foreground="#666").pack()
            ttk.Button(card, text="Select", command=lambda i=part_id: self.choose(i)).pack(pady=(4, 0))

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Label(bottom, text="None of these? Part number:").pack(side="left")
        self.entry = ttk.Combobox(bottom, width=14, values=[p["id"] for p in app.parts])
        self.entry.pack(side="left", padx=6)
        self.entry.bind("<Return>", lambda e: self.choose(self.entry.get()))
        ttk.Button(bottom, text="Save", command=lambda: self.choose(self.entry.get())).pack(side="left")
        ttk.Button(bottom, text="Skip", command=self.destroy).pack(side="right")
        for label, command in extra:
            ttk.Button(bottom, text=label, command=command).pack(side="right", padx=4)
        if not source:
            ttk.Button(bottom, text="Treat as one piece…",
                       command=lambda: app.treat_as_one(crop, self.color.get().strip(), self)).pack(side="right", padx=4)
        self.hint = Label(self, text="", foreground="#666")
        self.hint.pack(anchor="w")
        self.entry.bind("<KeyRelease>", self._hint)
        self.images = imgs
        self.entry.focus_set()

    def _hint(self, _):
        part = self.app.by_id.get(self.entry.get().strip())
        self.hint.configure(text=part["name"] if part else "")

    def choose(self, part_id):
        if part_id.strip() and self.app.save_correction(self.crop, part_id, self.color.get().strip(), self.source):
            self.finish(part_id.strip(), self.color.get().strip())

    def finish(self, part_id, color):
        if self.on_saved:
            self.on_saved(part_id, color)
        self.destroy()


class CustomPieceForm(tk.Toplevel):
    """Make one of your own pieces: a number, name, category and tags (e.g. 'helmet')."""

    def __init__(self, app, suggested_id=None):
        super().__init__(app)
        self.app, self.result = app, None
        self.title("New custom piece")
        self.configure(padx=12, pady=12)
        self.transient(app)
        cats = sorted({p.get("category", "") for p in app.parts + catalog.load_category_parts()} - {""})
        self.vars = {}
        fields = (("Number", suggested_id or custom.next_id(), None),
                  ("Name", "", None),
                  ("Category", "minifig shields, weapons, & tools", cats),
                  ("Tags (comma separated)", "", None))
        for i, (label, value, options) in enumerate(fields):
            Label(self, text=label).grid(row=i, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=value)
            widget = ttk.Combobox(self, textvariable=var, values=options, width=40) if options else \
                ttk.Entry(self, textvariable=var, width=43)
            if options:
                wide_dropdown(widget)
                autocomplete(widget, options)
            widget.grid(row=i, column=1, pady=3)
            self.vars[label] = var
        Label(self, text="The model learns it from your photos in my_photos/<number>/<colour>/.\n"
                             "The category also teaches the category answer; tags can be used in bins.json.",
                  foreground="#666").grid(row=4, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(self, text="Make piece", command=self._ok).grid(row=5, column=1, sticky="e")
        self.grab_set()
        self.wait_window()

    def _ok(self):
        v = {k: var.get().strip() for k, var in self.vars.items()}
        if not v["Number"] or not v["Name"]:
            messagebox.showwarning("Missing", "Please give it a number and a name.", parent=self)
            return
        self.result = custom.add({"id": v["Number"], "kind": "custom", "name": v["Name"],
                                  "category": v["Category"], "tags": v["Tags (comma separated)"].split(",")})
        self.app.reload_parts()
        self.destroy()


def run():
    app = Demo()
    if "--rest" in sys.argv:      # opened from the sorting machine's buttons
        app.after(300, app.review_rest)
    elif "--spot" in sys.argv:
        app.after(300, app.spot_check)
    app.mainloop()


if __name__ == "__main__":
    run()
