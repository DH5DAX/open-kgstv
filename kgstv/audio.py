"""Offline audio I/O. Reading a file never opens an audio device."""
from math import gcd
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly


def resample(samples, source_rate, target_rate):
    samples = np.asarray(samples, dtype=float)
    if source_rate == target_rate:
        return samples
    divisor = gcd(int(source_rate), int(target_rate))
    return resample_poly(samples, target_rate//divisor, source_rate//divisor)


def load_audio(path, rate=12000):
    path = Path(path)
    if path.suffix.lower() == ".wav":
        source_rate, raw = wavfile.read(path)
        if np.issubdtype(raw.dtype, np.integer):
            if raw.dtype == np.uint8:
                samples = (raw.astype(float)-128)/128
            else:
                samples = raw.astype(float)/(2.0**(raw.dtype.itemsize*8-1))
        else:
            samples = raw.astype(float)
        if samples.ndim == 2:
            samples = samples.mean(axis=1)
        if samples.ndim != 1 or not np.all(np.isfinite(samples)):
            raise ValueError("Audio must contain finite mono or stereo samples")
        return resample(samples, source_rate, rate)
    try:
        import av
    except ImportError as exc:
        raise ValueError("MP3 and other formats require the optional 'audio' dependencies") from exc
    chunks = []
    with av.open(str(path)) as container:
        converter = av.AudioResampler(format="fltp", layout="mono", rate=rate)
        for frame in container.decode(audio=0):
            chunks.extend(f.to_ndarray().ravel() for f in converter.resample(frame))
        chunks.extend(f.to_ndarray().ravel() for f in converter.resample(None))
    if not chunks:
        raise ValueError("No audio samples found")
    return np.concatenate(chunks).astype(float)


def save_wav(path, samples, rate=48000):
    samples = np.asarray(samples)
    if not np.all(np.isfinite(samples)):
        raise ValueError("Nonfinite audio samples")
    wavfile.write(path, rate, np.round(np.clip(samples, -1, 1)*32767).astype(np.int16))
