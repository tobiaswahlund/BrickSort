"""Small shared UI helpers.

Label(...) works like ttk.Label, but any text it shows can be selected with the
mouse and copied (Ctrl+C, or right-click > Copy). Labels that only show a
picture stay ordinary labels.
"""
import math
import tkinter as tk
from tkinter import font as tkfont, ttk


def make_copyable(text_widget):
    """For read-only log boxes: clicking gives focus (so Ctrl+C works) and right-click offers Copy."""
    text_widget.bind("<Button-1>", lambda e: text_widget.focus_set(), add="+")

    def menu(e):
        m = tk.Menu(text_widget, tearoff=0)
        m.add_command(label="Copy", command=lambda: text_widget.event_generate("<<Copy>>"))
        m.add_command(label="Copy all", command=lambda: (text_widget.clipboard_clear(),
                                                        text_widget.clipboard_append(text_widget.get("1.0", "end-1c"))))
        m.tk_popup(e.x_root, e.y_root)
    text_widget.bind("<Button-3>", menu)


def Label(master, **kw):
    if "image" in kw or "textvariable" in kw or "text" not in kw:
        return ttk.Label(master, **kw)
    return TextLabel(master, **kw)


class TextLabel(tk.Text):
    """Looks like a label; the text can be selected and copied but not edited."""

    def __init__(self, master, text="", wraplength=None, justify="left", font=None, foreground=None,
                 width=None, anchor=None, **_):
        bg = ttk.Style(master).lookup("TFrame", "background") or "SystemButtonFace"
        self._font = tkfont.Font(font=font) if font else tkfont.nametofont("TkDefaultFont")
        super().__init__(master, font=self._font, bg=bg, relief="flat", borderwidth=0, highlightthickness=0,
                         padx=0, pady=0, cursor="xterm", takefocus=0, wrap="word" if wraplength else "none",
                         foreground=foreground or "black", insertwidth=0, exportselection=True)
        self._wrap, self._fixed_width = wraplength, width
        self.tag_configure("all", justify=justify)
        self.bind("<Button-1>", lambda e: self.focus_set(), add="+")
        self.bind("<Control-a>", self._select_all)
        self.bind("<Control-c>", lambda e: self.event_generate("<<Copy>>"))
        self.bind("<Button-3>", self._menu)
        self._set_text(text)

    def _set_text(self, text):
        text = str(text)
        self.configure_raw(state="normal")
        self.delete("1.0", "end")
        self.insert("1.0", text, "all")
        self.configure_raw(state="disabled")
        lines = text.split("\n") or [""]
        char = max(self._font.measure("0"), 1)
        if self._wrap:
            width_px = self._wrap
            height = sum(max(1, math.ceil(self._font.measure(l) / width_px)) for l in lines)
        else:
            width_px = max((self._font.measure(l) for l in lines), default=0) + char
            height = len(lines)
        width = self._fixed_width or max(1, math.ceil(width_px / char))
        self.configure_raw(width=width, height=height)

    # tk.Text.configure is used for our own settings; text=/foreground= behave like a label
    def configure_raw(self, **kw):
        return tk.Text.configure(self, **kw)

    def configure(self, cnf=None, **kw):
        if "text" in kw:
            self._set_text(kw.pop("text"))
        if "wraplength" in kw:
            self._wrap = kw.pop("wraplength")
        return tk.Text.configure(self, cnf, **kw) if (cnf or kw) else None

    config = configure

    def cget(self, key):
        if key == "text":
            return self.get("1.0", "end-1c")
        return tk.Text.cget(self, key)

    def _select_all(self, _=None):
        self.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _menu(self, e):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Copy", command=lambda: self.event_generate("<<Copy>>"))
        m.add_command(label="Copy all", command=self._copy_all)
        m.tk_popup(e.x_root, e.y_root)

    def _copy_all(self):
        self.clipboard_clear()
        self.clipboard_append(self.cget("text"))
