"""Window for choosing which pieces may appear on the virtual belt.

Pieces whose numbers share a base (3062a, 3062b, ...) are listed once under that base number,
with an arrow to open the group and pick only some of its versions. Click a row to tick it.
The choice is saved in belt_pieces.json, so it's still there next time.
"""
import json
import re
import tkinter as tk
from tkinter import ttk

from .. import config
from ..ui import Label

CHOICE_FILE = config.PROJECT_DIR / "belt_pieces.json"
ON, OFF, SOME = "☑", "☐", "◩"


def load_choice():
    try:
        return set(json.loads(CHOICE_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _base(pid):
    m = re.match(r"^(\d+)", pid)
    return m.group(1) if m else pid


class PiecePicker(tk.Toplevel):
    """pieces: [{"id", "name", ...}]; known: ids the model is trained on. After closing,
    .chosen is the set of ticked ids, or None if the window was closed without 'Done'."""

    def __init__(self, master, pieces, known):
        super().__init__(master)
        self.title("Choose the pieces for the belt")
        self.geometry("620x700")
        self.known, self.chosen = known, None
        self.ticked = load_choice() & {p["id"] for p in pieces}
        self.groups = {}
        # old numbers Rebrickable has moved to another number are just clutter (unless the model knows them)
        pieces = [p for p in pieces if not p.get("name", "").startswith("~Moved") or p["id"] in known]
        for p in sorted(pieces, key=lambda p: (len(_base(p["id"])), _base(p["id"]), p["id"])):
            self.groups.setdefault(_base(p["id"]), []).append(p)

        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        Label(top, text="Search:").pack(side="left")
        self.search = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.search, width=30)
        entry.pack(side="left", padx=4)
        self.search.trace_add("write", lambda *a: self._fill())
        self.only_known = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Only pieces the model knows", variable=self.only_known,
                        command=self._fill).pack(side="left", padx=8)
        Label(self, text="Click a piece to tick it. The + in front opens a piece's versions, to pick only some of them.  "
                         "✓ = the model knows it.", foreground="#666", wraplength=600).pack(anchor="w", padx=6)

        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True, padx=6, pady=4)
        self.tree = ttk.Treeview(holder, columns=("name",), show="tree headings", selectmode="none")
        self.tree.heading("#0", text="Piece")
        self.tree.heading("name", text="Name")
        self.tree.column("#0", width=170, stretch=False)
        self.tree.column("name", width=400)
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._click)

        bottom = ttk.Frame(self, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Tick all shown", command=lambda: self._all(True)).pack(side="left")
        ttk.Button(bottom, text="Untick all shown", command=lambda: self._all(False)).pack(side="left", padx=4)
        self.count = Label(bottom, text="")
        self.count.pack(side="left", padx=8)
        ttk.Button(bottom, text="Done", command=self._done).pack(side="right")
        self._fill()
        entry.focus_set()
        self.transient(master)
        self.grab_set()
        self.wait_window()

    # ------------------------------------------------------------ list
    def _shown_groups(self):
        q = self.search.get().strip().lower()
        for base, members in self.groups.items():
            if self.only_known.get():
                members = [p for p in members if p["id"] in self.known]
            if q:
                members = [p for p in members if q in p["id"].lower() or q in p.get("name", "").lower()] \
                    or (members if q in base.lower() else [])
            if members:
                yield base, members

    def _mark(self, ids):
        n = sum(i in self.ticked for i in ids)
        return ON if n == len(ids) else OFF if n == 0 else SOME

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = {}   # tree item -> list of piece ids it stands for
        for base, members in self._shown_groups():
            ids = [p["id"] for p in members]
            if len(members) == 1:
                p = members[0]
                item = self.tree.insert("", "end", text=self._row_label(p["id"], ids), values=(self._piece_name(p),))
                self.rows[item] = ids
                continue
            main = next((p for p in members if p["id"] == base), members[0])
            item = self.tree.insert("", "end", text=self._row_label(base, ids),
                                    values=(f"{self._piece_name(main)}  ({len(members)} versions)",))
            self.rows[item] = ids
            for p in members:
                child = self.tree.insert(item, "end", text=self._row_label(p["id"], [p["id"]]), values=(self._piece_name(p),))
                self.rows[child] = [p["id"]]
        self._count()

    def _piece_name(self, p):
        return ("✓ " if p["id"] in self.known else "") + p.get("name", "")

    def _row_label(self, pid, ids):
        return f"{self._mark(ids)} {pid}"

    def _refresh_marks(self):
        for item, ids in self.rows.items():
            pid = self.tree.item(item, "text").split(" ", 1)[1]
            self.tree.item(item, text=self._row_label(pid, ids))
        self._count()

    def _count(self):
        self.count.configure(text=f"{len(self.ticked)} pieces ticked")

    # ------------------------------------------------------------ clicks
    def _click(self, event):
        if self.tree.identify_element(event.x, event.y) in ("Treeitem.indicator", "indicator"):
            return  # the ▸ arrow: let the tree open/close the group
        item = self.tree.identify_row(event.y)
        if not item:
            return
        ids = self.rows[item]
        if all(i in self.ticked for i in ids):
            self.ticked -= set(ids)
        else:
            self.ticked |= set(ids)
        self._refresh_marks()
        return "break"

    def _all(self, on):
        ids = {i for _, members in self._shown_groups() for i in (p["id"] for p in members)}
        self.ticked = self.ticked | ids if on else self.ticked - ids
        self._refresh_marks()

    def _done(self):
        CHOICE_FILE.write_text(json.dumps(sorted(self.ticked)), encoding="utf-8")
        self.chosen = set(self.ticked)
        self.destroy()
