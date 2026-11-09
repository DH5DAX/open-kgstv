"""Checks for frozen-process isolation and architecture/unsigned release gates."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from kgstv.runtime import external_environment, external_libraries
from tools.build_standalone import binary_info


class PackagingTests(unittest.TestCase):
    def test_linux_child_uses_original_library_path_without_changing_parent(self):
        for original in (None, '', '/system/libs'):
            env = {'LD_LIBRARY_PATH': '/tmp/_MEI123:/system/libs', 'KEEP': 'value'}
            if original is not None:
                env['LD_LIBRARY_PATH_ORIG'] = original
            with patch.dict(os.environ, env, clear=True), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'linux'):
                child = external_environment()
                self.assertEqual(child.get('LD_LIBRARY_PATH'), original)
                self.assertEqual(os.environ['LD_LIBRARY_PATH'], env['LD_LIBRARY_PATH'])
                self.assertEqual(child['KEEP'], 'value')

    def test_source_process_preserves_environment_and_context_propagates_failure(self):
        with patch.object(sys, 'frozen', False, create=True), patch.dict(os.environ, {'LD_LIBRARY_PATH': '/custom'}):
            self.assertEqual(external_environment()['LD_LIBRARY_PATH'], '/custom')
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                with external_libraries():
                    raise RuntimeError('failed')

    def test_frozen_app_finds_optional_adjacent_hamlib(self):
        from kgstv.hamlib import find_rigctld
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            helper = base/'hamlib'/'bin'/'rigctld.exe'
            helper.parent.mkdir(parents=True)
            helper.touch()
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'win32'), patch.object(sys, 'executable', str(base/'OpenKGSTV.exe')), patch('kgstv.hamlib.shutil.which', return_value=None):
                self.assertEqual(Path(find_rigctld()), helper)

    def test_pe_architecture_and_certificate_presence(self):
        data = bytearray(512)
        data[:2] = b'MZ'; struct.pack_into('<I', data, 60, 128)
        data[128:132] = b'PE\0\0'
        struct.pack_into('<H', data, 132, 0x8664)
        struct.pack_into('<H', data, 152, 0x20b)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'app.exe'
            path.write_bytes(data)
            self.assertEqual(binary_info(path), {'format': 'PE', 'arch': 'x64', 'signed': False})
            struct.pack_into('<II', data, 128+24+112+32, 512, 128)
            path.write_bytes(data)
            self.assertTrue(binary_info(path)['signed'])

    def test_elf_architectures_and_invalid_binary_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'app'
            for machine, arch in ((62, 'x64'), (183, 'arm64')):
                data = bytearray(64); data[:6] = b'\x7fELF\x02\x01'
                struct.pack_into('<H', data, 18, machine)
                path.write_bytes(data)
                self.assertEqual(binary_info(path)['arch'], arch)
            path.write_bytes(b'not executable')
            with self.assertRaises(ValueError):
                binary_info(path)
