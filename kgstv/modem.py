"""Offline CPFSK modulator and independently synchronized packet receiver."""
from dataclasses import dataclass
import numpy as np
from scipy.signal import hilbert
from .protocol import (BAUD, SYNC, PREAMBLE, HEADER_ONLY, Frame, Header,
                       convolution_decode, dewhiten_soft, crc_valid, whiten,
                       convolution_encode)


def modulate(frames, rate=48000, amplitude=0.65, end_repeats=10):
    """Generate audio only; no audio device or PTT is touched."""
    from .protocol import control_frame, Command
    if rate % BAUD or rate < 9600 or not 0 < amplitude <= 1:
        raise ValueError("Rate must be a multiple of 1200 >= 9600; amplitude in (0,1]")
    if not 1 <= end_repeats <= 30:
        raise ValueError("End repeats must be in 1..30")
    frames = list(frames)
    if not frames:
        raise ValueError("No frames to transmit")
    segments = [(PREAMBLE, 0)]
    for frame in frames:
        segments.extend(frame.segments())
    if frames[-1].header.com not in (Command.END, Command.ABORT):
        for _ in range(end_repeats):
            segments.extend(control_frame(Command.END).segments())
    phase = 0.0
    chunks = [np.zeros(rate//10)]
    for data, mode in segments:
        if mode == 0:
            tones = 1200.0 + 600.0*data
        else:
            if len(data) % 2:
                data = np.append(data, 0)
            pairs = data.reshape(-1, 2)
            tones = 1200.0 + 200.0*(2*pairs[:, 0]+pairs[:, 1])
        steps = np.repeat(2*np.pi*tones/rate, rate//BAUD)
        phases = phase + np.cumsum(steps)
        chunks.append(amplitude*np.sin(phases))
        if len(phases):
            phase = float(phases[-1] % (2*np.pi))
    chunks.append(np.zeros(rate//10))
    return np.concatenate(chunks)


@dataclass
class DecodeStats:
    sync_groups: int = 0
    headers: int = 0
    valid_payloads: int = 0
    bad_payloads: int = 0
    truncated: int = 0


class Receiver:
    """Find each frame independently, recovering after dropped/corrupt frames.

    Working rate is 12 kHz. Header candidates are CRC checked before trusting
    their length or mode. Timing is reacquired per packet, not once per file.
    """
    def __init__(self, rate=12000, frequency_offset=0.0, max_sync_errors=6):
        if rate != 12000:
            raise ValueError("Receiver working rate is 12000 Hz")
        if not -500 <= frequency_offset <= 500:
            raise ValueError("Frequency offset must be within +/-500 Hz")
        if not 0 <= max_sync_errors <= 10:
            raise ValueError("Sync error limit must be in 0..10")
        self.rate = rate
        self.sps = rate//BAUD
        self.frequency_offset = frequency_offset
        self.max_sync_errors = max_sync_errors
        self.stats = DecodeStats()

    def frames(self, samples, progress=None, cancelled=None):
        self.stats = DecodeStats()
        samples = np.asarray(samples, dtype=float)
        if samples.ndim != 1 or not np.all(np.isfinite(samples)):
            raise ValueError("Expected finite mono audio")
        if len(samples) < 171*self.sps:
            return
        analytic = hilbert(samples)
        time = np.arange(len(samples))/self.rate
        if self.frequency_offset:
            analytic *= np.exp(-2j*np.pi*self.frequency_offset*time)
        energies = []
        for frequency in (1200, 1800):
            baseband = analytic*np.exp(-2j*np.pi*frequency*time)
            # Rectangular matched windows; every possible integer start sample.
            integral = np.concatenate(([0j], np.cumsum(baseband)))
            energies.append(np.abs(integral[self.sps:]-integral[:-self.sps])**2)
        soft = (energies[1]-energies[0])/(energies[1]+energies[0]+1e-20)
        sync_sign = SYNC.astype(float)*2-1
        candidates = []
        for offset in range(self.sps):
            lane = soft[offset::self.sps]
            if len(lane) < 171:
                continue
            hard = (lane > 0).astype(np.int16)*2-1
            matches = np.correlate(hard, sync_sign, mode="valid")
            for n in np.flatnonzero(matches >= 63-2*self.max_sync_errors):
                score = float(np.dot(lane[n:n+63], sync_sign))
                candidates.append((int(n)*self.sps+offset, score, (63-int(matches[n]))//2))
        candidates.sort()
        groups = []
        for candidate in candidates:
            if not groups or candidate[0]-groups[-1][-1][0] > self.sps:
                groups.append([candidate])
            else:
                groups[-1].append(candidate)
        self.stats.sync_groups = len(groups)
        for group in groups:
            if cancelled and cancelled():
                return
            if progress:
                progress(group[0][0]/len(samples))
            best = None
            for start, score, sync_errors in sorted(group, key=lambda t:-t[1]):
                hstart = start+63*self.sps
                hsoft = soft[hstart:hstart+108*self.sps:self.sps]
                if len(hsoft) < 108:
                    continue
                decoded, errors = convolution_decode(dewhiten_soft(hsoft))
                try:
                    header = Header.from_bits(decoded)
                except ValueError:
                    continue
                if header.com in HEADER_ONLY:
                    best = Frame(header, np.empty(0, dtype=np.uint8), True, start, errors, sync_errors)
                    break
                count = (header.size+16)*(2 if header.c else 1)
                dstart = start+171*self.sps
                nsymbols = count if header.m == 0 else (count+1)//2
                if dstart+nsymbols*self.sps > len(analytic):
                    self.stats.truncated += 1
                    continue
                if header.m == 0:
                    chunks = [soft[dstart:dstart+count*self.sps:self.sps]]
                else:
                    # Estimate payload carrier phase from the known coded header.
                    known = np.concatenate((SYNC, whiten(convolution_encode(header.to_bits()))))
                    steps = np.repeat(2*np.pi*(1200+600*known.astype(float))/self.rate, self.sps)
                    phase = np.cumsum(steps)-steps[0]
                    observed = analytic[start:dstart]
                    initial = np.angle(np.vdot(np.exp(1j*phase), observed))
                    payload_phase = initial+np.sum(steps)
                    chunks = self._fsk4_candidates(analytic, dstart, nsymbols, payload_phase, count)
                for received in chunks:
                    received = dewhiten_soft(received)
                    raw = convolution_decode(received)[0] if header.c else (received > 0).astype(np.uint8)
                    valid = crc_valid(raw)
                    frame = Frame(header, raw[:-16], valid, start, errors, sync_errors)
                    if best is None or (valid, -errors) > (best.crc_ok, -best.header_errors):
                        best = frame
                    if valid:
                        break
                if best is not None and best.crc_ok:
                    break
            if best is not None:
                self.stats.headers += 1
                if best.header.com not in HEADER_ONLY:
                    if best.crc_ok:
                        self.stats.valid_payloads += 1
                    else:
                        self.stats.bad_payloads += 1
                yield best
        if progress:
            progress(1.0)

    def _fsk4_candidates(self, analytic, start, count, phase, bit_count):
        # Six absolute phase states: each 200 Hz step advances by 60 degrees
        # per symbol. All starting states are allowed; phase offset is searched.
        block = analytic[start:start+count*self.sps].reshape(count, self.sps)
        t = np.arange(self.sps)/self.rate
        tones = np.exp(-2j*np.pi*np.outer(1200+200*np.arange(4), t))
        correlations = block @ tones.T
        dest = np.arange(6)[:, None]
        symbols = np.arange(4)[None, :]
        prev = (dest-symbols) % 6
        rotations = np.exp(-1j*(phase+np.arange(6)*np.pi/3))
        # First use the phase inferred from the header. Fine offsets compensate
        # finite-window filtering and a sample boundary between integer samples.
        for adjustment in (0, -np.pi/12, np.pi/12, -np.pi/6, np.pi/6):
            branches = np.real(correlations[:, None, :]*rotations[None, :, None]*np.exp(-1j*adjustment))
            metrics = np.zeros(6)
            trace = np.empty((count, 6), dtype=np.uint8)
            for n in range(count):
                scores = metrics[prev]+branches[n, prev, symbols]
                choices = np.argmax(scores, axis=1)
                metrics = scores[np.arange(6), choices]
                trace[n] = choices
            state = int(np.argmax(metrics))
            decoded = np.empty(count, dtype=np.uint8)
            for n in range(count-1, -1, -1):
                symbol = int(trace[n, state])
                decoded[n] = symbol
                state = (state-symbol) % 6
            pairs = np.stack((decoded >> 1, decoded & 1), axis=1).reshape(-1)[:bit_count]
            yield pairs.astype(float)*2-1
