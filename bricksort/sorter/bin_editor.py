"""A window to add, remove, reorder and edit the sorting bins (saved in bins.json).

How sure the model must be comes from the sorting machine's slider. A bin can ask for its own
level instead (e.g. 99% for a bin of valuable pieces): the "Confidence" column.
"""
import json
import tkinter as tk
from tkinter import messagebox, ttk

from .. import catalog, colours
from ..cut import autocomplete, wide_dropdown
from ..ui import MUTED, Label
from . import rules as rules_mod

LIST_FIELDS = (("category", "Category contains (comma separated)"),
               ("name", "Part name contains (comma separated)"),
               ("part", "Part numbers (comma separated)"),
               ("tag", "Your tags (comma separated)"))
NUMBER_FIELDS = (("min_length", "Longest side at least (studs)"), ("max_length", "Longest side at most (studs)"),
                 ("min_width", "Shortest side at least (studs)"), ("max_width", "Shortest side at most (studs)"),
                 ("min_height", "Height at least (plates)"), ("max_height", "Height at most (plates)"))
ON, OFF, SOME = "☑", "☐", "◩"
SLIDER = "slider"


describe = rules_mod.describe


def _confidence_text(b):
    return f"{b['confidence']:.0%}" if "confidence" in b else SLIDER


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
        holder = ttk.Frame(self)
        holder.grid(row=1, column=0, sticky="nsew", pady=6)
        self.table = ttk.Treeview(holder, columns=("rule", "confidence"), height=12, selectmode="browse")
        self.table.heading("#0", text="Bin", anchor="w")
        self.table.heading("rule", text="Gets", anchor="w")
        self.table.heading("confidence", text="Confidence", anchor="e")
        self.table.column("#0", width=170, stretch=False)
        self.table.column("rule", width=380)
        self.table.column("confidence", width=80, anchor="e", stretch=False)
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=sb.set)
        self.table.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.table.bind("<Double-Button-1>", lambda e: self.edit())
        self.table.bind("<Delete>", lambda e: self.remove())
        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=1, sticky="n", padx=(8, 0), pady=6)
        for text, cmd in (("Add…", self.add), ("Edit…", self.edit), ("Remove", self.remove),
                          ("▲ Move up", lambda: self.move(-1)), ("▼ Move down", lambda: self.move(+1))):
            ttk.Button(buttons, text=text, command=cmd, width=14).pack(pady=2)
        ttk.Label(self, text="Confidence: 'slider' = the sorting machine's Confidence needed slider.",
                  foreground=MUTED).grid(row=2, column=0, columnspan=2, sticky="w")

        bottom = ttk.Frame(self)
        bottom.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Save", command=self.save).pack(side="right", padx=6)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.bind("<Escape>", lambda e: self.destroy())
        self._fill()
        self.grab_set()
        self.wait_window()

    def _fill(self, select=None):
        self.table.delete(*self.table.get_children())
        for i, b in enumerate(self.bins):
            self.table.insert("", "end", iid=str(i), text=f"{i + 1}. {b['name']}",
                              values=(describe(b["when"]), _confidence_text(b)))
        if select is not None and self.bins:
            self.table.selection_set(str(select))
            self.table.see(str(select))

    def _selected(self):
        sel = self.table.selection()
        return int(sel[0]) if sel else None

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
        names = [b["name"] for b in self.bins]
        if len(set(names)) != len(names):
            messagebox.showwarning("Same name twice", "Two bins have the same name; please rename one.", parent=self)
            return
        special = {self.rules["not_lego_bin"], self.rules["rest_bin"]}
        if special & set(names):
            messagebox.showwarning("Name already used", f"'{self.rules['not_lego_bin']}' and "
                                   f"'{self.rules['rest_bin']}' are the machine's own bins; please pick "
                                   "another name.", parent=self)
            return
        self.rules["bins"] = self.bins
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
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", pady=2, padx=(0, 8))
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

        # colours: chosen in a list grouped by main colour (see ColourPicker)
        ttk.Label(self, text="Colours").grid(row=row, column=0, sticky="w", pady=2)
        self.colours = list(when.get("color", []))
        line = ttk.Frame(self)
        line.grid(row=row, column=1, sticky="we", pady=2)
        self.colour_text = ttk.Label(line, text="", width=40, wraplength=280, foreground=MUTED)
        self.colour_text.pack(side="left")
        ttk.Button(line, text="Choose…", command=self._choose_colours).pack(side="right")
        self._show_colours()
        row += 1

        flat = {True: "Yes (plates and tiles)", False: "No (bricks and others)"}.get(when.get("flat"), "Doesn't matter")
        self.vars["flat"] = add_row("Flat", flat, ["Doesn't matter", "Yes (plates and tiles)", "No (bricks and others)"])
        printed = {True: "Yes (has a print)", False: "No (plain)"}.get(when.get("printed"), "Doesn't matter")
        self.vars["printed"] = add_row("Printed", printed, ["Doesn't matter", "Yes (has a print)", "No (plain)"])
        for key, label in NUMBER_FIELDS:
            self.vars[key] = add_row(label, str(when.get(key, "")))
        conf = str(round(b["confidence"] * 100)) if "confidence" in b else ""
        self.vars["_confidence"] = add_row("Own confidence needed (%)", conf)
        ttk.Label(self, text="Leave empty to use the sorting machine's slider.", foreground=MUTED
                  ).grid(row=row, column=1, sticky="w")
        row += 1
        buttons = ttk.Frame(self)
        buttons.grid(row=row, column=1, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window()

    def _show_colours(self):
        self.colour_text.configure(text=", ".join(self.colours) if self.colours else "any colour")

    def _choose_colours(self):
        picked = ColourPicker(self, self.colours).result
        if picked is not None:
            self.colours = picked
            self._show_colours()

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
        if self.colours:
            when["color"] = list(self.colours)
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
                    when[key] = float(v[key].replace(",", "."))
                except ValueError:
                    messagebox.showwarning("Number", f"'{label}' must be a number.", parent=self)
                    return
        self.result = {"name": v["_bin_name"], "when": when}
        if v["_confidence"]:
            try:
                c = float(v["_confidence"].replace("%", "").replace(",", ".")) / 100
                if not 0 <= c <= 1:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Number", "Own confidence: a number from 0 to 100, or empty.", parent=self)
                return
            self.result["confidence"] = c
        self.destroy()


class ColourPicker(tk.Toplevel):
    """Tick colours in a list grouped by main colour (Red, Blue, ...), most of them split again into
    light / medium / dark. Ticking a group ticks every colour in it. .result: the ticked names, or None
    if closed with Cancel."""

    def __init__(self, master, chosen):
        super().__init__(master)
        self.title("Choose colours")
        self.geometry("420x600")
        self.transient(master)
        self.result = None
        table = catalog.colors(include_trans=True)
        self.rgb = {n: c for n, c in table.values()}
        self.ticked = {c for c in chosen if c in self.rgb}
        groups = colours.grouped(table, catalog.color_choices())

        holder = ttk.Frame(self, padding=6)
        holder.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(holder, show="tree", selectmode="none")
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._click)

        self.swatches = {}   # small colour squares (Tk forgets images nobody holds on to)
        self.members = {}    # tree item -> the colour names it stands for
        for fam, subs in groups.items():
            fam_names = [n for names in subs.values() for n in names]
            if len(fam_names) == 1:   # e.g. Black: just the colour itself, nothing to open
                self.members[self.tree.insert("", "end", text=fam_names[0], image=self._swatch(fam_names[0]))] \
                    = fam_names
                continue
            typical = fam if fam in fam_names else fam_names[0]   # the plain "Green" for the Green group
            fam_item = self.tree.insert("", "end", text=fam, image=self._swatch(typical))
            self.members[fam_item] = fam_names
            for sub, names in subs.items():
                parent = fam_item
                if sub:
                    parent = self.tree.insert(fam_item, "end", text=f"{sub} {fam.lower()}"
                                              if fam != "Transparent" else sub, image=self._swatch(names[0]))
                    self.members[parent] = names
                for n in names:
                    self.members[self.tree.insert(parent, "end", text=n, image=self._swatch(n))] = [n]
            if any(n in self.ticked for n in fam_names):
                self.tree.item(fam_item, open=True)
        self.labels = {item: self.tree.item(item, "text") for item in self.members}
        self._refresh()

        bottom = ttk.Frame(self, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Untick all", command=self._clear).pack(side="left")
        self.count = ttk.Label(bottom, text="")
        self.count.pack(side="left", padx=8)
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="OK", command=self._ok).pack(side="right", padx=6)
        self._refresh()
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window()

    def _swatch(self, name):
        if name not in self.swatches:
            img = tk.PhotoImage(width=14, height=14)
            r, g, b = self.rgb.get(name, (128, 128, 128))
            img.put("#555555", to=(0, 0, 14, 14))            # thin dark edge, so white shows up too
            img.put("#%02x%02x%02x" % (r, g, b), to=(1, 1, 13, 13))
            self.swatches[name] = img
        return self.swatches[name]

    def _refresh(self):
        for item, names in self.members.items():
            n = sum(x in self.ticked for x in names)
            mark = ON if n == len(names) else OFF if n == 0 else SOME
            self.tree.item(item, text=f" {mark}  {self.labels[item]}")
        if hasattr(self, "count"):
            self.count.configure(text=f"{len(self.ticked)} ticked")

    def _click(self, e):
        if self.tree.identify_element(e.x, e.y) in ("Treeitem.indicator", "indicator"):
            return   # the arrow: let the tree open or close the group
        item = self.tree.identify_row(e.y)
        if not item:
            return
        names = self.members[item]
        if all(n in self.ticked for n in names):
            self.ticked -= set(names)
        else:
            self.ticked |= set(names)
        self._refresh()
        return "break"

    def _clear(self):
        self.ticked.clear()
        self._refresh()

    def _ok(self):
        # list order, each colour once (a group with a single colour holds the same name as its row)
        order = dict.fromkeys(n for names in self.members.values() if len(names) == 1 for n in names)
        self.result = [n for n in order if n in self.ticked]
        self.destroy()
