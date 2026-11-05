"""Command-line entry point; all transmit commands write WAV, never play it."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from PIL import Image
from . import __version__
from .audio import load_audio, save_wav
from .modem import Receiver, modulate
from .protocol import SCALES, text_frame
from .session import Session, image_frames, request_frames


def parser():
    root = argparse.ArgumentParser(prog="kgstv", description="Open KG-STV — Python digital image modem")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    dec = commands.add_parser("decode", help="Decode a WAV/MP3 recording to PNG and JSON")
    dec.add_argument("input", type=Path)
    dec.add_argument("--output", type=Path, default=Path("decoded"))
    dec.add_argument("--frequency-offset", type=float, default=0)
    dec.add_argument("--include-payload", action="store_true")
    dec.add_argument("--decode-corrupt", action="store_true", help="Attempt damaged tiles; retain failed status")
    dec.add_argument("--force", action="store_true", help="Allow replacing the output directory's named files")
    txt = commands.add_parser("encode-text", help="Encode text to a WAV file")
    txt.add_argument("text")
    img = commands.add_parser("encode-image", help="Encode an image to a WAV file")
    img.add_argument("image", type=Path)
    img.add_argument("--scale", type=float, choices=SCALES, default=1.0)
    img.add_argument("--scan", choices=("horizontal", "vertical", "random"), default="horizontal")
    img.add_argument("--repair-request", type=Path, help="Decoded BSR report selecting blocks to resend (experimental)")
    req = commands.add_parser("request-repair", help="Create a BSR WAV from missing blocks in a decode report (experimental)")
    req.add_argument("report", type=Path)
    req.add_argument("--image-index", type=int, default=-1)
    for sub in (txt, img, req):
        sub.add_argument("--callsign", required=True)
        sub.add_argument("--output", required=True, type=Path)
        sub.add_argument("--force", action="store_true")
        sub.add_argument("--end-repeats", type=int, default=10)
    for sub in (txt, img):
        sub.add_argument("--mode", choices=("msk", "4fsk"), default="msk")
        sub.add_argument("--fec", action="store_true")
    commands.add_parser("gui", help="Open the desktop application")
    commands.add_parser("devices", help="List available sound devices")
    return root


def decode_file(path, output, *, frequency_offset=0, include_payload=False,
                decode_corrupt=False, force=False, on_frame=None, progress=None, cancelled=None):
    output = Path(output)
    if output.exists() and any(output.iterdir()) and not force:
        raise ValueError("Output directory is not empty; choose a new directory or use --force")
    samples = load_audio(path)
    receiver = Receiver(frequency_offset=frequency_offset)
    session = Session(decode_corrupt=decode_corrupt)
    frames = []
    for frame in receiver.frames(samples, progress=progress, cancelled=cancelled):
        session.accept(frame)
        frames.append(frame.to_dict(include_payload))
        if on_frame:
            on_frame(frame, session)
    if cancelled and cancelled():
        raise InterruptedError("Decoding cancelled")
    output.mkdir(parents=True, exist_ok=True)
    summary = session.summary()
    for n, image in enumerate(session.images, 1):
        filename = f"image-{n:03d}.png"
        Image.fromarray(image.pixels).save(output/filename)
        summary["images"][n-1]["file"] = filename
    result = dict(application="open-kgstv", version=__version__, input=str(path),
                  sample_rate=receiver.rate, audio_seconds=len(samples)/receiver.rate,
                  stats=asdict(receiver.stats), session=summary, frames=frames,
                  compatibility="Original audio RX tested; original-application TX and BSR interoperability pending")
    (output/"report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import main as gui_main
            gui_main(); return 0
        if args.command == "devices":
            import sounddevice as sd
            print(sd.query_devices()); return 0
        if args.command == "decode":
            result = decode_file(args.input, args.output, frequency_offset=args.frequency_offset,
                                 include_payload=args.include_payload, decode_corrupt=args.decode_corrupt,
                                 force=args.force)
            print(json.dumps(dict(stats=result["stats"], session=result["session"]), ensure_ascii=False, indent=2))
            print(f"Saved: {args.output / 'report.json'}")
            return 0 if result["stats"]["headers"] else 2
        if args.output.exists() and not args.force:
            raise ValueError("Output file exists; choose another path or use --force")
        if args.output.suffix.lower() != ".wav":
            raise ValueError("Transmit output must be a .wav file")
        if args.command == "encode-text":
            frames = [text_frame(args.text, callsign=args.callsign, mode=int(args.mode == "4fsk"), fec=args.fec)]
        elif args.command == "encode-image":
            blocks = None
            if args.repair_request:
                data = json.loads(args.repair_request.read_text(encoding="utf-8"))
                blocks = data["session"]["requested_blocks"]
            frames = image_frames(args.image, args.callsign, mode=int(args.mode == "4fsk"), fec=args.fec,
                                  scale_index=SCALES.index(args.scale), scan=args.scan,
                                  blocks=blocks, repair=args.repair_request is not None)
        else:
            data = json.loads(args.report.read_text(encoding="utf-8"))
            missing = data["session"]["images"][args.image_index]["missing"]
            frames = request_frames(missing, args.callsign)
        audio = modulate(frames, end_repeats=args.end_repeats)
        save_wav(args.output, audio)
        print(f"Saved {args.output} ({len(audio)/48000:.2f} seconds, 48000 Hz mono)")
        return 0
    except (OSError, ValueError, KeyError, IndexError, ImportError) as exc:
        print(f"kgstv: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
