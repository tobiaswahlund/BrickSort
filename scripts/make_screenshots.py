"""Make the annotated screenshots in docs/WINDOWS.md: every window, with a numbered red box on each
button and control, and a line per number saying what it does.

Run:  python scripts/make_screenshots.py          (all windows; takes a few minutes)
      python scripts/make_screenshots.py demo     (one window)

The windows open on top of the screen for a moment and only their own area is captured. They run on
throwaway copies (temp folders, a temp machine setup), so no real photos, settings or corrections are
shown, changed or saved. Re-run it after changing a window, so the pictures never go out of date.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont, ImageGrab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "images" / "windows"
DOC = ROOT / "docs" / "WINDOWS.md"
RED = (220, 30, 30)

# What each control does, by the text on it (or the label next to it). Controls not listed get no box.
DESCRIBE = {
    # demo
    "Open photo…": "Check any photo: the model guesses the part and colour, and you can correct it.",
    "Sort unknown photos…": "Go through the photos in my_photos/unknown/; choosing the part files each one.",
    "Review rest bin…": "Look at what the sorting machine set aside and say what each piece was.",
    "Spot check…": "Check pieces the machine did sort (least sure first): a real-world accuracy score.",
    "New custom piece…": "Add a piece Rebrickable doesn't have (your own number, name, category, tags).",
    "Retrain model": "Make pictures of any new parts and train a few rounds with your corrections.",
    "Search by number or name": "Type to filter the list of parts.",
    "Colour": "The colour to drop it in (Random: one this part really comes in).",
    "▼ Drop": "Drop the chosen piece onto the tray; the camera photographs it and the model guesses.",
    "Random piece": "Pick a random part and drop it.",
    "_parts_list": "The parts the model knows. Double-click one to drop it.",
    # review window
    "_colour_guess": "One of the model's colour guesses: click to use it.",
    "_review_colour": "The colour to save the picture under (type to search).",
    "Show which piece was dropped": "Reveal the right answer (in the demo it's known).",
    "Select": "This is the right part: save the picture with it (and the colour above).",
    "None of these? Part number:": "Type the right part number if none of the guesses is right.",
    "Save": "Save with the typed part number.",
    "Treat as one piece…": "Several parts that belong together (like a hinge): learn them as one piece.",
    "Skip": "Close without saving anything.",
    "bins:Save": "Save the bins; the sorting machine uses them right away.",
    "setup:Save": "Save the machine setup (training pictures and the sorting machine use it).",
    # sorting machine
    "▶ Start": "Start or pause the belt (or press Space).",
    "↺ Reset": "Empty the belt and the bins and start counting again.",
    "Edit bins…": "Change which pieces go into which bin.",
    "Speed": "How fast the simulation runs.",
    "Non-LEGO objects": "How often something that isn't LEGO comes along the belt.",
    "Pieces touching": "How often a piece is dropped onto another one.",
    "Confidence needed": "How sure the model must be; less sure pieces go to the rest bin.",
    "Pieces": "Which pieces ride the belt: the ones the model knows, all LEGO parts, or ones you choose.",
    "Belt": "The belt's look (also set in Model training > Machine setup).",
    "Clear": "Empty the log.",
    # bin editor
    "Add…": "Add a bin below the selected one.",
    "Edit…": "Change the selected bin (or double-click it).",
    "Remove": "Remove the selected bin.",
    "▲ Move up": "Move the bin up: bins are checked from the top.",
    "▼ Move down": "Move the bin down.",
    "Cancel": "Close without saving.",
    "_bins_table": "The bins, checked from the top: a piece goes into the first one it fits.",
    # bin form
    "Bin name": "The bin's name.",
    "Category contains (comma separated)": "Rebrickable categories this bin takes (part of the name is enough).",
    "Part name contains (comma separated)": "Words in the part's name, like slope.",
    "Part numbers (comma separated)": "Exact part numbers (look-alike versions count too).",
    "Your tags (comma separated)": "Tags of your own custom pieces.",
    "Choose…": "Pick colours in a list grouped by main colour.",
    "Flat": "Only plates and tiles, only other pieces, or either.",
    "Printed": "Only printed pieces, only plain ones, or either.",
    "Own confidence needed (%)": "A confidence just for this bin; empty = the sorting machine's slider.",
    "OK": "Keep the changes.",
    # colour picker
    "_colour_tree": "Tick colours; ticking a group ticks all of it. The arrow opens a group.",
    "Untick all": "Clear all ticks.",
    # piece picker
    "Search:": "Filter the list by number or name.",
    "Only pieces the model knows": "Hide parts the model hasn't learned.",
    "Tick all shown": "Tick every piece in the list as it's filtered now.",
    "Untick all shown": "Untick every piece in the list as it's filtered now.",
    "Done": "Use the ticked pieces on the belt.",
    "_piece_tree": "Click a piece to tick it; the arrow opens a part's versions.",
    # cut out pieces
    "Save draft": "Keep the boxes and answers for this photo, to finish later.",
    "◀ Back": "The previous photo (this one's progress is kept).",
    "Next ▶": "The next photo (what you typed on this one is kept).",
    "Save pieces, next photo": "Save one picture per piece in my_photos/<part>/<colour>/, then the next photo.",
    "_part_number": "The piece's part number (the model's guess is filled in). Empty = skip this piece.",
    "_part_colour": "Its colour. Unknown sends it to Check colours.",
    "_part_version": "For numbers with versions (3062a / 3062b): which one, or Unknown version.",
    # check colours
    "◀ Previous piece": "The previous piece.",
    "Next piece ▶": "The next piece.",
    "_jump": "Jump to any piece (✓ = done).",
    "↶ Undo": "Take back the last step, photos moved back too (or Ctrl+Z).",
    "_colour_button": "A colour this piece could be: press every colour you can see in the photos.",
    "Another colour:": "Add a colour that's missing from the buttons.",
    "Add": "Add the typed colour.",
    "Done, continue ▶": "Go on to sorting the photos one colour at a time.",
    "🗑 Delete marked": "Throw away the marked photos (kept in _check/_deleted, so it can be undone).",
    # model training
    "▶ Start training": "Make missing training pictures, then train (Continue training after a pause).",
    "⏸ Pause": "Stop now; Start carries on where it stopped.",
    "Open model folder": "The folder with the model files (and backups of earlier models).",
    "Open data folder": "The folder with the training pictures and downloads.",
    "Pictures per part": "How many training pictures each part gets.",
    "Training rounds": "How many rounds to train (each round saves its progress).",
    "Make missing training pictures first": "Make pictures for new parts before training.",
    "_tabs": "Training: run it. Machine setup: make the pictures look like your machine.",
    "Being made now": "Show the newest training pictures of the current run.",
    "All training pictures": "Page through every picture the next training uses.",
    "Part": "Only one part's pictures, or all.",
    "Shuffle": "Mix the pictures, so you see a bit of everything.",
    "◀": "Previous page (or PageUp).",
    "▶": "Next page (or PageDown).",
    # machine setup
    "_belt_choice": "Your machine's belt: a built-in one or your own photo.",
    "Use a photo of my belt…": "Use a photo of your own belt, taken from straight above.",
    "Width of belt the photo shows (mm)": "How wide a piece of belt your photo shows, so pieces get the right size.",
    "Train on all belts, not only mine (copes better with changes)": "Train on every belt, or only yours.",
    "Camera height": "The camera lens's height above the belt, in mm.",
    "Number of lamps": "How many lamps light the belt.",
    "Lamp height": "The lamps' height above the belt, in mm.",
    "Lamps to the side of the camera": "How far to the side the lamps hang, in mm.",
    "Brightness": "How bright the lamps are.",
    "Light colour (white to warm)": "White daylight lamps or warm yellowish bulbs.",
    "Pictures like my machine": "How much of the training looks like your machine (the rest: tables, floors).",
    "Preview pictures": "Six pictures of a random piece with these settings, before saving.",
    "Built-in values": "Put every setting back to the built-in values.",
    "Make all training pictures again…": "Delete the training pictures so they're made again with the new setup.",
    "Shine like my photos": "Give the plastic the shine measured on your real photos.",
    "Learn from my photos": "Measure the shine on your photos again (about a minute).",
    "Update": "Redraw the 3D preview with the settings as they are now.",
    "Another piece": "Show another piece in the 3D preview.",
}
WINDOWS = {   # name: (title in the guide, a sentence about the window)
    "demo": ("Demo", "Drop a piece in the virtual world and check the model's guesses (Start demo.bat)."),
    "review": ("Check the guess", "Opens after a drop or a photo: the model's colour and part guesses."),
    "sorter": ("Sorting machine", "The virtual conveyor belt (Start sorting machine.bat)."),
    "bins": ("Edit bins", "From the sorting machine: the bins and what goes into each."),
    "bin_form": ("One bin", "Adding or editing a bin: everything a piece must match."),
    "colours": ("Choose colours", "From a bin: colours grouped by main colour."),
    "piece_picker": ("Choose the pieces for the belt", "From the sorting machine's Pieces list."),
    "cut": ("Cut out pieces", "One picture per piece from photos of several pieces (Cut out pieces.bat)."),
    "check": ("Check colours", "Give photos their colour, piece by piece (Check colours.bat)."),
    "training": ("Model training", "Make training pictures and train the model (Model training.bat)."),
    "setup": ("Model training: Machine setup", "Make the training pictures look like your own machine."),
}


# ---------------------------------------------------------------------------- finding the controls
def _text(w):
    try:
        return str(w.cget("text")).strip()
    except tk.TclError:
        return ""


def _label_for(w):
    """The text of the label next to (or just above) an input without a text of its own."""
    master = w.master
    try:
        info = w.grid_info()
    except tk.TclError:
        info = {}
    if info:
        row, col = int(info["row"]), int(info["column"])
        for s in master.grid_slaves(row=row):
            if s is not w and int(s.grid_info()["column"]) < col and _text(s):
                return _text(s)
        for s in master.grid_slaves(row=row - 1):
            if s is not w and int(s.grid_info()["column"]) == col and _text(s):
                return _text(s)
    slaves = master.pack_slaves()
    if w in slaves:
        i = slaves.index(w)
        for s in reversed(slaves[:i]):
            if isinstance(s, (ttk.Label, tk.Label)) or type(s).__name__ == "TextLabel":
                return _text(s)
            if _text(s):
                break
    return ""


INPUTS = (ttk.Combobox, ttk.Entry, ttk.Spinbox, ttk.Scale, tk.Listbox, ttk.Treeview, ttk.Notebook)
BUTTONS = (ttk.Button, tk.Button, ttk.Checkbutton, ttk.Radiobutton)


def controls(window, special=None, name=""):
    """[(widget, key)] for every described control in the window (not in other windows)."""
    special = special or {}
    out = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Toplevel) or not c.winfo_ismapped():
                continue
            key = special.get(c)
            if key is None and isinstance(c, BUTTONS):
                key = _text(c)
                if re.match(r".+ \(\d+%\)$", key):
                    key = "_colour_guess"
                elif isinstance(c, tk.Button) and key and not key.startswith(("✔", "✘")) and "colour" in str(
                        type(window)).lower():
                    key = "_colour_button"
            elif key is None and isinstance(c, INPUTS):
                key = _label_for(c)
            if key and f"{name}:{key}" in DESCRIBE:   # a description just for this window
                key = f"{name}:{key}"
            if key and key in DESCRIBE:
                out.append((c, key))
            walk(c)   # (a notebook's hidden tabs aren't mapped, so they're skipped above)
    walk(window)
    return out


# ---------------------------------------------------------------------------- drawing
def capture(window, name, special=None):
    window.attributes("-topmost", True)
    window.lift()
    window.update()
    time.sleep(0.3)
    window.update()
    x0, y0 = window.winfo_rootx(), window.winfo_rooty()
    img = ImageGrab.grab((x0, y0, x0 + window.winfo_width(), y0 + window.winfo_height()), all_screens=True)
    found = controls(window, special, name)
    keys, boxes = [], []
    def size(w):   # a notebook: only its row of tabs, not the whole page under it
        return (170, 24) if isinstance(w, ttk.Notebook) else (w.winfo_width(), w.winfo_height())

    # numbered in reading order: rows (by the middle of each control), then left to right
    order = sorted(found, key=lambda t: ((t[0].winfo_rooty() + size(t[0])[1] // 2) // 20, t[0].winfo_rootx()))
    for w, key in order:
        if key not in keys:
            keys.append(key)
        x, y = w.winfo_rootx() - x0, w.winfo_rooty() - y0
        ww, hh = size(w)
        boxes.append((keys.index(key) + 1, (x - 2, y - 2, x + ww + 1, y + hh + 1)))
    pad = 14   # room for the numbers at the window's edges
    canvas = Image.new("RGB", (img.width + 2 * pad, img.height + 2 * pad), "white")
    canvas.paste(img, (pad, pad))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("segoeuib.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    for n, (a, b, c, e) in boxes:
        d.rectangle((a + pad, b + pad, c + pad, e + pad), outline=RED, width=2)
    for n, (a, b, c, e) in boxes:   # numbers on top of all boxes
        cx, cy = a + pad, b + pad
        r = 9
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RED)
        d.text((cx, cy), str(n), fill="white", font=font, anchor="mm")
    OUT.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT / f"{name}.png", optimize=True)
    (OUT / f"{name}.json").write_text(json.dumps(keys))
    print(f"{name}: {len(keys)} controls")


# ---------------------------------------------------------------------------- each window
def _throwaway_data():
    """Point everything at temp folders: no real photos, settings or corrections are used or changed."""
    from bricksort import config, machine_setup
    tmp = Path(tempfile.mkdtemp())
    config.MY_PHOTOS, config.CORRECTIONS = tmp / "my_photos", tmp / "corrections"
    config.REST_LOG, config.SORTED_LOG = tmp / "rest", tmp / "sorted"
    machine_setup.FILE = tmp / "machine_setup.json"
    return tmp


def _sample_photo(path, size=1200):
    """A photo of three pieces lying apart (the rendered 'several pieces' picture)."""
    Image.open(ROOT / "bricksort" / "assets" / "multiple.png").resize((size, size)).save(path)


def run(name):
    tmp = _throwaway_data()
    if name in ("demo", "review"):
        from bricksort import demo
        app = demo.Demo()
        app.geometry("1100x700+40+40")
        if name == "demo":
            app.after(1500, lambda: (app.log.configure(state="normal"), app.log.delete("1.0", "end"),
                                     app.log.configure(state="disabled"),
                                     capture(app, "demo", {app.listbox: "_parts_list"}), app.destroy()))
        else:
            tries = {"n": 0, "right": 0}

            def drop():
                # a drop the model gets right makes the clearer picture: try a few
                tries["n"] += 1
                tries["right"] = app.tally["first"]
                app.search.set(["3039", "3001", "3062b", "3003"][tries["n"] % 4])
                app.update()
                app.listbox.selection_clear(0, "end")
                app.listbox.selection_set(0)
                app._show_preview()
                app.color_choice.set("Red")
                app.drop()
                wait()

            def wait():
                r = next((w for w in app.winfo_children() if isinstance(w, demo.ReviewWindow)), None)
                if r is None:
                    app.after(300, wait)
                elif app.tally["first"] == tries["right"] and tries["n"] < 8:
                    r.destroy()
                    app.after(300, drop)
                else:
                    app.after(800, lambda: (capture(r, "review", {r.color: "_review_colour"}), app.destroy()))
            app.after(1500, drop)
        app.mainloop()
    elif name in ("sorter", "bins", "bin_form", "colours", "piece_picker"):
        from bricksort import conveyor_demo
        from bricksort.sorter import bin_editor, piece_picker
        piece_picker.CHOICE_FILE = tmp / "belt_pieces.json"
        app = conveyor_demo.ConveyorDemo()
        app.geometry("1280x820+30+30")

        def find(cls):
            return next((w for w in app.winfo_children() if isinstance(w, cls)), None)

        if name == "sorter":
            app.after(800, app.toggle)
            app.after(15000, lambda: (capture(app, "sorter", {app.bin_table: None}), app.destroy()))
        elif name == "piece_picker":
            def shoot():
                p = find(piece_picker.PiecePicker)
                capture(p, "piece_picker", {p.tree: "_piece_tree"})
                p.destroy()
                app.after(200, app.destroy)
            app.after(1500, lambda: (app.after(1500, shoot), app._pick_pieces()))
        else:
            def editor_open():
                ed = find(bin_editor.BinEditor)
                if name == "bins":
                    capture(ed, "bins", {ed.table: "_bins_table"})
                    ed.destroy()
                    app.after(200, app.destroy)
                    return
                ed.table.selection_set("2")   # "Flat black": has colours
                app.after(1200, form_open)
                ed.edit()

            def form_open():
                ed = find(bin_editor.BinEditor)
                form = next(w for w in ed.winfo_children() if isinstance(w, bin_editor.BinForm))
                if name == "bin_form":
                    capture(form, "bin_form")
                    form.destroy()
                    ed.destroy()
                    app.after(200, app.destroy)
                    return
                app.after(1500, picker_open)
                form._choose_colours()

            def picker_open():
                ed = find(bin_editor.BinEditor)
                form = next(w for w in ed.winfo_children() if isinstance(w, bin_editor.BinForm))
                pick = next(w for w in form.winfo_children() if isinstance(w, bin_editor.ColourPicker))
                for item, names in pick.members.items():   # open the group with the ticked colour
                    if any(n in pick.ticked for n in names) and len(names) > 1:
                        pick.tree.item(item, open=True)
                capture(pick, "colours", {pick.tree: "_colour_tree"})
                pick.destroy()
                form.destroy()
                ed.destroy()
                app.after(200, app.destroy)
            app.after(1500, lambda: (app.after(1200, editor_open), app.edit_bins()))
        app.mainloop()
    elif name == "cut":
        from bricksort import colour_review, config, cut
        cut.TO_CUT = config.MY_PHOTOS / "_to_cut"
        cut.TO_CUT.mkdir(parents=True)
        colour_review.SOURCE = tmp / "check"
        _sample_photo(cut.TO_CUT / "photo.jpg")
        app = cut.Cutter()
        app.geometry("1250x720+30+30")

        def shoot():
            special = {}
            for box, part, col in app.fields:
                special[part.number] = "_part_number"
                special[part.version] = "_part_version"
                special[col] = "_part_colour"
            app.fields[1][1].set("3062")   # show the version dropdown on one piece
            app.update()
            capture(app, "cut", special)
            app.destroy()
        app.after(2500, shoot)
        app.mainloop()
    elif name == "check":
        from bricksort import colour_review
        colour_review.SOURCE = tmp / "check"
        colour_review.STATE = colour_review.SOURCE / "_review_progress.json"
        colour_review.DELETED = tmp / "deleted"
        from bricksort import config
        renders = sorted((config.RENDERS / "3001").glob("*.png"))[:24]   # made by code: fine to publish
        src = Image.open(ROOT / "bricksort" / "assets" / "multiple.png")
        for j, sub in enumerate(("Red", "_check - Red or Dark Red")):
            d = colour_review.SOURCE / "3001" / sub
            d.mkdir(parents=True)
            for k in range(12):
                pic = Image.open(renders[j * 12 + k]) if len(renders) >= 24 else                     src.rotate(30 * k, fillcolor=(60, 60, 62))
                pic.save(d / f"photo_{sub[:3]}_{k}.png")
        app = colour_review.ColourReview()
        app.wm_geometry("1150x800+30+30")
        app.after(2000, lambda: (capture(app, "check", {app.jump: "_jump"}), app.destroy()))
        app.mainloop()
    elif name in ("training", "setup"):
        from bricksort import training_app
        app = training_app.TrainingApp()
        app.geometry("1500x820+20+20")
        tabs = app.winfo_children()[1].winfo_children()[0]
        special = {tabs: "_tabs", getattr(app, "belt_box", None): "_belt_choice"}

        def shoot():
            if name == "setup":
                tabs.select(1)
                app.update()
                app._update_look()
            app.after(1500, lambda: (capture(app, name, special), app.destroy()))
        app.after(2000, shoot)
        app.mainloop()
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------- the guide
def write_doc():
    lines = ["# The windows", "",
             "Every window of BrickSort, with a number on each button and control. Made by",
             "`scripts/make_screenshots.py`; run it again after changing a window.", ""]
    for name, (title, about) in WINDOWS.items():
        f = OUT / f"{name}.json"
        if not f.exists():
            continue
        keys = json.loads(f.read_text())
        lines += [f"## {title}", "", about, "", f"![{title}](images/windows/{name}.png)", ""]
        for n, key in enumerate(keys, 1):
            plain = key.split(":", 1)[1] if key.split(":", 1)[0] in WINDOWS else key   # "bins:Save" -> "Save"
            label = plain.rstrip(":") if not plain.startswith("_") else ""
            lines.append(f"{n}. " + (f"**{label}**: " if label else "") + DESCRIBE[key])
        lines.append("")
    DOC.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", DOC)


if __name__ == "__main__":
    names = sys.argv[1:] or list(WINDOWS)
    if len(names) == 1 and names[0] in WINDOWS and os.environ.get("BRICKSORT_SHOT_CHILD"):
        run(names[0])
    else:
        for n in names:   # each window in its own program run, so their windows don't mix
            subprocess.run([sys.executable, __file__, n], env={**os.environ, "BRICKSORT_SHOT_CHILD": "1"})
        write_doc()
