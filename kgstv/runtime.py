"""Keep external Hamlib processes independent of the frozen app's libraries."""
from contextlib import contextmanager
import os
import sys
import threading

_launch_lock = threading.RLock()


def external_environment():
    env = os.environ.copy()
    if getattr(sys, 'frozen', False) and sys.platform.startswith('linux'):
        if 'LD_LIBRARY_PATH_ORIG' in env:
            env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
        else:
            env.pop('LD_LIBRARY_PATH', None)
    return env


@contextmanager
def external_libraries():
    """PyInstaller adjusts DLL search paths; children need the system defaults.

    Windows has a process-wide search directory, so restore it immediately
    after spawn. Linux can sanitize only the child's environment instead.
    """
    if not (getattr(sys, 'frozen', False) and sys.platform == 'win32'):
        yield
        return
    import ctypes
    with _launch_lock:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p]
        kernel.GetDllDirectoryW.restype = ctypes.c_uint
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.restype = ctypes.c_int
        previous = ctypes.create_unicode_buffer(32768)
        kernel.GetDllDirectoryW(len(previous), previous)
        if not kernel.SetDllDirectoryW(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            kernel.SetDllDirectoryW(previous.value or None)
