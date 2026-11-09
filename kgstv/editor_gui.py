"""Interactive, non-destructive 320x240 TX composition editor."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
import uuid
from PIL import Image, ImageTk
from . import theme
from .image_document import Document, History, Layer, FONTS, MAX_DOCUMENT, load_image
from .library_gui import StudioWindow, GalleryWindow, STORAGE_ERRORS


class ImageEditor(StudioWindow):
    def __init__(self, app, document=None):
        super().__init__(app, "studio", f"1180x{min(850, app.root.winfo_screenheight()-70)}")
        self.window.minsize(980, 680)
        self.document = (document or app.tx_document or
                         (Document.from_image(app.tx_image) if app.tx_image is not None else Document())).clone()
        self.history = History()
        self.selected = self.document.layers[-1].id if self.document.layers else None
        self.dirty = False
        self.updating = False
        self.pending = None
        self.drag = None
        self.boxes = {}
        self.variables = {}
        self.mycall = tk.StringVar(self.window, app.callsign.get() or app.tx_context.get("MYCALL", ""))
        self.hiscall = tk.StringVar(self.window, (app.rx_summary or {}).get("callsign") or app.tx_context.get("HISCALL", ""))
        self.status = tk.StringVar(self.window, app.tr("studio_ready"))
        self._build()
        self.mycall.trace_add("write", self.context_changed)
        self.hiscall.trace_add("write", self.context_changed)
        self.refresh()

    def context_changed(self, *_):
        self.dirty = True
        self.redraw()

    def context(self):
        now = datetime.now(timezone.utc)
        return {"MYCALL":self.mycall.get().strip() or "{MYCALL}",
                "HISCALL":self.hiscall.get().strip() or "{HISCALL}",
                "DATE":now.strftime("%Y-%m-%d"), "TIME":now.strftime("%H:%M UTC")}

    def _build(self):
        top = tk.Frame(self.window, bg=theme.BG, padx=16, pady=12)
        top.pack(fill="x")
        self.label(top, "studio").configure(font=(self.app.sans, 16, "bold"))
        heading = top.winfo_children()[-1]
        heading.pack(side="left")
        self.button(top, "use_tx", self.apply, style="Primary.TButton").pack(side="right")
        self.button(top, "export_png", self.export_image).pack(side="right", padx=8)
        self.button(top, "save_template", self.save_template).pack(side="right")
        tools = tk.Frame(self.window, bg=theme.BG, padx=16)
        tools.pack(fill="x", pady=(0, 10))
        self.undo_button = self.button(tools, "undo", self.undo)
        self.undo_button.pack(side="left")
        self.redo_button = self.button(tools, "redo", self.redo)
        self.redo_button.pack(side="left", padx=(5, 14))
        for key, callback in (("new_canvas", self.blank), ("background", lambda:self.open_image(True)),
                              ("add_image", self.open_image), ("add_rx", self.add_rx), ("add_text", self.add_text),
                              ("gallery", self.gallery)):
            self.button(tools, key, callback).pack(side="left", padx=(0, 5))
        bottom = tk.Frame(self.window, bg=theme.BG, padx=16, pady=10)
        bottom.pack(side="bottom", fill="x")
        tk.Label(bottom, textvariable=self.status, bg=theme.BG, fg=theme.GREEN, font=(self.app.sans, 9)).pack(anchor="w")
        self.label(bottom, "studio_hint", wraplength=1050, justify="left").pack(anchor="w", pady=(5, 0))
        body = tk.Frame(self.window, bg=theme.BG, padx=16)
        body.pack(fill="both", expand=True)
        inspector = tk.Frame(body, bg=theme.PANEL, width=315, padx=12, pady=10)
        inspector.pack(side="right", fill="y", padx=(12, 0))
        inspector.pack_propagate(False)
        self.label(inspector, "layers").pack(anchor="w", pady=(0, 5))
        layer_row = tk.Frame(inspector, bg=theme.PANEL)
        layer_row.pack(fill="x")
        scroll = ttk.Scrollbar(layer_row)
        scroll.pack(side="right", fill="y")
        self.layer_list = tk.Listbox(layer_row, height=4, exportselection=False, bg=theme.WELL, fg=theme.TEXT,
            selectbackground="#25457C", selectforeground=theme.TEXT, highlightthickness=0, relief="flat",
            font=(self.app.sans, 10), yscrollcommand=scroll.set)
        self.layer_list.pack(fill="x", expand=True)
        scroll.configure(command=self.layer_list.yview)
        self.layer_list.bind("<<ListboxSelect>>", self.select_list)
        buttons = tk.Frame(inspector, bg=theme.PANEL)
        buttons.pack(fill="x", pady=6)
        for col, (key, callback) in enumerate((("up", lambda:self.reorder(1)), ("down", lambda:self.reorder(-1)),
                                              ("duplicate", self.duplicate), ("delete", self.remove))):
            buttons.columnconfigure(col%2, weight=1)
            self.button(buttons, key, callback).grid(row=col//2, column=col%2, sticky="ew", padx=2, pady=2)
        self.notebook = ttk.Notebook(inspector)
        self.notebook.pack(fill="both", expand=True, pady=(4, 0))
        self.tabs = {}
        self.tab_frames = {}
        for key in ("layer", "image_adjust", "text_adjust"):
            frame = tk.Frame(self.notebook, bg=theme.PANEL)
            self.notebook.add(frame, text=self.app.tr(key))
            self.tab_frames[key] = frame
            scroll = ttk.Scrollbar(frame)
            scroll.pack(side="right", fill="y")
            canvas = tk.Canvas(frame, bg=theme.PANEL, highlightthickness=0, yscrollcommand=scroll.set, width=285)
            canvas.pack(fill="both", expand=True)
            scroll.configure(command=canvas.yview)
            page = tk.Frame(canvas, bg=theme.PANEL, padx=8, pady=8)
            item = canvas.create_window(0, 0, window=page, anchor="nw")
            page.bind("<Configure>", lambda e, c=canvas:c.configure(scrollregion=c.bbox("all")))
            canvas.bind("<Configure>", lambda e, c=canvas, i=item:c.itemconfigure(i, width=e.width))
            self.tabs[key] = page
        common = self.tabs["layer"]
        self._check(common, "visible", "visible")
        for key, title, lo, hi in (("x", "X", -640, 960), ("y", "Y", -480, 720),
                                  ("width", "width", 1, 1280), ("height", "height", 1, 960),
                                  ("opacity", "opacity", 0, 100), ("angle", "angle", -360, 360)):
            self._number(common, key, title, lo, hi)
        self.button(common, "background_color", self.canvas_color).pack(fill="x", pady=(12, 0))
        self.button(common, "save_picture", lambda:self.save_template(kind="image")).pack(fill="x", pady=5)
        self.button(common, "export_template", self.export_document).pack(fill="x", pady=5)
        self.button(common, "import_template", self.import_document).pack(fill="x", pady=5)
        image = self.tabs["image_adjust"]
        self._combo(image, "fit", "fit", ("cover", "contain", "stretch"), "fit_")
        for key, title in (("crop_x", "crop_x"), ("crop_y", "crop_y"), ("brightness", "brightness"),
                           ("contrast", "contrast"), ("saturation", "saturation"), ("sharpness", "sharpness")):
            self._number(image, key, title, 0, 100 if key.startswith("crop") else 300)
        self._check(image, "flip", "flip")
        self._check(image, "autocontrast", "autocontrast")
        self.button(image, "reset_adjust", self.reset_adjustments).pack(fill="x", pady=(10, 0))
        text = self.tabs["text_adjust"]
        self.text_input = tk.Text(text, height=3, wrap="word", bg=theme.WELL, fg=theme.TEXT, insertbackground=theme.TEXT,
                                  font=(self.app.sans, 11), relief="flat", padx=5, pady=5)
        self.text_input.pack(fill="x", pady=(0, 7))
        self.text_input.bind("<<Modified>>", self.text_changed)
        self._combo(text, "font", "font", FONTS)
        self._number(text, "size", "font_size", 6, 120)
        self._number(text, "outline", "outline", 0, 8)
        self._combo(text, "align", "align", ("left", "center", "right"), "align_")
        self._check(text, "bold", "bold")
        self._check(text, "shadow", "shadow")
        self.button(text, "text_color", lambda:self.color("color")).pack(fill="x", pady=5)
        self.button(text, "outline_color", lambda:self.color("outline_color")).pack(fill="x", pady=5)
        center = tk.Frame(body, bg=theme.BG)
        center.pack(fill="both", expand=True)
        calls = tk.Frame(center, bg=theme.BG)
        calls.pack(fill="x", pady=(0, 10))
        for key, var in (("callsign", self.mycall), ("their_call", self.hiscall)):
            self.label(calls, key).pack(side="left", padx=(0, 7))
            ttk.Entry(calls, textvariable=var, width=12).pack(side="left", padx=(0, 12))
        self.canvas = tk.Canvas(center, bg=theme.WELL, highlightthickness=1, highlightbackground=theme.BORDER, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e:self.redraw())
        self.canvas.bind("<ButtonPress-1>", self.pointer_down)
        self.canvas.bind("<B1-Motion>", self.pointer_move)
        self.canvas.bind("<ButtonRelease-1>", self.pointer_up)
        self.canvas.bind("<Delete>", lambda e:self.remove())
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self.canvas.bind("<"+key+">", lambda e, dx=dx, dy=dy:self.nudge(dx, dy, 10 if e.state&1 else 1))
        self.canvas.bind("<Control-d>", lambda e:self.duplicate())
        self.window.bind("<Control-z>", lambda e:self.undo())
        self.window.bind("<Control-y>", lambda e:self.redo())
        quick = tk.Frame(center, bg=theme.BG)
        quick.pack(fill="x", pady=10)
        self.label(quick, "quick_text").pack(side="left", padx=(0, 10))
        for key in ("CQ", "reply", "RSV 595", "73"):
            if key == "reply":
                self.button(quick, key, lambda:self.quick("reply")).pack(side="left", padx=3)
            else:
                ttk.Button(quick, text=key, command=lambda key=key:self.quick(key)).pack(side="left", padx=3)
        self.label(center, "tokens_hint", wraplength=650, justify="left").pack(anchor="w", pady=(0, 8))

    def _number(self, parent, key, title, low, high):
        row = tk.Frame(parent, bg=theme.PANEL)
        row.pack(fill="x", pady=3)
        if title in ("X", "Y"):
            tk.Label(row, text=title, bg=theme.PANEL, fg=theme.TEXT).pack(side="left")
        else:
            self.label(row, title).pack(side="left")
        variable = self.variables[key] = tk.StringVar(self.window)
        ttk.Spinbox(row, from_=low, to=high, increment=1, textvariable=variable, width=8).pack(side="right")
        variable.trace_add("write", self.queue_properties)

    def _check(self, parent, key, title):
        variable = self.variables[key] = tk.BooleanVar(self.window)
        check = ttk.Checkbutton(parent, text=self.app.tr(title), variable=variable)
        check.pack(anchor="w", pady=4)
        self.bindings.append((check, title))
        variable.trace_add("write", self.queue_properties)

    def _combo(self, parent, key, title, values, prefix=""):
        row = tk.Frame(parent, bg=theme.PANEL)
        row.pack(fill="x", pady=3)
        self.label(row, title).pack(side="left")
        variable = self.variables[key] = tk.StringVar(self.window)
        combo = ttk.Combobox(row, textvariable=variable, width=17, state="readonly")
        combo.pack(side="right")
        combo.configure(values=[self.app.tr(prefix+v) if prefix else v for v in values])
        setattr(self, key+"_options", (combo, values, prefix))
        variable.trace_add("write", self.queue_properties)

    def current(self):
        return next((layer for layer in self.document.layers if layer.id == self.selected), None)

    def text_changed(self, event=None):
        if self.text_input.edit_modified():
            self.text_input.edit_modified(False)
            self.queue_properties()

    def queue_properties(self, *_):
        if self.updating:
            return
        if self.pending:
            self.window.after_cancel(self.pending)
        self.pending = self.window.after(250, self.flush_properties)

    def flush_properties(self):
        if self.pending:
            self.window.after_cancel(self.pending)
            self.pending = None
        layer = self.current()
        if layer is None:
            return True
        candidate = replace(layer)
        try:
            for key, variable in self.variables.items():
                if hasattr(self, key+"_options"):
                    combo, values, _ = getattr(self, key+"_options")
                    if combo.current() >= 0:
                        setattr(candidate, key, values[combo.current()])
                else:
                    setattr(candidate, key, variable.get() if isinstance(variable, tk.BooleanVar) else float(variable.get().replace(",", ".")))
            candidate.text = self.text_input.get("1.0", "end-1c")
            candidate.validate()
            if candidate != layer:
                self.history.push(self.document)
                self.document.layers[self.document.layers.index(layer)] = candidate
                self.dirty = True
                self.refresh(properties=False)
            return True
        except (ValueError, tk.TclError) as exc:
            self.status.set(str(exc))
            return False

    def refresh(self, properties=True):
        self.updating = True
        self.layer_list.delete(0, "end")
        for layer in reversed(self.document.layers):
            name = layer.text.replace("\n", " ") if layer.kind == "text" else layer.name
            self.layer_list.insert("end", ("● " if layer.visible else "○ ")+("T  " if layer.kind == "text" else "▧  ")+name[:35])
            if layer.id == self.selected:
                self.layer_list.selection_set(self.layer_list.size()-1)
        layer = self.current()
        if properties:
            sample = layer or Layer("text")
            for key, variable in self.variables.items():
                value = getattr(sample, key)
                if hasattr(self, key+"_options"):
                    combo, values, _ = getattr(self, key+"_options")
                    combo.current(values.index(value))
                else:
                    variable.set(value if isinstance(variable, tk.BooleanVar) else f"{value:g}")
            self.text_input.delete("1.0", "end")
            self.text_input.insert("1.0", sample.text)
            self.text_input.edit_modified(False)
        self.updating = False
        self.undo_button.state(["!disabled" if self.history.past else "disabled"])
        self.redo_button.state(["!disabled" if self.history.future else "disabled"])
        self.redraw()

    def redraw(self):
        if not hasattr(self, "canvas") or not self.canvas.winfo_exists():
            return
        try:
            output, self.boxes = self.document.render(self.context(), bounds=True)
            width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
            self.zoom = max(.1, min((width-40)/320, (height-40)/240))
            w, h = max(1, round(320*self.zoom)), max(1, round(240*self.zoom))
            self.origin = ((width-w)/2, (height-h)/2)
            self.photo = ImageTk.PhotoImage(output.resize((w, h), Image.Resampling.LANCZOS), master=self.window)
            self.canvas.delete("all")
            self.canvas.create_image(*self.origin, image=self.photo, anchor="nw")
            x, y = self.origin
            self.canvas.create_rectangle(x, y, x+w, y+h, outline=theme.BORDER)
            if self.selected in self.boxes:
                a, b, c, d = self.boxes[self.selected]
                points = (x+a*self.zoom, y+b*self.zoom, x+c*self.zoom, y+d*self.zoom)
                self.canvas.create_rectangle(*points, outline=theme.BLUE, width=2, dash=(5, 3))
                self.canvas.create_rectangle(points[2]-5, points[3]-5, points[2]+5, points[3]+5,
                                             fill=theme.BLUE, outline=theme.TEXT)
            self.status.set(self.app.tr("studio_ready"))
        except (ValueError, OSError) as exc:
            self.status.set(str(exc))

    def translate(self):
        self.flush_properties()
        super().translate()
        for key, frame in self.tab_frames.items():
            self.notebook.tab(frame, text=self.app.tr(key))
        self.updating = True
        for key in ("fit", "align", "font"):
            combo, values, prefix = getattr(self, key+"_options")
            combo.configure(values=[self.app.tr(prefix+v) if prefix else v for v in values])
        self.updating = False
        self.refresh()

    def change(self, action, *, selected=None):
        if not self.flush_properties():
            return
        before = self.document.clone()
        try:
            result = action()
            self.document.render(self.context())
            self.history.push(before)
            if isinstance(result, Layer):
                self.selected = result.id
            elif selected is not None:
                self.selected = selected
            self.dirty = True
            self.refresh()
        except (ValueError, OSError) as exc:
            self.document = before
            self.error(exc)

    def select_list(self, event=None):
        if self.updating or not self.layer_list.curselection():
            return
        index = self.layer_list.curselection()[0]
        self.flush_properties()
        self.selected = self.document.layers[-1-index].id
        self.refresh()

    def add_text(self):
        self.change(lambda:self.document.add(Layer("text", text="TEXT")))
        self.notebook.select(self.tab_frames["text_adjust"])
        self.text_input.focus_set()
        self.text_input.tag_add("sel", "1.0", "end-1c")

    def open_image(self, background=False):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[(self.app.tr("images_filter"), "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff")])
        if path:
            try:
                self.insert_image(load_image(path), Path(path).stem, background)
            except (OSError, ValueError) as exc:
                self.error(exc)

    def insert_image(self, image, name="Image", background=False):
        source = load_image(image)
        def action():
            layer = Layer("image", name=name, image=source, width=320 if background else 160,
                          height=240 if background else min(180, 160*source.height/source.width), fit="cover" if background else "contain")
            if background:
                if self.document.layers and self.document.layers[0].kind == "image":
                    self.document.layers[0] = layer
                else:
                    self.document.add(layer)
                    self.document.layers.insert(0, self.document.layers.pop())
            else:
                self.document.add(layer)
            return layer
        self.change(action)
        self.notebook.select(self.tab_frames["image_adjust"])

    def add_rx(self):
        if self.app.rx_image is None:
            self.gallery(kind="rx")
        else:
            self.insert_image(self.app.rx_image, "RX "+self.hiscall.get())

    def gallery(self, kind=None):
        if not self.app.library:
            self.app._error("library_error")
            return
        def choose(item, mode):
            if mode == "edit":
                self.change(lambda:setattr(self, "document", (item["document"] or Document.from_image(item["image"], item["name"])).clone()))
                self.selected = self.document.layers[-1].id if self.document.layers else None
                self.refresh()
            else:
                self.insert_image(item["image"], item["name"], mode == "background")
        GalleryWindow(self.app, choose=choose, kind=kind)

    def blank(self):
        self.change(lambda:setattr(self, "document", Document()))
        self.selected = None
        self.refresh()

    def quick(self, key):
        def action():
            if key == "reply" and self.app.rx_image is not None:
                self.document.add(Layer("image", name="RX "+self.hiscall.get(), image=load_image(self.app.rx_image),
                                        x=235, y=145, width=150, height=112, fit="contain"))
            text, y, size = {"CQ":("CQ CQ\n{MYCALL}", 53, 27), "reply":("{HISCALL} de {MYCALL}", 24, 17),
                             "RSV 595":("RSV 595", 213, 24), "73":("73 de {MYCALL}", 214, 23)}[key]
            return self.document.add(Layer("text", text=text, y=y, size=size, shadow=True))
        self.change(action)
        self.notebook.select(self.tab_frames["text_adjust"])

    def remove(self):
        if not self.flush_properties():
            return
        layer = self.current()
        if layer:
            self.change(lambda:self.document.layers.remove(layer))
            self.selected = self.document.layers[-1].id if self.document.layers else None
            self.refresh()

    def duplicate(self):
        if self.flush_properties() and self.current():
            layer = self.current()
            self.change(lambda:self.document.add(replace(layer, id=uuid.uuid4().hex, x=min(960, layer.x+8), y=min(720, layer.y+8))))

    def reorder(self, delta):
        if self.flush_properties() and self.current():
            layer = self.current()
            index = self.document.layers.index(layer)
            target = max(0, min(len(self.document.layers)-1, index+delta))
            if index != target:
                self.change(lambda:self.document.layers.insert(target, self.document.layers.pop(index)))

    def reset_adjustments(self):
        if not self.flush_properties():
            return
        layer = self.current()
        if layer:
            def action():
                for key in ("brightness", "contrast", "saturation", "sharpness"):
                    setattr(layer, key, 100)
                layer.autocontrast = False
            self.change(action)

    def color(self, key):
        if self.flush_properties() and self.current():
            layer = self.current()
            color = colorchooser.askcolor(getattr(layer, key), parent=self.window)[1]
            if color:
                self.change(lambda:setattr(layer, key, color))

    def canvas_color(self):
        color = colorchooser.askcolor(self.document.background, parent=self.window)[1]
        if color:
            self.change(lambda:setattr(self.document, "background", color))

    def undo(self):
        self.flush_properties()
        self.document = self.history.undo(self.document)
        self.selected = self.document.layers[-1].id if self.document.layers else None
        self.dirty = True
        self.refresh()
        return "break"

    def redo(self):
        self.flush_properties()
        self.document = self.history.redo(self.document)
        self.selected = self.document.layers[-1].id if self.document.layers else None
        self.dirty = True
        self.refresh()
        return "break"

    def point(self, event):
        return ((event.x-self.origin[0])/self.zoom, (event.y-self.origin[1])/self.zoom)

    def pointer_down(self, event):
        if not self.flush_properties():
            return
        self.canvas.focus_set()
        x, y = self.point(event)
        box = self.boxes.get(self.selected)
        resize = box is not None and abs(x-box[2])*self.zoom < 12 and abs(y-box[3])*self.zoom < 12
        if not resize:
            self.selected = next((layer.id for layer in reversed(self.document.layers) if layer.id in self.boxes and
                self.boxes[layer.id][0] <= x <= self.boxes[layer.id][2] and self.boxes[layer.id][1] <= y <= self.boxes[layer.id][3]), None)
        layer = self.current()
        self.drag = (x, y, replace(layer), self.document.clone(), resize) if layer else None
        self.refresh()

    def pointer_move(self, event):
        if self.drag is None or self.current() is None:
            return
        x, y = self.point(event)
        start_x, start_y, original, _, resize = self.drag
        layer = self.current()
        if resize:
            ratio = max(.1, 1+(x-start_x)/max(20, original.width/2))
            if layer.kind == "text":
                layer.size = max(6, min(120, original.size*ratio))
            else:
                ratio = min(ratio, 1280/original.width, 960/original.height)
                layer.width, layer.height = max(1, original.width*ratio), max(1, original.height*ratio)
        else:
            layer.x = max(-640, min(960, original.x+x-start_x))
            layer.y = max(-480, min(720, original.y+y-start_y))
            if abs(layer.x-160) < 3:
                layer.x = 160
            if abs(layer.y-120) < 3:
                layer.y = 120
        self.redraw()

    def pointer_up(self, event):
        if self.drag:
            _, _, original, before, _ = self.drag
            if self.current() != original:
                self.history.push(before)
                self.dirty = True
            self.drag = None
            self.refresh()

    def nudge(self, dx, dy, distance=1):
        if self.flush_properties() and self.current():
            layer = self.current()
            def action():
                layer.x = max(-640, min(960, layer.x+dx*distance))
                layer.y = max(-480, min(720, layer.y+dy*distance))
            self.change(action)
        return "break"

    def apply(self):
        if not self.flush_properties():
            return
        try:
            self.app.set_tx_document(self.document, self.context())
            self.dirty = False
            self.status.set(self.app.tr("studio_applied"))
        except STORAGE_ERRORS as exc:
            self.error(exc)

    def save_template(self, kind="template"):
        if not self.app.library:
            self.app._error("library_error")
            return
        if not self.flush_properties():
            return
        name = simpledialog.askstring(self.app.tr("save_template" if kind == "template" else "save_picture"),
                                      self.app.tr("name"), parent=self.window)
        if name:
            try:
                self.app.library.add_image(name, self.document.render(self.context()), kind=kind, document=self.document)
                self.status.set(self.app.tr("library_saved"))
                self.app.refresh_library_windows()
            except STORAGE_ERRORS as exc:
                self.error(exc)

    def export_image(self):
        if not self.flush_properties():
            return
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension=".png", filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
        if path:
            try:
                self.document.render(self.context()).save(path)
            except (OSError, ValueError) as exc:
                self.error(exc)

    def export_document(self):
        if not self.flush_properties():
            return
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension=".kgstv.json", filetypes=[("KG-STV template", "*.kgstv.json")])
        if path:
            try:
                Path(path).write_text(self.document.to_json(), encoding="utf-8")
            except STORAGE_ERRORS as exc:
                self.error(exc)

    def import_document(self):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[("KG-STV template", "*.kgstv.json *.json")])
        if path:
            try:
                if Path(path).stat().st_size > MAX_DOCUMENT:
                    raise ValueError("Composition exceeds 32 MB")
                document = Document.from_json(Path(path).read_text(encoding="utf-8"))
                self.change(lambda:setattr(self, "document", document))
                self.selected = document.layers[-1].id if document.layers else None
                self.refresh()
            except STORAGE_ERRORS as exc:
                self.error(exc)

    def close(self):
        self.flush_properties()
        if self.dirty and not self.app.closing and not messagebox.askyesno(self.app.tr("studio"), self.app.tr("discard_edits"), parent=self.window):
            return
        if self.pending:
            self.window.after_cancel(self.pending)
        super().close()
