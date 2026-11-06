# Screenshot sources

These are captures of the real Windows Tk application with the dark
HamRig-inspired interface. No application controls or reception results were painted onto the
screenshots. The calibration card is original project artwork under the MIT
license; no downloaded reference images are included.

To reproduce a scene from an installed checkout:

```console
python tools/screenshot_demo.py image
python tools/screenshot_demo.py missing
python tools/screenshot_demo.py text
python tools/screenshot_demo.py image --language de
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

The scene starts in English unless `--language de` is supplied. The EN/DE buttons
also work during the demo; its language preference is kept separately under
`outputs/screenshots/settings.json`. Captures use the default window size.

All scenes pass generated audio through the actual modem decoder. They are
local demonstrations, not original-application or radio-hardware tests.
