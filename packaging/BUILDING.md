# Unsigniertes Standalone / Unsigned standalone builds

Open KG-STV uses the same approach inspected in HamRig Gateway 3's
`build-linux/Dockerfile`, `build-linux/build-all.sh` and PyInstaller specs:
one-file PyInstaller on the target operating system and architecture, with
Debian 12 (glibc 2.36) containers for Linux x64 and ARM64. ARM64 uses native
hardware or Docker Desktop's QEMU support. The build never invokes a signer.

Unlike a cross-compiler, PyInstaller packages the running interpreter and its
native libraries. A Windows build cannot produce the Linux binary. See the
[PyInstaller platform notes](https://pyinstaller.org/en/stable/usage.html#supporting-multiple-platforms).
Python packages are pinned in `requirements.txt`; build-info.json records their
versions, the actual Python version, source commit, target, binary hash and
self-test result. This is a repeatable procedure, not a bit-for-bit reproducibility claim.

## Windows x64

Use a 64-bit Python 3.13 installation with Tk. In PowerShell at the repository root:

```powershell
python -m venv outputs/standalone-venv
outputs/standalone-venv/Scripts/python -m pip install -r packaging/requirements.txt
outputs/standalone-venv/Scripts/python tools/build_standalone.py
```

Optionally add `--rigctld C:/path/to/rigctld.exe` to exercise the external
Hamlib Dummy backend. The build produces `dist/windows-x64/OpenKGSTV.exe` and
`OpenKGSTV-0.1.0-windows-x64.zip`. The PE certificate table is checked to ensure
the executable is unsigned. It opens the GUI on double-click, without a console.

## Linux x64 and Raspberry Pi ARM64

With Docker Desktop running on Windows, or Docker with ARM64 emulation/native ARM:

```console
python tools/build_linux.py x64 arm64
```

The build contexts contain only the Dockerfile and dependency pins; source is
mounted read-only. Each build has its own temporary working directory and
output mount. The image download/dependency installation uses the network;
the executable build and offline self-test run with networking disabled.
Loopback is available for the Hamlib Dummy test.

Outputs:

- `dist/linux-x64/OpenKGSTV-0.1.0-linux-x64.tar.gz`
- `dist/linux-arm64/OpenKGSTV-0.1.0-linux-arm64.tar.gz`

Each archive contains one executable, a short README, build metadata and
licence notices. Linux executables retain their execute permission in tar.
The ARM64 package targets **64-bit Raspberry Pi OS Bookworm or newer** with
a desktop, and other compatible aarch64 Linux systems. It does not support
32-bit Raspberry Pi OS/ARMv7. The x64 package targets Debian 12 / Ubuntu 24.04
or newer compatible desktop systems. Neither Linux package supports musl/Alpine.

## Included and external components

Included: Python, Tcl/Tk, NumPy/SciPy, Pillow, PyAV/FFmpeg, sounddevice/PortAudio,
pyserial, Robbie artwork, GUI translations and all Open KG-STV modules.
No global Python installation or pip commands are needed by the recipient.
Linux still uses the desktop's X11/XWayland, fonts and basic OS/audio libraries;
one-file extraction needs an executable, symlink-capable temporary filesystem.

Hamlib remains an **external optional dependency**, as in the source application.
Use a network rigctld or install Hamlib locally (`libhamlib-utils` on Debian).
The executable also finds `hamlib/bin/rigctld[.exe]` alongside itself. The frozen
app restores system library search paths when spawning Hamlib, following the
[PyInstaller subprocess guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application).
Radio USB drivers and serial/audio access permissions belong to the operating system.

## Verification and release

The build fails if its frozen self-test fails. It validates four modem modes,
Japanese text encoding, WAV/FLAC input, image compositions, SQLite gallery,
ADIF logging, waterfall spectra and the actual Tk interface in EN/DE. Linux
runs Tk under Xvfb; an explicit rigctld path enables the software Dummy test.
No physical radio, serial port or soundcard stream is opened. Hardware and
original-KG-STV interoperability are separate tests, not implied by packaging.

To repeat a package check after extraction:

```console
./OpenKGSTV --self-test self-test.json --gui
```

On Windows use `OpenKGSTV.exe --self-test self-test.json --gui`; the windowed
executable writes results to JSON. Normal CLI subcommands still work, but
the Windows GUI build does not display console output.

Release archives have adjacent SHA-256 files. Publish only a complete set of
three validated archives plus SHA256SUMS.txt. Keep the release labelled as
a preview until the protocol's remaining compatibility checks are complete.

`packaging/runtime.Dockerfile` supplies an additional clean Debian runtime
with desktop/audio system libraries but no Python, Tcl/Tk, PortAudio or pip.
Use the matching architecture to run the extracted binary's self-test there.

After committing and pushing the exact source used for all builds,
`python tools/publish_release.py` verifies the three archives without publishing.
`python tools/publish_release.py --publish` uploads a draft to
`DH5DAX/open-kgstv`, checks GitHub's asset SHA-256 digests and publishes the
complete set as a prerelease. It uses `GITHUB_TOKEN` or the existing Git
credential helper in memory, never writes credentials, never signs and refuses
to overwrite an already published version.
