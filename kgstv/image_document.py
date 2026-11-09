"""Editable TX compositions. Pillow rendering, no Tk, radio or network access."""
from dataclasses import dataclass, field, replace
import base64
from io import BytesIO
import json
import math
import os
from pathlib import Path
import uuid
from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFont, ImageOps

SIZE = (320, 240)
MAX_LAYERS = 64
MAX_DOCUMENT = 32 * 1024 * 1024
FONTS = ("Sans", "Mono", "Serif", "Arial", "Impact")


def load_image(source):
    """Keep an independent, oriented source, bounded for editor memory use."""
    if isinstance(source, Image.Image):
        image = ImageOps.exif_transpose(source).convert("RGBA")
    else:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
    image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    return image.copy()


def png_bytes(image):
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def font_for(family, size, bold=True):
    windows = Path(os.environ.get("WINDIR", "C:/Windows"))/"Fonts"
    names = {
        "Sans": ("segoeuib.ttf" if bold else "segoeui.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        "Mono": ("consolab.ttf" if bold else "consola.ttf", "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"),
        "Serif": ("georgiab.ttf" if bold else "georgia.ttf", "DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf"),
        "Arial": ("arialbd.ttf" if bold else "arial.ttf", "DejaVuSans.ttf"),
        "Impact": ("impact.ttf", "DejaVuSans-Bold.ttf"),
    }[family]
    candidates = [windows/names[0], names[1], Path("/usr/share/fonts/truetype/dejavu")/names[1],
                  Path("/System/Library/Fonts/Supplemental")/("Arial Bold.ttf" if bold else "Arial.ttf")]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def expand_text(text, context):
    for key in ("MYCALL", "HISCALL", "DATE", "TIME"):
        text = text.replace("{"+key+"}", str(context.get(key, "{"+key+"}")))
    return text


@dataclass
class Layer:
    kind: str
    name: str = ""
    id: str = field(default_factory=lambda:uuid.uuid4().hex)
    x: float = 160
    y: float = 120
    width: float = 160
    height: float = 120
    visible: bool = True
    opacity: float = 100
    angle: float = 0
    image: Image.Image | None = field(default=None, repr=False, compare=False)
    fit: str = "cover"
    crop_x: float = 50
    crop_y: float = 50
    flip: bool = False
    brightness: float = 100
    contrast: float = 100
    saturation: float = 100
    sharpness: float = 100
    autocontrast: bool = False
    text: str = "TEXT"
    font: str = "Sans"
    size: float = 26
    bold: bool = True
    color: str = "#ffffff"
    outline_color: str = "#000000"
    outline: float = 1
    shadow: bool = False
    align: str = "center"

    def validate(self):
        if self.kind not in ("image", "text") or self.font not in FONTS:
            raise ValueError("Unsupported layer or font")
        if self.fit not in ("cover", "contain", "stretch") or self.align not in ("left", "center", "right"):
            raise ValueError("Unsupported image fit or text alignment")
        limits = {"x":(-640, 960), "y":(-480, 720), "width":(1, 1280), "height":(1, 960),
                  "opacity":(0, 100), "angle":(-360, 360), "crop_x":(0, 100), "crop_y":(0, 100),
                  "brightness":(0, 300), "contrast":(0, 300), "saturation":(0, 300),
                  "sharpness":(0, 300), "size":(6, 120), "outline":(0, 8)}
        for key, (low, high) in limits.items():
            value = getattr(self, key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError("Invalid layer value: "+key)
        for key in ("visible", "flip", "autocontrast", "bold", "shadow"):
            if not isinstance(getattr(self, key), bool):
                raise ValueError("Invalid layer switch: "+key)
        for key in ("name", "text", "id", "color", "outline_color"):
            if not isinstance(getattr(self, key), str):
                raise ValueError("Invalid layer text")
        if len(self.text) > 1000 or len(self.name) > 200 or len(self.id) > 80:
            raise ValueError("Layer text is too long")
        ImageColor.getrgb(self.color)
        ImageColor.getrgb(self.outline_color)
        if self.kind == "image" and self.image is None:
            raise ValueError("Missing layer image")


def layer_bitmap(layer, context=None):
    """Render at 2x output size for smooth text and rotations."""
    layer.validate()
    if layer.kind == "image":
        source = layer.image
        if layer.flip:
            source = ImageOps.mirror(source)
        alpha = source.getchannel("A")
        rgb = source.convert("RGB")
        if layer.autocontrast:
            rgb = ImageOps.autocontrast(rgb)
        for enhancer, value in ((ImageEnhance.Brightness, layer.brightness),
                                (ImageEnhance.Contrast, layer.contrast),
                                (ImageEnhance.Color, layer.saturation),
                                (ImageEnhance.Sharpness, layer.sharpness)):
            if value != 100:
                rgb = enhancer(rgb).enhance(value/100)
        rgb.putalpha(alpha)
        size = (max(1, round(layer.width*2)), max(1, round(layer.height*2)))
        if layer.fit == "cover":
            bitmap = ImageOps.fit(rgb, size, Image.Resampling.LANCZOS,
                                  centering=(layer.crop_x/100, layer.crop_y/100))
        elif layer.fit == "contain":
            fitted = ImageOps.contain(rgb, size, Image.Resampling.LANCZOS)
            bitmap = Image.new("RGBA", size)
            bitmap.alpha_composite(fitted, ((size[0]-fitted.width)//2, (size[1]-fitted.height)//2))
        else:
            bitmap = rgb.resize(size, Image.Resampling.LANCZOS)
    else:
        font = font_for(layer.font, round(layer.size*2), layer.bold)
        text = expand_text(layer.text, context or {}) or " "
        pen = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        stroke = round(layer.outline*2)
        box = pen.multiline_textbbox((0, 0), text, font=font, stroke_width=stroke, spacing=4, align=layer.align)
        width, height = math.ceil(box[2]-box[0]+8), math.ceil(box[3]-box[1]+8)
        if width*height > 8_000_000:
            raise ValueError("Text layer is too large; use line breaks or a smaller font")
        bitmap = Image.new("RGBA", (max(1, width), max(1, height)))
        draw = ImageDraw.Draw(bitmap)
        origin = (4-box[0], 4-box[1])
        if layer.shadow:
            draw.multiline_text((origin[0]+3, origin[1]+3), text, font=font, fill="#000000",
                                stroke_width=stroke+1, stroke_fill="#000000", spacing=4, align=layer.align)
        draw.multiline_text(origin, text, font=font, fill=layer.color, stroke_width=stroke,
                            stroke_fill=layer.outline_color, spacing=4, align=layer.align)
    if layer.angle:
        bitmap = bitmap.rotate(-layer.angle, Image.Resampling.BICUBIC, expand=True)
    if layer.opacity != 100:
        bitmap.putalpha(bitmap.getchannel("A").point(lambda a:round(a*layer.opacity/100)))
    return bitmap


class Document:
    def __init__(self, layers=None, background="#18202c"):
        self.layers = list(layers or [])
        self.background = background

    def clone(self):
        # Sources are immutable. History shares them, not full-resolution copies.
        return Document([replace(layer) for layer in self.layers], self.background)

    @classmethod
    def from_image(cls, image, name="Image"):
        return cls([Layer("image", name=name, image=load_image(image), width=320, height=240)])

    def add(self, layer):
        if len(self.layers) >= MAX_LAYERS:
            raise ValueError(f"At most {MAX_LAYERS} layers per image")
        layer.validate()
        self.layers.append(layer)
        return layer

    def render(self, context=None, *, bounds=False):
        canvas = Image.new("RGBA", (640, 480), self.background)
        boxes = {}
        for layer in self.layers:
            if not layer.visible:
                continue
            bitmap = layer_bitmap(layer, context)
            x, y = round(layer.x*2-bitmap.width/2), round(layer.y*2-bitmap.height/2)
            canvas.alpha_composite(bitmap, (x, y))
            boxes[layer.id] = (x/2, y/2, (x+bitmap.width)/2, (y+bitmap.height)/2)
        result = canvas.convert("RGB").resize(SIZE, Image.Resampling.LANCZOS)
        return (result, boxes) if bounds else result

    def to_json(self):
        layers = []
        for layer in self.layers:
            layer.validate()
            item = dict(vars(layer))
            source = item.pop("image")
            if source is not None:
                item["png"] = base64.b64encode(png_bytes(source)).decode("ascii")
            layers.append(item)
        result = json.dumps({"format":"open-kgstv-composition", "version":1,
                             "size":list(SIZE), "background":self.background, "layers":layers}, ensure_ascii=False)
        if len(result.encode("utf-8")) > MAX_DOCUMENT:
            raise ValueError("Composition exceeds 32 MB")
        return result

    @classmethod
    def from_json(cls, value):
        if len(value) > MAX_DOCUMENT:
            raise ValueError("Composition exceeds 32 MB")
        try:
            data = json.loads(value)
            if (data["format"] != "open-kgstv-composition" or data["version"] != 1 or
                    data["size"] != list(SIZE) or not isinstance(data["layers"], list) or
                    len(data["layers"]) > MAX_LAYERS):
                raise ValueError("Unsupported composition format")
            ImageColor.getrgb(data["background"])
            document = cls(background=data["background"])
            ids = set()
            for source in data["layers"]:
                item = dict(source)
                encoded = item.pop("png", None)
                if "image" in item:
                    raise ValueError("External image references are not supported")
                if encoded is not None:
                    raw = base64.b64decode(encoded, validate=True)
                    with Image.open(BytesIO(raw)) as image:
                        if image.width > 2048 or image.height > 2048:
                            raise ValueError("Embedded image exceeds 2048 pixels")
                        item["image"] = image.convert("RGBA")
                layer = Layer(**item)
                if layer.id in ids:
                    raise ValueError("Duplicate layer ID")
                ids.add(layer.id)
                document.add(layer)
            return document
        except (KeyError, TypeError, OSError, SyntaxError) as exc:
            raise ValueError("Invalid composition") from exc


class History:
    def __init__(self, limit=50):
        self.limit = limit
        self.past, self.future = [], []

    def push(self, document):
        self.past.append(document.clone())
        self.past = self.past[-self.limit:]
        self.future.clear()

    def undo(self, document):
        if not self.past:
            return document
        self.future.append(document.clone())
        return self.past.pop()

    def redo(self, document):
        if not self.future:
            return document
        self.past.append(document.clone())
        return self.future.pop()
