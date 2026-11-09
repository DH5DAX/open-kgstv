First unsigned standalone preview of Open KG-STV. Download, unpack and start —
Python is included. No installer or signing service is involved.

| Download | System |
|---|---|
| `OpenKGSTV-0.1.0-windows-x64.zip` | Windows 10/11 x64 |
| `OpenKGSTV-0.1.0-linux-x64.tar.gz` | Linux x64, Debian 12 / Ubuntu 24.04 or newer compatible desktop |
| `OpenKGSTV-0.1.0-linux-arm64.tar.gz` | 64-bit Raspberry Pi OS Bookworm or newer / compatible ARM64 Linux desktop |
| `SHA256SUMS.txt` | SHA-256 checksums of all three packages |

Each archive contains one executable plus README, licence notices and build/test
metadata. Linux packages preserve the executable bit; start with `./OpenKGSTV`.
The Raspberry package requires **64-bit** Raspberry Pi OS.

Includes the English/German HamRig-style operating window, Robbie, TX image
editor and templates, local gallery, persistent chat, activity-frequency presets,
local ADIF logging and the 0–3 kHz audio waterfall.

Hamlib CAT uses a separately installed `rigctld` or an existing rigctld server.
Linux: install `libhamlib-utils`; Windows: select the executable from the official
Hamlib distribution in Setup. No radio/audio stream opens at startup.

All packages run an offline self-test against their **built executable**:
MSK/4L-FSK with and without FEC, Japanese text, WAV/FLAC, image editor, SQLite,
ADIF, waterfall, Tk EN/DE and external Hamlib Dummy control.
ARM64 build and validation use a target-architecture container under emulation;
physical Raspberry Pi and IC-7610 testing remains pending.

This is a **preview**, not a claim of complete original-KG-STV compatibility.
See [compatibility status](https://github.com/DH5DAX/open-kgstv/blob/main/COMPATIBILITY.md)
and [build instructions](https://github.com/DH5DAX/open-kgstv/blob/main/packaging/BUILDING.md).

Deutsch: Unsignierte Einzeldatei-Pakete zum Entpacken und Starten, ohne
Python-Installation. Die Raspberry-Version setzt ein 64-Bit-System voraus.
CAT-Steuerung verwendet eine separate Hamlib-Installation oder einen rigctld-Server.
Geprüft mit Offline-Signalen und Software-Dummy; echte Hardwaretests und weitere
Kompatibilitätsnachweise stehen aus.
