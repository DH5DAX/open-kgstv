"""Explicit offline validation of an installed/frozen app, without radio/audio I/O."""
import argparse
import json
from pathlib import Path
import platform
import sys
import tempfile
import traceback

from . import __version__


def check(*, gui=False, rigctld=None):
    import av
    import numpy as np
    from PIL import Image
    import serial
    import sounddevice
    from .audio import load_audio, save_wav
    from .image_document import Document, Layer
    from .library import Library
    from .logbook import AdifLogbook, Qso
    from .modem import Receiver, modulate
    from .protocol import text_frame
    from .waterfall import AudioMonitor, SpectrumAnalyzer, HOP

    checks = []
    sounddevice.get_portaudio_version()  # Load the native library, no stream/device access.
    assert serial.VERSION and av.__version__
    checks.append('audio-libraries')
    for mode in (0, 1):
        for fec in (False, True):
            message = 'TEST>OpenKGSTV 日本語'
            audio = modulate([text_frame(message, mode=mode, fec=fec)], rate=12000, end_repeats=1)
            frames = list(Receiver().frames(audio))
            assert [f.text() for f in frames if f.header.com == 0 and f.crc_ok] == [message]
    checks.append('four-modem-modes-and-cp932')
    with tempfile.TemporaryDirectory(prefix='openkgstv-selftest-') as directory:
        folder = Path(directory)
        save_wav(folder/'test.wav', audio, rate=12000)
        assert len(load_audio(folder/'test.wav')) == len(audio)
        # Exercise FFmpeg-backed compressed input, not just scipy's WAV path.
        with av.open(str(folder/'test.flac'), 'w') as container:
            stream = container.add_stream('flac', rate=12000)
            frame = av.AudioFrame.from_ndarray((audio[None, :]*16000).astype('int16'), format='s16', layout='mono')
            frame.sample_rate = 12000
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        assert len(load_audio(folder/'test.flac')) == len(audio)
        checks.append('wav-and-flac')
        doc = Document.from_image(Image.new('RGB', (320, 240), '#203a5e'))
        doc.add(Layer('text', text='CQ {MYCALL}', size=24))
        rendered = doc.render({'MYCALL': 'TEST'})
        library = Library(folder/'library.sqlite3')
        library.add_image('Self-test', rendered, kind='template', document=doc)
        library.add_message('TEST>73', 'RX')
        assert len(library.images()) == len(library.messages()) == 1
        checks.append('image-editor-and-sqlite')
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        AdifLogbook(folder/'log.adi').save(Qso(call='TEST2', station_call='TEST', time_on=now, time_off=now, frequency=14233000))
        assert '<CALL:5>TEST2' in (folder/'log.adi').read_text('ascii')
        checks.append('adif')
        monitor = AudioMonitor()
        monitor.publish(np.cos(2*np.pi*1500*np.arange(HOP)/12000)*.25)
        row = SpectrumAnalyzer().feed(monitor.drain())[0]
        assert np.argmax(row.db) == 128
        checks.append('waterfall')
        if gui:
            import tkinter as tk
            from .gui import Application
            root = tk.Tk()
            root.withdraw()
            app = Application(root, settings_path=folder/'settings.json')
            try:
                app.set_tx_document(doc, {'MYCALL': 'TEST'})
                for language in ('en', 'de'):
                    app.set_language(language, persist=False)
                    root.update()
                editor = app.open_editor()
                editor.dirty = False
                editor.close()
                app.open_gallery().close()
                app.open_logbook().close()
                app.open_setup()
                app.close_setup()
                root.update()
                assert app.tx_preview.image is not None
                checks.append('tk-robbie-editor-gallery-setup-logbook-en-de')
            finally:
                root.after_cancel(app._poll_after)
                root.destroy()
        if rigctld:
            from .hamlib import list_models, RadioConfig, RadioSession
            assert any(model[0] == 1 for model in list_models(rigctld))
            session = RadioSession(lambda *args: None)
            try:
                session.connect(RadioConfig(executable=rigctld, model=1, connection='local', baud=0, civ=''))
                session.tune(14233000)
            finally:
                session.close()
            checks.append('external-hamlib-dummy')
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--gui', action='store_true', help='Also test Tk (requires a display or Xvfb)')
    parser.add_argument('--rigctld', help='Optional explicit executable; only the Dummy backend is used')
    args = parser.parse_args(argv)
    report = dict(version=__version__, frozen=bool(getattr(sys, 'frozen', False)),
                  python=platform.python_version(), system=platform.system(), machine=platform.machine())
    try:
        report.update(ok=True, checks=check(gui=args.gui, rigctld=args.rigctld))
    except Exception:
        report.update(ok=False, error=traceback.format_exc())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
