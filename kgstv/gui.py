"""Bilingual Tk desktop client. Only the UI thread touches Tk."""
import math
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
from . import __version__, theme
from .audio import save_wav
from .cli import decode_file
from .i18n import TRANSLATIONS, load_language, save_language, settings_file, translate, load_settings, save_settings
from .modem import modulate
from .protocol import SCALES, text_frame
from .session import image_frames, request_frames
from .hamlib import PTTReleaseError
from .radio_gui import RadioPanel
from .image_document import Document, load_image
from .library import Library, message_line, utc_now
from .library_gui import GalleryWindow, HistoryWindow, STORAGE_ERRORS


class Application:
    def __init__(self, root, *, settings_path=None, language=None):
        self.root = root
        root.title("Open KG-STV")
        root.geometry(f"1120x{min(1000, root.winfo_screenheight()-60)}")
        root.minsize(940, 640)
        self.settings_path = Path(settings_path) if settings_path is not None else settings_file()
        self.language = language or load_language(self.settings_path)
        if self.language not in TRANSLATIONS:
            raise ValueError("Unsupported interface language")
        self.sans, self.mono = theme.setup(root)
        with Image.open(Path(__file__).parent / "assets" / "hamrig-robbie.png") as source:
            robbie = source.convert("RGBA")
        self._icons = []
        for size in (16, 32, 48, 64, 128, 256):
            icon = robbie.copy()
            icon.thumbnail((size, size), Image.Resampling.LANCZOS)
            self._icons.append(ImageTk.PhotoImage(icon, master=root))
        root.iconphoto(True, *self._icons)
        robbie.thumbnail((58, 64), Image.Resampling.LANCZOS)
        self.robbie = ImageTk.PhotoImage(robbie, master=root)
        self.events = queue.Queue()
        self.busy = self.closing = False
        self.worker_thread = None
        self.cancelled = threading.Event()
        self.live = None
        self.tx_image = self.rx_image = self.rx_summary = None
        self.tx_document = None
        self.tx_context = {}
        self.studio_windows = []
        self._archived_rx = None
        self._recent_messages = []
        self.library = None
        storage_error = None
        try:
            self.library = Library(self.settings_path.parent/"library.sqlite3")
            self.tx_document = self.library.draft()
            self.tx_context = self.library.draft_context()
            if self.tx_document is not None:
                self.tx_image = self.tx_document.render(self.tx_context)
            self._recent_messages = list(reversed(self.library.messages(limit=200)))
        except STORAGE_ERRORS as exc:
            storage_error = str(exc)
        self.requested_blocks = []
        self.last_preview = 0
        stored = load_settings(self.settings_path)
        self.callsign = tk.StringVar(root, str(stored.get("callsign", "")))
        self.mode = tk.StringVar(root, "MSK")
        self.fec = tk.BooleanVar(root, False)
        self.scale = tk.StringVar(root, "1.0")
        self.input_device = tk.StringVar(root, self.tr("default_device"))
        self.output_device = tk.StringVar(root, self.tr("default_device"))
        self.ptt_port = tk.StringVar(root, "")
        self.ptt_line = tk.StringVar(root, "rts")
        self.frequency = tk.StringVar(root, "0")
        self.device_ids = {self.tr("default_device"): None}
        self._devices = []
        self.status = tk.StringVar(root)
        self.block_status = tk.StringVar(root)
        self.radio_status = tk.StringVar(root)
        self._status_message = ("ready", {})
        self.activity = "idle"
        self._bindings = []
        self._idle_buttons = []
        self._build()
        self._restore_audio(stored.get("audio", {}))
        if self.tx_image is not None:
            self.tx_preview.show(self.tx_image)
        self._render_messages()
        self._translate_widgets()
        if storage_error:
            self._set_status("library_error")
        self._sync_controls()
        self._poll_after = root.after(80, self._poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def tr(self, key, **values):
        return translate(self.language, key, **values)

    def _label(self, parent, key, **options):
        widget = tk.Label(parent, text=self.tr(key), bg=parent.cget("bg"), fg=theme.TEXT,
                          font=(self.sans, 10), **options)
        self._bindings.append((widget, key))
        return widget

    def _button(self, parent, key, command, *, style="TButton", idle=False):
        widget = ttk.Button(parent, text=self.tr(key), command=command, style=style)
        self._bindings.append((widget, key))
        if idle:
            self._idle_buttons.append(widget)
        return widget

    def _heading(self, parent, key):
        label = self._label(parent, key)
        label.configure(font=(self.sans, 12, "bold"))
        label.pack(anchor="w", pady=(0, 10))
        return label

    def _build(self):
        header = tk.Frame(self.root, bg=theme.BG, padx=22, pady=12)
        header.pack(fill="x")
        mark = tk.Label(header, image=self.robbie, bg=theme.BG, borderwidth=0)
        mark.pack(side="left", padx=(0, 12))
        brand = tk.Frame(header, bg=theme.BG)
        brand.pack(side="left")
        tk.Label(brand, text="Open KG-STV", bg=theme.BG, fg=theme.TEXT,
                 font=(self.sans, 21, "bold")).pack(anchor="w")
        subtitle = self._label(brand, "subtitle")
        subtitle.configure(fg=theme.MUTED, font=(self.sans, 9))
        subtitle.pack(anchor="w")
        languages = tk.Frame(header, bg=theme.BG)
        languages.pack(side="right")
        language_label = self._label(languages, "language")
        language_label.configure(fg=theme.MUTED, font=(self.sans, 9))
        language_label.pack(side="left", padx=(0, 9))
        self.language_buttons = {}
        for code in ("en", "de"):
            button = ttk.Button(languages, text=code.upper(), width=3,
                                command=lambda code=code:self.set_language(code))
            button.pack(side="left", padx=2)
            self.language_buttons[code] = button
        self._button(header, "beta", self.about).pack(side="right", padx=24)
        self.setup_button = ttk.Button(header, text="⚙", width=3, command=self.open_setup)
        self.setup_button.pack(side="right", padx=(12, 0))
        self._button(header, "log_qso", self.open_logbook, style="Receive.TButton").pack(side="right")

        # The footer remains reachable when a small window scrolls the workspace.
        footer = tk.Frame(self.root, bg=theme.BG, padx=22, pady=12)
        footer.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.pack(fill="x", pady=(0, 10))
        status_row = tk.Frame(footer, bg=theme.BG)
        status_row.pack(fill="x")
        self.activity_label = tk.Label(status_row, bg=theme.BG, fg=theme.GREEN,
                                       font=(self.mono, 9, "bold"), anchor="w", width=17)
        self.activity_label.pack(side="left")
        self.stop_button = self._button(status_row, "stop", self.stop, style="Stop.TButton")
        self.stop_button.pack(side="right", padx=(8, 0))
        self.start_button = self._button(status_row, "start_rx", self.start_live,
                                          style="Receive.TButton", idle=True)
        self.start_button.pack(side="right")
        status_label = tk.Label(status_row, textvariable=self.status, bg=theme.BG,
                               fg=theme.MUTED, anchor="w", justify="left", font=(self.sans, 9))
        status_label.pack(side="left", fill="x", expand=True, padx=(0, 12))
        status_label.bind("<Configure>", lambda event:status_label.configure(wraplength=max(1, event.width)))

        viewport = self.viewport = tk.Frame(self.root, bg=theme.BG)
        viewport.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.canvas = tk.Canvas(viewport, bg=theme.BG, highlightthickness=0,
                                yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.canvas.yview)
        self.outer = tk.Frame(self.canvas, bg=theme.BG, padx=22)
        window = self.canvas.create_window(0, 0, window=self.outer, anchor="nw")
        self.outer.bind("<Configure>", lambda event:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event:self.canvas.itemconfigure(window, width=event.width))
        self.root.bind("<MouseWheel>", self._wheel, add="+")
        self.canvas.bind("<Button-4>", lambda event:self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda event:self.canvas.yview_scroll(3, "units"))
        self.setup_window = tk.Toplevel(self.root, bg=theme.BG)
        self.setup_window.withdraw()
        self.setup_window.geometry(f"960x{min(820, self.root.winfo_screenheight()-80)}")
        self.setup_window.minsize(900, 540)
        self.setup_window.protocol("WM_DELETE_WINDOW", self.close_setup)
        foot = tk.Frame(self.setup_window, bg=theme.BG, padx=18, pady=12)
        foot.pack(side="bottom", fill="x")
        self._button(foot, "setup_save", self.close_setup, style="Primary.TButton").pack(side="right")
        scroll = ttk.Scrollbar(self.setup_window)
        scroll.pack(side="right", fill="y")
        setup_canvas = tk.Canvas(self.setup_window, bg=theme.BG, highlightthickness=0, yscrollcommand=scroll.set)
        setup_canvas.pack(fill="both", expand=True)
        scroll.configure(command=setup_canvas.yview)
        setup_body = tk.Frame(setup_canvas, bg=theme.BG, padx=18, pady=16)
        setup_id = setup_canvas.create_window(0, 0, window=setup_body, anchor="nw")
        setup_body.bind("<Configure>", lambda e:setup_canvas.configure(scrollregion=setup_canvas.bbox("all")))
        setup_canvas.bind("<Configure>", lambda e:setup_canvas.itemconfigure(setup_id, width=e.width))
        self.setup_window.bind("<MouseWheel>", lambda e:setup_canvas.yview_scroll(-1 if e.delta>0 else 1, "units")
                               if not isinstance(e.widget, (ttk.Combobox, tk.Text)) else None)
        self.radio_panel = RadioPanel(self, setup_body, self.outer)
        self._build_audio(setup_body)
        self._build_workspace(self.outer)

    def _build_workspace(self, parent):
        controls = theme.Card(parent, padding=10)
        controls.pack(fill="x", pady=(0, 12))
        body = controls.body
        for column, key in ((0, "callsign"), (2, "modulation"), (5, "scale_short")):
            self._label(body, key).grid(row=0, column=column, sticky="w", padx=(0, 7))
        ttk.Entry(body, textvariable=self.callsign, width=12).grid(row=0, column=1, padx=(0, 16))
        ttk.Combobox(body, textvariable=self.mode, values=("MSK", "4L-FSK"), width=10,
                     state="readonly").grid(row=0, column=3, padx=(0, 16))
        check = ttk.Checkbutton(body, variable=self.fec, text=self.tr("fec"))
        check.grid(row=0, column=4, padx=(0, 16))
        self._bindings.append((check, "fec"))
        ttk.Combobox(body, textvariable=self.scale, values=[str(x) for x in SCALES], width=8,
                     state="readonly").grid(row=0, column=6)
        panels = tk.Frame(parent, bg=theme.BG)
        panels.pack(fill="x", pady=(0, 12))
        panels.columnconfigure((0, 1), weight=1, uniform="images")
        tx, rx = theme.Card(panels), theme.Card(panels)
        tx.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        rx.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        tx_header = tk.Frame(tx.body, bg=theme.PANEL)
        tx_header.pack(fill="x")
        self._heading(tx_header, "transmit").pack_configure(side="left")
        self._button(tx_header, "edit_image", self.open_editor, style="Link.TButton").pack(side="right")
        rx_header = tk.Frame(rx.body, bg=theme.PANEL)
        rx_header.pack(fill="x")
        self._heading(rx_header, "receive").pack_configure(side="left")
        self.block_badge = tk.Label(rx_header, bg=theme.PANEL, fg=theme.DIM, font=(self.mono, 10))
        self.block_badge.pack(side="right")
        self.tx_preview = theme.ImagePreview(tx.body, self.sans, height=160)
        self.tx_preview.pack(fill="x")
        self.rx_preview = theme.ImagePreview(rx.body, self.sans, height=160)
        self.rx_preview.pack(fill="x")
        self.tx_caption = tk.Label(tx.body, bg=theme.PANEL, fg=theme.MUTED, font=(self.sans, 9))
        self.tx_caption.pack(anchor="w", pady=(8, 10))
        tk.Label(rx.body, textvariable=self.block_status, bg=theme.PANEL, fg=theme.MUTED,
                 font=(self.sans, 9)).pack(anchor="w", pady=(8, 10))
        tx_buttons = tk.Frame(tx.body, bg=theme.PANEL)
        tx_buttons.pack(fill="x")
        self._button(tx_buttons, "open_image", self.open_image).pack(side="left")
        self.image_wav_button = self._button(tx_buttons, "save_wav", lambda:self.encode("image", False), idle=True)
        self.image_wav_button.pack(side="left", padx=6)
        self.image_send_button = self._button(tx_buttons, "send_image", lambda:self.encode("image", True),
                                               style="Primary.TButton", idle=True)
        self.image_send_button.pack(side="left")
        rx_buttons = tk.Frame(rx.body, bg=theme.PANEL)
        rx_buttons.pack(fill="x")
        self._button(rx_buttons, "open_recording", self.open_recording, idle=True).pack(side="left")
        self.save_image_button = self._button(rx_buttons, "save_image", self.save_image)
        self.save_image_button.pack(side="left", padx=6)
        tx_repair = tk.Frame(tx.body, bg=theme.PANEL)
        tx_repair.pack(fill="x", pady=(9, 0))
        rx_repair = tk.Frame(rx.body, bg=theme.PANEL)
        rx_repair.pack(fill="x", pady=(9, 0))
        self.repair_button = self._button(tx_repair, "repair_response", lambda:self.encode("repair", False),
                                           style="Link.TButton", idle=True)
        self.repair_button.pack(side="left")
        self._button(tx_repair, "gallery", self.open_gallery, style="Link.TButton").pack(side="right")
        self.bsr_button = self._button(rx_repair, "repair_request", lambda:self.encode("bsr", False),
                                        style="Link.TButton", idle=True)
        self.bsr_button.pack(side="left")
        for body in (rx_repair,):
            label = self._label(body, "experimental")
            label.configure(fg=theme.DIM, font=(self.sans, 8))
            label.pack(side="right")
        messages = theme.Card(self.root, padding=10)
        messages.pack(side="bottom", fill="x", padx=22, pady=(8, 0), before=self.viewport)
        message_header = tk.Frame(messages.body, bg=theme.PANEL)
        message_header.pack(fill="x")
        self._heading(message_header, "messages").pack_configure(side="left")
        self._button(message_header, "history_open", self.open_history, style="Link.TButton").pack(side="right")
        compose = tk.Frame(messages.body, bg=theme.PANEL)
        compose.pack(fill="x", pady=(0, 10))
        self._label(compose, "compose").pack(side="left", padx=(0, 10))
        self.text_send_button = self._button(compose, "send_text", lambda:self.encode("text", True),
                                              style="Primary.TButton", idle=True)
        self.text_send_button.pack(side="right")
        self._button(compose, "text_wav", lambda:self.encode("text", False), idle=True).pack(side="right", padx=6)
        self.message = ttk.Entry(compose)
        self.message.pack(side="left", fill="x", expand=True)
        log_frame = tk.Frame(messages.body, bg=theme.PANEL)
        log_frame.pack(fill="x")
        scroll = ttk.Scrollbar(log_frame)
        scroll.pack(side="right", fill="y")
        self.log = tk.Text(log_frame, height=7, wrap="word", state="disabled", font=(self.mono, 10),
                           bg=theme.WELL, fg=theme.TEXT, insertbackground=theme.TEXT, relief="flat",
                           highlightthickness=1, highlightbackground=theme.BORDER, padx=10, pady=8,
                           yscrollcommand=scroll.set)
        self.log.pack(fill="x", expand=True)
        scroll.configure(command=self.log.yview)
        self.log.tag_configure("TX", foreground=theme.BLUE)

    def _build_audio(self, parent):
        devices = theme.Card(parent)
        devices.pack(fill="x", pady=(0, 12))
        self._heading(devices.body, "audio_tab")
        grid = tk.Frame(devices.body, bg=theme.PANEL)
        grid.pack(fill="x")
        grid.columnconfigure((0, 1), weight=1, uniform="devices")
        for column, key, variable in ((0, "input", self.input_device), (1, "output", self.output_device)):
            self._label(grid, key).grid(row=0, column=column, sticky="w", pady=(0, 5))
            combo = ttk.Combobox(grid, textvariable=variable, values=(self.tr("default_device"),),
                                  state="readonly", width=20)
            combo.grid(row=1, column=column, sticky="ew", padx=(0, 12) if column == 0 else 0)
            setattr(self, key+"_combo", combo)
            hint = self._label(grid, key+"_hint", justify="left", anchor="w", wraplength=390)
            hint.configure(fg=theme.MUTED, font=(self.sans, 9))
            hint.grid(row=2, column=column, sticky="w", pady=(7, 16))
        self._button(devices.body, "refresh_devices", self.devices, idle=True).pack(anchor="w")
        hint = self._label(devices.body, "audio_hint")
        hint.configure(fg=theme.DIM, font=(self.sans, 9))
        hint.pack(anchor="w", pady=(12, 0))
        offset = theme.Card(parent)
        offset.pack(fill="x", pady=(0, 12))
        self._heading(offset.body, "frequency")
        ttk.Entry(offset.body, textvariable=self.frequency, width=12).pack(anchor="w")
        hint = self._label(offset.body, "frequency_hint")
        hint.configure(fg=theme.MUTED)
        hint.pack(anchor="w", pady=(10, 0))
        ptt = theme.Card(parent)
        ptt.pack(fill="x")
        self._heading(ptt.body, "ptt")
        row = tk.Frame(ptt.body, bg=theme.PANEL)
        row.pack(anchor="w")
        self._label(row, "ptt_port").grid(row=0, column=0, sticky="w", pady=(0, 5))
        self._label(row, "ptt_line").grid(row=0, column=1, sticky="w", pady=(0, 5))
        ttk.Entry(row, textvariable=self.ptt_port, width=20).grid(row=1, column=0, padx=(0, 16))
        ttk.Combobox(row, textvariable=self.ptt_line, values=("rts", "dtr"), width=8,
                     state="readonly").grid(row=1, column=1)
        hint = self._label(ptt.body, "ptt_hint")
        hint.configure(fg=theme.MUTED)
        hint.pack(anchor="w", pady=(12, 0))

    def _wheel(self, event):
        if isinstance(event.widget, (tk.Text, ttk.Combobox)):
            return
        if self.outer.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def open_setup(self):
        self.setup_window.deiconify()
        self.setup_window.lift()

    def _restore_audio(self, stored):
        if not isinstance(stored, dict):
            return
        for key in ("ptt_port", "ptt_line", "frequency"):
            value = stored.get(key)
            if isinstance(value, str):
                getattr(self, key).set(value)
        # PortAudio accepts stable device-name substrings as well as indexes.
        for key in ("input", "output"):
            name = stored.get(key)
            if isinstance(name, str) and name:
                self.device_ids[name] = name
                getattr(self, key+"_device").set(name)
                getattr(self, key+"_combo").configure(values=(self.tr("default_device"), name))

    def save_operating_settings(self):
        def device_name(variable):
            value = self.device_ids.get(variable.get())
            if isinstance(value, int) and 0 <= value < len(self._devices):
                return self._devices[value]["name"]
            return value if isinstance(value, str) else ""
        save_settings(self.settings_path, {"callsign":self.callsign.get().strip(), "audio":{
            "input":device_name(self.input_device), "output":device_name(self.output_device),
            "ptt_port":self.ptt_port.get(), "ptt_line":self.ptt_line.get(), "frequency":self.frequency.get()}})

    def close_setup(self):
        if not self.radio_panel.save():
            return
        try:
            self.save_operating_settings()
        except OSError as exc:
            self._error("preference_error", exc)
            return
        self.setup_window.withdraw()

    def open_logbook(self):
        from .logbook_gui import QsoWindow
        existing = next((w for w in self.studio_windows if isinstance(w, QsoWindow)), None)
        if existing:
            existing.window.lift()
            return existing
        return QsoWindow(self)

    def set_language(self, language, *, persist=True):
        if language not in TRANSLATIONS:
            raise ValueError("Unsupported interface language")
        selected = (self.device_ids.get(self.input_device.get()), self.device_ids.get(self.output_device.get()))
        self.language = language
        self._refresh_device_labels(selected)
        self._translate_widgets()
        if persist:
            try:
                save_language(self.settings_path, language)
            except OSError:
                self._set_status("preference_error")

    def _translate_widgets(self):
        for widget, key in self._bindings:
            widget.configure(text=self.tr(key))
        for code, button in self.language_buttons.items():
            button.configure(style="Receive.TButton" if code == self.language else "TButton")
        self.tx_preview.placeholder(self.tr("tx_empty"), self.tr("tx_hint"))
        self.rx_preview.placeholder(self.tr("rx_empty"), self.tr("rx_hint"))
        self._image_labels()
        self._set_status(*self._status_message)
        self._set_activity(self.activity)
        self.radio_panel.refresh_labels()
        self.setup_window.title(self.tr("setup_title"))
        for window in list(self.studio_windows):
            window.translate()

    def _image_labels(self):
        self.tx_caption.configure(text=self.tr("image_ready" if self.tx_image is not None else "no_image"))
        if self.rx_summary:
            summary = self.rx_summary
            missing = len(summary["missing"])
            self.block_badge.configure(text=self.tr("blocks", good=summary["good_blocks"]),
                                        fg=theme.AMBER if missing else theme.GREEN)
            station = summary["callsign"] or self.tr("unknown")
            state = self.tr("missing", count=missing) if missing else self.tr("complete")
            self.block_status.set(f"{station} · {state}")
        else:
            self.block_badge.configure(text="—", fg=theme.DIM)
            self.block_status.set(self.tr("no_received_image"))

    def _set_status(self, key, values=None):
        self._status_message = (key, values or {})
        self.status.set(self.tr(key, **(values or {})))

    def _post_status(self, key, **values):
        self.events.put(("status", (key, values)))

    def _set_activity(self, activity):
        self.activity = activity
        color = {"idle":theme.GREEN, "working":theme.AMBER, "rx":theme.BLUE,
                 "tx":theme.TINT, "stopping":theme.AMBER}[activity]
        self.activity_label.configure(text="● "+self.tr(activity), fg=color)

    def _sync_controls(self):
        idle = not self.busy and self.live is None
        for button in self._idle_buttons:
            button.state(["!disabled" if idle else "disabled"])
        for button in (self.image_wav_button, self.image_send_button):
            button.state(["!disabled" if idle and self.tx_image is not None else "disabled"])
        self.save_image_button.state(["!disabled" if self.rx_image is not None else "disabled"])
        self.bsr_button.state(["!disabled" if idle and self.rx_summary and self.rx_summary["missing"] else "disabled"])
        self.repair_button.state(["!disabled" if idle and self.tx_image is not None and self.requested_blocks else "disabled"])
        self.stop_button.state(["disabled" if idle else "!disabled"])
        if hasattr(self, "radio_panel"):
            radio = self.radio_panel
            if radio.busy or (radio.ptt_method.get() == "hamlib" and (not radio.connected or radio.release_failed)):
                for button in (self.image_send_button, self.text_send_button):
                    button.state(["disabled"])
            radio.sync()

    def about(self):
        messagebox.showinfo(self.tr("about_title"), self.tr("about", version=__version__), parent=self.root)

    def _error(self, key, detail=None):
        text = self.tr(key)
        if detail:
            text += "\n\n"+str(detail)
        messagebox.showerror(self.tr("error_title"), text, parent=self.root)

    def _is_active(self):
        if self.busy or self.live is not None:
            messagebox.showinfo(self.tr("busy_title"), self.tr("busy"), parent=self.root)
            return True
        return False

    def _show(self, preview, image):
        preview.show(image)
        self._image_labels()
        self._sync_controls()

    def open_image(self):
        path = filedialog.askopenfilename(parent=self.root, title=self.tr("open_image"),
                    filetypes=[(self.tr("images_filter"), "*.png *.jpg *.jpeg *.bmp *.gif"), (self.tr("all_filter"), "*.*")])
        if path:
            try:
                self.set_tx_document(Document.from_image(load_image(path), Path(path).stem))
                self._set_status("image_opened", {"name":Path(path).name})
            except Exception as exc:
                self._error("open_image_error", exc)

    def set_tx_document(self, document, context=None):
        context = context or self.tx_context
        rendered = document.render(context)
        if self.library:
            self.library.save_draft(document, context)
        self.tx_document, self.tx_context = document.clone(), dict(context)
        self.tx_image = rendered
        self._show(self.tx_preview, rendered)

    def open_editor(self, document=None):
        from .editor_gui import ImageEditor
        if document is None:
            existing = next((w for w in self.studio_windows if isinstance(w, ImageEditor)), None)
            if existing:
                existing.window.deiconify()
                existing.window.lift()
                return existing
        return ImageEditor(self, document)

    def open_gallery(self):
        if self.library:
            return GalleryWindow(self)
        self._error("library_error")

    def open_history(self):
        if self.library:
            existing = next((w for w in self.studio_windows if isinstance(w, HistoryWindow)), None)
            if existing:
                existing.window.lift()
                return existing
            return HistoryWindow(self)
        self._error("library_error")

    def refresh_library_windows(self):
        for window in list(self.studio_windows):
            if isinstance(window, GalleryWindow):
                window.refresh()

    def _render_messages(self):
        position = self.log.yview()
        following = not self.log.get("1.0", "end-1c") or not position or position[1] >= .99
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        for item in self._recent_messages:
            self.log.insert("end", message_line(item), item["direction"])
        self.log.configure(state="disabled")
        if following:
            self.log.see("end")
        elif position:
            self.log.yview_moveto(position[0])

    def _record_message(self, text, direction="RX"):
        item = dict(text=text, direction=direction, created=utc_now())
        try:
            if self.library:
                item = self.library.add_message(text, direction)
        except STORAGE_ERRORS:
            self._set_status("library_error")
        self._recent_messages.append(item)
        self._recent_messages = self._recent_messages[-200:]
        self._render_messages()
        for window in list(self.studio_windows):
            if isinstance(window, HistoryWindow):
                window.refresh()

    def _archive_image(self, image, summary, kind):
        if not self.library:
            return
        call = summary.get("callsign", "") or self.tr("unknown")
        name = self.tr("rx_archive", call=call, blocks=summary.get("good_blocks", 0)) if kind == "rx" else self.tr("tx_archive", call=call)
        try:
            self.library.add_image(name, image, kind=kind, metadata=summary)
            self.refresh_library_windows()
        except STORAGE_ERRORS:
            self._set_status("library_error")

    def save_image(self):
        if self.rx_image is None:
            self._error("missing_received")
            return
        path = filedialog.asksaveasfilename(parent=self.root, title=self.tr("save_image"),
                                             defaultextension=".png", filetypes=[("PNG", "*.png")])
        if path:
            try:
                self.rx_image.save(path)
                self._set_status("image_saved", {"path":path})
            except OSError as exc:
                self._error("save_image_error", exc)

    def _worker(self, work, error_key="error_title"):
        if self._is_active():
            return
        self.busy = True
        self.cancelled.clear()
        self.progress["value"] = 0
        self._set_status("processing")
        self._set_activity("working")
        self._sync_controls()
        def run():
            try:
                work()
            except PTTReleaseError as exc:
                self.events.put(("radio_release_error", str(exc)))
            except Exception as exc:
                if not self.cancelled.is_set():
                    self.events.put(("error", (error_key, str(exc))))
            finally:
                self.events.put(("done", None))
        self.worker_thread = threading.Thread(target=run, daemon=True)
        self.worker_thread.start()

    def _on_frame(self, frame, session):
        if frame.header.com == 0 and frame.crc_ok:
            self.events.put(("text", frame.text()))
        if frame.header.com == 4:
            self.events.put(("request", sorted(session.requested)))
        im = session.current_image
        now = time.monotonic()
        if im is not None and (now-self.last_preview > .15 or im.finished):
            self.last_preview = now
            self.events.put(("image", (im.pixels.copy(), im.summary())))
        if im is not None and frame.header.com in (3, 5) and im.finished and im.good.any():
            signature = (int(im.good.sum()), im.aborted, im.codec_errors)
            if self._archived_rx is None or self._archived_rx[0] is not im or self._archived_rx[1] != signature:
                self._archived_rx = (im, signature)
                self.events.put(("archive_rx", (im.pixels.copy(), im.summary())))

    def _frequency(self):
        try:
            value = float(self.frequency.get().replace(",", "."))
            if not math.isfinite(value) or abs(value) > 500:
                raise ValueError
            return value
        except ValueError:
            self._error("invalid_frequency")
            return None

    def open_recording(self):
        if self._is_active():
            return
        frequency = self._frequency()
        if frequency is None:
            return
        path = filedialog.askopenfilename(parent=self.root, title=self.tr("open_recording"),
            filetypes=[(self.tr("audio_filter"), "*.wav *.mp3 *.flac *.ogg"), (self.tr("all_filter"), "*.*")])
        if not path:
            return
        directory = filedialog.askdirectory(parent=self.root, title=self.tr("output_directory"))
        if not directory:
            return
        output = Path(directory)/(Path(path).stem+"-decoded")
        if output.exists() and any(output.iterdir()):
            self._error("directory_not_empty")
            return
        def work():
            result = decode_file(path, output, frequency_offset=frequency, on_frame=self._on_frame,
                                 progress=lambda p:self.events.put(("progress", p*100)),
                                 cancelled=self.cancelled.is_set)
            self._post_status("decoded", count=result["stats"]["headers"], path=str(output))
        self._worker(work, "decode_error")

    def encode(self, kind, play):
        if self._is_active():
            return
        call = self.callsign.get().strip()
        if not call:
            self._error("missing_call")
            return
        if any(char in call for char in "\r\n>"):
            self._error("invalid_call")
            return
        if kind in ("image", "repair") and self.tx_image is None:
            self._error("missing_image")
            return
        if kind == "bsr" and (self.rx_summary is None or not self.rx_summary["missing"]):
            self._error("no_missing_blocks")
            return
        if kind == "repair" and not self.requested_blocks:
            self._error("no_request")
            return
        mode, fec = int(self.mode.get() == "4L-FSK"), self.fec.get()
        index = SCALES.index(float(self.scale.get()))
        message, image = self.message.get(), self.tx_image
        try:
            # Validate before a save dialog or any hardware access.
            text_frame(message if kind == "text" else "", callsign=call, mode=mode, fec=fec)
        except (ValueError, UnicodeError):
            self._error("invalid_text")
            return
        path = None
        if not play:
            path = filedialog.asksaveasfilename(parent=self.root, title=self.tr("save_wav_title"),
                                                defaultextension=".wav", filetypes=[("WAV", "*.wav")])
            if not path:
                return
        missing = list(self.rx_summary["missing"]) if self.rx_summary else []
        requested = list(self.requested_blocks)
        device = self.device_ids[self.output_device.get()]
        port, line = self.ptt_port.get().strip(), self.ptt_line.get()
        transmit_options = {}
        radio = None
        if play:
            try:
                transmit_options = self.radio_panel.transmit_options()
                if "ptt" in transmit_options:
                    radio = self.radio_panel.session
                    port = ""
            except ValueError as exc:
                self._error("radio_config_error", exc)
                return
        def work():
            if kind in ("image", "repair"):
                frames = image_frames(image, call, mode=mode, fec=fec, scale_index=index,
                                      repair=kind == "repair", blocks=requested if kind == "repair" else None)
            elif kind == "bsr":
                frames = request_frames(missing, call)
            else:
                frames = [text_frame(message, callsign=call, mode=mode, fec=fec)]
            audio = modulate(frames)
            if self.cancelled.is_set():
                return
            if play:
                from .live import play_audio
                self.events.put(("activity", "tx"))
                self._post_status("transmitting", seconds=len(audio)/48000)
                play_audio(audio, device=device, port=port or None, ptt_line=line,
                           cancelled=lambda:self.cancelled.is_set() or (radio is not None and not radio.connected),
                           **transmit_options)
                if not self.cancelled.is_set() and (radio is None or radio.connected):
                    if kind == "text":
                        self.events.put(("sent_text", call+">"+message))
                    elif kind == "image":
                        self.events.put(("archive_tx", (image.copy(), {"callsign":call})))
                    self._post_status("transmitted")
            else:
                save_wav(path, audio)
                self._post_status("wav_saved", seconds=len(audio)/48000, path=path)
            self.events.put(("progress", 100))
        self._worker(work, "encode_error")

    def _refresh_device_labels(self, selected):
        default = self.tr("default_device")
        self.device_ids = {default:None}
        inputs, outputs = [default], [default]
        for n, dev in enumerate(self._devices):
            name = f"{n}: {dev['name']}"
            self.device_ids[name] = n
            if dev["max_input_channels"]:
                inputs.append(name)
            if dev["max_output_channels"]:
                outputs.append(name)
        for combo, variable, names, index in ((self.input_combo, self.input_device, inputs, selected[0]),
                                               (self.output_combo, self.output_device, outputs, selected[1])):
            if isinstance(index, str):
                matching = next((name for name in names if name.endswith(": "+index)), None)
                if matching:
                    index = self.device_ids[matching]
                else:
                    names.append(index)
                    self.device_ids[index] = index
            combo.configure(values=names)
            variable.set(next((name for name in names if self.device_ids[name] == index), default))

    def devices(self):
        if self._is_active():
            return
        try:
            import sounddevice as sd
            selected = (self.device_ids.get(self.input_device.get()), self.device_ids.get(self.output_device.get()))
            self._devices = sd.query_devices()
            self._refresh_device_labels(selected)
            self._set_status("devices_loaded", {"inputs":len(self.input_combo["values"])-1,
                                                  "outputs":len(self.output_combo["values"])-1})
        except Exception as exc:
            self._error("audio_error", exc)

    def start_live(self):
        if self._is_active():
            return
        frequency = self._frequency()
        if frequency is None:
            return
        try:
            from .live import LiveReceiver
            def callback(event, data):
                if event == "frame":
                    self._on_frame(*data)
                elif event == "status":
                    self._post_status(data)
                elif event == "error":
                    self.events.put(("error", ("audio_error", str(data))))
                else:
                    self.events.put((event, data))
            self.live = LiveReceiver(callback, device=self.device_ids[self.input_device.get()], frequency_offset=frequency)
            self._set_status("starting_rx")
            self._set_activity("rx")
            self.live.start()
            self._sync_controls()
        except Exception as exc:
            self.live = None
            self._set_activity("idle")
            self._sync_controls()
            self._error("audio_error", exc)

    def stop(self):
        if not self.busy and self.live is None:
            return
        self.cancelled.set()
        if self.live is not None:
            self.live.stop()
        if self.activity == "tx":
            from .live import stop_playback
            try:
                stop_playback()
            except Exception as exc:
                # The worker still owns PTT cleanup; never interrupt window shutdown.
                self.events.put(("error", ("audio_error", str(exc))))
        self._set_activity("stopping")

    def _poll(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "done":
                    self.busy = False
                    if self.radio_panel.release_failed:
                        self._set_status("radio_release_error")
                    elif self.cancelled.is_set():
                        self._set_status("stopped")
                    self._set_activity("idle")
                elif event == "stopped":
                    self.live = None
                    self._set_activity("idle")
                elif event == "progress":
                    self.progress["value"] = data
                elif event == "status":
                    self._set_status(*data)
                elif event == "activity":
                    self._set_activity(data)
                elif event == "error":
                    self._set_status(data[0])
                    if not self.closing:
                        self._error(*data)
                elif event == "text":
                    self._record_message(data)
                elif event == "sent_text":
                    self._record_message(data, "TX")
                elif event in ("archive_rx", "archive_tx"):
                    source, summary = data
                    self._archive_image(Image.fromarray(source) if event == "archive_rx" else source,
                                        summary, "rx" if event == "archive_rx" else "tx")
                elif event == "request":
                    self.requested_blocks = data
                    self._set_status("requested", {"count":len(data)})
                elif event == "image":
                    pixels, self.rx_summary = data
                    self.rx_image = Image.fromarray(pixels)
                    self._show(self.rx_preview, self.rx_image)
                elif event.startswith("radio_"):
                    self.radio_panel.handle(event, data)
        except queue.Empty:
            pass
        self._sync_controls()
        self._poll_after = self.root.after(80, self._poll)

    def close(self):
        if self.closing:
            return
        for window in list(self.studio_windows):
            window.close()
            if window in self.studio_windows:
                return
        try:
            self.save_operating_settings()
        except OSError as exc:
            self._error("preference_error", exc)
            return
        self.closing = True
        self.stop()
        self.setup_window.withdraw()
        self.radio_panel.tuning_window.withdraw()
        self.root.withdraw()
        def wait_for_cleanup():
            if not self.closing:
                return
            running = self.worker_thread and self.worker_thread.is_alive()
            listening = self.live and self.live.thread and self.live.thread.is_alive()
            if running or listening or self.radio_panel.busy:
                self.root.after(50, wait_for_cleanup)
            elif self.radio_panel.session:
                self.radio_panel.begin_shutdown()
                self.root.after(50, wait_for_cleanup)
            else:
                self.root.after_cancel(self._poll_after)
                self.root.destroy()
        wait_for_cleanup()


def main():
    root = tk.Tk()
    Application(root)
    root.mainloop()


if __name__ == "__main__":
    main()
