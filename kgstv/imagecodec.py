"""KG-STV's headerless, independently coded 16x16 image tiles.

JPEG's standard example Huffman/quantization tables are obtained from Pillow's
non-optimized quality-50 JPEG writer, avoiding a second table implementation.
No original executable or third-party decoder is loaded at runtime.
"""
from functools import lru_cache
from io import BytesIO
import numpy as np
from PIL import Image, ImageOps
from scipy.fft import dctn, idctn
from .protocol import SCALES

# JPEG zig-zag traverses the diagonals of an 8x8 matrix.
ZIGZAG = []
for _diag in range(15):
    _entries = [(r, _diag-r) for r in range(8) if 0 <= _diag-r < 8]
    ZIGZAG.extend(reversed(_entries) if _diag % 2 == 0 else _entries)
ZIGZAG = tuple(ZIGZAG)


class InvalidTile(ValueError):
    pass


class BitReader:
    def __init__(self, values):
        self.values = values
        self.pos = 0

    def read(self, width):
        if self.pos+width > len(self.values):
            raise InvalidTile("Truncated image coefficient")
        value = 0
        for bit in self.values[self.pos:self.pos+width]:
            value = value*2+int(bit)
        self.pos += width
        return value


def _canonical(counts, symbols):
    decoder, encoder = {}, {}
    code = 0
    pos = 0
    for width, count in enumerate(counts, 1):
        for _ in range(count):
            symbol = symbols[pos]; pos += 1
            decoder[width, code] = symbol
            encoder[symbol] = (code, width)
            code += 1
        code <<= 1
    return decoder, encoder


@lru_cache(maxsize=1)
def _tables():
    output = BytesIO()
    Image.new("RGB", (16, 16)).save(output, format="JPEG", quality=50, optimize=False, subsampling=2)
    data = output.getvalue()
    pos = 2
    huffman, quantization = {}, {}
    while pos < len(data):
        if data[pos] != 0xFF:
            raise RuntimeError("Unexpected JPEG table source")
        marker = data[pos+1]; pos += 2
        length = int.from_bytes(data[pos:pos+2], "big")
        segment = data[pos+2:pos+length]; pos += length
        if marker == 0xDA:
            break
        if marker == 0xC4:
            n = 0
            while n < len(segment):
                table_id = segment[n]; counts = segment[n+1:n+17]; n += 17
                count = sum(counts); symbols = segment[n:n+count]; n += count
                huffman[table_id] = _canonical(counts, symbols)
        if marker == 0xDB:
            n = 0
            while n < len(segment):
                info = segment[n]; n += 1
                if info >> 4:
                    raise RuntimeError("Expected 8-bit JPEG quantization tables")
                table = np.zeros((8, 8), dtype=float)
                for coord, value in zip(ZIGZAG, segment[n:n+64]):
                    table[coord] = value
                quantization[info & 15] = table
                n += 64
    if set(huffman) != {0, 1, 16, 17} or set(quantization) != {0, 1}:
        raise RuntimeError("Missing baseline JPEG tables")
    return huffman, quantization


def _symbol(reader, table):
    code = 0
    for width in range(1, 17):
        code = code*2+reader.read(1)
        if (width, code) in table:
            return table[width, code]
    raise InvalidTile("Invalid Huffman code")


def _amplitude(reader, width):
    if width == 0:
        return 0
    value = reader.read(width)
    # KG-STV uses the high bit as a positive-sign flag; the remaining bits
    # retain magnitude. This differs from JPEG's complemented negatives.
    return value if value >= 1 << (width-1) else -(value+(1 << (width-1)))


def quantization(scale_index, chroma=False):
    if not 0 <= scale_index < 16:
        raise ValueError("Scale index must be in 0..15")
    base = _tables()[1][int(chroma)]
    # The original uses fractional divisors, not integer JPEG DQT entries.
    # Independently verified with the scale-0.5 reference PNG (integer rounding
    # creates up to 20 levels of error; fractional values reduce that to <=1).
    return base*SCALES[scale_index]


