"""Bounded audio preview and calibrated spectra; no GUI or audio-device access."""
from dataclasses import dataclass
import queue

import numpy as np

SAMPLE_RATE = 12000
FFT_SIZE = 1024
HOP = 1200  # One row per 100 ms, independent of GUI polling / decoder speed.
FREQUENCIES = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)[:257]
FLOOR_DB = -95.0
CEILING_DB = -15.0


class AudioMonitor:
    """Single capture producer / GUI consumer, retaining at most 1.2 s of audio.

    The producer transfers ownership of each sample array. No FFT, Tk call or
    blocking queue operation runs on the PortAudio callback. Sequence numbers
    expose discarded preview chunks without affecting the decoder's own queue.
    """
    def __init__(self):
        self._chunks = queue.Queue(maxsize=12)
        self._sequence = 0

    def publish(self, samples, gap=False):
        item = (self._sequence, samples, bool(gap))
        self._sequence += 1
        try:
            self._chunks.put_nowait(item)
        except queue.Full:
            try:
                self._chunks.get_nowait()
            except queue.Empty:
                pass
            self._chunks.put_nowait(item)

    def drain(self):
        chunks = []
        # Also bounded if the capture thread is still publishing.
        for _ in range(self._chunks.maxsize):
            try:
                chunks.append(self._chunks.get_nowait())
            except queue.Empty:
                break
        return chunks


@dataclass(frozen=True)
class Spectrum:
    db: np.ndarray
    peak_db: float
    clipped: bool


class SpectrumAnalyzer:
    """Hann-windowed, peak-amplitude dBFS, 0–3000 Hz inclusive.

    Full-scale bin-centred sine = 0 dBFS; DC is not doubled. A None row marks
    a capture / preview gap. Samples on opposite sides are never combined.
    """
    def __init__(self):
        self._window = np.hanning(FFT_SIZE+1)[:-1]
        self._gain = self._window.sum()
        self._pending = np.empty(0, dtype=np.float32)
        self._sequence = -1

    def feed(self, chunks):
        rows = []
        for sequence, samples, gap in chunks:
            samples = np.asarray(samples, dtype=np.float32)
            valid = samples.ndim == 1 and np.isfinite(samples).all()
            if gap or sequence != self._sequence + 1 or not valid:
                self._pending = np.empty(0, dtype=np.float32)
                rows.append(None)
            self._sequence = sequence
            if not valid:
                continue
            self._pending = np.concatenate((self._pending, samples))
            while len(self._pending) >= HOP:
                block, self._pending = self._pending[:HOP], self._pending[HOP:]
                amplitude = abs(np.fft.rfft(block[-FFT_SIZE:] * self._window))[:len(FREQUENCIES)]
                amplitude *= 2 / self._gain
                amplitude[0] /= 2
                db = 20 * np.log10(np.maximum(amplitude, 1e-12))
                peak = float(np.max(abs(block)))
                rows.append(Spectrum(db, 20 * np.log10(max(peak, 1e-12)), peak >= .999))
        return rows


def palette():
    """Dark HamRig wells through blue/cyan to warm signal highlights."""
    stops = np.array([[10, 16, 26], [21, 39, 75], [38, 77, 151],
                      [40, 166, 207], [109, 219, 196], [240, 180, 76], [255, 244, 212]])
    x = np.linspace(0, 1, len(stops))
    return np.column_stack([np.interp(np.linspace(0, 1, 256), x, stops[:, c])
                            for c in range(3)]).astype(np.uint8)
