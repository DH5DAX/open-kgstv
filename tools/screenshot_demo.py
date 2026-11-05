"""Reproducible documentation scenes in the real GUI; no audio devices opened.

Run from the checkout: python tools/screenshot_demo.py image|missing|text
Capture the application window after outputs/screenshots/<scene>.json appears.
The test card is original project artwork, covered by the project's MIT license.
"""
import argparse
import json
from pathlib import Path
import sys
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kgstv.gui import Application
from kgstv.modem import Receiver, modulate
from kgstv.protocol import Command, text_frame
from kgstv.session import Session, image_frames


def test_card():
    """An original 320x240 calibration card, without external image assets."""
    image = Image.new("RGB", (320, 240), "#12202f")
    draw = ImageDraw.Draw(image)
    colors = ("#ffffff", "#ffe05c", "#5cd8e8", "#51cf95", "#cc80eb", "#f46c74", "#608cf0", "#192737")
    for n, color in enumerate(colors):
        draw.rectangle((n*40, 0, n*40+39, 37), fill=color)
    for x in range(0, 320, 16):
        draw.line((x, 46, x, 191), fill="#24364a")
    for y in range(48, 192, 16):
        draw.line((0, y, 319, y), fill="#24364a")
    draw.rounded_rectangle((13, 60, 306, 172), radius=12, fill="#12202f", outline="#57d0d4", width=2)
    draw.text((27, 77), "OPEN KG-STV", font=ImageFont.load_default(size=31), fill="#ffffff")
    draw.text((28, 122), "320 x 240  /  300 blocks", font=ImageFont.load_default(size=17), fill="#57d0d4")
    for x in range(320):
        value = round(x*255/319)
        draw.line((x, 196, x, 219), fill=(value, value, value))
    draw.text((14, 225), "MSK / 4L-FSK     73 DE TEST", font=ImageFont.load_default(size=12), fill="#ffffff")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", choices=("image", "missing", "text"))
    args = parser.parse_args()
    output = ROOT/"outputs"/"screenshots"
    output.mkdir(parents=True, exist_ok=True)

    root = tk.Tk()
    app = Application(root)
    root.title(f"Open KG-STV | Documentation: {args.scene}")
    app.callsign.set("TEST")
    if args.scene != "text":
        app.mode.set("4L-FSK")
        app.fec.set(True)
        app.tx_image = test_card()
        app._show(app.tx_preview, app.tx_image)
        root.geometry("1000x850")
    app.message.insert(0, "CQ CQ de TEST - open-source digital SSTV")
    details = {}

    def receive():
        session = Session()
        receiver = Receiver()
        if args.scene == "text":
            messages = (
                "CQ CQ de TEST - open-source digital SSTV",
                "MSK at 1200 baud. Image and text transmission.",
                "The quick brown fox jumps over the lazy dog. 73!",
            )
            transmitted = [text_frame(message, callsign="TEST") for message in messages]
        else:
            transmitted = image_frames(app.tx_image, "TEST", mode=1, fec=True)
            if args.scene == "missing":
                transmitted = [frame for frame in transmitted if not (
                    frame.header.com == Command.IMAGE and
                    14 <= frame.header.x < 20 and 9 <= frame.header.y < 13)]
        audio = modulate(transmitted, rate=12000)
        for frame in receiver.frames(audio, cancelled=app.cancelled.is_set):
            session.accept(frame)
            app._on_frame(frame, session)
        if app.cancelled.is_set():
            return
        if receiver.stats.bad_payloads:
            raise RuntimeError("The documentation loopback has CRC errors")
        if args.scene == "text":
            expected = ["TEST>"+message for message in messages]
            if session.messages != expected:
                raise RuntimeError("Text loopback did not decode all messages")
            status = "Demo: MSK-Textempfang aus erzeugten Audiodaten · 3 Nachrichten · CRC gültig"
        else:
            good = int(session.current_image.good.sum())
            if good != (276 if args.scene == "missing" else 300):
                raise RuntimeError(f"Unexpected image block count: {good}")
            status = f"Demo: eigener WAV-Sende-/Empfangstest · {good}/300 Bildblöcke"
            if args.scene == "missing":
                status += " · 24 Blöcke absichtlich ausgelassen"
            else:
                status += " · keine CRC-Fehler"
        app.events.put(("progress", 100))
        app.events.put(("status", status))
        details.update(scene=args.scene, session=session.summary(), crc_errors=receiver.stats.bad_payloads)

    def start():
        app._worker(receive)
        root.after(100, ready)

    def ready():
        if app.busy:
            root.after(100, ready)
        elif details:
            (output/(args.scene+".json")).write_text(json.dumps(details, indent=2)+"\n", encoding="utf-8")

    root.after(300, start)
    root.mainloop()


if __name__ == "__main__":
    main()
