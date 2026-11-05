"""Optional soundcard interfaces. Importing this module opens no devices."""
import queue
import threading
import time
import numpy as np
from .modem import Receiver
from .session import Session


class LiveReceiver:
    def __init__(self, callback, *, device=None, frequency_offset=0):
        self.callback = callback
        self.device = device
        self.frequency_offset = frequency_offset
        self.stopped = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Receiver is already running")
        self.stopped.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()

    def _run(self):
        try:
            import sounddevice as sd
            packets = queue.Queue(maxsize=100)
            pending_gap = False

            def capture(indata, frames, time_info, status):
                nonlocal pending_gap
                if status:
                    pending_gap = True
                try:
                    packets.put_nowait((indata[:, 0].copy(), pending_gap))
                    pending_gap = False
                except queue.Full:
                    pending_gap = True

            session = Session()
            buffer = np.empty(0)
            total = since = 0
            last_sample = -1e9
            receiver = Receiver(frequency_offset=self.frequency_offset)
            with sd.InputStream(samplerate=12000, blocksize=1200, channels=1,
                                dtype="float32", device=self.device, callback=capture):
                self.callback("status", "Empfang läuft")
                while not self.stopped.is_set():
                    try:
                        part, gap = packets.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if gap:
                        # Never concatenate across a known missing audio interval.
                        buffer = np.empty(0)
                        since = 0
                        self.callback("status", "Audioaussetzer – Synchronisation wird neu gesucht")
                    buffer = np.concatenate((buffer, part))[-20*12000:]
                    total += len(part); since += len(part)
                    if since < 2*12000:
                        continue
                    since = 0
                    start = total-len(buffer)
                    for frame in receiver.frames(buffer, cancelled=self.stopped.is_set):
                        absolute = start+frame.sample
                        # Ignore already processed overlap; retain 50 ms for the
                        # analytic filter's right edge before accepting a frame.
                        h = frame.header
                        from .protocol import HEADER_ONLY
                        body_bits = 0 if h.com in HEADER_ONLY else (h.size+16)*(2 if h.c else 1)
                        symbols = body_bits if h.m == 0 else (body_bits+1)//2
                        end = frame.sample+(171+symbols)*10
                        if absolute <= last_sample+20 or end > len(buffer)-600:
                            continue
                        session.accept(frame)
                        last_sample = absolute
                        self.callback("frame", (frame, session))
            self.callback("status", "Empfang angehalten")
        except Exception as exc:
            self.callback("error", str(exc))
        finally:
            self.callback("stopped", None)


def play_audio(samples, *, device=None, port=None, ptt_line="rts", cancelled=None):
    """Explicit user-triggered playback with optional serial PTT release."""
    import sounddevice as sd
    serial_port = None
    playback_started = False
    try:
        if cancelled and cancelled():
            return
        if port:
            import serial
            if ptt_line not in ("rts", "dtr"):
                raise ValueError("PTT line must be rts or dtr")
            serial_port = serial.Serial(port=None)
            serial_port.rts = False
            serial_port.dtr = False
            serial_port.port = port
            serial_port.open()
            setattr(serial_port, ptt_line, True)
        if cancelled and cancelled():
            return
        playback_started = True
        sd.play(samples, samplerate=48000, device=device)
        while sd.get_stream().active:
            if cancelled and cancelled():
                sd.stop()
                break
            time.sleep(.02)
        sd.wait()
    finally:
        try:
            if playback_started:
                sd.stop()
        finally:
            if serial_port is not None:
                try:
                    setattr(serial_port, ptt_line, False)
                finally:
                    serial_port.close()


def stop_playback():
    import sounddevice as sd
    sd.stop()
