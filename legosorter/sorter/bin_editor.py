"""A window to add, remove, reorder and edit the sorting bins (saved in bins.json)."""
import json
import tkinter as tk
from tkinter import messagebox, ttk

from .. import catalog
from ..cut import autocomplete, wide_dropdown
from ..ui import Label
from . import rules as rules_mod

LIST_FIELDS = (("category", "Category contains (comma separated)"),
               ("name", "Part name contains (comma separated)"),
               ("color", "Colours (comma separated)"),
               ("part", "Part numbers (comma separated)"),
               ("tag", "Your tags (comma separated)"))
NUMBER_FIELDS = (("min_length", "Longest side at least (studs)"), ("max_length", "Longest side at most (studs)"),
                 ("min_width", "Shortest side at least (studs)"), ("max_width", "Shortest side at most (studs)"),
                 ("min_height", "Height at least (plates)"), ("max_height", "Height at most (plates)"))


def describe(when):
    if not when:
        return "any Lego piece"
    return ", ".join(f"{k}={', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in when.items())


class BinEditor(tk.Toplevel):
    """Bins are checked top to bottom; a piece goes into the first bin it matches."""

    def __init__(self, master, parts):
        super().__init__(master)
        self.title("Edit bins")
        self.configure(padx=12, pady=12)
        self.transient(master)
        self.parts = parts
        self.saved = False
        self.rules = rules_mod.load()
        self.bins = [dict(b) for b in self.rules["bins"]]

        Label(self, text="Bins are checked from the top: a piece goes into the first bin it fits.\n"
                         f"'{self.rules['not_lego_bin']}' and '{self.rules['rest_bin']}' are always last.",
              justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
        self.listbox = tk.Listbox(self, width=70, height=12, exportselection=False)
        self.listbox.grid(row=1, column=0, sticky="nsew", pady=6)
        self.listbox.bind("<Double-Button-1>", lambda e: self.edit())
        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=1, sticky="n", padx=(8, 0), pady=6)
        for text, cmd in (("Add bin…", self.add), ("Edit…", self.edit), ("Remove", self.remove),
                          ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(+1))):
            ttk.Button(buttons, text=text, command=cmd, width=14).pack(pady=2)

        conf = ttk.Frame(self)
        conf.grid(row=2, column=0, columnspan=2, sticky="w")
        Label(conf, text="How sure the model must be (%), or the piece goes to the rest bin:").pack(side="left")
        self.confidence = tk.StringVar(value=str(round(self.rules["confidence_needed"] * 100)))
        ttk.Entry(conf, textvariable=self.confidence, width=5).pack(side="left", padx=4)

        bottom = ttk.Frame(self)
        bottom.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Save bins", command=self.save).pack(side="right", padx=6)
        self._fill()
        self.grab_set()
        self.wait_window()

    def _fill(self, select=None):
        self.listbox.delete(0, "end")
        for i, b in enumerate(self.bins, 1):
            self.listbox.insert("end", f"{i}. {b['name']}  —  {describe(b['when'])}")
        if select is not None and self.bins:
            self.listbox.selection_set(select)

    def _selected(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def add(self):
        b = BinForm(self, {"name": "", "when": {}}, self.parts).result
        if b:
            i = self._selected()
            i = len(self.bins) if i is None else i + 1
            self.bins.insert(i, b)
            self._fill(i)

    def edit(self):
        i = self._selected()
        if i is None:
            return
        b = BinForm(self, self.bins[i], self.parts).result
        if b:
            self.bins[i] = b
            self._fill(i)

    def remove(self):
        i = self._selected()
        if i is not None and messagebox.askyesno("Remove bin", f"Remove the bin '{self.bins[i]['name']}'?", parent=self):
            del self.bins[i]
            self._fill(min(i, len(self.bins) - 1) if self.bins else None)

    def move(self, step):
        i = self._selected()
        if i is None or not 0 <= i + step < len(self.bins):
            return
        self.bins[i], self.bins[i + step] = self.bins[i + step], self.bins[i]
        self._fill(i + step)

    def save(self):
        try:
            conf = float(self.confidence.get()) / 100
            assert 0 < conf <= 1
        except Exception:
            messagebox.showwarning("Check the number", "How sure the model must be: a number from 1 to 100.", parent=self)
            return
        names = [b["name"] for b in self.bins]
        if len(set(names)) != len(names):
            messagebox.showwarning("Same name twice", "Two bins have the same name; please rename one.", parent=self)
            return
        self.rules["bins"] = self.bins
        self.rules["confidence_needed"] = conf
        rules_mod.RULES_FILE.write_text(json.dumps(self.rules, indent=2), encoding="utf-8")
        self.saved = True
        self.destroy()


class BinForm(tk.Toplevel):
    """What goes into one bin. Empty fields don't matter; filled ones must all match."""

    def __init__(self, master, b, parts):
        super().__init__(master)
        self.title("Bin")
        self.configure(padx=12, pady=12)
        self.transient(master)
        self.result = None
        when = b.get("when", {})
        self.vars = {}
        row = 0

        def add_row(label, value, options=None):
            nonlocal row
            Label(self, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=value)
            if options:
                w = ttk.Combobox(self, textvariable=var, values=options, width=46)
                wide_dropdown(w)
                autocomplete(w, options)
            else:
                w = ttk.Entry(self, textvariable=var, width=49)
            w.grid(row=row, column=1, sticky="w", pady=2)
            row += 1
            return var

        self.vars["_bin_name"] = add_row("Bin name", b.get("name", ""))
        categories = sorted({p.get("category", "") for p in parts + catalog.load_category_parts()} - {""})
        for key, label in LIST_FIELDS:
            v = when.get(key, [])
            v = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
            self.vars[key] = add_row(label, v, categories if key == "category" else None)
        Label(self, text="(Colour names as in the colour lists, e.g. Black, Light Bluish Gray, Trans-Clear)",
              foreground="#666").grid(row=row, column=1, sticky="w")
        row += 1
        flat = {True: "Yes (plates and tiles)", False: "No (bricks and others)"}.get(when.get("flat"), "Doesn't matter")
        self.vars["flat"] = add_row("Flat", flat, ["Doesn't matter", "Yes (plates and tiles)", "No (bricks and others)"])
        printed = {True: "Yes (has a print)", False: "No (plain)"}.get(when.get("printed"), "Doesn't matter")
        self.vars["printed"] = add_row("Printed", printed, ["Doesn't matter", "Yes (has a print)", "No (plain)"])
        for key, label in NUMBER_FIELDS:
            self.vars[key] = add_row(label, str(when.get(key, "")))
        ttk.Button(self, text="OK", command=self._ok).grid(row=row, column=1, sticky="e", pady=(10, 0))
        self.grab_set()
        self.wait_window()

    def _ok(self):
        v = {k: var.get().strip() for k, var in self.vars.items()}
        if not v["_bin_name"]:
            messagebox.showwarning("Name", "Please give the bin a name.", parent=self)
            return
        when = {}
        for key, _ in LIST_FIELDS:
            items = [x.strip() for x in v[key].split(",") if x.strip()]
            if items:
                when[key] = items
        if v["flat"].startswith("Yes"):
            when["flat"] = True
        elif v["flat"].startswith("No"):
            when["flat"] = False
        if v["printed"].startswith("Yes"):
            when["printed"] = True
        elif v["printed"].startswith("No"):
            when["printed"] = False
        for key, label in NUMBER_FIELDS:
            if v[key]:
                try:
                    when[key] = float(v[key])
                except ValueError:
                    messagebox.showwarning("Number", f"'{label}' must be a number.", parent=self)
                    return
        self.result = {"name": v["_bin_name"], "when": when}
        self.destroy()
