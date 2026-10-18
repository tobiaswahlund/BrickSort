"""Small shared UI helpers.

Label(...) works like ttk.Label, but any text it shows can be selected with the
mouse and copied (Ctrl+C, or right-click > Copy). Labels that only show a
picture stay ordinary labels.
"""
import math
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageTk

HEADING = ("Segoe UI", 10, "bold")
MUTED = "#666"
ASSETS = Path(__file__).resolve().parent / "assets"


# Opened from the BrickSort menu: this program's window is shown inside the menu's window
# (BRICKSORT_INSIDE holds the id of the frame to show it in). Taken out of the environment straight
# away, so a program this one opens gets a window of its own.
_INSIDE = os.environ.pop("BRICKSORT_INSIDE", None)
if _INSIDE:
    _tk_init = tk.Tk.__init__

    def _init_inside(self, *args, **kw):
        global _INSIDE
        if _INSIDE:
            kw.setdefault("use", _INSIDE)
            _INSIDE = None   # only the first window goes inside the menu
        _tk_init(self, *args, **kw)
    tk.Tk.__init__ = _init_inside


def _listen_to_menu(root):
    """Inside the menu: its "Menu" button sends "close" here, and this program closes the way its
    own close button would (so it can save, or ask first)."""
    def close():
        try:
            handler = root.protocol("WM_DELETE_WINDOW")
            root.tk.call(handler) if handler else root.destroy()
        except tk.TclError:
            pass

    def listen():
        for line in sys.stdin:
            if line.strip() == "close":
                root.after(0, close)
    threading.Thread(target=listen, daemon=True).start()


def use_logo(root):
    """BrickSort's logo as the window and taskbar icon of this program (instead of Tk's feather).
    Opened from the BrickSort menu, it also listens for the menu's "back to the menu"."""
    if isinstance(root, tk.Tk) and root.cget("use"):
        _listen_to_menu(root)
    try:
        if sys.platform == "win32":
            import ctypes  # its own taskbar button, not grouped under Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BrickSort")
            root.iconbitmap(default=str(ASSETS / "logo.ico"))   # every window of this program
        root._logo = tk.PhotoImage(file=str(ASSETS / "logo.png"))
        root.iconphoto(True, root._logo)
    except (tk.TclError, OSError, AttributeError):
        pass   # no logo is no reason not to start


class ImageBox(ttk.Frame):
    """Shows a picture as large as the space it gets, keeping its shape: give it room with
    grid(sticky="nsew") and a weight, and it grows and shrinks with the window.
    width/height: the size it asks for at first (and the smallest it is laid out at)."""

    def __init__(self, master, width, height, background=None):
        super().__init__(master, width=width, height=height)
        self.label = tk.Label(self, bd=0, bg=background or ttk.Style(master).lookup("TFrame", "background"))
        # place() doesn't make the frame ask for the picture's size, so a big picture can't push
        # the window larger: the frame's size alone decides how big the picture is drawn
        self.label.place(relx=0.5, rely=0.5, anchor="center")
        self._img, self._shown_size, self._photo = None, None, None
        self.bind("<Configure>", lambda e: self._render())

    def set(self, img):
        """img: a PIL image or a numpy array (H, W, 3)."""
        self._img = img if isinstance(img, Image.Image) else Image.fromarray(img)
        self._render(force=True)

    def _render(self, force=False):
        if self._img is None:
            return
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10:   # not laid out yet: use the size it asked for
            w, h = int(self.cget("width")), int(self.cget("height"))
        k = min(w / self._img.width, h / self._img.height)
        size = (max(1, int(self._img.width * k)), max(1, int(self._img.height * k)))
        if not force and size == self._shown_size:
            return
        self._shown_size = size
        self._photo = ImageTk.PhotoImage(self._img.resize(size, Image.BILINEAR))
        self.label.configure(image=self._photo)

    def bind_image(self, sequence, func):
        """Mouse events on the picture itself (e.g. clicks)."""
        self.label.bind(sequence, func)


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
            height = sum(max(1, math.ceil(self._font.measure(line) / width_px)) for line in lines)
        else:
            width_px = max((self._font.measure(line) for line in lines), default=0) + char
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
