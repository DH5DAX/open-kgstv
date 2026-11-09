# Radio control with Hamlib

Open KG-STV talks to Hamlib's `rigctld` using TCP. It can start and stop its own
local daemon for a USB/CAT radio, or connect to an existing server. Frequency,
mode and PTT are read back in the operating window. **⚙** opens connection,
audio and PTT setup; there are no navigation tabs. No connection starts automatically.
Audio still travels through the soundcard selected under **⚙ → Audio & PTT**.

## Install Hamlib

For a Windows x64 checkout:

```console
python tools/fetch_hamlib.py
```

This explicitly downloads the official Hamlib 4.7.2 ZIP, verifies its pinned
SHA-256, and extracts it under `outputs/hamlib`. The application finds that copy
automatically; restart the application after downloading. Nothing is installed
system-wide. The archive and its licenses remain alongside the executable.

Alternatively install [Hamlib](https://github.com/Hamlib/Hamlib/releases/tag/4.7.2)
yourself and select `rigctld.exe` / `rigctld` with **Browse…**, or put it on PATH.
On Linux and macOS use an appropriate Hamlib package for your system. Neither
Hamlib binaries nor Python Hamlib bindings are bundled in the Python package.

## Icom IC-7610 over USB

1. Install the [Icom USB driver](https://www.icomjapan.com/support/firmware_driver/1974/)
   following its installation guide. Connect the radio's USB port for CI-V/audio
   and identify its CI-V COM port. Close other applications using that port.
2. Under the radio's **MENU → SET → Connectors → CI-V**, match these settings:
   **CI-V Address: 98h**, **CI-V USB Port: Unlink from [REMOTE]** and
   **CI-V USB Baud Rate: 115200**. If your radio has a different CI-V address or
   baud rate, use its actual values in the application instead.
3. Under **Connectors**, set **DATA1 MOD: USB** for USB-D1 operation. The IC-7610
   has separate DATA1/2/3 input selections; check the input for the data mode
   actually shown on the radio. With CAT PTT, leave **USB SEND** off so serial
   control-line changes do not also key the transmitter.
4. In Open KG-STV select **⚙ → IC-7610 USB profile**. This selects Hamlib
   model **3078**, 115200 baud, CI-V **0x98** and **Hamlib CAT PTT**. Choose the
   correct **CAT port / device** using **Refresh ports**, save and close Setup,
   then click **Connect** in the operating window.
5. Verify that frequency and mode match the radio. Connecting only reads state;
   it does not tune the radio or key PTT. Open **Frequency & mode…** to set these
   explicitly when needed. **PKTUSB** requests USB data mode; filter **0** uses
   Hamlib's normal/default width.
6. Under **⚙ → Audio & PTT**, refresh devices and choose the IC-7610 USB input and
   output. CAT connection alone does not select the soundcard. Start reception
   to check decoding. For transmission, stop reception, enter your callsign,
   and use **Send image** or **Send text**. Set audio drive and radio output
   levels for your station before an on-air test.

The menu names above follow Icom's [basic manual, Connectors section](https://icomuk.co.uk/files/icom/PDF/productManual/IC-7610_ENG_BM_6.pdf).
The model's default CI-V address and serial range are documented in the
[Hamlib IC-7610 backend](https://github.com/Hamlib/Hamlib/blob/4.7.2/rigs/icom/ic7610.c).
This profile has been implemented and tested with simulated CAT responses;
**a physical IC-7610 USB/audio/RF test is still pending**.

## PTT and connection lifecycle

- **Hamlib CAT PTT** replaces serial RTS/DTR PTT for that transmission. It must
  be selected explicitly; the IC-7610 preset selects it for you.
- The default lead/tail times are 200/100 ms, adjustable from 0 to 10000 ms.
  PTT is requested before playback and released after playback, cancellation,
  an audio error, disconnect or a normal application shutdown.
- **PTT off / RX** stops playback and requests receive. It never sends PTT-on.
  If OFF cannot be confirmed, a visible error remains and another OFF request
  is possible. Do not assume that a disconnected radio has returned to RX.
- Ordinary failed commands are not retried automatically. Only PTT-off may use
  one new connection to recover from a lost acknowledgement. There is no
  automatic reconnection or automatic resumption of transmission.
- A radio already reporting TX is not taken over by a new audio transmission.
  Forced process termination or loss of power cannot guarantee PTT release.
- WAV export never connects to a radio or activates PTT.
- **Save radio profile**, **Save & close** and **Connect** save connection/PTT
  settings alongside the language preference. **Save & close** also remembers
  audio-device names and serial PTT; callsign is saved on application close.
  Messages and images are stored separately in the local library.

The operating window also provides sourced [activity presets](ACTIVITY-FREQUENCIES.md).
QO-100 requires a station-specific CAT/IF dial and does not configure split or a
transverter automatically. Selection alone never tunes or transmits.

## Other radios and existing servers

Use **Load models** to read supported models from your installed Hamlib version.
Choose the model/device, match its baud rate, and clear the Icom-specific CI-V
field for non-Icom devices. Supported operations depend on the Hamlib backend;
unsupported optional mode/PTT readback is shown as `—`, not an invented value.

For an existing daemon, choose **Existing rigctld server** and enter its address
and port (default 4532). The application does not terminate an external daemon.
The [rigctld protocol](https://hamlib.sourceforge.net/html/rigctld.1.html) has no
authentication here: keep the server on localhost or a trusted private network.
An application-owned local daemon listens only on `127.0.0.1`, on a temporary port.

## Repeatable software verification

The normal test suite includes a simulated TCP server, fragmented replies,
VFO-mode handshakes, errors/timeouts, lost PTT acknowledgements, audio failures,
saved profiles and the GUI's send path. It opens no physical radio or soundcard.
Enable the additional real Hamlib **Dummy** backend test in PowerShell with:

```powershell
$env:KGSTV_RIGCTLD = (Resolve-Path 'outputs/hamlib/hamlib-w64-4.7.2/bin/rigctld.exe').Path
python -m unittest tests.test_hamlib -v
```

`python tools/screenshot_demo.py radio` opens the actual GUI connected only to
that Dummy backend, for documentation and manual UI inspection.
