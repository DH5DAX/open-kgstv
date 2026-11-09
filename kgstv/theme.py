"""HamRig-family palette, independently implemented for Tk/ttk.

Visual references: HamRig Portal's hamrig.css and HamRig Rotor's app.css.
Robbie artwork is bundled separately in assets; no fonts are bundled.
"""
import tkinter as tk
from tkinter import ttk, font
from PIL import Image, ImageTk

BG = "#16161A"
PANEL = "#24242B"
WELL = "#1A1A20"
HOVER = "#31313A"
BORDER = "#37373F"
TEXT = "#F2F2F7"
MUTED = "#AEAEB2"
DIM = "#8E8E93"
CRIMSON = "#8B1D1D"
TINT = "#E05252"
BLUE = "#6B9BFF"
GREEN = "#34C759"
AMBER = "#F0B44C"


def setup(root):
    families = set(font.families(root))
    sans = next((f for f in ("Inter", "Segoe UI", "DejaVu Sans") if f in families), "TkDefaultFont")
    mono = next((f for f in ("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono") if f in families), "TkFixedFont")
    root.configure(bg=BG)
    root.option_add("*Font", (sans, 10))
    root.option_add("*TCombobox*Listbox.background", WELL)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", "#33466B")
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=PANEL, foreground=TEXT, font=(sans, 10))
    style.configure("TButton", background=HOVER, foreground=TEXT, bordercolor=HOVER,
                    lightcolor=HOVER, darkcolor=HOVER, focuscolor=BLUE,
                    padding=(12, 7), font=(sans, 10, "bold"), borderwidth=1)
    style.map("TButton", background=[("disabled", PANEL), ("active", "#41414C")],
              foreground=[("disabled", DIM)], bordercolor=[("focus", BLUE)])
    for name, color, active in (("Primary", CRIMSON, "#A12626"),
                                 ("Receive", "#25457C", "#315A9D"),
                                 ("Stop", "#382428", "#503036")):
        style.configure(name+".TButton", background=color, bordercolor=color,
                        lightcolor=color, darkcolor=color)
        style.map(name+".TButton", background=[("disabled", PANEL), ("active", active)],
                  foreground=[("disabled", DIM), ("!disabled", TEXT)])
    style.configure("Link.TButton", background=PANEL, bordercolor=PANEL,
                    lightcolor=PANEL, darkcolor=PANEL, foreground=MUTED,
                    padding=(0, 4), font=(sans, 9))
    style.map("Link.TButton", background=[("active", HOVER)], foreground=[("disabled", DIM), ("active", TEXT)])
    style.configure("TEntry", fieldbackground=WELL, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=7)
    style.map("TEntry", bordercolor=[("focus", BLUE)], fieldbackground=[("disabled", PANEL)])
    style.configure("TSpinbox", fieldbackground=WELL, foreground=TEXT, insertcolor=TEXT,
                    background=HOVER, arrowcolor=MUTED, bordercolor=BORDER, padding=5)
    style.configure("TNotebook", background=PANEL, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background=HOVER, foreground=MUTED, padding=(10, 7))
    style.map("TNotebook.Tab", background=[("selected", "#25457C")], foreground=[("selected", TEXT)])
    style.configure("TCombobox", fieldbackground=WELL, background=HOVER, foreground=TEXT,
                    arrowcolor=MUTED, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, padding=6)
    style.map("TCombobox", fieldbackground=[("readonly", WELL)],
              foreground=[("readonly", TEXT), ("disabled", DIM)],
              selectbackground=[("readonly", WELL)], selectforeground=[("readonly", TEXT)],
              bordercolor=[("focus", BLUE)])
    style.configure("TCheckbutton", background=PANEL, foreground=TEXT,
                    indicatorbackground=WELL, indicatorforeground=BLUE,
                    indicatorcolor=BLUE, padding=3)
    style.map("TCheckbutton", background=[("active", PANEL)],
              indicatorbackground=[("selected", "#25457C")])
    style.configure("Horizontal.TProgressbar", background=GREEN, troughcolor=WELL,
                    bordercolor=WELL, lightcolor=GREEN, darkcolor=GREEN, thickness=4)
    style.configure("Vertical.TScrollbar", background=HOVER, troughcolor=BG,
                    bordercolor=BG, arrowcolor=DIM, lightcolor=HOVER, darkcolor=HOVER)
    style.map("Vertical.TScrollbar", background=[("disabled", HOVER), ("active", "#41414C")],
              arrowcolor=[("disabled", DIM)], lightcolor=[("disabled", HOVER)],
              darkcolor=[("disabled", HOVER)], bordercolor=[("disabled", BG)])
    return sans, mono


def rounded(canvas, x1, y1, x2, y2, radius, **kwargs):
    return canvas.create_polygon(x1+radius, y1, x2-radius, y1, x2, y1, x2, y1+radius,
                                 x2, y2-radius, x2, y2, x2-radius, y2, x1+radius, y2,
                                 x1, y2, x1, y2-radius, x1, y1+radius, x1, y1,
                                 smooth=True, splinesteps=24, **kwargs)


class Card(tk.Frame):
    def __init__(self, parent, padding=14):
        super().__init__(parent, bg=BG)
        self.padding = padding
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, width=1)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=PANEL)
        self.window = self.canvas.create_window(padding, padding, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._height)
        self.canvas.bind("<Configure>", self._resize)

    def _height(self, event):
        self.canvas.configure(height=self.body.winfo_reqheight()+self.padding*2)

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=max(1, event.width-self.padding*2))
        self.canvas.delete("surface")
        rounded(self.canvas, 1, 1, event.width-1, event.height-1, 14,
                fill=PANEL, outline=BORDER, tags="surface")
        self.canvas.tag_lower("surface")


class ImagePreview(tk.Canvas):
    def __init__(self, parent, sans, height=192):
        super().__init__(parent, bg=WELL, height=height, width=320,
                         highlightthickness=1, highlightbackground=BORDER)
        self.sans = sans
        self.source = None
        self.image = None
        self.title = self.hint = ""
        self.bind("<Configure>", lambda event:self.redraw())

    def placeholder(self, title, hint):
        self.title, self.hint = title, hint
        self.redraw()

    def show(self, image):
        self.source = image
        self.redraw()

    def redraw(self):
        self.delete("all")
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        if self.source is not None:
            ratio = min((width-16)/320, (height-16)/240)
            size = (max(1, int(320*ratio)), max(1, int(240*ratio)))
            self.image = ImageTk.PhotoImage(self.source.resize(size, Image.Resampling.LANCZOS), master=self)
            self.create_image(width/2, height/2, image=self.image)
        else:
            x, y = width/2, height/2-32
            self.create_rectangle(x-22, y-17, x+22, y+17, outline="#565662", width=2)
            self.create_oval(x+7, y-10, x+13, y-4, outline=DIM)
            self.create_line(x-17, y+11, x-5, y-1, x+2, y+6, x+10, y, x+18, y+11, fill=DIM, width=2)
            self.create_text(x, y+49, text=self.title, fill=TEXT, font=(self.sans, 11, "bold"))
            self.create_text(x, y+75, text=self.hint, fill=DIM, font=(self.sans, 9), width=max(100, width-24))
