"""Resolve the bundled PortAudio even on desktops without a system installation."""
import ctypes.util
from pathlib import Path
import sys

if sys.platform.startswith('linux') and getattr(sys, 'frozen', False):
    _bundled = Path(sys._MEIPASS)/'libportaudio.so.2'
    if not _bundled.is_file():
        raise RuntimeError('The standalone bundle is missing libportaudio.so.2')
    _find_library = ctypes.util.find_library

    def _find_bundled_audio(name):
        if name == 'portaudio':
            return str(_bundled)
        return _find_library(name)

    ctypes.util.find_library = _find_bundled_audio
