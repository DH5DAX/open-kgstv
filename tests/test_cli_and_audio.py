import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock
import numpy as np
from scipy.io import wavfile
from kgstv.cli import main
from kgstv.audio import load_audio
from kgstv.live import play_audio, LiveReceiver


class InterfaceTests(unittest.TestCase):
    def test_cli_text_wav_to_report(self):
        with TemporaryDirectory() as directory:
            wave = Path(directory)/"message.wav"
            output = Path(directory)/"rx"
            self.assertEqual(main(["encode-text", "CLI test", "--callsign", "TEST", "--mode", "4fsk",
                                   "--fec", "--output", str(wave)]), 0)
            self.assertEqual(main(["decode", str(wave), "--output", str(output)]), 0)
            report = json.loads((output/"report.json").read_text())
            self.assertEqual(report["session"]["messages"], ["TEST>CLI test"])
            self.assertEqual(main(["decode", str(wave), "--output", str(output)]), 1)
            self.assertEqual(main(["encode-text", "x", "--callsign", "TEST", "--output", str(wave)]), 1)

    def test_pcm_uint8_stereo(self):
        with TemporaryDirectory() as directory:
            wave = Path(directory)/"silence.wav"
            wavfile.write(wave, 12000, np.full((12000, 2), 128, dtype=np.uint8))
            self.assertEqual(np.max(abs(load_audio(wave))), 0)

    def test_ptt_is_released_on_audio_failure(self):
        fake_audio = Mock(); fake_audio.play.side_effect = RuntimeError("output disconnected")
        fake_serial = Mock(); port = fake_serial.Serial.return_value
        with patch.dict("sys.modules", {"sounddevice": fake_audio, "serial": fake_serial}):
            with self.assertRaises(RuntimeError): play_audio(np.zeros(10), port="TEST-PORT")
        self.assertFalse(port.rts); port.close.assert_called_once()
        fake_audio.stop.assert_called_once()

    def test_ptt_is_released_even_if_audio_cleanup_fails(self):
        fake_audio = Mock()
        fake_audio.play.side_effect = RuntimeError("output disconnected")
        fake_audio.stop.side_effect = RuntimeError("audio cleanup failed")
        fake_serial = Mock(); port = fake_serial.Serial.return_value
        with patch.dict("sys.modules", {"sounddevice": fake_audio, "serial": fake_serial}):
            with self.assertRaises(RuntimeError): play_audio(np.zeros(10), port="TEST-PORT", ptt_line="dtr")
        self.assertFalse(port.dtr); port.close.assert_called_once()

    def test_cancel_before_play_opens_nothing(self):
        fake_audio, fake_serial = Mock(), Mock()
        with patch.dict("sys.modules", {"sounddevice": fake_audio, "serial": fake_serial}):
            play_audio(np.zeros(10), port="TEST-PORT", cancelled=lambda:True)
        fake_audio.play.assert_not_called(); fake_serial.Serial.assert_not_called()

    def test_live_receiver_crosses_windows_without_duplicate_text(self):
        from kgstv.modem import modulate
        from kgstv.protocol import text_frame, Command
        from contextlib import contextmanager
        messages = ['TEST>'+letter*128 for letter in ('A', 'B')]
        samples = modulate([text_frame(s) for s in messages], rate=12000, end_repeats=1)
        samples = np.r_[samples, np.zeros(3*12000)]
        received, errors = [], []

        @contextmanager
        def fake_input(**kwargs):
            for start in range(0, len(samples), 1200):
                part = samples[start:start+1200, None]
                kwargs['callback'](part, len(part), None, False)
            yield

        def callback(event, data):
            if event == 'frame':
                frame, _ = data
                if frame.header.com == Command.TEXT:
                    received.append(frame.text())
                if frame.header.com == Command.END:
                    receiver.stop()
            elif event == 'error':
                errors.append(data)

        fake_audio = Mock(); fake_audio.InputStream.side_effect = fake_input
        receiver = LiveReceiver(callback)
        with patch.dict('sys.modules', {'sounddevice':fake_audio}):
            try:
                receiver.start()
                receiver.thread.join(timeout=10)
                self.assertFalse(receiver.thread.is_alive(), 'Live decoder did not reach END')
                self.assertFalse(errors)
                self.assertEqual(received, messages)
            finally:
                receiver.stop()
                receiver.thread.join(timeout=2)


if __name__ == "__main__": unittest.main()
