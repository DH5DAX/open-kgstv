"""Independent original-signal fixtures. Downloads are intentionally unbundled."""
import hashlib
import json
from pathlib import Path
import unittest
import numpy as np
from PIL import Image
from kgstv.audio import load_audio
from kgstv.modem import Receiver
from kgstv.session import Session

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT/"research"/"reference"
AVAILABLE = all((REF/(name+".mp3")).is_file() for name in (
    "KG-STV_MSK_text", "KG-STV_4L-FSK_text", "KG-STV_MSK_Norm", "KG-STV_MSK_Convolution",
    "KG-STV_4LFSK_Norm", "KG-STV_4LFSK_Convolution", "KG-STV_.10_scale", "KG-STV_.50_scale"))


@unittest.skipUnless(AVAILABLE, "Original recordings absent; see tools/fetch_fixtures.py")
class OriginalRecordingTests(unittest.TestCase):
    def test_pinned_recording_hashes(self):
        entries = json.loads((ROOT/"tests"/"fixtures.json").read_text())
        for entry in entries:
            name = entry["filename"]
            self.assertEqual(hashlib.sha256((REF/name).read_bytes()).hexdigest(), entry["sha256"])

    def test_original_text_in_both_modes(self):
        for name in ("KG-STV_MSK_text", "KG-STV_4L-FSK_text"):
            with self.subTest(recording=name):
                frames = list(Receiver().frames(load_audio(REF/(name+".mp3"))))
                self.assertEqual([f.text() for f in frames if f.header.com == 0 and f.crc_ok],
                                 ["TEST3>The Quick Brown Fox Jumps Over The Lazy Dog 0123456789"])

    def test_all_six_original_images(self):
        references = {
            "KG-STV_MSK_Norm": "reference-scale-1.png",
            "KG-STV_MSK_Convolution": "reference-scale-1.png",
            "KG-STV_4LFSK_Norm": "reference-scale-1.png",
            "KG-STV_4LFSK_Convolution": "reference-scale-1.png",
            "KG-STV_.50_scale": "reference-scale-05.png",
            "KG-STV_.10_scale": None,
        }
        for name, reference in references.items():
            with self.subTest(recording=name):
                session = Session(); receiver = Receiver()
                for frame in receiver.frames(load_audio(REF/(name+".mp3"))):
                    session.accept(frame)
                self.assertEqual(receiver.stats.bad_payloads, 0)
                self.assertEqual(receiver.stats.valid_payloads, 336)
                self.assertEqual(len(session.images), 1)
                self.assertTrue(session.current_image.complete)
                self.assertEqual(session.current_image.codec_errors, 0)
                if reference:
                    self.assertTrue((REF/reference).exists(), f"Missing reference PNG: {reference}")
                    expected = np.asarray(Image.open(REF/reference).convert("RGB"), dtype=int)
                    delta = abs(session.current_image.pixels.astype(int)-expected)
                    self.assertLessEqual(int(delta.max()), 1)
                    self.assertLess(float(delta.mean()), .01)


if __name__ == "__main__": unittest.main()
