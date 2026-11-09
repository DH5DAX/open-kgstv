"""Frequency/level accuracy, audio-thread isolation and the operating display."""
from contextlib import contextmanager
import unittest
from unittest.mock import Mock, patch

import numpy as np

from kgstv.live import LiveReceiver
from kgstv.waterfall import AudioMonitor, SpectrumAnalyzer, FREQUENCIES, HOP, SAMPLE_RATE
from tests import test_gui


def tone(hz, amplitude=.25, count=HOP):
    return (amplitude * np.cos(2*np.pi*hz*np.arange(count)/SAMPLE_RATE)).astype(np.float32)


class SpectrumTests(unittest.TestCase):
    def test_frequency_endpoints_and_tone_amplitude_calibration(self):
        self.assertEqual((FREQUENCIES[0], FREQUENCIES[-1]), (0, 3000))
        for hz in (0, 750, 1500, 2250, 3000):
            with self.subTest(hz=hz):
                row = SpectrumAnalyzer().feed([(0, tone(hz), False)])[0]
                if hz:  # Windowing DC also produces an equally high adjacent bin.
                    self.assertEqual(FREQUENCIES[np.argmax(row.db)], hz)
                self.assertAlmostEqual(row.db[np.flatnonzero(FREQUENCIES == hz)[0]], 20*np.log10(.25), delta=.02)
                self.assertAlmostEqual(row.peak_db, 20*np.log10(.25), delta=.01)
                self.assertFalse(row.clipped)

    def test_outside_passband_silence_and_clipping(self):
        analyzer = SpectrumAnalyzer()
        outside = analyzer.feed([(0, tone(4500), False)])[0]
        self.assertLess(max(outside.db), -100)
        silence = analyzer.feed([(1, np.zeros(HOP), False)])[0]
        self.assertTrue(np.isfinite(silence.db).all())
        self.assertLess(max(silence.db), -200)
        clipped = analyzer.feed([(2, np.clip(tone(1500, 2), -1, 1), False)])[0]
        self.assertTrue(clipped.clipped)
        self.assertEqual(clipped.peak_db, 0)

    def test_row_timing_is_independent_of_gui_polling_and_capture_chunks(self):
        samples = tone(1500, count=HOP*7+315)
        analyzer = SpectrumAnalyzer()
        rows = []
        for sequence, start in enumerate(range(0, len(samples), 317)):
            rows.extend(analyzer.feed([(sequence, samples[start:start+317], False)]))
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(FREQUENCIES[np.argmax(row.db)] == 1500 for row in rows))

    def test_preview_backpressure_keeps_recent_audio_and_marks_discontinuities(self):
        monitor = AudioMonitor()
        analyzer = SpectrumAnalyzer()
        monitor.publish(tone(750, count=600))
        self.assertEqual(analyzer.feed(monitor.drain()), [])
        for _ in range(40):
            monitor.publish(tone(2250))
        chunks = monitor.drain()
        self.assertEqual(len(chunks), 12)
        self.assertEqual([chunk[0] for chunk in chunks], list(range(29, 41)))
        rows = analyzer.feed(chunks)
        self.assertIsNone(rows[0])
        self.assertEqual(len(rows), 13)
        self.assertTrue(all(FREQUENCIES[np.argmax(row.db)] == 2250 for row in rows[1:]))
        self.assertEqual(monitor.drain(), [])

    def test_capture_gap_and_invalid_samples_never_join_unrelated_audio(self):
        analyzer = SpectrumAnalyzer()
        self.assertEqual(analyzer.feed([(0, tone(750, count=600), False)]), [])
        after_gap = tone(2250)
        self.assertEqual(analyzer.feed([(1, after_gap[:600], True)]), [None])
        row = analyzer.feed([(2, after_gap[600:], False)])[0]
        self.assertEqual(FREQUENCIES[np.argmax(row.db)], 2250)
        self.assertEqual(analyzer.feed([(3, np.full(HOP, np.nan), False)]), [None])
        self.assertTrue(np.isfinite(analyzer.feed([(4, tone(1500), False)])[0].db).all())

    def test_live_capture_publishes_before_decoder_runs_and_owns_its_buffer(self):
        monitor = AudioMonitor()
        received = []
        receiver = LiveReceiver(lambda *event: received.append(event), audio_monitor=monitor)
        source = tone(1500)[:, None]

        @contextmanager
        def fake_input(**kwargs):
            self.assertEqual(kwargs['samplerate'], SAMPLE_RATE)
            kwargs['callback'](source, HOP, None, True)
            # PortAudio reuses its input buffer; preview must retain the copy.
            source[:] = 0
            chunks = monitor.drain()
            self.assertEqual(len(chunks), 1)
            self.assertTrue(chunks[0][2])
            self.assertGreater(np.max(abs(chunks[0][1])), .2)
            receiver.stop()
            yield

        audio = Mock(InputStream=fake_input)
        with patch.dict('sys.modules', {'sounddevice': audio}), patch('kgstv.live.Receiver') as decoder:
            receiver._run()
            decoder.return_value.frames.assert_not_called()
        self.assertNotIn('error', [event[0] for event in received])
        self.assertIn(('stopped', None), received)


class WaterfallDesktopTests(unittest.TestCase):
    setUp = test_gui.DesktopTests.setUp
    drain = test_gui.DesktopTests.drain

    def test_monitor_follows_rx_then_freezes_and_resets_on_restart(self):
        app = self.app
        with patch('kgstv.live.LiveReceiver') as live:
            app.start_live()
            self.assertIs(live.call_args.kwargs['audio_monitor'], app.audio_monitor)
            app.audio_monitor.publish(tone(1500))
            self.drain()
            self.assertTrue(app.waterfall.running)
            self.assertTrue(app.waterfall.has_audio)
            before = app.waterfall.history.copy()
            app.set_language('de', persist=False)
            np.testing.assert_array_equal(before, app.waterfall.history)
            app.stop()
            app.events.put(('stopped', None))
            self.drain()
            self.assertFalse(app.waterfall.running)
            np.testing.assert_array_equal(before, app.waterfall.history)
            app.start_live()
            self.assertFalse(app.waterfall.has_audio)
            self.assertEqual(app.audio_monitor.drain(), [])
            app.live = None

    def test_compact_layout_keeps_chat_and_waterfall_visible_in_both_languages(self):
        self.root.deiconify()
        self.root.geometry('940x640')
        for language in ('en', 'de'):
            self.app.set_language(language, persist=False)
            self.root.update()
            display = self.app.waterfall
            self.assertGreaterEqual(display.winfo_width(), 340)
            self.assertGreaterEqual(display.winfo_height(), 140)
            self.assertGreater(self.app.log.winfo_width(), 350)
            self.assertGreater(self.app.log.winfo_height(), 100)
            for widget in (display, self.app.log):
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+940)
                self.assertLess(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+640)
            labels = [display.itemcget(item, 'text') for item in display.find_all() if display.type(item) == 'text']
            self.assertIn(self.app.tr('waterfall'), labels)
            self.assertIn('3 kHz', labels)
            for event in ('<Motion>', '<Button-1>'):
                display.event_generate(event, x=display.winfo_width()//2, y=70)
                self.root.update()
                labels = [display.itemcget(item, 'text') for item in display.find_withtag('cursor')
                          if display.type(item) == 'text']
                self.assertEqual(labels, ['1500 Hz'])
            display.event_generate('<Leave>')
            self.root.update()
            self.assertEqual(display.find_withtag('cursor'), ())
