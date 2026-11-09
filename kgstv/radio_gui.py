"""Radio settings and background Hamlib operations for the Tk client."""
from dataclasses import asdict
import math
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from . import theme
from .hamlib import RadioConfig, RadioSession, PTTReleaseError, find_rigctld, list_models
from .i18n import load_settings, save_settings
from .activity import ACTIVITIES


class RadioPanel:
    def __init__(self, app, parent, operating_parent):
        self.app = app
        self.session = None
        self.busy = False
        self.thread = None
        self.generation = 0
        self.state = None
        self.release_failed = False
        self._connection_widgets = []
        self._local_widgets = []
        self._network_widgets = []
        stored = load_settings(app.settings_path).get("radio", {})
        if not isinstance(stored, dict):
            stored = {}
        defaults = asdict(RadioConfig(executable=find_rigctld()))
        defaults.update(ptt_method="serial", lead_ms="200", tail_ms="100")
        for key, value in defaults.items():
            saved = stored.get(key, value)
            if not isinstance(saved, (str, int)):
                saved = value
            setattr(self, key, tk.StringVar(app.root, str(saved)))
        if self.connection.get() not in ("local", "network"):
            self.connection.set("local")
        if self.ptt_method.get() not in ("serial", "hamlib"):
            self.ptt_method.set("serial")
        self.target_frequency = tk.StringVar(app.root, "")
        self.target_mode = tk.StringVar(app.root, "PKTUSB")
        self.bandwidth = tk.StringVar(app.root, "0")
        self.readback = tk.StringVar(app.root, "— MHz")
        self.mode_readback = tk.StringVar(app.root, "—")
        self.activity_index = None
        self.activity_label = tk.StringVar(app.root, app.tr("activity_choose"))
        self.activity_note = tk.StringVar(app.root, "")
        self.satellite_dial = tk.StringVar(app.root, "")
        self.last_activity = None
        self._activity_language = None
        self._build(parent, operating_parent)
        self.connection.trace_add("write", lambda *_:self.sync())
        self.ptt_method.trace_add("write", lambda *_:app._sync_controls())

    @property
    def connected(self):
        return self.session is not None and self.session.connected

    def _field(self, parent, key, variable, row, column, *, width=16, values=None, group=None):
        self.app._label(parent, key).grid(row=row, column=column, sticky="w", pady=(7, 4))
        widget = (ttk.Combobox(parent, textvariable=variable, values=values, width=width)
                  if values is not None else ttk.Entry(parent, textvariable=variable, width=width))
        widget.grid(row=row+1, column=column, sticky="ew", padx=(0, 12))
        if group is not None:
            group.append(widget)
        return widget

    def _radio(self, parent, key, variable, value):
        button = tk.Radiobutton(parent, text=self.app.tr(key), variable=variable, value=value,
                                bg=theme.PANEL, fg=theme.TEXT, selectcolor=theme.WELL,
                                activebackground=theme.PANEL, activeforeground=theme.TEXT,
                                font=(self.app.sans, 10), highlightthickness=0)
        self.app._bindings.append((button, key))
        return button

    def _build(self, parent, operating_parent):
        app = self.app
        status = theme.Card(operating_parent, padding=10)
        status.pack(fill="x", pady=(0, 12))
        row = tk.Frame(status.body, bg=theme.PANEL)
        row.pack(fill="x")
        tk.Label(row, textvariable=self.readback, bg=theme.PANEL, fg=theme.TEXT,
                 font=(app.mono, 18, "bold")).pack(side="left")
        tk.Label(row, textvariable=self.mode_readback, bg=theme.PANEL, fg=theme.BLUE,
                 font=(app.mono, 11)).pack(side="left", padx=18)
        self.disconnect_button = app._button(row, "radio_disconnect", self.disconnect)
        self.disconnect_button.pack(side="right", padx=(8, 0))
        self.connect_button = app._button(row, "radio_connect", self.connect, style="Receive.TButton")
        self.connect_button.pack(side="right")
        app._button(row, "tuning_open", self.open_tuning, style="Link.TButton").pack(side="right", padx=16)
        self.tuning_window = tk.Toplevel(app.root, bg=theme.PANEL)
        self.tuning_window.withdraw()
        self.tuning_window.geometry("850x190")
        self.tuning_window.minsize(800, 190)
        self.tuning_window.protocol("WM_DELETE_WINDOW", self.tuning_window.withdraw)
        controls = tk.Frame(self.tuning_window, bg=theme.PANEL, padx=18, pady=18)
        controls.pack(fill="x")
        self.freq_entry = self._field(controls, "radio_frequency", self.target_frequency, 0, 0, width=14)
        self.freq_button = app._button(controls, "radio_set_frequency", self.set_frequency)
        self.freq_button.grid(row=1, column=1, padx=(0, 20))
        self.mode_combo = self._field(controls, "radio_mode", self.target_mode, 0, 2, width=10,
                                      values=("PKTUSB", "USB", "PKTLSB", "LSB", "PKTFM", "FM", "AM"))
        self.width_entry = self._field(controls, "radio_bandwidth", self.bandwidth, 0, 3, width=8)
        self.mode_button = app._button(controls, "radio_set_mode", self.set_mode)
        self.mode_button.grid(row=1, column=4)
        app._label(self.tuning_window, "radio_control_hint", wraplength=800, justify="left").pack(anchor="w", padx=18)
        presets = tk.Frame(status.body, bg=theme.PANEL)
        presets.pack(fill="x", pady=(8, 0))
        app._label(presets, "activity_frequencies").pack(side="left", padx=(0, 10))
        self.activity_combo = ttk.Combobox(presets, textvariable=self.activity_label, state="readonly", width=42,
                                          values=[entry.label(app.language) for entry in ACTIVITIES])
        self.activity_combo.pack(side="left", fill="x", expand=True)
        self.activity_combo.bind("<<ComboboxSelected>>", self.select_activity)
        self.activity_tune = app._button(presets, "activity_tune", self.tune_activity, style="Receive.TButton")
        self.activity_tune.pack(side="left", padx=8)
        app._button(presets, "activity_details", self.activity_details).pack(side="left")
        self.satellite_row = tk.Frame(status.body, bg=theme.PANEL)
        app._label(self.satellite_row, "activity_sat_dial").pack(side="left", padx=(0, 10))
        self.satellite_entry = ttk.Entry(self.satellite_row, textvariable=self.satellite_dial, width=16)
        self.satellite_entry.pack(side="left")

        setup = theme.Card(parent)
        setup.pack(fill="x", pady=(0, 12))
        app._heading(setup.body, "radio_connection")
        choices = tk.Frame(setup.body, bg=theme.PANEL)
        choices.pack(fill="x")
        for key, value in (("radio_local", "local"), ("radio_network", "network")):
            button = self._radio(choices, key, self.connection, value)
            button.pack(side="left", padx=(0, 14))
            self._connection_widgets.append(button)
        self.preset_button = app._button(choices, "radio_ic7610", self.preset)
        self.preset_button.pack(side="right")
        self._connection_widgets.append(self.preset_button)
        executable_row = tk.Frame(setup.body, bg=theme.PANEL)
        executable_row.pack(fill="x", pady=(10, 0))
        app._label(executable_row, "radio_executable").pack(side="left", padx=(0, 10))
        browse = app._button(executable_row, "radio_browse", self.browse)
        browse.pack(side="right")
        self.models_button = app._button(executable_row, "radio_models", self.models)
        self.models_button.pack(side="right", padx=8)
        exe = ttk.Entry(executable_row, textvariable=self.executable)
        exe.pack(side="left", fill="x", expand=True)
        self._local_widgets += [browse, self.models_button, exe]
        local = tk.Frame(setup.body, bg=theme.PANEL)
        local.pack(fill="x")
        local.columnconfigure((0, 1), weight=1)
        self.model_combo = self._field(local, "radio_model", self.model, 0, 0,
            values=("3078 · Icom IC-7610", "3073 · Icom IC-7300", "1 · Hamlib Dummy"), group=self._local_widgets)
        self.port_combo = self._field(local, "radio_cat_port", self.device, 0, 1,
                                      values=(), group=self._local_widgets)
        refresh = app._button(local, "radio_ports", self.ports)
        refresh.grid(row=1, column=2)
        self._local_widgets.append(refresh)
        options = tk.Frame(setup.body, bg=theme.PANEL)
        options.pack(fill="x")
        self._field(options, "radio_baud", self.baud, 0, 0, width=12,
                    values=("0", "9600", "19200", "38400", "57600", "115200"), group=self._local_widgets)
        self._field(options, "radio_civ", self.civ, 0, 1, width=10, group=self._local_widgets)
        self._field(options, "radio_host", self.host, 0, 2, width=22, group=self._network_widgets)
        self._field(options, "radio_tcp_port", self.port, 0, 3, width=8, group=self._network_widgets)
        self.save_button = app._button(setup.body, "radio_save", self.save)
        self.save_button.pack(anchor="w", pady=(12, 0))
        hint = app._label(setup.body, "radio_setup_hint", anchor="w", justify="left", wraplength=820)
        hint.configure(fg=theme.MUTED, font=(app.sans, 9))
        hint.pack(anchor="w", pady=(10, 0))

        ptt = theme.Card(parent)
        ptt.pack(fill="x", pady=(0, 2))
        app._heading(ptt.body, "radio_ptt")
        choices = tk.Frame(ptt.body, bg=theme.PANEL)
        choices.pack(fill="x")
        self.ptt_widgets = []
        for key, value in (("radio_ptt_serial", "serial"), ("radio_ptt_hamlib", "hamlib")):
            button = self._radio(choices, key, self.ptt_method, value)
            button.pack(side="left", padx=(0, 14))
            self.ptt_widgets.append(button)
        self.rx_button = app._button(choices, "radio_force_rx", self.force_rx, style="Stop.TButton")
        self.rx_button.pack(side="right")
        delay = tk.Frame(ptt.body, bg=theme.PANEL)
        delay.pack(fill="x")
        self.ptt_widgets += [self._field(delay, "radio_lead", self.lead_ms, 0, 0, width=10),
                             self._field(delay, "radio_tail", self.tail_ms, 0, 1, width=10)]
        hint = app._label(ptt.body, "radio_ptt_hint", anchor="w", justify="left", wraplength=820)
        hint.configure(fg=theme.MUTED, font=(app.sans, 9))
        hint.pack(anchor="w", pady=(10, 0))

    def config(self, *, validate=True):
        local = self.connection.get() == "local"
        model = self.model.get().split()
        if local and not model:
            raise ValueError(self.app.tr("radio_model"))
        config = RadioConfig(connection=self.connection.get(), executable=self.executable.get().strip(),
            model=int(model[0]) if local else 3078, device=self.device.get().strip(),
            baud=int(self.baud.get()) if local else 115200, civ=self.civ.get().strip(),
            host=self.host.get().strip(), port=4532 if local else int(self.port.get()))
        if validate:
            config.validate()
        return config

    def open_tuning(self):
        self.tuning_window.deiconify()
        self.tuning_window.lift()

    def delays(self):
        values = [float(value.get().replace(",", "."))/1000 for value in (self.lead_ms, self.tail_ms)]
        if any(not math.isfinite(value) or not 0 <= value <= 10 for value in values):
            raise ValueError(self.app.tr("radio_invalid_delay"))
        return values

    def save(self):
        try:
            config = self.config(validate=False)
            self.delays()
            save_settings(self.app.settings_path, {"radio":dict(asdict(config),
                ptt_method=self.ptt_method.get(), lead_ms=self.lead_ms.get(), tail_ms=self.tail_ms.get())})
            self.app._set_status("radio_saved")
            return True
        except (OSError, ValueError) as exc:
            self.app._error("radio_config_error", exc)
            return False

    def preset(self):
        self.connection.set("local")
        self.model.set("3078 · Icom IC-7610")
        self.baud.set("115200")
        self.civ.set("0x98")
        self.ptt_method.set("hamlib")
        self.target_mode.set("PKTUSB")
        self.app._set_status("radio_preset_loaded")

    def browse(self):
        path = filedialog.askopenfilename(parent=self.app.root, title=self.app.tr("radio_executable"))
        if path:
            self.executable.set(path)

    def _task(self, work, *, done="radio_done"):
        if self.busy:
            return
        self.busy = True
        self.sync()
        def run():
            try:
                result = work()
                self.app.events.put((done, result))
            except PTTReleaseError as exc:
                self.app.events.put(("radio_release_error", str(exc)))
            except Exception as exc:
                self.app.events.put(("radio_error", str(exc)))
            finally:
                self.app.events.put(("radio_task_done", None))
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def models(self):
        executable = self.executable.get().strip()
        self._task(lambda:list_models(executable), done="radio_models_ready")

    def ports(self):
        def read():
            from serial.tools import list_ports
            return [port.device for port in list_ports.comports()]
        self._task(read, done="radio_ports_ready")

    def connect(self):
        if self.busy or self.app.busy:
            return
        if self.session and self.session.ptt_may_be_on:
            self.app._error("radio_release_error")
            return
        if not self.save():
            return
        try:
            config = self.config()
        except ValueError as exc:
            self.app._error("radio_config_error", exc)
            return
        old = self.session
        self.generation += 1
        generation = self.generation
        self.session = RadioSession(lambda event, data:self.app.events.put((event, (generation, data))))
        session = self.session
        self.app._set_status("radio_connecting")
        def work():
            if old:
                old.close()
            session.connect(config)
        self._task(work, done="radio_connected")

    def disconnect(self):
        if self.busy or self.app.busy or self.session is None:
            return
        session = self.session
        self.generation += 1
        self._task(session.close, done="radio_disconnected")

    def set_frequency(self):
        if not self.connected or self.app.busy or self.busy:
            return
        try:
            value = float(self.target_frequency.get().replace(",", "."))*1_000_000
            if not math.isfinite(value) or not 0 < value <= 1e12:
                raise ValueError
        except ValueError:
            self.app._error("radio_invalid_frequency")
            return
        self._task(lambda:self.session.set_frequency(value))

    def select_activity(self, event=None):
        index = self.activity_combo.current()
        if index < 0:
            return
        self.activity_index = index
        entry = ACTIVITIES[index]
        self.activity_note.set(entry.note(self.app.language))
        if entry.satellite:
            self.satellite_row.pack(fill="x", pady=8)
        else:
            self.satellite_row.pack_forget()
            self.target_frequency.set(f"{entry.hz/1e6:.6f}")
        self.target_mode.set("PKTUSB")
        self.sync()

    def tune_activity(self):
        if self.activity_index is None or not self.connected or self.busy or self.app.busy:
            return
        entry = ACTIVITIES[self.activity_index]
        try:
            value = entry.dial_hz(self.satellite_dial.get())
        except ValueError:
            self.app._error("activity_sat_required")
            return
        self.target_frequency.set(f"{value/1e6:.6f}")
        self.target_mode.set("PKTUSB")
        session = self.session
        self._task(lambda:(session.tune(value, "PKTUSB"), (entry.id, value))[1], done="radio_activity_tuned")

    def activity_details(self):
        text = self.activity_note.get()+"\n\n"+self.app.tr("activity_hint")
        if self.activity_index is not None:
            text += "\n\n"+ACTIVITIES[self.activity_index].source
            if messagebox.askyesno(self.app.tr("activity_frequencies"), text+"\n\n"+self.app.tr("activity_open_source"), parent=self.app.root):
                self.activity_source()
        else:
            messagebox.showinfo(self.app.tr("activity_frequencies"), text.strip(), parent=self.app.root)

    def activity_source(self):
        if self.activity_index is not None:
            import webbrowser
            webbrowser.open(ACTIVITIES[self.activity_index].source)

    def set_mode(self):
        if not self.connected or self.app.busy or self.busy:
            return
        try:
            mode, width = self.target_mode.get().strip().upper(), int(self.bandwidth.get())
        except ValueError:
            self.app._error("radio_config_error")
            return
        self._task(lambda:self.session.set_mode(mode, width))

    def transmit_options(self):
        lead, tail = self.delays()
        if self.ptt_method.get() == "hamlib":
            if not self.connected or self.busy or self.release_failed:
                raise ValueError(self.app.tr("radio_not_connected"))
            return dict(ptt=self.session.ptt, lead=lead, tail=tail)
        return dict(lead=lead, tail=tail)

    def force_rx(self):
        if self.busy or self.session is None:
            return
        self.app.stop()
        self._task(self.session.release_ptt, done="radio_released")

    def handle(self, event, data):
        app = self.app
        if event in ("radio_state", "radio_lost"):
            generation, data = data
            if generation != self.generation:
                return
        if event == "radio_state":
            self.state = data
        elif event == "radio_lost":
            self.state = None
            if self.ptt_method.get() == "hamlib":
                app.stop()
            app._set_status("radio_connection_lost")
            if not app.closing:
                app._error("radio_connection_lost", data)
        elif event == "radio_connected":
            app._set_status("radio_ready")
            self.release_failed = False
        elif event == "radio_disconnected":
            self.session = None
            self.state = None
            app._set_status("radio_offline")
        elif event == "radio_released":
            self.release_failed = False
            app._set_status("radio_ptt_released")
        elif event == "radio_activity_tuned":
            self.last_activity = data
            app._set_status("activity_tuned")
        elif event == "radio_models_ready":
            self.model_combo.configure(values=[label for _, label in data])
            app._set_status("radio_models_loaded", {"count":len(data)})
        elif event == "radio_ports_ready":
            self.port_combo.configure(values=data)
            app._set_status("radio_ports_loaded", {"count":len(data)})
        elif event == "radio_error":
            app._set_status("radio_error")
            if not app.closing:
                app._error("radio_error", data)
        elif event == "radio_release_error":
            self.release_failed = True
            app._set_status("radio_release_error")
            # Keep an unconfirmed PTT release visible even during window close.
            if app.closing:
                app.closing = False
                app.root.deiconify()
            app._error("radio_release_error", data)
        elif event == "radio_task_done":
            self.busy = False
        self.refresh_labels()

    def refresh_labels(self):
        self.tuning_window.title(self.app.tr("tuning_open"))
        if hasattr(self, "activity_combo") and self._activity_language != self.app.language:
            self._activity_language = self.app.language
            self.activity_combo.configure(values=[entry.label(self.app.language) for entry in ACTIVITIES])
            if self.activity_index is None:
                self.activity_label.set(self.app.tr("activity_choose"))
            else:
                entry = ACTIVITIES[self.activity_index]
                self.activity_label.set(entry.label(self.app.language))
                self.activity_note.set(entry.note(self.app.language))
        if self.release_failed:
            self.app.radio_status.set(self.app.tr("radio_release_error"))
        elif self.connected and self.state:
            state = self.state
            self.readback.set(f"{state.frequency/1_000_000:.6f} MHz")
            ptt = "—" if state.ptt is None else ("TX" if state.ptt else "RX")
            self.mode_readback.set(f"{state.mode or '—'} · {ptt}")
            self.app.radio_status.set(f"{self.readback.get()} · {state.mode or '—'} · {ptt}")
        else:
            self.readback.set("— MHz")
            self.mode_readback.set("—")
            self.app.radio_status.set(self.app.tr("radio_offline"))

    def sync(self):
        locked = self.busy or self.app.busy
        configured = self.session is not None and self.connected
        for widget in self._connection_widgets:
            widget.configure(state="disabled" if locked or configured else "normal")
        for group, enabled in ((self._local_widgets, self.connection.get() == "local"),
                               (self._network_widgets, self.connection.get() == "network")):
            for widget in group:
                widget.configure(state="normal" if enabled and not locked and not configured else "disabled")
        for widget in self.ptt_widgets:
            widget.configure(state="disabled" if locked else "normal")
        self.connect_button.state(["disabled" if locked or configured else "!disabled"])
        self.disconnect_button.state(["!disabled" if not locked and self.session else "disabled"])
        self.rx_button.state(["!disabled" if self.session and not self.busy else "disabled"])
        for widget in (self.freq_entry, self.freq_button, self.mode_combo, self.width_entry, self.mode_button):
            widget.configure(state="normal" if configured and not locked else "disabled")
        self.activity_combo.configure(state="disabled" if locked else "readonly")
        self.activity_tune.state(["!disabled" if configured and not locked and self.activity_index is not None else "disabled"])
        self.satellite_entry.configure(state="disabled" if locked else "normal")
        self.save_button.state(["disabled" if locked else "!disabled"])
        self.refresh_labels()

    def begin_shutdown(self):
        if self.session:
            self.generation += 1
            self._task(self.session.close, done="radio_disconnected")
