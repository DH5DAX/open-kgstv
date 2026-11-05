# Recherchearchiv

Diese Dateien dokumentieren die erste Recherche vom 5. November 2026 und den
damaligen MSK-Textversuch. Sie enthalten historische Zwischenstände und
Hypothesen, die bei der späteren Implementierung teilweise korrigiert wurden.
Für den aktuellen Nachweisstand gilt [COMPATIBILITY.md](../COMPATIBILITY.md),
insbesondere für Koeffizientenvorzeichen, Farbtransformation und Quantisierung.

- `findings.json`: Quellen, dokumentierte Protokolleigenschaften und damalige
  offene Fragen.
- `reference_manifest.json`: Metadaten und Prüfsummen der lokal gesicherten
  Originalunterlagen; die Fremddateien selbst werden nicht veröffentlicht.
- `audio_inventory.json`: Metadaten der öffentlichen Testaufnahmen.
- `probe_msk.py`, `msk_probe_result.json`: früher unabhängiger MSK-Textversuch.

Die für die heutigen Tests benötigten Aufnahmen und Referenzbilder lassen sich
mit `python tools/fetch_fixtures.py` aus dem Projektverzeichnis herunterladen.
Ihre URLs und SHA-256-Prüfsummen stehen in `tests/fixtures.json`.
