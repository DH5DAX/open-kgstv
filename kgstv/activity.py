"""Published activity points, reviewed 2026-11-09; not a live activity feed.

See docs/ACTIVITY-FREQUENCIES.md for evidence, dates and scope limitations.
"""
from dataclasses import dataclass
import math

REVIEWED = "2026-11-09"
USKA = "https://uska.ch/en/radio-amateurs/operation/modes/image-transmission/"
F5PEY = "https://www.qsl.net/f5pey/kgsstv/kgstv.html"
QO_SOURCE = "https://www.ref66.fr/2026/05/24/transmettre-des-images-sur-qo-100-au-dela-de-la-sstv/"


@dataclass(frozen=True)
class Activity:
    id: str
    hz: int
    en: str
    de: str
    note_en: str
    note_de: str
    source: str
    satellite: bool = False

    def label(self, language):
        return f"{self.hz/1e6:.6f} MHz · "+(self.de if language == "de" else self.en)

    def note(self, language):
        return self.note_de if language == "de" else self.note_en

    def dial_hz(self, satellite_dial=""):
        if not self.satellite:
            return self.hz
        try:
            hz = float(satellite_dial.replace(",", "."))*1e6
            if not math.isfinite(hz) or not 0 < hz <= 1e12:
                raise ValueError
            return round(hz)
        except (ValueError, AttributeError) as exc:
            raise ValueError("Enter your station's actual QO-100 CAT/IF dial frequency") from exc


ACTIVITIES = (
    Activity("20m", 14233000, "20 m · KG-STV / digital SSTV", "20 m · KG-STV / Digital-SSTV",
        "KG-STV reception documented by F5PEY; shared with other digital SSTV. USB dial frequency.",
        "KG-STV-Empfang bei F5PEY dokumentiert; mit anderen Digital-SSTV-Verfahren geteilt. USB-Skalenfrequenz.", F5PEY),
    Activity("80m", 3733000, "80 m · shared digital SSTV", "80 m · gemeinsames Digital-SSTV",
        "USKA lists this USB digital-SSTV calling point. No dedicated KG-STV schedule verified.",
        "USKA nennt diesen USB-Digital-SSTV-Treffpunkt. Kein eigener KG-STV-Zeitplan bestätigt.", USKA),
    Activity("40m", 7173000, "40 m · shared digital SSTV", "40 m · gemeinsames Digital-SSTV",
        "USKA lists this USB digital-SSTV calling point. Regional practice varies; no exclusive KG-STV channel.",
        "USKA nennt diesen USB-Digital-SSTV-Treffpunkt. Regionale Nutzung variiert; kein exklusiver KG-STV-Kanal.", USKA),
    Activity("15m", 21340000, "15 m · shared SSTV", "15 m · gemeinsames SSTV",
        "USKA lists analogue and digital SSTV here. A general rendezvous, not verified regular KG-STV activity.",
        "USKA nennt hier analoges und digitales SSTV. Allgemeiner Treffpunkt, keine bestätigte regelmäßige KG-STV-Aktivität.", USKA),
    Activity("qo100", 10489625000, "QO-100 · KG-STV downlink", "QO-100 · KG-STV-Downlink",
        "KG-STV USB downlink confirmed in a May 2026 club report. RF uplink: 2400.125 MHz. Enter your CAT/IF dial below; no split or transverter setup is configured automatically.",
        "KG-STV-USB-Downlink im Clubbericht vom Mai 2026 bestätigt. HF-Uplink: 2400,125 MHz. Unten die eigene CAT-/ZF-Skalenfrequenz eintragen; Split und Transverter werden nicht automatisch konfiguriert.", QO_SOURCE, True),
)
