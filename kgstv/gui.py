"""Bilingual Tk desktop client. Only the UI thread touches Tk."""
import math
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image
from . import __version__, theme
from .audio import save_wav
from .cli import decode_file
from .i18n import TRANSLATIONS, load_language, save_language, settings_file, translate
from .imagecodec import prepare_image
from .modem import modulate
from .protocol import SCALES, text_frame
from .session import image_frames, request_frames


class Application:
    def __init__(self, root, *, settings_path=None, language=None):
        self.root = root
        root.title("Open KG-STV")
        root.geometry(f"1120x{min(900, root.winfo_screenheight()-60)}")
        root.minsize(940, 640)
        self.settings_path = Path(settings_path) if settings_path is not None else settings_file()
        self.language = language or load_language(self.settings_path)
        if self.language not in TRANSLATIONS:
            raise ValueError("Unsupported interface language")
        self.sans, self.mono = theme.setup(root)
        self.events = queue.Queue()
        self.busy = self.closing = False
        self.worker_thread = None
        self.cancelled = threading.Event()
        self.live = None
        self.tx_image = self.rx_image = self.rx_summary = None
        self.requested_blocks = []
        self.last_preview = 0
        self.callsign = tk.StringVar(root, "")
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
        self._status_message = ("ready", {})
        self.activity = "idle"
        self._bindings = []
        self._idle_buttons = []
        self.page = "workspace"
        self._build()
        self._translate_widgets()
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
        mark = tk.Canvas(header, width=44, height=44, bg=theme.BG, highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        theme.rounded(mark, 0, 0, 44, 44, 10, fill=theme.CRIMSON, outline="")
        mark.create_line(7, 23, 13, 23, 17, 11, 22, 34, 28, 16, 32, 23, 37, 23,
                         fill=theme.TEXT, width=2)
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

        navigation = tk.Frame(self.root, bg=theme.BG, padx=22)
        navigation.pack(fill="x", pady=(0, 12))
        self.nav_buttons = {}
        for page in ("workspace", "audio_tab"):
            button = self._button(navigation, page, lambda page=page:self.show_page(page))
            button.pack(side="left", padx=(0, 8))
            self.nav_buttons[page] = button
        self._button(navigation, "compatibility", self.about, style="Link.TButton").pack(side="right")

        viewport = tk.Frame(self.root, bg=theme.BG)
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
        self.pages = {key:tk.Frame(self.outer, bg=theme.BG) for key in ("workspace", "audio_tab")}
        self._build_workspace(self.pages["workspace"])
        self._build_audio(self.pages["audio_tab"])
        self.show_page("workspace")

    def _build_workspace(self, parent):
        controls = theme.Card(parent)
        controls.pack(fill="x", pady=(0, 12))
        body = controls.body
        for column, key in ((0, "callsign"), (1, "modulation"), (3, "scale")):
            self._label(body, key).grid(row=0, column=column, sticky="w", pady=(0, 4))
        ttk.Entry(body, textvariable=self.callsign, width=16).grid(row=1, column=0, padx=(0, 16))
        ttk.Combobox(body, textvariable=self.mode, values=("MSK", "4L-FSK"), width=10,
                     state="readonly").grid(row=1, column=1, padx=(0, 16))
        check = ttk.Checkbutton(body, variable=self.fec, text=self.tr("fec"))
        check.grid(row=1, column=2, padx=(0, 20))
        self._bindings.append((check, "fec"))
        ttk.Combobox(body, textvariable=self.scale, values=[str(x) for x in SCALES], width=8,
                     state="readonly").grid(row=1, column=3)
        body.columnconfigure(4, weight=1)
        label = self._label(body, "format")
        label.configure(fg=theme.DIM, font=(self.mono, 9))
        label.grid(row=1, column=4, sticky="e", padx=(12, 0))
        panels = tk.Frame(parent, bg=theme.BG)
        panels.pack(fill="x", pady=(0, 12))
        panels.columnconfigure((0, 1), weight=1, uniform="images")
        tx, rx = theme.Card(panels), theme.Card(panels)
        tx.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        rx.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._heading(tx.body, "transmit")
        rx_header = tk.Frame(rx.body, bg=theme.PANEL)
        rx_header.pack(fill="x")
        self._heading(rx_header, "receive").pack_configure(side="left")
        self.block_badge = tk.Label(rx_header, bg=theme.PANEL, fg=theme.DIM, font=(self.mono, 10))
        self.block_badge.pack(side="right")
        self.tx_preview = theme.ImagePreview(tx.body, self.sans)
        self.tx_preview.pack(fill="x")
        self.rx_preview = theme.ImagePreview(rx.body, self.sans)
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
        self.bsr_button = self._button(rx_repair, "repair_request", lambda:self.encode("bsr", False),
                                        style="Link.TButton", idle=True)
        self.bsr_button.pack(side="left")
        for body in (tx_repair, rx_repair):
            label = self._label(body, "experimental")
            label.configure(fg=theme.DIM, font=(self.sans, 8))
            label.pack(side="right")
        messages = theme.Card(parent)
        messages.pack(fill="x", pady=(0, 2))
        self._heading(messages.body, "messages")
        compose = tk.Frame(messages.body, bg=theme.PANEL)
        compose.pack(fill="x", pady=(0, 10))
        self._label(compose, "compose").pack(side="left", padx=(0, 10))
        self._button(compose, "send_text", lambda:self.encode("text", True),
                     style="Primary.TButton", idle=True).pack(side="right")
        self._button(compose, "text_wav", lambda:self.encode("text", False), idle=True).pack(side="right", padx=6)
        self.message = ttk.Entry(compose)
        self.message.pack(side="left", fill="x", expand=True)
        self.log = tk.Text(messages.body, height=3, wrap="word", state="disabled", font=(self.mono, 10),
                           bg=theme.WELL, fg=theme.TEXT, insertbackground=theme.TEXT, relief="flat",
                           highlightthickness=1, highlightbackground=theme.BORDER, padx=10, pady=8)
        self.log.pack(fill="x")

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

    def show_page(self, page):
        self.pages[self.page].pack_forget()
        self.page = page
        self.pages[page].pack(fill="x")
        for key, button in self.nav_buttons.items():
            button.configure(style="Receive.TButton" if key == page else "TButton")
        self.canvas.yview_moveto(0)

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
                self.tx_image = prepare_image(path)
                self._show(self.tx_preview, self.tx_image)
                self._set_status("image_opened", {"name":Path(path).name})
            except Exception as exc:
                self._error("open_image_error", exc)

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
                play_audio(audio, device=device, port=port or None, ptt_line=line, cancelled=self.cancelled.is_set)
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
            stop_playback()
        self._set_activity("stopping")

    def _poll(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "done":
                    self.busy = False
                    if self.cancelled.is_set():
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
                    self.log.configure(state="normal")
                    self.log.insert("end", data+"\n")
                    self.log.see("end-2c")
                    self.log.configure(state="disabled")
                elif event == "request":
                    self.requested_blocks = data
                    self._set_status("requested", {"count":len(data)})
                elif event == "image":
                    pixels, self.rx_summary = data
                    self.rx_image = Image.fromarray(pixels)
                    self._show(self.rx_preview, self.rx_image)
        except queue.Empty:
            pass
        self._sync_controls()
        self._poll_after = self.root.after(80, self._poll)

    def close(self):
        self.closing = True
        self.stop()
        self.root.withdraw()
        def wait_for_cleanup():
            running = self.worker_thread and self.worker_thread.is_alive()
            listening = self.live and self.live.thread and self.live.thread.is_alive()
            if running or listening:
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
