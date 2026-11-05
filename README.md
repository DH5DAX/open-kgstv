# Open KG-STV

Eigenständiger Python-Nachbau des digitalen Bildfunkprotokolls von KG-STV.
Der eigene Code steht unter der MIT-Lizenz. Ziel ist Interoperabilität mit
KG-STV 1.0.1 build 004. **Eine vollständige Kompatibilitätszusage gibt es noch
nicht**; die einzelnen Nachweise stehen in [COMPATIBILITY.md](COMPATIBILITY.md).

## Aktueller Funktionsumfang

- MSK und 4L-FSK, jeweils mit oder ohne Faltungscode.
- WAV-/MP3-Empfang, Text und 320×240-Bilder, getrennte CRC-Prüfungen.
- Sender für Text und Bilder, WAV-Export und explizite Soundkartenausgabe.
- Alle 16 Kompressionsskalen; horizontale, vertikale und zufällige Blockfolge.
- Experimentelle BSR-Anfragen, Antworten und Bildreparatur.
- Tk-Oberfläche mit Bildvorschau, Textprotokoll, Live-Empfang und optionalem
  seriellen RTS-/DTR-PTT. Kein Senden beim Start.
- Empfangsberichte mit Paketdaten, Fehlerstatus und fehlenden Bildblöcken.

Sechs öffentlich verfügbare Original-Bildaufnahmen werden mit je **300/300
CRC-gültigen Bildblöcken** empfangen. Beide Original-Textaufnahmen werden korrekt
gelesen. Gegen die verlustfreien Referenzbilder bei Scale 1.0 und 0.5 liegt die
maximale Abweichung bei 1 auf der RGB-Skala von 0 bis 255; über 99,5 % der Kanalwerte
sind identisch. Das ersetzt keinen Test unserer Sendesignale im Windows-Original.

## Installation und Start

Python 3.11 oder neuer; lokal geprüft mit Python 3.13. Tk muss installiert sein
(bei Python für Windows enthalten; auf manchen Linux-Systemen `python3-tk`).

```console
python -m pip install -e ".[audio,live]"
python -m kgstv gui
```

Unter Windows kann mit vorhandenem Python 3.13 auch `start-gui.cmd` verwendet
werden. Für die reine WAV-Kommandozeile reicht `pip install -e .`.

Die Oberfläche öffnet beim Start keine Audiogeräte. „Geräte laden“ listet
Eingänge und Ausgänge. „Empfangen“ startet den ausgewählten Eingang. Vor dem
Senden einen laufenden Empfang stoppen. „Bild senden“ und „Text senden“ geben
Audio auf dem gewählten Ausgang aus; ein eingetragener PTT-Port wird dabei
aktiviert. Ein leerer PTT-Port bedeutet: keine serielle Steuerung.

## Kommandozeile

Aufnahme empfangen; Bilder und `report.json` landen in einem neuen Ordner:

```console
python -m kgstv decode aufnahme.wav --output empfang
python -m kgstv decode aufnahme.mp3 --output empfang-mp3 --frequency-offset 70
```

Ein positiver Frequenzversatz bedeutet, dass die aufgenommenen Töne zu hoch
liegen. Ein gefüllter Ausgabeordner wird nur mit `--force` erneut verwendet.

Text oder ein Bild als 48-kHz-/16-Bit-Mono-WAV vorbereiten:

```console
python -m kgstv encode-text "Hallo, 73!" --callsign DL0TEST --output text.wav
python -m kgstv encode-image bild.png --callsign DL0TEST --mode 4fsk --fec --scale 0.5 --output bild.wav
```

Diese Befehle öffnen **keine** Soundkarte und schalten **kein** PTT. Die
Rufzeichen in den Beispielen sind Platzhalter. Text muss in CP932/Shift-JIS
darstellbar sein; maximal 510 codierte Bytes einschließlich Rufzeichenpräfix.

Experimentelle Reparatur:

```console
python -m kgstv request-repair empfang/report.json --callsign DL0TEST --output bsr.wav
python -m kgstv decode bsr-vom-partner.wav --output anfrage
python -m kgstv encode-image urspruengliches-bild.png --callsign DL0TEST --repair-request anfrage/report.json --output reparatur.wav
```

Für eine Antwort muss genau das vorher gesendete Bild verwendet werden. Das
Originalprotokoll enthält keine hier nachgewiesene eindeutige Bild-ID. Die
BSR-Sitzungsdetails sind noch nicht gegen das laufende Original geprüft.

## Tests

```console
python tools/fetch_fixtures.py
python -m unittest discover -v
```

Der Download ist ausdrücklich, hashgeprüft und umfasst nur öffentliche
Audio-/Bild-Testdaten. Ohne die Aufnahmen werden die Originalsignal-Tests als
übersprungen gemeldet. Die Fremddateien unter `research/reference/` sind
gitignoriert und werden nicht im Python-Paket ausgeliefert.

## Aufbau

| Modul | Verantwortung |
|---|---|
| `protocol.py` | Bits, CRC, Whitening, Faltungscode, Header und Kommandos |
| `modem.py` | Phasenkontinuierliche Modulation, Synchronisation, MSK/4L-FSK |
| `imagecodec.py` | KG-STV-spezifischer Bildbitstrom, DCT und Huffman-Codes |
| `session.py` | Bildaufbau, Rufzeichen, Sender und experimentelles BSR |
| `audio.py` | Offline-Audio, WAV/MP3 und Abtastratenkonvertierung |
| `live.py` | Optionale Soundkarte und PTT mit Freigabe im Fehlerfall |
| `cli.py`, `gui.py` | Kommandozeile und Desktop-Oberfläche |

## Herkunft

Primärquelle sind die erhaltenen japanischen Readmes von JJ0OBZ und öffentliche
Testaufnahmen von [SigIDWiki](https://www.sigidwiki.com/wiki/KG-STV). Das Projekt
[multiplatform-KGSTV](https://github.com/barisdinc/multiplatform-KGSTV) lieferte
technische Ansatzpunkte. Sein Python-Forschungscode und seine aus dem Original
extrahierten Filter wurden nicht übernommen. Die hier implementierten
Koeffizienten-, Farb- und Quantisierungskonventionen wurden unabhängig an den
Referenzbildern geprüft. JPEG-Standardtabellen werden aus Pillow gewonnen.

Die MIT-Lizenz dieses Projekts umfasst eigenen Code und eigene Dokumentation,
nicht die separat heruntergeladenen Originalprogramme, Bilder oder Aufnahmen.
