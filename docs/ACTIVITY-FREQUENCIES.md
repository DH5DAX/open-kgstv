# KG-STV activity points

Reviewed **9 November 2026**. These are published meeting points, not a live
activity feed, guaranteed schedules or exclusive KG-STV channels.

| USB dial / RF frequency | Evidence | Classification in the application |
|---|---|---|
| **14.233 MHz** | [F5PEY's KG-STV receiving page](https://www.qsl.net/f5pey/kgsstv/kgstv.html) describes reception generally on 14233 kHz; [USKA](https://uska.ch/en/radio-amateurs/operation/modes/image-transmission/) lists the same digital-SSTV point | Documented KG-STV use, shared digital SSTV |
| **3.733 MHz** | USKA's digital-SSTV list | Shared digital SSTV; no dedicated KG-STV schedule verified |
| **7.173 MHz** | USKA's digital-SSTV list | Shared digital SSTV; regional practice varies |
| **21.340 MHz** | USKA lists both analogue and digital SSTV | Shared SSTV; regular KG-STV activity not independently established |
| **10489.625 MHz** | [F6KBR / REF66 report, 24 May 2026, citing F8BSY](https://www.ref66.fr/2026/05/24/transmettre-des-images-sur-qo-100-au-dela-de-la-sstv/) explicitly gives KG-STV on QO-100 in USB | QO-100 KG-STV downlink |

The F5PEY page is undated: it documents a listening frequency, not evidence of
continuous activity in November 2026. The REF66 article is a dated 2026 operating
report. Its suggested KG-STV settings are MSK, Normal (no convolutional FEC),
scale 1.0. Selecting a frequency does not change the modem's settings.

The [AMSAT linear satellite table](https://www.amsat.org/live-linear-satellites/)
lists QO-100's non-inverting narrowband transponder: 2400.000–2400.500 MHz uplink
corresponds to 10489.500–10490.000 MHz downlink. **2400.125 MHz uplink is calculated**
from that mapping for the 10489.625 MHz downlink.

## Using the list

Choose a point in **Activity frequencies** in the operating window. Selection
alone does not tune or transmit. **Tune selected** explicitly sends frequency
and `PKTUSB` (USB data mode) to the connected Hamlib radio; unsupported operations
produce an error, with no automatic fallback or PTT activation. A mode-setting
error can occur after frequency has already changed; check the readback.
**Info…** explains the entry and offers its source in the browser.

QO-100 requires an explicit **CAT/IF dial frequency** for your station. The
10 GHz downlink must not be sent directly to an IC-7610's CAT dial. Open KG-STV
does not infer converter offsets, configure split, route separate uplink/downlink
radios or track satellite Doppler. Configure your RF chain yourself. The QSO
dialog records actual RF frequencies, with separate TX/RX fields, rather than
copying an applied satellite preset's IF into the logbook.

Check the applicable band plan, licence privileges and occupancy before on-air
use. These presets are reference points, not permission to transmit. They are
static and offline; the application performs no background web requests.

## Deliberately excluded

- Ordinary analogue-SSTV frequencies such as 14.230 MHz are not labelled KG-STV.
- Secondary lists mention 14.111 MHz, but a current primary KG-STV operating
  source was not established in this review, so it is not a default preset.
- Historical ISS KG-STV experiments do not establish a current regular service.
- HS Modem's QO-100 point is a different protocol and is not a KG-STV preset.

The catalogue and bilingual notes live in `kgstv/activity.py`; update the source
links, evidence qualifications, review date and tests when changing it.
