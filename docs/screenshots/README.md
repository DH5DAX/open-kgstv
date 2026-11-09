# Screenshot sources

These are captures of the real Windows Tk application with the dark
HamRig-inspired interface. No application controls or reception results were painted onto the
screenshots. The calibration card is original project artwork under the MIT
license; no downloaded reference images are included.

To reproduce a scene from an installed checkout:

```console
python tools/studio_demo.py operating
python tools/studio_demo.py operating --language de
python tools/studio_demo.py editor
python tools/studio_demo.py gallery
python tools/studio_demo.py history
python tools/studio_demo.py qso
python tools/studio_demo.py setup
```

The current screenshots (`operating.jpg`, `operating-de.jpg`, `tx-editor.jpg`,
`gallery.jpg`, `qso-log.jpg`) use original generated landscape/test-card artwork,
isolated sample contacts and Hamlib Dummy at 14.233 MHz, PKTUSB, RX. They demonstrate
the real UI, not received on-air contacts. Each run stores sample data in a fresh
folder under `outputs/studio-demo/`; the user's normal library/logbook is untouched.
Use `--compact` for minimum-size layout checks. The editor and QSO dialog have
scrollable inspectors/forms; chat remains visible below the operating workspace.

The following earlier screenshots preserve modem-loopback verification scenes
and show the previous navigation layout. To reproduce the same signal tests
with the current UI:

```console
python tools/screenshot_demo.py image
python tools/screenshot_demo.py missing
python tools/screenshot_demo.py text
python tools/screenshot_demo.py image --language de
python tools/screenshot_demo.py radio
```

Run one scene at a time. After decoding finishes, capture that application's
window and close it before starting the next scene. The script writes a
verification summary to `outputs/screenshots/<scene>.json` after the GUI has
processed the received frames. It opens no soundcard or serial PTT port.

| File | Scene |
|---|---|
| `image-reception.jpg` | Own 4L-FSK/CONV transmitter → receiver, 300/300 image blocks |
| `missing-blocks.jpg` | Same image with 24 deliberately omitted packets, 276/300 blocks |
| `text-reception.jpg` | Three MSK text messages decoded into the receive log |
| `interface-de.jpg` | Complete image reception after switching the interface to German |
| `hamlib-radio.jpg` | Real Hamlib Dummy backend: 14.230 MHz, PKTUSB, RX; no physical radio |
| `hamlib-ptt-de.jpg` | German PTT controls, compact window scrolled to the bottom |

The scene starts in English unless `--language de` is supplied. The EN/DE buttons
also work during the demo; its language preference is kept separately under
`outputs/screenshots/<scene>-settings.json`. Captures use the default window size.
`--compact` opens the minimum supported window for layout checks.

Image and text scenes pass generated audio through the actual modem decoder.
The radio scene requires Hamlib and connects only to its software Dummy backend.
These are local demonstrations, not original-application or radio-hardware tests.
The header and window icon use the original [HamRig Robbie artwork](../../kgstv/assets/README.md).
