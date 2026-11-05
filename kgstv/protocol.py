"""KG-STV system 0 packets, CRC, whitening and K=7 convolutional coding.

Reference: JJ0OBZ's original readme; conventions independently checked against
the public TEST3 MSK recording. All bit arrays are in transmission order.
"""
from dataclasses import dataclass, asdict
from enum import IntEnum
import numpy as np

BAUD = 1200
SYNC = np.array(list(map(int, "000011100001001000110110010110101110111100110001010100111111010")), dtype=np.uint8)
WHITENING = np.array(list(map(int,
    "1110110011000100100111001111100100000100011010101001101101001010"
    "000101100001100101111111010110111011110001110100010101110000001")), dtype=np.uint8)
PREAMBLE = np.tile(np.array([0, 1], dtype=np.uint8), 128)
FIELD_WIDTHS = (4, 4, 1, 1, 6, 6, 4, 12)
SCALES = (0.07, 0.08, 0.09, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1., 1.2, 1.4, 1.6, 1.8, 2.)


class Command(IntEnum):
    TEXT = 0
    IMAGE = 1
    REPAIR = 2
    END = 3
    REQUEST = 4
    ABORT = 5
    CALLSIGN = 6


HEADER_ONLY = frozenset((Command.END, Command.REQUEST, Command.ABORT))


def bits(value, width):
    if not 0 <= value < (1 << width):
        raise ValueError(f"{value} does not fit in {width} bits")
    return np.array([(value >> n) & 1 for n in range(width-1, -1, -1)], dtype=np.uint8)


def integer(values):
    result = 0
    for value in values:
        result = (result << 1) | int(value)
    return result


def bytes_to_bits(value):
    return np.unpackbits(np.frombuffer(value, dtype=np.uint8))


def bits_to_bytes(value):
    if len(value) % 8:
        raise ValueError("Text must be byte-aligned")
    return np.packbits(np.asarray(value, dtype=np.uint8)).tobytes()


def crc16(values):
    """AUG-CCITT, bit serial: no padding of the 38-bit header body."""
    crc = 0x1D0F
    for value in values:
        feedback = (crc >> 15) ^ int(value)
        crc = (crc << 1) & 0xFFFF
        if feedback:
            crc ^= 0x1021
    return crc


def with_crc(values):
    values = np.asarray(values, dtype=np.uint8)
    return np.concatenate((values, bits(crc16(values), 16)))


def crc_valid(values):
    return len(values) >= 16 and crc16(values[:-16]) == integer(values[-16:])


def whiten(values):
    return np.asarray(values, dtype=np.uint8) ^ np.resize(WHITENING, len(values))


def dewhiten_soft(values):
    return np.asarray(values, dtype=float) * (1.0 - 2.0*np.resize(WHITENING, len(values)))


def convolution_encode(values):
    """Zero initial register; no inserted tail bits; newest bit at bit zero.

    With this shift direction 155/117 are the bit-reflected 133/171 masks.
    """
    state = 0
    result = np.empty(len(values)*2, dtype=np.uint8)
    for n, value in enumerate(values):
        state = ((state << 1) | int(value)) & 127
        result[2*n] = (state & 0o155).bit_count() & 1
        result[2*n+1] = (state & 0o117).bit_count() & 1
    return result


_DEST = np.arange(64)
_PREV = np.stack((_DEST >> 1, (_DEST >> 1) | 32), axis=1)
_REG = (_PREV << 1) | (_DEST[:, None] & 1)
_EXPECTED = np.array([[[((int(r) & mask).bit_count() & 1) for mask in (0o155, 0o117)]
                        for r in row] for row in _REG]) * 2.0 - 1.0


def convolution_decode(soft):
    """Viterbi with soft evidence: positive means one, negative means zero."""
    soft = np.asarray(soft, dtype=float)
    if len(soft) % 2:
        raise ValueError("A convolutional symbol must contain two bits")
    pairs = soft.reshape(-1, 2)
    metrics = np.full(64, np.inf)
    metrics[0] = 0.0
    parents = np.empty((len(pairs), 64), dtype=np.uint8)
    for n, pair in enumerate(pairs):
        costs = metrics[_PREV] - np.sum(_EXPECTED * pair, axis=2)
        choices = np.argmin(costs, axis=1)
        metrics = costs[_DEST, choices]
        metrics -= np.min(metrics)
        parents[n] = _PREV[_DEST, choices]
    state = int(np.argmin(metrics))
    decoded = np.empty(len(pairs), dtype=np.uint8)
    for n in range(len(pairs)-1, -1, -1):
        decoded[n] = state & 1
        state = int(parents[n, state])
    errors = int(np.count_nonzero(convolution_encode(decoded) != (soft > 0)))
    return decoded, errors


