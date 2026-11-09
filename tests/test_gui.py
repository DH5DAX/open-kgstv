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
        app.open_setup()
        receiver = Mock()
        app.live = receiver
        app._set_activity("rx")
        app._set_status("live_receiving")
        with patch("kgstv.gui.save_language", wraps=save_language) as save:
            app.language_buttons["de"].invoke()
            save.assert_called_once_with(self.settings, "de")
        self.assertEqual(app.language, "de")
        self.assertEqual(load_language(self.settings), "de")
        self.assertNotEqual(app.setup_window.state(), "withdrawn")
        self.assertIs(app.live, receiver)
        receiver.stop.assert_not_called()
        self.assertEqual(app.activity_label.cget("text"), "● EMPFANG")
        self.assertEqual(app.status.get(), DE["live_receiving"])
        self.assertEqual(app.block_status.get(), "TEST · 1 fehlen")
        self.assertEqual((app.callsign.get(), app.mode.get(), app.fec.get(), app.scale.get()),
                         ("TEST", "4L-FSK", True, "0.5"))
        self.assertEqual((app.frequency.get(), app.ptt_port.get(), app.ptt_line.get()), ("70", "COM8", "dtr"))
        self.assertEqual(app.message.get(), "CQ de TEST")
        self.assertIn("RX  TEST>received 日本語\n", app.log.get("1.0", "end-1c"))
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

    def wait_for_radio(self):
        deadline = time.monotonic()+10
        while self.app.radio_panel.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app.radio_panel.busy, "Radio operation did not finish")

    def test_radio_profile_persists_without_starting_connection(self):
        from kgstv.i18n import load_settings
        panel = self.app.radio_panel
        with patch("kgstv.radio_gui.RadioSession") as session:
            panel.preset()
            panel.device.set("COM7")
            panel.save()
            self.app.set_language("de")
            session.assert_not_called()
        stored = load_settings(self.settings)
        self.assertEqual(stored["language"], "de")
        self.assertEqual(stored["radio"]["model"], 3078)
        self.assertEqual(stored["radio"]["device"], "COM7")
        self.assertEqual(stored["radio"]["ptt_method"], "hamlib")
        self.assertEqual(panel.target_mode.get(), "PKTUSB")
        self.assertTrue(self.app.text_send_button.instate(["disabled"]))

    def test_connected_radio_controls_and_actual_gui_send_use_cat_ptt(self):
        from tests.test_hamlib import fake_server
        with fake_server() as (rig, port):
            panel = self.app.radio_panel
            panel.connection.set("network")
            panel.port.set(str(port))
            panel.ptt_method.set("hamlib")
            panel.lead_ms.set("0"); panel.tail_ms.set("0")
            with patch("kgstv.gui.messagebox.showerror") as error:
                panel.connect()
                self.wait_for_radio()
                self.assertTrue(panel.connected)
                panel.target_frequency.set("7,074")
                panel.set_frequency()
                self.wait_for_radio()
                panel.set_mode()
                self.wait_for_radio()
                self.assertEqual((rig.frequency, rig.mode), (7074000, "PKTUSB"))
                self.app.set_language("de", persist=False)
                self.assertIn("7.074000 MHz", self.app.radio_status.get())
                audio, serial = Mock(), Mock()
                audio.get_stream.return_value.active = False
                keyed = []
                audio.play.side_effect = lambda *a, **k:keyed.append(rig.ptt)
                self.app.callsign.set("TEST")
                self.app.message.insert(0, "Hamlib GUI test")
                self.app.ptt_port.set("DO-NOT-OPEN")
                with patch.dict("sys.modules", {"sounddevice":audio, "serial":serial}):
                    self.app.encode("text", True)
                    self.wait_for_worker()
                self.assertEqual(keyed, [1])
                self.assertEqual(rig.ptt, 0)
                serial.Serial.assert_not_called()
                panel.disconnect()
                self.wait_for_radio()
                self.assertIsNone(panel.session)
                error.assert_not_called()

    def test_radio_validates_only_active_connection_fields(self):
        panel = self.app.radio_panel
        panel.model.set("")
        with self.assertRaises(ValueError):
            panel.config()
        panel.baud.set("invalid")
        panel.connection.set("network")
        self.assertEqual(panel.config().port, 4532)
        panel.preset()
        panel.device.set("COM7")
        panel.port.set("")
        self.assertEqual(panel.config().model, 3078)

    def test_uncertain_ptt_connection_cannot_be_replaced(self):
        panel = self.app.radio_panel
        old = panel.session = Mock(connected=False, ptt_may_be_on=True)
        with patch("kgstv.gui.messagebox.showerror") as error, patch("kgstv.radio_gui.RadioSession") as new:
            panel.connect()
            error.assert_called_once()
            new.assert_not_called()
            self.assertIs(panel.session, old)
        panel.session = None

    def test_wav_export_does_not_require_selected_hamlib_connection(self):
        path = Path(self.folder.name)/"offline.wav"
        self.app.radio_panel.ptt_method.set("hamlib")
        self.app.callsign.set("TEST")
        self.app.message.insert(0, "Offline")
        with patch("kgstv.gui.filedialog.asksaveasfilename", return_value=str(path)), \
             patch("kgstv.live.play_audio") as play, patch("kgstv.gui.messagebox.showerror") as error:
            self.app.encode("text", False)
            self.wait_for_worker()
            self.assertTrue(path.is_file())
            play.assert_not_called()
            error.assert_not_called()

    def test_unconfirmed_ptt_release_is_not_hidden_by_cancellation(self):
        from kgstv.hamlib import PTTReleaseError
        def work():
            self.app.cancelled.set()
            raise PTTReleaseError("PTT off acknowledgement lost")
        with patch("kgstv.gui.messagebox.showerror") as error:
            self.app._worker(work)
            self.wait_for_worker()
            self.assertTrue(self.app.radio_panel.release_failed)
            self.assertEqual(self.app.status.get(), EN["radio_release_error"])
            error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
