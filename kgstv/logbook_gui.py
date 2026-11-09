"""Operating QSO dialog. Depends only on the logbook backend contract."""
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog
import uuid

from . import theme
from .i18n import load_settings, save_settings
from .library_gui import StudioWindow
from .logbook import Qso, AdifLogbook, LogbookError, frequency_hz


class QsoWindow(StudioWindow):
    def __init__(self, app, *, backend_factory=AdifLogbook):
        super().__init__(app, "log_qso", f"740x{min(850, app.root.winfo_screenheight()-90)}")
        self.window.minsize(700, 600)
        self.backend_factory = backend_factory
        self.qso_id = str(uuid.uuid4())
        self.saved = False
        self.values = {}
        self.satellite = tk.BooleanVar(self.window, False)
        now = datetime.now(timezone.utc)
        radio = app.radio_panel
        hz = radio.state.frequency if radio.connected and radio.state else None
        call = (app.rx_summary or {}).get("callsign", "")
        if not call:
            for item in reversed(app._recent_messages):
                if item["direction"] == "RX" and ">" in item["text"]:
                    call = item["text"].split(">", 1)[0]
                    break
        defaults = dict(call=call, station_call=app.callsign.get(), date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"), end_date="", end_time="", frequency=f"{hz/1e6:.6f}" if hz else "",
            frequency_rx="", satellite_name="", rst_sent="", rst_received="", name="", grid="", comment="")
        for key, value in defaults.items():
            self.values[key] = tk.StringVar(self.window, value)
        stored_path = load_settings(app.settings_path).get("logbook_path")
        self.path = tk.StringVar(self.window, stored_path if isinstance(stored_path, str) and stored_path else str(app.settings_path.parent/"logbook.adi"))
        footer = tk.Frame(self.window, bg=theme.BG, padx=20, pady=12)
        footer.pack(side="bottom", fill="x")
        scroll = ttk.Scrollbar(self.window)
        scroll.pack(side="right", fill="y")
        canvas = tk.Canvas(self.window, bg=theme.BG, highlightthickness=0, yscrollcommand=scroll.set)
        canvas.pack(fill="both", expand=True)
        scroll.configure(command=canvas.yview)
        body = tk.Frame(canvas, bg=theme.BG, padx=20, pady=16)
        item = canvas.create_window(0, 0, window=body, anchor="nw")
        body.bind("<Configure>", lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e:canvas.itemconfigure(item, width=e.width))
        self.window.bind("<MouseWheel>", lambda e:canvas.yview_scroll(-2 if e.delta>0 else 2, "units"))
        self.label(body, "log_qso").pack(anchor="w")
        self.label(body, "qso_hint", wraplength=690, justify="left", fg=theme.MUTED).pack(anchor="w", pady=(6, 12))
        grid = tk.Frame(body, bg=theme.BG)
        grid.pack(fill="x")
        grid.columnconfigure((0, 1), weight=1, uniform="qso")
        for n, (key, label) in enumerate((("call", "their_call"), ("station_call", "callsign"),
                ("date", "qso_date"), ("time", "qso_time"), ("end_date", "qso_end_date"), ("end_time", "qso_end_time"),
                ("frequency", "qso_frequency"), ("frequency_rx", "qso_frequency_rx"),
                ("rst_sent", "qso_rst_sent"), ("rst_received", "qso_rst_received"),
                ("name", "name"), ("grid", "qso_grid"))):
            row, col = (n//2)*2, n%2
            self.label(grid, label).grid(row=row, column=col, sticky="w", pady=(3, 3))
            entry = ttk.Entry(grid, textvariable=self.values[key])
            entry.grid(row=row+1, column=col, sticky="ew", padx=(0, 12) if col == 0 else 0, pady=(0, 5))
            if key == "call":
                entry.focus_set()
        sat = tk.Frame(body, bg=theme.BG)
        sat.pack(fill="x", pady=8)
        check = ttk.Checkbutton(sat, text=app.tr("qso_satellite"), variable=self.satellite, command=self.satellite_changed)
        check.pack(side="left")
        self.bindings.append((check, "qso_satellite"))
        ttk.Entry(sat, textvariable=self.values["satellite_name"], width=16).pack(side="left", padx=12)
        self.label(sat, "qso_sat_hint").pack(side="left")
        self.label(body, "qso_comment").pack(anchor="w", pady=(3, 3))
        ttk.Entry(body, textvariable=self.values["comment"]).pack(fill="x")
        self.label(body, "qso_path").pack(anchor="w", pady=(12, 3))
        path_row = tk.Frame(body, bg=theme.BG)
        path_row.pack(fill="x")
        self.button(path_row, "qso_choose_path", self.choose_path).pack(side="right", padx=(8, 0))
        ttk.Entry(path_row, textvariable=self.path).pack(fill="x", expand=True)
        self.label(footer, "qso_ascii_hint", fg=theme.MUTED, wraplength=650, justify="left").pack(anchor="w", pady=(0, 8))
        self.save_button = self.button(footer, "qso_save", self.save, style="Primary.TButton")
        self.save_button.pack(side="right", pady=6)
        self.button(footer, "qso_cancel", self.close).pack(side="right", padx=8, pady=6)
        # Only a successfully applied satellite preset matching the current CAT
        # frequency is evidence of this station's QO-100 operating setup.
        if radio.last_activity and radio.last_activity[0] == "qo100" and hz and abs(hz-radio.last_activity[1]) < 2:
            self.satellite.set(True)
            self.satellite_changed()

    def satellite_changed(self):
        if self.satellite.get():
            self.values["frequency"].set("2400.125000")
            self.values["frequency_rx"].set("10489.625000")
            self.values["satellite_name"].set("QO-100")
        else:
            self.values["frequency_rx"].set("")
            self.values["satellite_name"].set("")
            radio = self.app.radio_panel
            self.values["frequency"].set(f"{radio.state.frequency/1e6:.6f}" if radio.connected and radio.state else "")

    def choose_path(self):
        path = filedialog.asksaveasfilename(parent=self.window, title=self.app.tr("qso_choose_path"),
            initialfile=Path(self.path.get()).name, defaultextension=".adi", confirmoverwrite=False,
            filetypes=[("ADIF", "*.adi *.adif")])
        if path:
            self.path.set(path)

    def record(self):
        values = {key:variable.get().strip() for key, variable in self.values.items()}
        def timestamp(date, time):
            try:
                return datetime.strptime(date+" "+time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                raise LogbookError("qso_time_error") from None
        end = timestamp(values["end_date"], values["end_time"]) if values["end_date"] or values["end_time"] else None
        if self.satellite.get() and not values["satellite_name"]:
            raise LogbookError("qso_invalid")
        return Qso(call=values["call"].upper(), station_call=values["station_call"].upper(),
            time_on=timestamp(values["date"], values["time"]), time_off=end,
            frequency=frequency_hz(values["frequency"]), frequency_rx=frequency_hz(values["frequency_rx"]) if values["frequency_rx"] else None,
            rst_sent=values["rst_sent"], rst_received=values["rst_received"], name=values["name"], grid=values["grid"],
            comment=values["comment"], satellite=values["satellite_name"] if self.satellite.get() else "", id=self.qso_id)

    def save(self):
        if self.saved:
            return
        try:
            record = self.record()
            record.validate()
            path = Path(self.path.get().strip()).expanduser()
            if not self.path.get().strip() or path.suffix.lower() not in (".adi", ".adif"):
                raise LogbookError("qso_path_error")
            receipt = self.backend_factory(path).save(record)
        except LogbookError as exc:
            self.app._error(exc.key, exc.detail)
            return
        except OSError as exc:
            self.app._error("qso_write_error", exc)
            return
        self.saved = True
        self.save_button.state(["disabled"])
        try:
            save_settings(self.app.settings_path, {"logbook_path":str(path)})
        except OSError:
            pass  # The QSO is durable; a preference error must not invite a second submission.
        self.app._set_status("qso_saved", {"call":record.call, "path":receipt.destination})
        self.close()
