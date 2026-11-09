"""Build an unsigned one-file desktop app and an install-free release archive."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import sysconfig
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kgstv import __version__

RUNTIME = ('numpy', 'scipy', 'Pillow', 'av', 'sounddevice', 'pyserial', 'cffi', 'pycparser')


def target():
    machine = platform.machine().lower()
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine)
    system = {'win32': 'windows', 'linux': 'linux'}.get(sys.platform)
    if not system or not arch or (system == 'windows' and arch != 'x64'):
        raise SystemExit('Supported build targets: Windows x64, Linux x64 and Linux ARM64')
    return f'{system}-{arch}'


def binary_info(path):
    with Path(path).open('rb') as stream:
        header = stream.read(64)
        if header[:4] == b'\x7fELF':
            if header[4:6] != b'\x02\x01':
                raise ValueError('Expected a little-endian ELF64 executable')
            machine = struct.unpack_from('<H', header, 18)[0]
            return {'format': 'ELF', 'arch': {62: 'x64', 183: 'arm64'}[machine], 'signed': False}
        if header[:2] == b'MZ':
            stream.seek(struct.unpack_from('<I', header, 60)[0])
            pe = stream.read(264)
            if pe[:4] != b'PE\0\0' or struct.unpack_from('<H', pe, 24)[0] != 0x20b:
                raise ValueError('Expected a PE32+ executable')
            # Certificate table (PE data directory 4) must remain absent.
            signed = any(struct.unpack_from('<II', pe, 24+112+4*8))
            return {'format': 'PE', 'arch': {0x8664: 'x64'}[struct.unpack_from('<H', pe, 4)[0]], 'signed': signed}
    raise ValueError('Not a supported executable')


def digest(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def collect_licenses(assets):
    licenses = assets/'licenses'
    licenses.mkdir(parents=True, exist_ok=True)
    inventory = []
    for name in RUNTIME + ('pyinstaller', 'pyinstaller-hooks-contrib'):
        dist = metadata.distribution(name)
        copied = []
        for entry in dist.files or []:
            if entry.suffix in ('.pyc', '.pyo'):
                continue
            if not any(part.lower().startswith(('license', 'copying', 'notice', 'authors')) for part in entry.parts):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file():
                continue
            relative = Path(*[part for part in entry.parts if part not in ('.', '..')])
            destination = licenses/name/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied.append(str(destination.relative_to(assets)))
        fallback = ROOT/'packaging'/'licenses'/(name+'-LICENSE.txt')
        if not copied and fallback.is_file():
            destination = licenses/name/fallback.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fallback, destination)
            copied.append(str(destination.relative_to(assets)))
        if not copied:
            raise RuntimeError(f'No licence files found for {name}')
        inventory.append({'name': name, 'version': dist.version, 'licenses': copied,
                          'source': f'https://pypi.org/project/{name}/{dist.version}/#files'})
    python_license = next((p for p in (Path(sys.base_prefix)/'LICENSE.txt',
                           Path(sysconfig.get_path('stdlib'))/'LICENSE.txt') if p.is_file()), None)
    if not python_license:
        raise RuntimeError('Python licence file missing')
    shutil.copyfile(python_license, licenses/'Python-LICENSE.txt')
    if sys.platform == 'win32':
        for source in (Path(sys.base_prefix)/'tcl').rglob('license.terms'):
            destination = licenses/'Tcl-Tk'/source.relative_to(Path(sys.base_prefix)/'tcl')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    else:
        # Debian runtime-library notices, including Tcl/Tk, ALSA and PortAudio.
        for source in Path('/usr/share/doc').glob('*/copyright'):
            destination = licenses/'Debian'/source.parent.name/'copyright'
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    notice = ('Open KG-STV standalone distribution\n\n'
              'Open KG-STV code: MIT (see LICENSE). HamRig Robbie is owner-provided branding;\n'
              'see HamRig-Robbie.txt. Bundled libraries retain their own licences.\n'
              'The licenses directory contains notices from the build distributions,\n'
              'including notices for native libraries shipped in Python wheels.\n'
              'Debian notices also include build-environment components.\n'
              'Source distributions for Python packages are linked below; native\n'
              'source projects and terms are identified in their respective notices.\n'
              'Python source: https://www.python.org/downloads/source/\n'
              'Tcl/Tk source: https://www.tcl.tk/software/tcltk/\n'
              'Debian sources: https://sources.debian.org/\n\n')
    notice += '\n'.join(f"{p['name']} {p['version']}: {p['source']}" for p in inventory)
    (assets/'THIRD-PARTY-NOTICES.txt').write_text(notice+'\n', encoding='utf-8')
    shutil.copyfile(ROOT/'kgstv/assets/README.md', assets/'HamRig-Robbie.txt')
    return inventory


def build(args):
    build_target = target()
    work = (args.work_dir or ROOT/'build'/f'standalone-{build_target}').resolve()
    output = (args.output or ROOT/'dist'/build_target).resolve()
    assets = work/'assets'
    assets.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    inventory = collect_licenses(assets)
    from PIL import Image
    with Image.open(ROOT/'kgstv/assets/hamrig-robbie.png') as image:
        image.save(assets/'openkgstv.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    env = os.environ.copy()
    env['OPENKGSTV_BUILD_ASSETS'] = str(assets)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--workpath', str(work/'pyinstaller'), '--distpath', str(output),
                    str(ROOT/'packaging/openkgstv.spec')], cwd=ROOT, env=env, check=True)
    binary = output/('OpenKGSTV.exe' if sys.platform == 'win32' else 'OpenKGSTV')
    info = binary_info(binary)
    if info['arch'] != build_target.split('-')[1] or info['signed']:
        raise RuntimeError('Wrong architecture or unexpectedly signed executable')
    report_path = output/'self-test.json'
    # A prior report cannot accidentally validate a failed new process.
    report_path.unlink(missing_ok=True)
    command = [str(binary), '--self-test', str(report_path), '--gui']
    if args.rigctld:
        command += ['--rigctld', args.rigctld]
    if sys.platform.startswith('linux'):
        command = ['xvfb-run', '-a'] + command
    subprocess.run(command, check=True, timeout=300)
    report = json.loads(report_path.read_text('utf-8'))
    if not report['ok'] or not report['frozen'] or report['version'] != __version__:
        raise RuntimeError('Frozen self-test failed or version mismatch')
    commit = os.environ.get('OPENKGSTV_SOURCE_COMMIT')
    if not commit:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    manifest = dict(version=__version__, target=build_target, built_at=datetime.now(timezone.utc).isoformat(),
                    commit=commit, python=platform.python_version(), binary=info, sha256=digest(binary),
                    dependencies=inventory, validation=report)
    (output/'build-info.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    readme = (ROOT/'packaging/README-download.txt').read_text('utf-8').replace('@VERSION@', __version__).replace('@TARGET@', build_target)
    (output/'README.txt').write_text(readme, encoding='utf-8')
    entries = [(binary, binary.name), (output/'README.txt', 'README.txt'),
               (output/'build-info.json', 'build-info.json'), (ROOT/'LICENSE', 'LICENSE')]
    entries += [(path, str(path.relative_to(assets)).replace('\\', '/')) for path in assets.rglob('*') if path.is_file() and path.suffix != '.ico']
    stem = f'OpenKGSTV-{__version__}-{build_target}'
    if sys.platform == 'win32':
        archive = output/(stem+'.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
            for path, name in entries:
                package.write(path, name)
    else:
        archive = output/(stem+'.tar.gz')
        with tarfile.open(archive, 'w:gz') as package:
            for path, name in entries:
                package.add(path, arcname=name)
    (output/(archive.name+'.sha256')).write_text(f'{digest(archive)}  {archive.name}\n', encoding='ascii')
    print(f'VERIFIED UNSIGNED PACKAGE: {archive} ({archive.stat().st_size:,} bytes)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--rigctld', help='Test an existing external Hamlib Dummy executable')
    build(parser.parse_args())


if __name__ == '__main__':
    main()