def _decode_block(reader, scale_index, chroma=False):
    huffman = _tables()[0]
    dc_table = huffman[int(chroma)][0]
    ac_table = huffman[16+int(chroma)][0]
    coeffs = np.zeros((8, 8))
    # Each component block has its own DC origin, even the four luma blocks.
    width = _symbol(reader, dc_table)
    if width > 11:
        raise InvalidTile("Invalid DC width")
    coeffs[0, 0] = _amplitude(reader, width)
    position = 1
    while position < 64:
        value = _symbol(reader, ac_table)
        if value == 0:
            break
        if value == 0xF0:
            position += 16
            if position > 64:
                raise InvalidTile("Zero run exceeds block")
            continue
        run, width = value >> 4, value & 15
        position += run
        if position >= 64 or not 1 <= width <= 10:
            raise InvalidTile("Invalid AC run or coefficient width")
        coeffs[ZIGZAG[position]] = _amplitude(reader, width)
        position += 1
    return idctn(coeffs*quantization(scale_index, chroma), norm="ortho")+128


def decode_tile(payload, scale_index, *, strict=True):
    reader = BitReader(payload)
    luma = np.empty((16, 16))
    for row, col in ((0, 0), (0, 8), (8, 0), (8, 8)):
        luma[row:row+8, col:col+8] = _decode_block(reader, scale_index)
    a = _decode_block(reader, scale_index, True)
    b = _decode_block(reader, scale_index, True)
    if strict and reader.pos != len(payload):
        raise InvalidTile(f"{len(payload)-reader.pos} trailing image bits")
    # Original color transform is applied to BGR, not RGB. The wire order is
    # four Y blocks, then Cb, then Cr in that BGR-derived coordinate system.
    cb, cr = a, b
    cb = np.repeat(np.repeat(cb, 2, axis=0), 2, axis=1)-128
    cr = np.repeat(np.repeat(cr, 2, axis=0), 2, axis=1)-128
    rgb = np.stack((luma+1.772*cb, luma-0.344136*cb-0.714136*cr, luma+1.402*cr), axis=-1)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def _append(output, value, width):
    output.extend((value >> bit) & 1 for bit in range(width-1, -1, -1))


def _encode_block(values, scale_index, chroma, output):
    coeffs = dctn(values-128, norm="ortho")/quantization(scale_index, chroma)
    coeffs = (np.sign(coeffs)*np.floor(np.abs(coeffs)+0.5)).astype(int)
    tables = _tables()[0]
    dc_table, ac_table = tables[int(chroma)][1], tables[16+int(chroma)][1]

    def emit_value(value, table, run=0):
        width = abs(int(value)).bit_length()
        key = (run << 4) | width
        if key not in table:
            raise InvalidTile("Coefficient exceeds baseline JPEG range")
        code, code_width = table[key]
        _append(output, code, code_width)
        if width:
            _append(output, value if value >= 0 else -value-(1 << (width-1)), width)

    emit_value(int(coeffs[0, 0]), dc_table)
    run = 0
    for coord in ZIGZAG[1:]:
        value = int(coeffs[coord])
        if value == 0:
            run += 1
        else:
            while run >= 16:
                _append(output, *ac_table[0xF0]); run -= 16
            emit_value(value, ac_table, run); run = 0
    if run:
        _append(output, *ac_table[0])


def encode_tile(rgb, scale_index):
    rgb = np.asarray(rgb, dtype=float)
    if rgb.shape != (16, 16, 3):
        raise ValueError("Expected one RGB 16x16 tile")
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.114*red+0.587*green+0.299*blue
    cb = 128+0.5*red-0.331264*green-0.168736*blue
    cr = 128-0.081312*red-0.418688*green+0.5*blue
    downsample = lambda v: v.reshape(8, 2, 8, 2).mean(axis=(1, 3))
    output = []
    for row, col in ((0, 0), (0, 8), (8, 0), (8, 8)):
        _encode_block(y[row:row+8, col:col+8], scale_index, False, output)
    for plane in (cb, cr):
        _encode_block(downsample(plane), scale_index, True, output)
    if len(output) > 4095:
        raise InvalidTile("Tile exceeds KG-STV's 4095-bit limit; increase the scale")
    return np.array(output, dtype=np.uint8)


def prepare_image(image):
    """Match the documented 4:3 center-crop behavior."""
    if not isinstance(image, Image.Image):
        with Image.open(image) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    return ImageOps.fit(image.convert("RGB"), (320, 240), Image.Resampling.LANCZOS)
