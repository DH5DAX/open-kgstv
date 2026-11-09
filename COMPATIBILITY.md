# Kompatibilitätsstand

Referenzziel: **KG-STV 1.0.1 build 004**, EXE-SHA-256
`4e1d3d121c7259410364863d4a31d94e27be186c733e4a2005255c1ee963b116`.

## Nachweise und Grenzen

Lokaler Prüfstand am 9. November 2026: 99 automatische Tests bestanden unter
Python 3.13. Zusätzlich wurde ein vollständiges Bild über den WAV-Export der
Oberfläche mit 4L-FSK/CONV erzeugt und wieder empfangen: 300/300 Bildblöcke,
336 gültige Nutzdatenpakete, keine CRC-Fehler. Das Live-Fensterverhalten und
PTT-Freigaben bei Fehlern werden mit simulierten Audiogeräten geprüft.
Hinzu kommen Tests für den Sprachwechsel während laufender Vorgänge, den Erhalt
der Eingaben und Geräteauswahl, die gespeicherte Sprache sowie WAV-Textexport
aus der zweisprachigen Oberfläche. Dabei wird keine Funkhardware geöffnet.
Hamlib wird mit simulierten TCP-Antworten und dem echten Dummy-Backend aus
Hamlib 4.7.2 geprüft: Frequenz/Betriebsart, CAT-PTT, Verbindungsverlust,
unbestätigte PTT-Freigabe, Prozessende und gespeicherte Profile. Das
IC-7610-USB-Profil ist vorbereitet, der physische Gerätetest steht aus.
Der lokale Bildeditor wurde mit Ebenen, RX-Collagen, Texten, portablen Vorlagen
und Undo/Redo geprüft. Weitere Tests sichern Galerie-/Chat-Persistenz,
kompakte deutsche Fenster, die ausdrücklich ausgelöste Frequenzwahl sowie
ADIF-Anhängen, stabile QSO-IDs, UTC-Tageswechsel, Satellitenfrequenzen und
Schreibfehler ab. Die neuen Fenster wurden zusätzlich am echten Windows-Desktop
angesehen. Fünf aktuelle Screenshots und ein geprüftes Python-Wheel liegen vor.

| Teil | Stand |
|---|---|
| Original MSK/NORM-Text | Öffentliche Aufnahme vollständig, beide CRCs gültig |
| Original 4L-FSK/NORM-Text | Öffentliche Aufnahme vollständig, beide CRCs gültig |
| Original MSK/NORM-Bild | 300/300 eindeutige Bildblöcke, keine Nutzdaten-CRC-Fehler |
| Original MSK/CONV-Bild | 300/300 eindeutige Bildblöcke, keine Nutzdaten-CRC-Fehler |
| Original 4L-FSK/NORM-Bild | 300/300 eindeutige Bildblöcke, keine Nutzdaten-CRC-Fehler |
| Original 4L-FSK/CONV-Bild | 300/300 eindeutige Bildblöcke, keine Nutzdaten-CRC-Fehler |
| Zusätzliche Scale-0.1-/0.5-Aufnahmen | Je 300/300 eindeutige Bildblöcke |
| Pixel bei Scale 1.0 und 0.5 | Maximal 1/255 Abweichung pro Farbkanal zum Referenz-PNG; Mittel <0.01 |
| Pixel bei Scale 0.1 | Referenz liegt verlustbehaftet als JPEG vor; kein pixelgenauer Nachweis |
| Eigener TX → eigener RX | Text und variable Bildpakete in allen vier Modus/FEC-Kombinationen |
| Eigener TX → Windows-Original | **Ausstehend** |
| BSR über Audio gegen Original | **Ausstehend**; interne Zustands-/Pakettests vorhanden |
| Alle 16 Skalen gegen Original | **Ausstehend**; eigene Farb-/Codec-Tests vorhanden |
| Live-Audio und PTT an Hardware | Implementiert, **nicht an Funkhardware getestet** |
| Hamlib-Frequenz/Betriebsart/CAT-PTT | Softwaretests mit rigctld 4.7.2 bestanden; IC-7610-Hardwaretest ausstehend |
| TX-Editor, Vorlagen, Galerie, Chat | Lokal implementiert und getestet; keine HamRig-Portal-Serversynchronisierung |
| Aktivitätsfrequenzen | Quellenstand 09.11.2026, keine Live-Aktivitätsanzeige |
| QSO-Logbuch | Lokales ADIF 3.1.8; Online-Anbindungen noch nicht implementiert |
| Windows-INI, Image-Processor-IPC, Archivdetails | Nicht implementiert |
| Audio-Wasserfall | Live-RX 0–3 kHz, acht Sekunden, Pegel/Clipping; mit synthetischem Audio geprüft |
| Augendiagramm | Nicht implementiert |

