"""Independent, narrowly scoped KG-STV MSK/NORM text research experiment.

Not a production modem. Written from protocol descriptions, without importing
or executing the third-party KG-STV implementation. Dependencies: av, numpy,
scipy. The original readme supplies the sequences and header field widths;
CRC parameters and convolution output order are hypotheses from
https://github.com/barisdinc/multiplatform-KGSTV/blob/d795cf445ae4cec38d7cba6904b172fa3d0ab03f/docs/protocol_spec.md
which this experiment checks against a separately obtained SigIDWiki recording.
"""
from pathlib import Path
import hashlib
import json

import av
import numpy as np
from scipy.signal import hilbert

ROOT = Path(__file__).resolve().parent
SYNC = "000011100001001000110110010110101110111100110001010100111111010"
WHITE = ("1110110011000100100111001111100100000100011010101001101101001010"
         "000101100001100101111111010110111011110001110100010101110000001")


def crc(bits):
    value = 0x1D0F
    for bit in bits:
        feedback = (value >> 15) ^ int(bit)
        value = (value << 1) & 0xFFFF
        if feedback:
            value ^= 0x1021
    return value


def number(bits):
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def unwhiten(bits):
    return np.asarray(bits) ^ np.resize(np.array(list(map(int, WHITE))), len(bits))


def decode_convolution(encoded):
    """Hard-decision K=7, rate 1/2 Viterbi; zero initial, free final state."""
    metrics = np.full(64, 100000, dtype=int)
    metrics[0] = 0
    parents = []
    for pair in np.asarray(encoded).reshape(-1, 2):
        following = np.full(64, 100000, dtype=int)
        parent = np.zeros(64, dtype=int)
        for state in range(64):
            for bit in (0, 1):
                register = (state << 1) | bit
                # Here the newest bit is at bit 0. Reversing the seven-bit
                # masks 133/171 gives 155/117 for this register convention.
                output = [(register & p).bit_count() % 2 for p in (0o155, 0o117)]
                candidate = metrics[state] + sum(a != b for a, b in zip(pair, output))
                dest = register & 63
                if candidate < following[dest]:
                    following[dest] = candidate
                    parent[dest] = state
        metrics = following
        parents.append(parent)
    state = int(np.argmin(metrics))
    cost = int(metrics[state])
    decoded = []
    for parent in reversed(parents):
        decoded.append(state & 1)
        state = int(parent[state])
    return np.array(decoded[::-1]), cost


def main():
    source = ROOT / "reference" / "KG-STV_MSK_text.mp3"
    chunks = []
    with av.open(str(source)) as container:
        converter = av.AudioResampler(format="fltp", layout="mono", rate=48000)
        for frame in container.decode(audio=0):
            chunks.extend(f.to_ndarray().ravel() for f in converter.resample(frame))
        chunks.extend(f.to_ndarray().ravel() for f in converter.resample(None))
    samples = np.concatenate(chunks).astype(float)
    analytic = hilbert(samples)
    time = np.arange(len(samples)) / 48000
    energies = [np.abs(np.convolve(analytic * np.exp(-2j*np.pi*f*time),
                                   np.ones(40), mode="valid")) ** 2
                for f in (1200, 1800)]
    target = 2*np.array(list(map(int, SYNC))) - 1
    found = []
    for offset in range(40):
        bits = (energies[1][offset::40] > energies[0][offset::40]).astype(int)
        scores = np.correlate(2*bits-1, target, mode="valid")
        for start in np.flatnonzero(scores >= len(SYNC)-4):
            header_start = int(start) + 63
            coded = bits[header_start:header_start+108]
            if len(coded) != 108:
                continue
            decoded, cost = decode_convolution(unwhiten(coded))
            if crc(decoded[:38]) != number(decoded[38:]):
                continue
            widths = dict(sys=4, com=4, c=1, m=1, x=6, y=6, sc=4, size=12)
            header = {}
            pos = 0
            for name, width in widths.items():
                header[name] = number(decoded[pos:pos+width]); pos += width
            if header["com"] != 0 or header["c"] != 0 or header["m"] != 0:
                continue
            data_start = header_start + 108
            data = unwhiten(bits[data_start:data_start+header["size"]+16])
            if len(data) != header["size"] + 16:
                continue
            raw = data[:-16]
            crc_good = crc(raw) == number(data[-16:])
            payload = bytes(number(raw[i:i+8]) for i in range(0, len(raw), 8))
            found.append(dict(offset=offset, sync_sample=int(start)*40+offset,
                              sync_bit_errors=(63-int(scores[start]))//2,
                              preamble_bit_errors=int(np.sum(bits[int(start)-256:int(start)] !=
                                                         np.tile([0, 1], 128))) if start >= 256 else None,
                              header=header, header_viterbi_metric=cost,
                              header_crc=f"{number(decoded[38:]):04x}",
                              data_crc=f"{number(data[-16:]):04x}",
                              data_crc_valid=crc_good,
                              payload_hex=payload.hex(),
                              decoded_text=payload.decode("cp932", errors="replace")))
    passing = [f for f in found if f["data_crc_valid"]]
    result = dict(sample_url="https://www.sigidwiki.com/images/5/58/KG-STV_MSK_text.mp3",
                  sample_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  resampled_rate_hz=48000, duration_seconds=len(samples)/48000,
                  sync_length=len(SYNC), whitening_length=len(WHITE),
                  conv_register="left shift; newest bit at LSB; masks octal 155,117 (reversed 133,171)",
                  crc_valid_timing_candidates=len(passing),
                  best=min(passing, key=lambda x:(x["header_viterbi_metric"],
                                                 x["sync_bit_errors"])) if passing else None,
                  scope="One public MSK/NORM text sample; no general compatibility claim")
    (ROOT/"msk_probe_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not passing:
        raise SystemExit("No CRC-valid text frame found")


if __name__ == "__main__":
    main()