@dataclass(frozen=True)
class Header:
    sys: int = 0
    com: int = Command.TEXT
    c: int = 0
    m: int = 0
    x: int = 0
    y: int = 0
    sc: int = 10
    size: int = 0

    def __post_init__(self):
        for (name, value), width in zip(asdict(self).items(), FIELD_WIDTHS):
            if not isinstance(value, (int, np.integer)) or not 0 <= value < 1 << width:
                raise ValueError(f"Invalid header field {name}={value}")
        if self.sys != 0 or self.com not in set(Command):
            raise ValueError("Unsupported KG-STV system or command")
        if self.com in HEADER_ONLY and self.size != 0:
            raise ValueError("Control packets have no data chunk")
        if self.com in (Command.TEXT, Command.CALLSIGN) and self.size % 8:
            raise ValueError("Text and callsign payloads must be byte-aligned")
        if self.com in (Command.IMAGE, Command.REPAIR, Command.REQUEST):
            if self.x >= 20 or self.y >= 15:
                raise ValueError("Image coordinates outside 20 x 15 tile grid")

    def to_bits(self):
        return with_crc(np.concatenate([bits(v, w) for v, w in zip(asdict(self).values(), FIELD_WIDTHS)]))

    @classmethod
    def from_bits(cls, values):
        if len(values) != 54 or not crc_valid(values):
            raise ValueError("Invalid header length or CRC")
        pos = 0
        fields = []
        for width in FIELD_WIDTHS:
            fields.append(integer(values[pos:pos+width])); pos += width
        return cls(*fields)


@dataclass
class Frame:
    header: Header
    payload: np.ndarray
    crc_ok: bool = True
    sample: float = 0.0
    header_errors: int = 0
    sync_errors: int = 0

    def __post_init__(self):
        self.payload = np.asarray(self.payload, dtype=np.uint8)
        if len(self.payload) != self.header.size or np.any(self.payload > 1):
            raise ValueError("Payload differs from the header length or contains non-bits")

    def text(self):
        return bits_to_bytes(self.payload).decode("cp932", errors="replace")

    def segments(self):
        if not self.crc_ok:
            raise ValueError("Refusing to transmit an unchecked payload")
        yield np.concatenate((SYNC, whiten(convolution_encode(self.header.to_bits())))), 0
        if self.header.com not in HEADER_ONLY:
            data = with_crc(self.payload)
            if self.header.c:
                data = convolution_encode(data)
            yield whiten(data), self.header.m

    def to_dict(self, include_payload=False):
        result = dict(header=asdict(self.header), crc_ok=self.crc_ok, sample=self.sample,
                      header_errors=self.header_errors, sync_errors=self.sync_errors)
        if self.header.com in (Command.TEXT, Command.CALLSIGN) and self.crc_ok:
            result["text"] = self.text()
        if include_payload:
            result["payload_bits"] = "".join(map(str, self.payload.tolist()))
        return result


def text_frame(text, *, callsign=None, fec=False, mode=0, command=Command.TEXT):
    if command == Command.CALLSIGN and (not text.strip() or any(ch in text for ch in "\r\n>")):
        raise ValueError("A nonempty single-line callsign is required")
    if callsign is not None:
        if not callsign.strip() or any(ch in callsign for ch in "\r\n>"):
            raise ValueError("A nonempty single-line callsign is required")
        text = f"{callsign}>{text}"
    encoded = text.encode("cp932", errors="strict")
    if not encoded or len(encoded) > 510:
        raise ValueError("Encoded text including callsign must contain 1..510 bytes")
    payload = bytes_to_bits(encoded)
    return Frame(Header(com=command, c=int(fec), m=mode, size=len(payload)), payload)


def control_frame(command, **kwargs):
    if command not in HEADER_ONLY:
        raise ValueError("Not a header-only command")
    return Frame(Header(com=command, **kwargs), np.empty(0, dtype=np.uint8))
