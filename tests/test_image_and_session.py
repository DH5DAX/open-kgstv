import unittest
import numpy as np
from PIL import Image
from kgstv.imagecodec import encode_tile, decode_tile, InvalidTile, quantization, BitReader, _amplitude
from kgstv.session import Session, image_frames, request_frames
from kgstv.protocol import Command, Frame, Header, text_frame, control_frame


class ImageTests(unittest.TestCase):
    def test_original_coefficient_sign_convention(self):
        self.assertEqual(_amplitude(BitReader([0, 0]), 2), -2)
        self.assertEqual(_amplitude(BitReader([0, 1]), 2), -3)
        self.assertEqual(_amplitude(BitReader([1, 0]), 2), 2)
        self.assertEqual(_amplitude(BitReader([1, 1]), 2), 3)

    def test_fractional_quantization(self):
        self.assertEqual(quantization(7)[0, 1], 5.5)
        self.assertAlmostEqual(quantization(3)[0, 0], 1.6)

    def test_primary_colors_at_all_scales(self):
        for scale in range(16):
            for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128)):
                with self.subTest(scale=scale, color=color):
                    src = np.tile(color, (16, 16, 1))
                    result = decode_tile(encode_tile(src, scale), scale)
                    self.assertLessEqual(np.max(abs(result.astype(int)-src)), 9)

    def test_texture_and_malformed_tile(self):
        tile = np.zeros((16, 16, 3), dtype=np.uint8)
        tile[::2] = 255
        payload = encode_tile(tile, 10)
        image = decode_tile(payload, 10)
        self.assertGreater(image[::2].mean()-image[1::2].mean(), 200)
        with self.assertRaises(InvalidTile): decode_tile(payload[:10], 10)
        with self.assertRaises(InvalidTile): decode_tile(np.r_[payload, 0], 10)

    def test_sender_callsign_cadence_and_scan_orders(self):
        source = Image.new("RGB", (320, 240), (20, 100, 200))
        for scan in ("horizontal", "vertical", "random"):
            frames = image_frames(source, "TEST", scan=scan, seed=1)
            self.assertEqual(sum(f.header.com == Command.CALLSIGN for f in frames), 36)
            self.assertEqual(len({(f.header.x, f.header.y) for f in frames if f.header.com == 1}), 300)

    def test_bsr_repairs_only_matching_station(self):
        s = Session()
        tile = encode_tile(np.zeros((16, 16, 3)), 10)
        s.accept(text_frame("ORIGINAL", command=Command.CALLSIGN))
        s.accept(Frame(Header(com=Command.IMAGE, x=0, y=0, size=len(tile)), tile))
        s.accept(control_frame(Command.END))
        s.accept(text_frame("OTHER", command=Command.CALLSIGN))
        repair = Frame(Header(com=Command.REPAIR, x=1, y=0, size=len(tile)), tile)
        self.assertEqual(s.accept(repair), "ignored_repair")
        s.accept(text_frame("ORIGINAL", command=Command.CALLSIGN)); s.accept(repair)
        self.assertEqual(int(s.current_image.good.sum()), 2)
        self.assertEqual(len(s.current_image.missing()), 298)

    def test_bsr_request_session_resets(self):
        s = Session()
        for f in request_frames([(1, 2), (3, 4)], "TEST"): s.accept(f)
        self.assertEqual(s.requested, {(1, 2), (3, 4)})
        s.accept(control_frame(Command.END))
        for f in request_frames([(0, 0)], "NEXT"): s.accept(f)
        self.assertEqual(s.requested, {(0, 0)}); self.assertEqual(s.requester, "NEXT")

    def test_repeated_callsign_does_not_erase_image(self):
        s = Session()
        frames = image_frames(Image.new("RGB", (320, 240)), "TEST")
        for f in frames: s.accept(f)
        self.assertEqual(len(s.images), 1)
        self.assertTrue(s.current_image.complete)
        s.accept(control_frame(Command.END))
        for f in frames[:7]: s.accept(f)
        self.assertEqual(len(s.images), 2)


if __name__ == "__main__": unittest.main()
