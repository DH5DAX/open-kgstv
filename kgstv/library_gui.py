"""Browsable local image library and a searchable, persistent message window."""
from io import BytesIO
from pathlib import Path
import sqlite3
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from PIL import Image, ImageTk
from . import theme
from .image_document import Document, load_image
from .library import message_line

STORAGE_ERRORS = (OSError, ValueError, sqlite3.Error)


class StudioWindow:
    def __init__(self, app, title, geometry):
        self.app, self.title_key = app, title
        self.window = tk.Toplevel(app.root)
        self.window.configure(bg=theme.BG)
        self.window.geometry(geometry)
        self.bindings = []
        self.window.title(app.tr(title)+" · Open KG-STV")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        app.studio_windows.append(self)

    def label(self, parent, key, **options):
        options = dict({"bg":parent.cget("bg"), "fg":theme.TEXT, "font":(self.app.sans, 10)}, **options)
        label = tk.Label(parent, text=self.app.tr(key), **options)
        self.bindings.append((label, key))
        return label

    def button(self, parent, key, action, **options):
        button = ttk.Button(parent, text=self.app.tr(key), command=action, **options)
        self.bindings.append((button, key))
        return button

    def translate(self):
        self.window.title(self.app.tr(self.title_key)+" · Open KG-STV")
        self.bindings = [(widget, key) for widget, key in self.bindings if widget.winfo_exists()]
        for widget, key in self.bindings:
            widget.configure(text=self.app.tr(key))

    def error(self, exc):
        messagebox.showerror(self.app.tr("error_title"), str(exc), parent=self.window)

    def close(self):
        if self in self.app.studio_windows:
            self.app.studio_windows.remove(self)
        self.window.destroy()


