"""Editable compositions, persistent library and integrated desktop workflows."""
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
from PIL import Image

from kgstv.image_document import Document, Layer, History, load_image, expand_text
from kgstv.library import Library
from tests import test_gui


class CompositionTests(unittest.TestCase):
    def test_layers_fit_crop_opacity_rotation_and_original_are_independent(self):
        source = Image.new("RGBA", (640, 240), "red")
        source.paste("blue", (320, 0, 640, 240))
        original = source.tobytes()
        doc = Document.from_image(source)
        doc.layers[0].crop_x = 100
        self.assertEqual(doc.render().getpixel((160, 120)), (0, 0, 255))
        overlay = doc.add(Layer("image", image=load_image(Image.new("RGB", (20, 40), "lime")), width=20, height=40, opacity=50, angle=90))
        result, boxes = doc.render(bounds=True)
        self.assertAlmostEqual(result.getpixel((160, 120))[1], 128, delta=2)
        self.assertEqual(boxes[overlay.id][2]-boxes[overlay.id][0], 40)
        overlay.visible = False
        self.assertEqual(doc.render().getpixel((160, 120)), (0, 0, 255))
        self.assertEqual(source.tobytes(), original)

    def test_portable_template_round_trip_embeds_images_and_unicode(self):
        doc = Document.from_image(Image.new("RGBA", (420, 240), "#345678"))
        doc.add(Layer("text", text="73 {HISCALL}\nGrüße {MYCALL}", shadow=True, angle=8))
        context = {"MYCALL":"TEST", "HISCALL":"TEST2"}
        restored = Document.from_json(doc.to_json())
        self.assertEqual(restored.render(context).tobytes(), doc.render(context).tobytes())
        self.assertIn("{MYCALL}", restored.layers[1].text)
        self.assertEqual(expand_text("{unknown} {MYCALL}", context), "{unknown} TEST")

    def test_invalid_templates_do_not_resolve_paths_or_accept_unbounded_values(self):
        original = json.loads(Document([Layer("text")]).to_json())
        for key, value in (("size", float("nan")), ("width", 999999), ("image", "C:/secret.png"), ("visible", "false")):
            data = json.loads(json.dumps(original))
            data["layers"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                Document.from_json(json.dumps(data))
        original["layers"] *= 2
        with self.assertRaises(ValueError):
            Document.from_json(json.dumps(original))

    def test_history_restores_properties_without_copying_sources_or_stale_redo(self):
        doc = Document.from_image(Image.new("RGB", (320, 240), "red"))
        history = History(limit=2)
        history.push(doc)
        doc.layers[0].x = 12
        restored = history.undo(doc)
        self.assertEqual(restored.layers[0].x, 160)
        self.assertIs(restored.layers[0].image, doc.layers[0].image)
        doc = history.redo(restored)
        self.assertEqual(doc.layers[0].x, 12)
        history.undo(doc)
        history.push(doc)
        self.assertFalse(history.future)


class LibraryTests(unittest.TestCase):
    def test_persistence_templates_categories_search_and_independent_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"library.sqlite3"
            store = Library(path)
            doc = Document.from_image(Image.new("RGB", (320, 240), "red"))
            original = store.add_image("CQ template", doc.render(), kind="template", document=doc, metadata={"callsign":"TEST"})
            store.add_image("Received", doc.render(), kind="rx")
            copy = store.duplicate(original, "Copy")
            store.rename(copy, "Reply")
            store.remove(original)
            store = Library(path)
            self.assertEqual([v["id"] for v in store.images(kind="template", search="TEST")], [copy])
            self.assertEqual(store.image(copy)["document"].render().tobytes(), doc.render().tobytes())
            with Image.open(BytesIO(store.images()[0]["thumbnail"])) as thumb:
                self.assertEqual(thumb.size, (160, 120))
            self.assertEqual(store.images(search="' OR 1=1 --"), [])
            store.save_draft(doc, {"MYCALL":"TEST"})
            self.assertEqual(store.draft_context(), {"MYCALL":"TEST"})
            self.assertEqual(store.draft().render().tobytes(), doc.render().tobytes())

    def test_history_persists_more_than_compact_view_and_paginates(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Library(Path(folder)/"library.sqlite3")
            for n in range(620):
                store.add_message(f"TEST>{n} Grüße 日本語", "TX" if n%2 else "RX")
            reopened = Library(store.path)
            self.assertEqual(len(reopened.messages(limit=1000)), 620)
            self.assertEqual(len(reopened.messages(offset=500)), 120)
            self.assertEqual(reopened.messages("619")[0]["direction"], "TX")
            self.assertEqual(reopened.messages("' OR 1=1 --"), [])


class StudioDesktopTests(unittest.TestCase):
    setUp = test_gui.DesktopTests.setUp
    drain = test_gui.DesktopTests.drain
    wait_for_worker = test_gui.DesktopTests.wait_for_worker
    wait_for_radio = test_gui.DesktopTests.wait_for_radio

    def editor(self):
        editor = self.app.open_editor()
        def cleanup():
            if editor.window.winfo_exists():
                editor.dirty = False
                editor.close()
        self.addCleanup(cleanup)
        return editor

    def test_edit_text_rx_collage_undo_redo_switch_language_and_apply(self):
        self.app.callsign.set("TEST")
        self.app.rx_image = Image.new("RGB", (320, 240), "lime")
        self.app.rx_summary = {"callsign":"TEST2", "missing":[], "good_blocks":300}
        editor = self.editor()
        editor.insert_image(Image.new("RGB", (320, 240), "navy"), background=True)
        editor.quick("reply")
        self.assertEqual([l.kind for l in editor.document.layers], ["image", "image", "text"])
        editor.text_input.delete("1.0", "end")
        editor.text_input.insert("1.0", "73 {HISCALL} de {MYCALL}")
        self.app.set_language("de", persist=False)
        self.assertEqual(editor.current().text, "73 {HISCALL} de {MYCALL}")
        editor.nudge(1, 0, 10)
        self.assertEqual(editor.current().x, 170)
        editor.undo()
        self.assertEqual(editor.current().x, 160)
        editor.redo()
        self.assertEqual(editor.current().x, 170)
        editor.apply()
        self.assertFalse(editor.dirty)
        self.assertEqual(self.app.tx_image.size, (320, 240))
        self.assertEqual(len(self.app.library.draft().layers), 3)
        self.assertEqual(self.app.library.draft_context()["HISCALL"], "TEST2")

    def test_template_save_gallery_edit_export_import_and_language(self):
        editor = self.editor()
        editor.insert_image(Image.new("RGB", (320, 240), "navy"), background=True)
        editor.quick("CQ")
        with patch("kgstv.editor_gui.simpledialog.askstring", return_value="CQ draft"):
            editor.save_template()
        gallery = self.app.open_gallery()
        identity = self.app.library.images(kind="template")[0]["id"]
        gallery.select(identity)
        self.app.set_language("de", persist=False)
        self.assertEqual(gallery.selected, identity)
        path = Path(self.folder.name)/"portable.kgstv.json"
        with patch("kgstv.editor_gui.filedialog.asksaveasfilename", return_value=str(path)):
            editor.export_document()
        editor.blank()
        with patch("kgstv.editor_gui.filedialog.askopenfilename", return_value=str(path)):
            editor.import_document()
        self.assertEqual(len(editor.document.layers), 2)
        gallery.close()

    def test_drag_resize_and_cancel_close_preserve_draft(self):
        self.root.deiconify()
        editor = self.editor()
        editor.insert_image(Image.new("RGB", (40, 40), "red"))
        editor.window.update()
        def pointer(x,y):
            return SimpleNamespace(x=editor.origin[0]+x*editor.zoom, y=editor.origin[1]+y*editor.zoom)
        editor.pointer_down(pointer(160,120))
        editor.pointer_move(pointer(180,130))
        editor.pointer_up(pointer(180,130))
        self.assertEqual((editor.current().x,editor.current().y), (180,130))
        _, _, right, bottom = editor.boxes[editor.selected]
        before = editor.current().width
        editor.pointer_down(pointer(right,bottom))
        editor.pointer_move(pointer(right+20,bottom+20))
        editor.pointer_up(pointer(right+20,bottom+20))
        self.assertGreater(editor.current().width, before)
        with patch("kgstv.editor_gui.messagebox.askyesno", return_value=False):
            editor.close()
        self.assertIn(editor, self.app.studio_windows)

    def test_setup_separate_and_audio_preferences_persist_without_hardware(self):
        from kgstv.i18n import load_settings
        self.assertFalse(hasattr(self.app, "nav_buttons"))
        self.assertEqual(self.app.setup_window.state(), "withdrawn")
        self.app.open_setup()
        self.app._devices = [{"name":"USB Audio CODEC", "max_input_channels":1, "max_output_channels":2}]
        self.app._refresh_device_labels((0, 0))
        self.app.ptt_port.set("COM9")
        self.app.close_setup()
        self.assertEqual(self.app.setup_window.state(), "withdrawn")
        stored = load_settings(self.settings)["audio"]
        self.assertEqual(stored["input"], "USB Audio CODEC")
        self.app._restore_audio(stored)
        self.app.set_language("de", persist=False)
        self.assertEqual(self.app.device_ids[self.app.output_device.get()], 0)

    def test_rx_archives_once_and_chat_restores_full_history(self):
        from kgstv.session import Session, image_frames
        from kgstv.protocol import control_frame, Command
        session = Session()
        for frame in image_frames(Image.new("RGB", (320, 240), "red"), "TEST")+[control_frame(Command.END)]:
            session.accept(frame)
            self.app._on_frame(frame, session)
        self.app._on_frame(frame, session)
        self.drain()
        self.assertEqual(len(self.app.library.images(kind="rx")), 1)
        self.app._record_message("TEST>hello 日本語")
        history = self.app.open_history()
        self.app._record_message("TEST>73", "TX")
        self.assertEqual(len(self.app.library.messages()), 2)
        self.app.set_language("de", persist=False)
        history.close()

    def test_wav_export_never_creates_transmitted_history(self):
        self.app.callsign.set("TEST")
        self.app.message.insert(0, "offline")
        with patch("kgstv.gui.filedialog.asksaveasfilename", return_value=str(Path(self.folder.name)/"text.wav")):
            self.app.encode("text", False)
            self.wait_for_worker()
        self.assertEqual(self.app.library.messages(), [])

    def test_activity_selection_tunes_only_on_action_and_never_keys_ptt(self):
        from tests.test_hamlib import fake_server
        with fake_server() as (rig, port):
            panel = self.app.radio_panel
            panel.connection.set("network"); panel.port.set(str(port))
            panel.connect(); self.wait_for_radio()
            try:
                panel.activity_combo.current(0); panel.select_activity()
                self.assertEqual(rig.frequency, 14230000)
                panel.tune_activity(); self.wait_for_radio()
                self.assertEqual((rig.frequency, rig.mode), (14233000, "PKTUSB"))
                self.assertFalse(any("set_ptt" in cmd for cmd in rig.commands))
                panel.activity_combo.current(4); panel.select_activity()
                with patch("kgstv.gui.messagebox.showerror") as error:
                    panel.tune_activity()
                    error.assert_called_once()
                self.assertEqual(rig.frequency, 14233000)
                rig.ptt = 1
                panel.activity_combo.current(1); panel.select_activity()
                with patch("kgstv.gui.messagebox.showerror") as error:
                    panel.tune_activity(); self.wait_for_radio()
                    error.assert_called_once()
                self.assertEqual(rig.frequency, 14233000)
                rig.ptt = 0
            finally:
                panel.disconnect(); self.wait_for_radio()

    def test_qso_dialog_writes_local_adif_and_modular_backend_receives_domain(self):
        from kgstv.logbook_gui import QsoWindow
        from kgstv.logbook import Qso, Receipt
        self.app.callsign.set("TEST")
        window = self.app.open_logbook()
        window.values["call"].set("test2")
        window.values["frequency"].set("14,233")
        window.values["comment"].set("73 <EOR> literally")
        window.save()
        path = Path(self.folder.name)/"logbook.adi"
        self.assertIn("<CALL:5>TEST2", path.read_text())
        self.assertNotIn(window, self.app.studio_windows)
        backend = Mock()
        backend.save.return_value = Receipt("test", "fake destination")
        other = QsoWindow(self.app, backend_factory=lambda path:backend)
        other.values["call"].set("TEST3"); other.values["frequency"].set("7.173")
        other.save()
        self.assertIsInstance(backend.save.call_args.args[0], Qso)
        self.assertEqual(backend.save.call_args.args[0].frequency, 7173000)

    def test_compact_german_layout_keeps_actions_and_message_history_reachable(self):
        self.root.deiconify()
        self.root.geometry("940x640")
        self.app.set_language("de", persist=False)
        self.root.update()
        self.assertGreater(self.app.log.winfo_height(), 100)
        self.assertLess(self.app.log.winfo_rooty()+self.app.log.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())
        editor = self.editor()
        editor.window.geometry("980x680")
        editor.window.update()
        toolbar = editor.window.winfo_children()[1]
        for button in toolbar.winfo_children():
            self.assertGreater(button.winfo_width(), 30)
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), editor.window.winfo_rootx()+editor.window.winfo_width())
        qso = self.app.open_logbook()
        qso.window.geometry("700x600")
        qso.window.update()
        self.assertGreater(qso.save_button.winfo_width(), 50)
        self.assertLess(qso.save_button.winfo_rooty()+qso.save_button.winfo_height(), qso.window.winfo_rooty()+qso.window.winfo_height())
        qso.close()

    def test_qso_errors_preserve_input_and_satellite_rf_is_explicit(self):
        from kgstv.hamlib import RadioState
        self.app.callsign.set("TEST")
        panel = self.app.radio_panel
        panel.session = Mock(connected=True)
        panel.state = RadioState(28125000,"PKTUSB",0,0)
        panel.last_activity = ("qo100",28125000)
        window = self.app.open_logbook()
        self.assertEqual(window.values["frequency"].get(), "2400.125000")
        self.assertEqual(window.values["frequency_rx"].get(), "10489.625000")
        window.values["call"].set("TEST2")
        window.values["name"].set("Müller")
        with patch("kgstv.gui.messagebox.showerror") as error:
            window.save()
            error.assert_called_once()
        self.assertFalse(window.saved)
        self.assertEqual(window.values["name"].get(), "Müller")
        self.assertFalse((Path(self.folder.name)/"logbook.adi").exists())
        window.close()
        panel.session = None
