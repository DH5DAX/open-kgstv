import unittest
import numpy as np
from kgstv.protocol import text_frame, Command
from kgstv.modem import Receiver, modulate
from kgstv.audio import resample


class ModemTests(unittest.TestCase):
    def test_text_all_four_modes_arbitrary_timing(self):
        for mode in (0, 1):
            for fec in (False, True):
                with self.subTest(mode=mode, fec=fec):
                    text = "TEST>Hallo 日本語 73!"
                    wave = modulate([text_frame(text, mode=mode, fec=fec)], rate=48000, end_repeats=1)
                    wave = np.r_[np.zeros(137), wave]
                    # Also exercise a noninteger symbol/sample ratio in input.
                    wave = resample(resample(wave, 48000, 44100), 44100, 12000)
                    frames = list(Receiver().frames(wave))
                    self.assertEqual([f.text() for f in frames if f.header.com == Command.TEXT and f.crc_ok], [text])

    def test_frequency_offset_and_noise(self):
        from scipy.signal import hilbert
        rng = np.random.default_rng(112)
        wave = modulate([text_frame("TEST>frequency offset", fec=True)], rate=12000, end_repeats=1)
        wave = np.real(hilbert(wave)*np.exp(2j*np.pi*70*np.arange(len(wave))/12000))
        wave += rng.normal(0, .035, len(wave))
        decoded = list(Receiver(frequency_offset=70).frames(wave))
        self.assertEqual([f.text() for f in decoded if f.header.com == 0 and f.crc_ok], ["TEST>frequency offset"])

    def test_recovers_after_gap(self):
        first = modulate([text_frame("TEST>first")], rate=12000, end_repeats=1)
        second = modulate([text_frame("TEST>second")], rate=12000, end_repeats=1)
        wave = np.r_[first[:len(first)//2], np.zeros(3000), second]
        decoded = list(Receiver().frames(wave))
        self.assertIn("TEST>second", [f.text() for f in decoded if f.header.com == 0 and f.crc_ok])

    def test_silence_and_truncation(self):
        self.assertEqual(list(Receiver().frames(np.zeros(12000))), [])
        self.assertEqual(list(Receiver().frames(np.zeros(50))), [])
        wave = modulate([text_frame("TEST>truncated")], rate=12000, end_repeats=1)
        frames = list(Receiver().frames(wave[:5000]))
        self.assertFalse(any(f.header.com == 0 and f.crc_ok for f in frames))

    def test_cancellation(self):
        wave = modulate([text_frame("TEST>cancel")], rate=12000, end_repeats=1)
        self.assertEqual(list(Receiver().frames(wave, cancelled=lambda:True)), [])

    def test_image_variable_length_packets_all_modes(self):
        from PIL import Image
        from kgstv.session import image_frames
        y, x = np.indices((240, 320))
        image = Image.fromarray(np.stack((x % 256, y % 256, (x+y) % 256), axis=-1).astype(np.uint8))
        for mode in (0, 1):
            for fec in (False, True):
                with self.subTest(mode=mode, fec=fec):
                    tx = image_frames(image, "TEST", mode=mode, fec=fec, blocks=[(0, 0), (10, 7), (19, 14)])
                    rx = list(Receiver().frames(modulate(tx, rate=12000, end_repeats=1)))
                    expected = [f for f in tx if f.header.com == 1]
                    actual = [f for f in rx if f.header.com == 1]
                    self.assertEqual(len(actual), 3)
                    for a, b in zip(actual, expected):
                        self.assertTrue(a.crc_ok)
                        np.testing.assert_array_equal(a.payload, b.payload)


if __name__ == "__main__": unittest.main()