Die Originalaufnahmen stammen aus einer kleinen, sauberen Testsammlung. Der
Erfolg sagt nichts über die allgemeine Empfindlichkeit bei Fading, Multipath,
starkem Taktfehler, Clipping oder Doppler aus. Frequenzversatz kann manuell
korrigiert werden; eine automatische AFC ist noch nicht implementiert.

BSR folgt der dokumentierten System-0-Struktur mit Koordinaten im Header. Die
Build-004-Zustandsmaschine ist bislang nur teilweise abgebildet. Wiederholte
Rufzeichen während eines Bildes löschen das Bild nicht; Reparaturblöcke werden
nur einem vorhandenen Bild mit passendem Rufzeichen zugeordnet. Ein neuer
Bildbeginn ohne erkennbare Rufzeichen-/Abschlusssequenz bleibt ein offener Fall.
Der Live-Empfänger verwendet überlappende 20-Sekunden-Fenster und hat mehrere
Sekunden Latenz. Er ist noch kein gegen alle Audioaussetzer validierter
Streaming-Modemkern.

## Unabhängig geklärte Bildcodec-Details

Die frühere Recherche enthielt Hypothesen anderer Projekte. Diese wurden bei
der Implementierung nicht als garantiert behandelt:

1. Negative Koeffizienten folgen einer Sign-/Magnitude-Konvention. Bei zwei
   Amplitudenbits bedeuten `00 → -2`, `01 → -3`, `10 → +2`, `11 → +3`.
   Das ist **nicht** die übliche JPEG-Komplementdarstellung negativer Werte.
2. Die Farbtransformation arbeitet auf BGR. Auf dem Funkweg folgen vier
   Y-Blöcke und dann Cb/Cr in diesem BGR-bezogenen Farbraum. Beim Rekonstruieren
   gilt `R = Y + 1.772*Cb`, `B = Y + 1.402*Cr` für bereits zentrierte Chroma-Werte.
3. Die Quantisierungsmatrix ist `Standardtabelle * Scale`, mit gebrochenen
   Einträgen. Rundung auf ganze JPEG-Quantisierungswerte erzeugt messbare Fehler.
4. RGB-Ausgabe wird begrenzt und abgeschnitten, nicht zum nächsten Ganzzahlwert
   gerundet. Kleine Restabweichungen sind noch vorhanden und werden nicht als
   vollständige Pixelidentität ausgegeben.
5. Alle vier Y-Blöcke haben einen unabhängigen DC-Ursprung; ihre räumliche
   Reihenfolge ist oben links, oben rechts, unten links, unten rechts.

Die End-to-End-Tests gegen die Referenz-PNGs sichern diese Kombination ab. Das
eigene Encoding ist noch nicht im Windows-Original verifiziert; dort bleiben
insbesondere DCT-Rundung, Grenzwerte und Fehlerfälle zu untersuchen.

## Nächster verbindlicher Gegentest

1. WAVs unseres Senders verlustfrei in den Audioeingang des unveränderten
   Windows-Originals führen; PTT/RF dabei deaktiviert lassen.
2. Texte einschließlich japanischer Zeichen und maximaler Länge prüfen.
3. Farbflächen, Grauverläufe, Schachbrett und ein Foto bei allen Skalen und
   Modulations-/FEC-Einstellungen übertragen.
4. Einzelne Bildpakete auslassen; BSR in beiden Richtungen austauschen.
5. Abbruch, Neustart, doppelte Abschlussmeldungen, mehrere Stationen und
   Empfang mitten im Bild testen.

In der vorliegenden Umgebung wurde kein virtueller Audioeingang/-ausgang
gefunden. Es wurde kein Treiber installiert, kein Funkgerät aktiviert und kein
Audiosignal auf einen Hardwareausgang ausgegeben.
