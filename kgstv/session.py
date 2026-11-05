"""Image assembly, transmission construction and experimental BSR sessions."""
from dataclasses import dataclass, field
import numpy as np
from .imagecodec import decode_tile, encode_tile, prepare_image, InvalidTile
from .protocol import Frame, Header, Command, text_frame, control_frame


@dataclass
class ReceivedImage:
    callsign: str = ""
    pixels: np.ndarray = field(default_factory=lambda: np.zeros((240, 320, 3), dtype=np.uint8))
    good: np.ndarray = field(default_factory=lambda: np.zeros((15, 20), dtype=bool))
    seen: np.ndarray = field(default_factory=lambda: np.zeros((15, 20), dtype=bool))
    codec_errors: int = 0
    finished: bool = False
    aborted: bool = False

    @property
    def complete(self):
        return bool(self.good.all())

    def missing(self):
        return [(int(x), int(y)) for y, x in np.argwhere(~self.good)]

    def summary(self):
        return dict(callsign=self.callsign, good_blocks=int(self.good.sum()),
                    seen_blocks=int(self.seen.sum()), missing=self.missing(),
                    codec_errors=self.codec_errors, finished=self.finished,
                    aborted=self.aborted, complete=self.complete)


class Session:
    def __init__(self, *, decode_corrupt=False, passive_repair=True):
        self.images = []
        self.messages = []
        self.callsign = ""
        self.requester = ""
        self.requested = set()
        self.decode_corrupt = decode_corrupt
        self.passive_repair = passive_repair
        self.request_sent = False
        self.operation = None
        self.ignored_repairs = 0

    @property
    def current_image(self):
        return self.images[-1] if self.images else None

    def accept(self, frame):
        h = frame.header
        if h.com == Command.CALLSIGN and frame.crc_ok:
            self.callsign = frame.text().strip("\x00\r\n ")
            return "callsign"
        if h.com == Command.TEXT and frame.crc_ok:
            self.messages.append(frame.text())
            self.operation = Command.TEXT
            return "text"
        if h.com in (Command.END, Command.ABORT):
            if self.operation in (Command.IMAGE, Command.REPAIR) and self.current_image:
                self.current_image.finished = True
                self.current_image.aborted = h.com == Command.ABORT
            self.operation = None
            return "end" if h.com == Command.END else "abort"
        if h.com == Command.REQUEST:
            if self.operation != Command.REQUEST:
                self.requested.clear()
                self.requester = self.callsign
            self.operation = Command.REQUEST
            self.requested.add((h.x, h.y))
            return "request"
        if h.com in (Command.IMAGE, Command.REPAIR):
            if h.com == Command.IMAGE:
                image = self.current_image
                if (self.operation != Command.IMAGE or image is None or
                        (self.callsign and image.callsign and self.callsign != image.callsign)):
                    image = ReceivedImage(callsign=self.callsign)
                    self.images.append(image)
                    self.requested.clear()
                    self.request_sent = False
            else:
                if self.operation != Command.REPAIR:
                    self.requested.clear()
                image = self.current_image
                if (image is None or not self.callsign or self.callsign != image.callsign or
                        not (self.passive_repair or self.request_sent)):
                    self.ignored_repairs += 1
                    return "ignored_repair"
            self.operation = h.com
            image.seen[h.y, h.x] = True
            if frame.crc_ok or self.decode_corrupt:
                try:
                    tile = decode_tile(frame.payload, h.sc, strict=frame.crc_ok)
                except (InvalidTile, ValueError):
                    image.codec_errors += 1
                    return "codec_error"
                # A later bad copy must not overwrite an already good tile.
                if frame.crc_ok or not image.good[h.y, h.x]:
                    image.pixels[h.y*16:h.y*16+16, h.x*16:h.x*16+16] = tile
                    image.good[h.y, h.x] = frame.crc_ok
            return "tile"
        return "ignored"

    def summary(self):
        return dict(messages=self.messages, images=[im.summary() for im in self.images],
                    requester=self.requester, requested_blocks=sorted(self.requested),
                    ignored_repairs=self.ignored_repairs)


def image_frames(image, callsign, *, mode=0, fec=False, scale_index=10,
                 scan="horizontal", callsign_repeats=5, blocks=None, repair=False, seed=None):
    if not 1 <= callsign_repeats <= 12:
        raise ValueError("Callsign repeat count must be 1..12")
    pixels = np.asarray(prepare_image(image))
    call = text_frame(callsign, command=Command.CALLSIGN, mode=mode, fec=fec)
    if not callsign.strip() or any(c in callsign for c in "\n\r>"):
        raise ValueError("A nonempty single-line callsign is required")
    coordinates = [(x, y) for y in range(15) for x in range(20)]
    if blocks is not None:
        coordinates = list(dict.fromkeys(tuple(pair) for pair in blocks))
        if not coordinates:
            raise ValueError("No image blocks requested")
        if any(len(p) != 2 or not all(isinstance(v, int) for v in p) or
               not (0 <= p[0] < 20 and 0 <= p[1] < 15) for p in coordinates):
            raise ValueError("Invalid block coordinates")
    if scan == "vertical":
        coordinates.sort(key=lambda p:(p[0], p[1]))
    elif scan == "random":
        np.random.default_rng(seed).shuffle(coordinates)
    elif scan != "horizontal":
        raise ValueError("Unknown scan order")
    result = [call]*callsign_repeats
    for n, (x, y) in enumerate(coordinates):
        if n % 10 == 0:
            result.append(call)
        data = encode_tile(pixels[y*16:y*16+16, x*16:x*16+16], scale_index)
        result.append(Frame(Header(com=Command.REPAIR if repair else Command.IMAGE,
                                   c=int(fec), m=mode, x=x, y=y, sc=scale_index,
                                   size=len(data)), data))
    result.append(call)
    return result


def request_frames(blocks, callsign):
    """BSR request format from the original documentation; RF interop pending."""
    blocks = list(dict.fromkeys(tuple(p) for p in blocks))
    if not blocks:
        raise ValueError("There are no missing blocks")
    frames = [text_frame(callsign, command=Command.CALLSIGN)]*5
    for x, y in blocks:
        frames.append(control_frame(Command.REQUEST, x=x, y=y))
    return frames