class GalleryWindow(StudioWindow):
    FILTERS = (("all_images", None), ("rx_images", "rx"), ("tx_images", "tx"),
               ("photos", "image"), ("templates", "template"))

    def __init__(self, app, *, choose=None, kind=None):
        super().__init__(app, "gallery", "1060x760")
        self.window.minsize(850, 600)
        self.choose = choose
        self.selected = None
        self.offset = 0
        self.photos = []
        top = tk.Frame(self.window, bg=theme.BG, padx=18, pady=14)
        top.pack(fill="x")
        self.label(top, "library_hint").pack(anchor="w", pady=(0, 10))
        bar = tk.Frame(top, bg=theme.BG)
        bar.pack(fill="x")
        self.filter = ttk.Combobox(bar, width=20, state="readonly")
        self.filter.pack(side="left")
        self.filter.bind("<<ComboboxSelected>>", lambda e:self.refresh(reset=True))
        self.search = tk.StringVar(self.window)
        entry = ttk.Entry(bar, textvariable=self.search)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        entry.bind("<Return>", lambda e:self.refresh(reset=True))
        self.button(bar, "search", lambda:self.refresh(reset=True)).pack(side="left")
        self.button(bar, "import", self.import_images).pack(side="left", padx=(8, 0))
        self.button(bar, "more", self.more).pack(side="left", padx=(8, 0))
        body = tk.Frame(self.window, bg=theme.BG, padx=18)
        body.pack(fill="both", expand=True, pady=(0, 16))
        sidebar = tk.Frame(body, bg=theme.PANEL, padx=12, pady=12, width=265)
        sidebar.pack(side="right", fill="y", padx=(14, 0))
        sidebar.pack_propagate(False)
        self.preview = tk.Label(sidebar, bg=theme.WELL)
        self.preview.pack(fill="x")
        self.details = tk.StringVar(self.window)
        tk.Label(sidebar, textvariable=self.details, bg=theme.PANEL, fg=theme.MUTED,
                 wraplength=235, justify="left", font=(app.sans, 10)).pack(fill="x", pady=14)
        self.actions = []
        choices = [("edit_selected", lambda:self.use("edit")), ("use_background", lambda:self.use("background")),
                   ("use_layer", lambda:self.use("layer"))] if choose else [("edit_selected", lambda:self.use("edit"))]
        choices += [("rename", self.rename), ("duplicate", self.duplicate), ("export", self.export), ("delete", self.remove)]
        for key, action in choices:
            button = self.button(sidebar, key, action)
            button.pack(fill="x", pady=4)
            self.actions.append(button)
        scroll = ttk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        self.canvas = tk.Canvas(body, bg=theme.BG, highlightthickness=0, yscrollcommand=scroll.set)
        self.canvas.pack(fill="both", expand=True)
        scroll.configure(command=self.canvas.yview)
        self.grid = tk.Frame(self.canvas, bg=theme.BG)
        self.grid_id = self.canvas.create_window(0, 0, anchor="nw", window=self.grid)
        self.grid.bind("<Configure>", lambda e:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e:self.canvas.itemconfigure(self.grid_id, width=e.width))
        self.window.bind("<MouseWheel>", lambda e:self.canvas.yview_scroll(-3 if e.delta>0 else 3, "units"))
        self.filter.configure(values=[app.tr(key) for key, _ in self.FILTERS])
        self.filter.current(next((n for n, (_, value) in enumerate(self.FILTERS) if value == kind), 0))
        self.refresh()

    def translate(self):
        super().translate()
        index = self.filter.current()
        self.filter.configure(values=[self.app.tr(key) for key, _ in self.FILTERS])
        self.filter.current(max(0, index))
        self.refresh()

    def refresh(self, reset=False):
        if reset:
            self.offset = 0
        try:
            rows = self.app.library.images(kind=self.FILTERS[max(0, self.filter.current())][1],
                search=self.search.get(), limit=60+self.offset)
        except STORAGE_ERRORS as exc:
            self.error(exc)
            return
        for widget in self.grid.winfo_children():
            widget.destroy()
        self.photos.clear()
        self.tiles = {}
        for column in range(3):
            self.grid.columnconfigure(column, weight=1, uniform="tiles")
        for index, item in enumerate(rows):
            with Image.open(BytesIO(item["thumbnail"])) as source:
                photo = ImageTk.PhotoImage(source.copy(), master=self.window)
            self.photos.append(photo)
            tile = tk.Button(self.grid, image=photo, text=item["name"][:33]+"\n"+item["kind"].upper(),
                compound="top", wraplength=155, bg=theme.PANEL, fg=theme.TEXT, activebackground=theme.HOVER,
                activeforeground=theme.TEXT, relief="flat", bd=2, padx=6, pady=9, font=(self.app.sans, 9),
                command=lambda identity=item["id"]:self.select(identity))
            tile.grid(row=index//3, column=index%3, sticky="nsew", padx=4, pady=5)
            tile.bind("<Double-Button-1>", lambda e, identity=item["id"]:self.open_tile(identity))
            self.tiles[item["id"]] = tile
        if not rows:
            self.label(self.grid, "library_empty", wraplength=450, justify="left").grid(padx=14, pady=30, columnspan=3)
        if self.selected in self.tiles:
            self.select(self.selected)
        else:
            self.selected = None
            self.preview.configure(image="")
            self.details.set("")
        for button in self.actions:
            button.state(["!disabled" if self.selected else "disabled"])

    def select(self, identity):
        try:
            item = self.app.library.image(identity)
            self.selected = identity
            image = item["image"].copy()
            image.thumbnail((235, 190), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(image, master=self.window)
            self.preview.configure(image=self.preview_photo)
            self.details.set(item["name"]+"\n"+item["created"].replace("T", " ").replace("+00:00", " UTC"))
            for key, tile in self.tiles.items():
                tile.configure(bg=theme.HOVER if key == identity else theme.PANEL)
            for button in self.actions:
                button.state(["!disabled"])
        except STORAGE_ERRORS as exc:
            self.error(exc)

    def open_tile(self, identity):
        self.select(identity)
        self.use("edit")

    def use(self, mode):
        if self.selected is None:
            return
        try:
            item = self.app.library.image(self.selected)
            if self.choose:
                self.choose(item, mode)
            else:
                self.app.open_editor(item["document"] or Document.from_image(item["image"], item["name"]))
            self.close()
        except STORAGE_ERRORS as exc:
            self.error(exc)

    def more(self):
        self.offset += 60
        self.refresh()

    def import_images(self):
        paths = filedialog.askopenfilenames(parent=self.window, filetypes=[(self.app.tr("images_filter"), "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff")])
        for path in paths:
            try:
                self.app.library.add_image(Path(path).stem, load_image(path))
            except STORAGE_ERRORS as exc:
                self.error(exc)
        self.refresh(reset=True)

    def rename(self):
        self._named_action(self.app.library.rename)

    def duplicate(self):
        self._named_action(self.app.library.duplicate, copy=True)

    def _named_action(self, action, copy=False):
        if self.selected is None:
            return
        try:
            item = self.app.library.image(self.selected)
            name = self.app.tr("copy_name", name=item["name"]) if copy else item["name"]
            name = simpledialog.askstring(self.app.tr("name"), self.app.tr("name"), initialvalue=name, parent=self.window)
            if name:
                action(self.selected, name)
                self.refresh()
        except STORAGE_ERRORS as exc:
            self.error(exc)

    def remove(self):
        if self.selected and messagebox.askyesno(self.app.tr("delete"), self.app.tr("delete_entry"), parent=self.window):
            try:
                self.app.library.remove(self.selected)
                self.refresh()
            except STORAGE_ERRORS as exc:
                self.error(exc)

    def export(self):
        if self.selected is None:
            return
        try:
            item = self.app.library.image(self.selected)
            template = item["kind"] == "template" and item["document"] is not None
            path = filedialog.asksaveasfilename(parent=self.window, defaultextension=".kgstv.json" if template else ".png",
                filetypes=[("KG-STV template", "*.kgstv.json")] if template else [("PNG", "*.png")])
            if path:
                if template:
                    Path(path).write_text(item["document"].to_json(), encoding="utf-8")
                else:
                    item["image"].save(path, format="PNG")
        except STORAGE_ERRORS as exc:
            self.error(exc)


class HistoryWindow(StudioWindow):
    def __init__(self, app):
        super().__init__(app, "history", "980x700")
        self.window.minsize(700, 450)
        self.limit, self.rows = 500, []
        self.search = tk.StringVar(self.window)
        self.follow = tk.BooleanVar(self.window, True)
        top = tk.Frame(self.window, bg=theme.BG, padx=18, pady=14)
        top.pack(fill="x")
        self.label(top, "history_hint", wraplength=850, justify="left").pack(anchor="w", pady=(0, 12))
        bar = tk.Frame(top, bg=theme.BG)
        bar.pack(fill="x")
        entry = ttk.Entry(bar, textvariable=self.search)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e:self.refresh())
        self.button(bar, "search", self.refresh).pack(side="left", padx=8)
        self.button(bar, "more", self.more).pack(side="left")
        self.button(bar, "history_export", self.export).pack(side="left", padx=(8, 0))
        bottom = tk.Frame(self.window, bg=theme.BG, padx=18, pady=12)
        bottom.pack(side="bottom", fill="x")
        self.count = tk.StringVar(self.window)
        tk.Label(bottom, textvariable=self.count, bg=theme.BG, fg=theme.MUTED).pack(side="left")
        check = ttk.Checkbutton(bottom, variable=self.follow, text=app.tr("history_follow"))
        check.pack(side="right")
        self.bindings.append((check, "history_follow"))
        body = tk.Frame(self.window, bg=theme.BG, padx=18)
        body.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        self.log = tk.Text(body, wrap="word", state="disabled", font=(app.mono, 11), bg=theme.WELL,
            fg=theme.TEXT, relief="flat", padx=12, pady=12, yscrollcommand=scroll.set)
        self.log.pack(fill="both", expand=True)
        scroll.configure(command=self.log.yview)
        self.log.tag_configure("TX", foreground=theme.BLUE)
        self.refresh()

    def refresh(self):
        try:
            position = self.log.yview()
            self.rows = list(reversed(self.app.library.messages(self.search.get(), limit=self.limit)))
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            for item in self.rows:
                self.log.insert("end", message_line(item), item["direction"])
            self.log.configure(state="disabled")
            if self.follow.get():
                self.log.see("end")
            elif position:
                self.log.yview_moveto(position[0])
            self.count.set(self.app.tr("history_count", count=len(self.rows)))
        except STORAGE_ERRORS as exc:
            self.error(exc)

    def translate(self):
        super().translate()
        self.count.set(self.app.tr("history_count", count=len(self.rows)))

    def more(self):
        self.limit += 500
        self.refresh()

    def export(self):
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if path:
            try:
                Path(path).write_text("".join(message_line(item) for item in self.rows), encoding="utf-8")
            except OSError as exc:
                self.error(exc)
