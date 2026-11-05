"""Tk desktop client. Workers send messages; only the UI thread touches Tk."""
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
from .audio import save_wav
from .cli import decode_file
from .imagecodec import prepare_image
from .modem import modulate
from .protocol import SCALES, text_frame
from .session import image_frames, request_frames


class Application:
    def __init__(self, root):
        self.root = root
        self.root.title("Open KG-STV")
        self.root.geometry("1000x720")
        self.root.minsize(820, 640)
        self.events = queue.Queue()
        self.busy = False
        self.worker_thread = None
        self.cancelled = threading.Event()
        self.live = None
        self.tx_image = None
        self.rx_image = None
        self.rx_summary = None
        self.requested_blocks = []
        self.last_preview = 0
        self.callsign = tk.StringVar(value="")
        self.mode = tk.StringVar(value="MSK")
        self.fec = tk.BooleanVar(value=False)
        self.scale = tk.StringVar(value="1.0")
        self.input_device = tk.StringVar(value="Standard")
        self.output_device = tk.StringVar(value="Standard")
        self.ptt_port = tk.StringVar(value="")
        self.ptt_line = tk.StringVar(value="rts")
        self.frequency = tk.StringVar(value="0")
        self.device_ids = {"Standard": None}
        self.status = tk.StringVar(value="Bereit · Testversion: Kompatibilität mit dem Original noch nicht vollständig geprüft")
        self.block_status = tk.StringVar(value="Noch kein Bild empfangen")
        self._build()
        self.root.after(80, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self):
        scrollbar = ttk.Scrollbar(self.root, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        canvas = tk.Canvas(self.root, highlightthickness=0, yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=canvas.yview)
        outer = ttk.Frame(canvas, padding=16)
        window = canvas.create_window(0, 0, window=outer, anchor="nw")
        outer.bind("<Configure>", lambda event:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event:canvas.itemconfigure(window, width=event.width))
        ttk.Label(outer, text="Open KG-STV", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Digitale Bilder und Text · Python · MSK / 4L-FSK").pack(anchor="w", pady=(0, 12))
        controls = ttk.Frame(outer); controls.pack(fill="x")
        ttk.Label(controls, text="Rufzeichen").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.callsign, width=15).grid(row=1, column=0, padx=(0, 12))
        ttk.Label(controls, text="Modulation").grid(row=0, column=1, sticky="w")
        ttk.Combobox(controls, textvariable=self.mode, values=("MSK", "4L-FSK"), width=10, state="readonly").grid(row=1, column=1, padx=(0, 12))
        ttk.Checkbutton(controls, text="Fehlerkorrektur", variable=self.fec).grid(row=1, column=2, padx=(0, 12))
        ttk.Label(controls, text="Kompressionsskala").grid(row=0, column=3, sticky="w")
        ttk.Combobox(controls, textvariable=self.scale, values=[str(x) for x in SCALES], width=8, state="readonly").grid(row=1, column=3)
        panels = ttk.Frame(outer); panels.pack(fill="both", expand=True, pady=14)
        panels.columnconfigure((0, 1), weight=1)
        panels.rowconfigure(0, weight=1)
        tx = ttk.LabelFrame(panels, text="Senden", padding=10); tx.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        rx = ttk.LabelFrame(panels, text="Empfangen", padding=10); rx.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.tx_preview = ttk.Label(tx, text="Bild öffnen, um eine Übertragung vorzubereiten", anchor="center")
        self.tx_preview.pack(fill="both", expand=True)
        self.rx_preview = ttk.Label(rx, text="Aufnahme öffnen oder Audioempfang starten", anchor="center")
        self.rx_preview.pack(fill="both", expand=True)
        tx_buttons = ttk.Frame(tx); tx_buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(tx_buttons, text="Bild öffnen…", command=self.open_image).pack(side="left")
        ttk.Button(tx_buttons, text="Als WAV…", command=lambda:self.encode("image", False)).pack(side="left", padx=4)
        ttk.Button(tx_buttons, text="Bild senden", command=lambda:self.encode("image", True)).pack(side="left")
        ttk.Button(tx, text="BSR-Antwort als WAV… (experimentell)", command=lambda:self.encode("repair", False)).pack(anchor="w", pady=(6, 0))
        ttk.Label(rx, textvariable=self.block_status).pack(anchor="w", pady=(5, 0))
        rx_buttons = ttk.Frame(rx); rx_buttons.pack(fill="x", pady=(5, 0))
        ttk.Button(rx_buttons, text="Aufnahme öffnen…", command=self.open_recording).pack(side="left")
        ttk.Button(rx_buttons, text="Bild speichern…", command=self.save_image).pack(side="left", padx=4)
        ttk.Button(rx, text="Fehlende Blöcke: BSR als WAV… (experimentell)", command=lambda:self.encode("bsr", False)).pack(anchor="w", pady=(6, 0))
        textbar = ttk.Frame(outer); textbar.pack(fill="x")
        self.message = ttk.Entry(textbar); self.message.pack(side="left", fill="x", expand=True)
        ttk.Button(textbar, text="Text als WAV…", command=lambda:self.encode("text", False)).pack(side="left", padx=4)
        ttk.Button(textbar, text="Text senden", command=lambda:self.encode("text", True)).pack(side="left")
        devices = ttk.LabelFrame(outer, text="Audio und PTT", padding=8); devices.pack(fill="x", pady=10)
        self.input_combo = ttk.Combobox(devices, textvariable=self.input_device, values=("Standard",), width=29, state="readonly")
        self.input_combo.grid(row=0, column=0, padx=3)
        self.output_combo = ttk.Combobox(devices, textvariable=self.output_device, values=("Standard",), width=29, state="readonly")
        self.output_combo.grid(row=0, column=1, padx=3)
        ttk.Button(devices, text="Geräte laden", command=self.devices).grid(row=0, column=2, padx=3)
        ttk.Button(devices, text="Empfangen", command=self.start_live).grid(row=0, column=3, padx=3)
        ttk.Button(devices, text="Stopp", command=self.stop).grid(row=0, column=4, padx=3)
        options = ttk.Frame(devices); options.grid(row=1, column=0, columnspan=5, sticky="w", pady=(7, 0))
        ttk.Label(options, text="RX-Versatz (Hz)").pack(side="left")
        ttk.Entry(options, textvariable=self.frequency, width=7).pack(side="left", padx=(5, 15))
        ttk.Label(options, text="PTT-Port (leer = aus)").pack(side="left")
        ttk.Entry(options, textvariable=self.ptt_port, width=12).pack(side="left", padx=5)
        ttk.Combobox(options, textvariable=self.ptt_line, values=("rts", "dtr"), width=5, state="readonly").pack(side="left")
        self.log = tk.Text(outer, height=5, wrap="word", state="disabled", font=("Consolas", 10))
        self.log.pack(fill="x")
        self.progress = ttk.Progressbar(outer, maximum=100); self.progress.pack(fill="x", pady=(8, 4))
        ttk.Label(outer, textvariable=self.status, wraplength=940).pack(anchor="w")
        self.root.update_idletasks()
        height = min(max(720, outer.winfo_reqheight()+20), self.root.winfo_screenheight()-100)
        self.root.geometry(f"1000x{height}")

    def _show(self, label, image):
        preview = ImageTk.PhotoImage(image)
        label.configure(image=preview, text="")
        label.image = preview

    def open_image(self):
        path = filedialog.askopenfilename(filetypes=[("Bilder", "*.png *.jpg *.jpeg *.bmp *.gif"), ("Alle Dateien", "*.*")])
        if path:
            try:
                self.tx_image = prepare_image(path)
                self._show(self.tx_preview, self.tx_image)
            except Exception as exc:
                messagebox.showerror("Bild konnte nicht geöffnet werden", str(exc))

    def save_image(self):
        if self.rx_image is None:
            messagebox.showinfo("Empfang", "Noch kein Bild vorhanden."); return
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
        if path:
            try:
                self.rx_image.save(path)
            except OSError as exc:
                messagebox.showerror("Speichern fehlgeschlagen", str(exc))

    def _worker(self, work):
        if self.busy:
            messagebox.showinfo("Beschäftigt", "Bitte den laufenden Vorgang beenden."); return
        self.busy = True
        self.cancelled.clear()
        self.status.set("Verarbeitung läuft…")
        def run():
            try:
                work()
            except Exception as exc:
                self.events.put(("error", str(exc)))
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

    def open_recording(self):
        if self.busy or self.live:
            messagebox.showinfo("Beschäftigt", "Zuerst den laufenden Vorgang stoppen."); return
        path = filedialog.askopenfilename(filetypes=[("Audio", "*.wav *.mp3 *.flac *.ogg"), ("Alle Dateien", "*.*")])
        if not path:
            return
        directory = filedialog.askdirectory(title="Ordner für Empfangsbild und Bericht")
        if not directory:
            return
        try:
            frequency = float(self.frequency.get())
        except ValueError:
            messagebox.showerror("Einstellung", "Der Frequenzversatz muss eine Zahl sein."); return
        output = Path(directory)/(Path(path).stem+"-decoded")
        def work():
            result = decode_file(path, output, frequency_offset=frequency,
                                 on_frame=self._on_frame,
                                 progress=lambda p:self.events.put(("progress", p*100)),
                                 cancelled=self.cancelled.is_set)
            self.events.put(("status", f"{result['stats']['headers']} Pakete · gespeichert in {output}"))
        self._worker(work)

    def encode(self, kind, play):
        if self.busy or self.live:
            messagebox.showinfo("Beschäftigt", "Zuerst den laufenden Vorgang stoppen."); return
        call = self.callsign.get().strip()
        if not call:
            messagebox.showerror("Rufzeichen fehlt", "Bitte ein Rufzeichen eintragen."); return
        if kind in ("image", "repair") and self.tx_image is None:
            messagebox.showinfo("Bild fehlt", "Bitte zuerst ein Bild öffnen."); return
        if kind == "bsr" and (self.rx_summary is None or not self.rx_summary["missing"]):
            messagebox.showinfo("BSR", "Es gibt kein unvollständiges Empfangsbild."); return
        if kind == "repair" and not self.requested_blocks:
            messagebox.showinfo("BSR", "Noch keine Reparaturanfrage empfangen."); return
        path = None
        if not play:
            path = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV", "*.wav")])
            if not path:
                return
        mode, fec, index = int(self.mode.get() == "4L-FSK"), self.fec.get(), SCALES.index(float(self.scale.get()))
        message, image = self.message.get(), self.tx_image
        missing = list(self.rx_summary["missing"]) if self.rx_summary else []
        requested = list(self.requested_blocks)
        device, port, line = self.device_ids[self.output_device.get()], self.ptt_port.get().strip(), self.ptt_line.get()
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
                self.events.put(("status", f"Senden · {len(audio)/48000:.1f} Sekunden"))
                play_audio(audio, device=device, port=port or None, ptt_line=line,
                           cancelled=self.cancelled.is_set)
                self.events.put(("status", "Senden beendet"))
            else:
                save_wav(path, audio)
                self.events.put(("status", f"WAV gespeichert · {len(audio)/48000:.1f} Sekunden · {path}"))
        self._worker(work)

    def devices(self):
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            inputs, outputs = ["Standard"], ["Standard"]
            self.device_ids = {"Standard": None}
            for n, dev in enumerate(devices):
                name = f"{n}: {dev['name']}"
                self.device_ids[name] = n
                if dev["max_input_channels"]: inputs.append(name)
                if dev["max_output_channels"]: outputs.append(name)
            self.input_combo.configure(values=inputs)
            self.output_combo.configure(values=outputs)
            self.input_device.set("Standard"); self.output_device.set("Standard")
        except Exception as exc:
            messagebox.showerror("Audiogeräte", str(exc))

    def start_live(self):
        if self.busy or self.live:
            return
        try:
            from .live import LiveReceiver
            def callback(event, data):
                if event == "frame":
                    self._on_frame(*data)
                else:
                    self.events.put((event, data))
            self.live = LiveReceiver(callback, device=self.device_ids[self.input_device.get()],
                                     frequency_offset=float(self.frequency.get()))
            self.live.start()
        except Exception as exc:
            self.live = None
            messagebox.showerror("Audioempfang", str(exc))

    def stop(self):
        self.cancelled.set()
        if self.live:
            self.live.stop()
        try:
            from .live import stop_playback
            stop_playback()
        except ImportError:
            pass
        self.status.set("Anhalten…")

    def _poll(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "done": self.busy = False
                elif event == "stopped": self.live = None
                elif event == "progress": self.progress["value"] = data
                elif event == "status": self.status.set(data)
                elif event == "error":
                    self.status.set(data); messagebox.showerror("Open KG-STV", data)
                elif event == "text":
                    self.log.configure(state="normal"); self.log.insert("end", data+"\n")
                    self.log.see("end"); self.log.configure(state="disabled")
                elif event == "request":
                    self.requested_blocks = data
                    self.status.set(f"BSR: {len(data)} Blöcke angefordert")
                elif event == "image":
                    pixels, summary = data
                    self.rx_summary = summary
                    self.rx_image = Image.fromarray(pixels)
                    self._show(self.rx_preview, self.rx_image)
                    self.block_status.set(f"{summary['callsign'] or 'Unbekannt'} · {summary['good_blocks']}/300 Blöcke")
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def close(self):
        self.stop()
        self.root.withdraw()
        def wait_for_cleanup():
            running = self.worker_thread and self.worker_thread.is_alive()
            listening = self.live and self.live.thread and self.live.thread.is_alive()
            if running or listening:
                self.root.after(50, wait_for_cleanup)
            else:
                self.root.destroy()
        wait_for_cleanup()


def main():
    root = tk.Tk()
    Application(root)
    root.mainloop()


if __name__ == "__main__":
    main()
