import unittest
import numpy as np
from kgstv.protocol import (Header, Command, SYNC, WHITENING, crc16, bytes_to_bits,
    bits_to_bytes, bits, integer, convolution_encode, convolution_decode, whiten,
    text_frame, control_frame, Frame)


class ProtocolTests(unittest.TestCase):
    def test_original_text_crc_vector(self):
        payload = b"TEST3>The Quick Brown Fox Jumps Over The Lazy Dog 0123456789"
        self.assertEqual(crc16(bytes_to_bits(payload)), 0xA2D1)
        header = Header(size=480)
        self.assertEqual(integer(header.to_bits()[-16:]), 0x6702)
        self.assertEqual(Header.from_bits(header.to_bits()), header)

    def test_bit_serial_crc_not_padded(self):
        header = Header(size=480).to_bits()
        self.assertNotEqual(crc16(np.pad(header[:38], (0, 2))), integer(header[38:]))

    def test_bad_header_is_rejected(self):
        data = Header(size=480).to_bits(); data[15] ^= 1
        with self.assertRaises(ValueError): Header.from_bits(data)

    def test_validation(self):
        for values in (dict(sys=1), dict(com=15), dict(size=4096), dict(size=7), dict(sc=-1),
                       dict(com=Command.REQUEST, x=20), dict(com=Command.END, size=1)):
            with self.subTest(values=values), self.assertRaises(ValueError): Header(**values)
        with self.assertRaises(ValueError): Frame(Header(size=8), [1])
        with self.assertRaises(ValueError): bits_to_bytes([0])

    def test_fec_corrects_separated_channel_errors(self):
        data = bytes_to_bits(b"Known payload for a convolutional-code test.")
        encoded = convolution_encode(data)
        encoded[[30, 80, 150, 220]] ^= 1
        decoded, errors = convolution_decode(encoded.astype(float)*2-1)
        np.testing.assert_array_equal(decoded, data)
        self.assertEqual(errors, 4)

    def test_whitening_resets(self):
        self.assertEqual(len(SYNC), 63); self.assertEqual(len(WHITENING), 127)
        data = np.zeros(300, dtype=np.uint8)
        np.testing.assert_array_equal(whiten(data)[:127], WHITENING)
        np.testing.assert_array_equal(whiten(whiten(data)), data)
        np.testing.assert_array_equal(whiten(data)[127:254], WHITENING)

    def test_text_byte_limits_and_japanese(self):
        frame = text_frame("日本語 73", callsign="TEST")
        self.assertEqual(frame.text(), "TEST>日本語 73")
        text_frame("A"*510)
        with self.assertRaises(ValueError): text_frame("A"*511)
        with self.assertRaises(ValueError): text_frame("", callsign="")
        with self.assertRaises(ValueError): text_frame(" ", command=Command.CALLSIGN)
        with self.assertRaises(UnicodeEncodeError): text_frame("🙂")

    def test_control_has_no_payload_segment(self):
        self.assertEqual(len(list(control_frame(Command.REQUEST, x=19, y=14).segments())), 1)


if __name__ == "__main__": unittest.main()
