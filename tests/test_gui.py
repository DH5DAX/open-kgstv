"""Language switching and desktop workflows, without audio or radio hardware."""
import json
from pathlib import Path
from string import Formatter
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

from kgstv.i18n import EN, DE, load_language, save_language


class LanguageTests(unittest.TestCase):
    def test_catalogues_have_matching_format_fields(self):
        self.assertEqual(EN.keys(), DE.keys())
        formatter = Formatter()
        for key in EN:
            with self.subTest(key=key):
                fields = lambda text:{(name, spec) for _, name, spec, _ in formatter.parse(text) if name}
                self.assertEqual(fields(EN[key]), fields(DE[key]))

    def test_preferences_persist_and_preserve_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"settings.json"
            self.assertEqual(load_language(path), "en")
            path.write_text('{"other": 42}', encoding="utf-8")
            save_language(path, "de")
            self.assertEqual(load_language(path), "de")
            self.assertEqual(json.loads(path.read_text())["other"], 42)
            save_language(path, "en")
            self.assertEqual(load_language(path), "en")
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])
            with self.assertRaises(ValueError):
                save_language(path, "fr")

    def test_bad_settings_fall_back_to_english(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"settings.json"
            for contents in ("broken", "[]", '{"language":"fr"}', '{"language":[]}'):
                path.write_text(contents, encoding="utf-8")
                self.assertEqual(load_language(path), "en")
            save_language(path, "de")
            self.assertEqual(load_language(path), "de")


class DesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
        except ImportError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        except tk.TclError as exc:
            # Tk is optional for command-line-only/headless installations.
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.root.destroy)
        self.settings = Path(self.folder.name)/"settings.json"
        from kgstv.gui import Application
        self.app = Application(self.root, settings_path=self.settings)
        self.addCleanup(lambda:self.root.after_cancel(self.app._poll_after))
        self.root.update_idletasks()

    def drain(self):
        self.root.after_cancel(self.app._poll_after)
        self.app._poll()

    def wait_for_worker(self):
        deadline = time.monotonic()+15
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app.busy, "GUI worker did not finish")

    def test_switch_preserves_draft_images_devices_and_reception(self):
        from PIL import Image
        app = self.app
        app.callsign.set("TEST")
        app.mode.set("4L-FSK")
        app.fec.set(True)
        app.scale.set("0.5")
        app.message.insert(0, "CQ de TEST")
        app.frequency.set("70")
        app.ptt_port.set("COM8")
        app.ptt_line.set("dtr")
        app.tx_image = Image.new("RGB", (320, 240), "red")
        app.rx_image = app.tx_image.copy()
        app.rx_summary = {"callsign":"TEST", "good_blocks":299, "missing":[(0, 0)]}
        app._show(app.tx_preview, app.tx_image)
        app._show(app.rx_preview, app.rx_image)
        app.events.put(("text", "TEST>received 日本語"))
        app.events.put(("request", [2, 5]))
        self.drain()
        app._devices = [{"name":"Test input", "max_input_channels":1, "max_output_channels":0},
                        {"name":"Test output", "max_input_channels":0, "max_output_channels":2}]
        app._refresh_device_labels((0, 1))
        app.show_page("audio_tab")
        receiver = Mock()
        app.live = receiver
        app._set_activity("rx")
        app._set_status("live_receiving")
        with patch("kgstv.gui.save_language", wraps=save_language) as save:
            app.language_buttons["de"].invoke()
            save.assert_called_once_with(self.settings, "de")
        self.assertEqual(app.language, "de")
        self.assertEqual(load_language(self.settings), "de")
        self.assertEqual(app.page, "audio_tab")
        self.assertIs(app.live, receiver)
        receiver.stop.assert_not_called()
        self.assertEqual(app.activity_label.cget("text"), "● EMPFANG")
        self.assertEqual(app.status.get(), DE["live_receiving"])
        self.assertEqual(app.block_status.get(), "TEST · 1 fehlen")
        self.assertEqual((app.callsign.get(), app.mode.get(), app.fec.get(), app.scale.get()),
                         ("TEST", "4L-FSK", True, "0.5"))
        self.assertEqual((app.frequency.get(), app.ptt_port.get(), app.ptt_line.get()), ("70", "COM8", "dtr"))
        self.assertEqual(app.message.get(), "CQ de TEST")
        self.assertEqual(app.log.get("1.0", "end-1c"), "TEST>received 日本語\n")
        self.assertEqual(app.requested_blocks, [2, 5])
        self.assertIs(app.tx_preview.source, app.tx_image)
        self.assertIs(app.rx_preview.source, app.rx_image)
        self.assertEqual((app.device_ids[app.input_device.get()], app.device_ids[app.output_device.get()]), (0, 1))
        app.set_language("en", persist=False)
        self.assertEqual(app.status.get(), EN["live_receiving"])
        app._refresh_device_labels((None, None))
        app.set_language("de", persist=False)
        self.assertEqual(app.input_device.get(), DE["default_device"])
        self.assertIsNone(app.device_ids[app.input_device.get()])
        app.live = None

    def test_worker_status_uses_current_language_and_cancel_is_not_an_error(self):
        release = threading.Event()
        self.addCleanup(release.set)
        def work():
            release.wait(3)
            self.app._post_status("requested", count=24)
            if self.app.cancelled.is_set():
                raise InterruptedError("cancelled")
        self.app._worker(work)
        self.app.set_language("de", persist=False)
        release.set()
        self.wait_for_worker()
        self.assertEqual(self.app.status.get(), DE["requested"].format(count=24))
        release.clear()
        with patch("kgstv.gui.messagebox.showerror") as error:
            self.app._worker(work)
            self.app.stop()
            release.set()
            self.wait_for_worker()
            error.assert_not_called()
        self.assertEqual(self.app.status.get(), DE["stopped"])
        self.assertTrue(self.app.stop_button.instate(["disabled"]))

    def test_text_wav_export_decodes_after_language_switch(self):
        from kgstv.audio import load_audio
        from kgstv.modem import Receiver
        path = Path(self.folder.name)/"message.wav"
        self.app.callsign.set("TEST")
        self.app.message.insert(0, "CQ de TEST 日本語")
        with patch("kgstv.gui.filedialog.asksaveasfilename", return_value=str(path)), \
             patch("kgstv.live.play_audio") as play, patch("kgstv.gui.messagebox.showerror") as error:
            self.app.encode("text", False)
            self.app.set_language("de", persist=False)
            self.wait_for_worker()
            play.assert_not_called()
            error.assert_not_called()
        frames = list(Receiver().frames(load_audio(path)))
        self.assertEqual([frame.text() for frame in frames if frame.header.com == 0], ["TEST>CQ de TEST 日本語"])
        self.assertTrue(self.app.status.get().startswith("WAV gespeichert"))

    def test_validation_dialogs_follow_language_before_hardware_access(self):
        with patch("kgstv.gui.messagebox.showerror") as error, patch("kgstv.live.LiveReceiver") as receiver:
            self.app.set_language("de", persist=False)
            self.app.encode("text", True)
            self.assertEqual(error.call_args.args, (DE["error_title"], DE["missing_call"]))
            self.app.frequency.set("nan")
            self.app.start_live()
            self.assertEqual(error.call_args.args, (DE["error_title"], DE["invalid_frequency"]))
            receiver.assert_not_called()
            self.app.frequency.set("12,5")
            self.assertEqual(self.app._frequency(), 12.5)

    def test_preferences_are_loaded_without_opening_hardware(self):
        save_language(self.settings, "de")
        from kgstv.gui import Application
        import tkinter as tk
        other = tk.Toplevel(self.root)
        other.withdraw()
        with patch("kgstv.live.LiveReceiver") as receiver, patch("kgstv.live.play_audio") as play:
            app = Application(other, settings_path=self.settings)
            try:
                self.assertEqual(app.language, "de")
                app.set_language("en")
                receiver.assert_not_called()
                play.assert_not_called()
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
