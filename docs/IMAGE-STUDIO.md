# Images, templates and message history

**Edit TX image…** opens the composition editor. **Use as TX image** renders a
320×240 KG-STV picture and saves the editable draft for the next application
start. It does not transmit. Image files remain unchanged.

- Load a photo as the background or add multiple image layers, including the
  current RX picture or an earlier received image from the gallery.
- Drag layers on the preview. The lower-right handle resizes; arrow keys move
  by one pixel, Shift+arrows by ten. Forward/backward changes stacking order.
- Adjust fit/crop position, brightness, contrast, colour, sharpness, mirroring,
  rotation and opacity. Auto levels and reset are available for image layers.
- Add text with font, size, alignment, bold, colour, outline and shadow.
  Templates can contain `{MYCALL}`, `{HISCALL}`, `{DATE}` and `{TIME}`; time is UTC.
  CQ, Reply + RX, RSV 595 and 73 buttons add editable layers.
- Undo/redo retains up to 50 steps. Applying the picture stores its current
  resolved callsigns and time; open the editor and apply again to update them.
- Export a flattened PNG/JPEG, or save/import/export an editable `.kgstv.json`
  template. Templates embed their source images and do not depend on file paths.

The editor keeps independent, EXIF-oriented image sources, bounded to 2048 pixels
per side. A composition has at most 64 layers and its portable JSON is limited
to 32 MB. Fonts use installed system fonts with fallbacks; different machines
can render text differently. The wire image remains 320×240.

## Local gallery

**Gallery** groups received images, transmitted images, photos and templates.
Search, import several photos, rename, duplicate, remove or export entries.
Select an item to open it in the editor; when opened from the editor, it can
also become a background or another layer. Removal affects the local library
entry, not an imported file. Saving a template creates a new entry; manage older
versions with rename/delete.

RX images with at least one valid tile are archived at END/ABORT; metadata
includes callsign, received/missing blocks and abort status. Duplicate end
frames do not create duplicate entries. A later completed repair can create
a new version. Successfully played image transmissions are archived as TX.
Canceled playback and WAV exports are not recorded as on-air transmissions.
Playback completion does not prove reception by another station.

## Messages

The operating window keeps a seven-line scrollable view of the latest 200
messages, pinned below the images. **Full history…** opens a larger searchable
window, initially showing 500 messages. **Load more** retrieves earlier entries;
**Export shown messages…** writes UTF-8 text. Follow-new can be disabled while
reading. RX and successfully played TX text are timestamped and saved; display
timestamps use the computer's local timezone, while storage uses UTC.

## Storage and provenance

`library.sqlite3` sits beside `settings.json` in the application's configuration
folder. It contains gallery images, templates, the applied TX draft and full
message history. There is no automatic retention limit. Close the application
before copying this file for backup. Imports are local; there is no cloud upload.

The workflows were independently implemented in Python after inspecting HamRig
Portal's SSTV client (`client/sstv-popup.html`, fetched on 2026-11-09). The local
gallery is shared by Open KG-STV's RX, TX and editor workflows. It does **not**
synchronize with the portal's server gallery or use its template file format.
Protocol-specific analogue SSTV slant correction does not apply to KG-STV tiles.
