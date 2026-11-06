"""UI translations and the user's language preference; no Tk dependency."""
import json
import os
from pathlib import Path
import sys
import tempfile


EN = {
    "subtitle": "Digital image & text radio",
    "beta": "BETA",
    "language": "Language",
    "workspace": "Images & messages",
    "audio_tab": "Audio & PTT",
    "callsign": "Callsign",
    "modulation": "Modulation",
    "fec": "Error correction",
    "scale": "Compression scale",
    "format": "320 × 240 px  ·  1200 baud",
    "transmit": "Transmit image",
    "receive": "Receive image",
    "tx_empty": "Your next transmission",
    "tx_hint": "Open an image to get started",
    "rx_empty": "Waiting for an image",
    "rx_hint": "Open a recording or start audio reception",
    "open_image": "Open image…",
    "save_wav": "Save WAV…",
    "send_image": "Send image",
    "open_recording": "Open recording…",
    "save_image": "Save image…",
    "repair_response": "Repair response as WAV…",
    "repair_request": "Request missing blocks…",
    "experimental": "BSR · experimental",
    "image_ready": "Image ready · 320 × 240 px",
    "no_image": "No image loaded",
    "no_received_image": "No image received yet",
    "blocks": "{good}/300 blocks",
    "complete": "Complete",
    "missing": "{count} missing",
    "unknown": "Unknown station",
    "messages": "Messages",
    "message_hint": "Received text appears here",
    "compose": "Your message",
    "text_wav": "Text to WAV…",
    "send_text": "Send text",
    "input": "Audio input",
    "output": "Audio output",
    "input_hint": "Select the soundcard connected to your receiver.",
    "output_hint": "Select the output used for transmission.",
    "default_device": "System default",
    "refresh_devices": "Refresh devices",
    "frequency": "Receive offset (Hz)",
    "frequency_hint": "Positive values correct tones that are too high. Range: −500 to +500 Hz.",
    "ptt": "Transmitter control",
    "ptt_port": "Serial port",
    "ptt_line": "PTT line",
    "ptt_hint": "Leave the port empty to disable serial PTT. WAV export never activates PTT.",
    "audio_hint": "Audio devices open only when you start receiving or sending.",
    "start_rx": "Start receiving",
    "stop": "Stop",
    "idle": "STANDBY",
    "working": "PROCESSING",
    "rx": "RECEIVING",
    "tx": "TRANSMITTING",
    "stopping": "STOPPING",
    "ready": "Ready",
    "processing": "Processing…",
    "stopped": "Operation stopped",
    "starting_rx": "Opening audio input…",
    "live_receiving": "Receiving from the selected audio input",
    "audio_gap": "Audio gap detected · reacquiring synchronization",
    "live_stopped": "Reception stopped",
    "transmitting": "Transmitting · {seconds:.1f} seconds",
    "transmitted": "Transmission finished",
    "wav_saved": "WAV saved · {seconds:.1f} seconds · {path}",
    "decoded": "{count} packets decoded · saved to {path}",
    "requested": "Repair request received · {count} blocks",
    "devices_loaded": "Found {inputs} inputs and {outputs} outputs",
    "image_opened": "Image loaded · {name}",
    "image_saved": "Received image saved · {path}",
    "preference_error": "Language changed, but the preference could not be saved",
    "compatibility": "Compatibility testing in progress",
    "about_title": "About Open KG-STV",
    "about": "Open KG-STV {version} · MIT license\n\nAn independent Python implementation of KG-STV.\n\nOriginal recordings decode successfully. Transmission into the original application, BSR interoperability and radio hardware tests are still pending.",
    "busy_title": "Operation in progress",
    "busy": "Stop the current operation first.",
    "missing_call": "Please enter your callsign.",
    "invalid_call": "The callsign must be a single line without the > character.",
    "missing_image": "Open an image first.",
    "missing_received": "There is no received image to save yet.",
    "no_missing_blocks": "There is no incomplete received image.",
    "no_request": "No repair request has been received yet.",
    "invalid_frequency": "Enter a frequency offset between −500 and +500 Hz.",
    "invalid_text": "Text must be encodable as CP932/Shift-JIS and contain at most 510 bytes, including the callsign prefix.",
    "error_title": "Operation failed",
    "open_image_error": "Could not open the image.",
    "save_image_error": "Could not save the received image.",
    "decode_error": "Could not decode the recording.",
    "encode_error": "Could not prepare or send the transmission.",
    "audio_error": "Could not use the selected audio device.",
    "directory_not_empty": "The reception output folder already contains files. Select a different folder.",
    "images_filter": "Images",
    "audio_filter": "Audio recordings",
    "all_filter": "All files",
    "output_directory": "Choose a folder for received images and the report",
    "save_wav_title": "Save transmission as WAV",
    "demo_image": "Local audio loopback · {good}/300 image blocks · no CRC errors",
    "demo_missing": "Local audio loopback · {good}/300 blocks · {count} deliberately omitted",
    "demo_text": "Local MSK audio loopback · {count} messages · CRC valid",
}

DE = {
    "subtitle": "Digitaler Bild- und Textfunk",
    "beta": "BETA",
    "language": "Sprache",
    "workspace": "Bilder & Nachrichten",
    "audio_tab": "Audio & PTT",
    "callsign": "Rufzeichen",
    "modulation": "Modulation",
    "fec": "Fehlerkorrektur",
    "scale": "Kompressionsskala",
    "format": "320 × 240 px  ·  1200 Baud",
    "transmit": "Bild senden",
    "receive": "Bild empfangen",
    "tx_empty": "Deine nächste Übertragung",
    "tx_hint": "Zum Starten ein Bild öffnen",
    "rx_empty": "Warten auf ein Bild",
    "rx_hint": "Aufnahme öffnen oder Audioempfang starten",
    "open_image": "Bild öffnen…",
    "save_wav": "WAV speichern…",
    "send_image": "Bild senden",
    "open_recording": "Aufnahme öffnen…",
    "save_image": "Bild speichern…",
    "repair_response": "Reparaturantwort als WAV…",
    "repair_request": "Fehlende Blöcke anfordern…",
    "experimental": "BSR · experimentell",
    "image_ready": "Bild bereit · 320 × 240 px",
    "no_image": "Kein Bild geladen",
    "no_received_image": "Noch kein Bild empfangen",
    "blocks": "{good}/300 Blöcke",
    "complete": "Vollständig",
    "missing": "{count} fehlen",
    "unknown": "Unbekannte Station",
    "messages": "Nachrichten",
    "message_hint": "Empfangene Texte erscheinen hier",
    "compose": "Deine Nachricht",
    "text_wav": "Text als WAV…",
    "send_text": "Text senden",
    "input": "Audioeingang",
    "output": "Audioausgang",
    "input_hint": "Die mit dem Empfänger verbundene Soundkarte auswählen.",
    "output_hint": "Den für die Übertragung verwendeten Ausgang auswählen.",
    "default_device": "Systemstandard",
    "refresh_devices": "Geräte aktualisieren",
    "frequency": "Empfangsversatz (Hz)",
    "frequency_hint": "Positive Werte korrigieren zu hohe Töne. Bereich: −500 bis +500 Hz.",
    "ptt": "Sendersteuerung",
    "ptt_port": "Serieller Port",
    "ptt_line": "PTT-Leitung",
    "ptt_hint": "Port leer lassen, um serielles PTT auszuschalten. WAV-Export aktiviert kein PTT.",
    "audio_hint": "Audiogeräte werden erst beim Starten des Empfangs oder Sendens geöffnet.",
    "start_rx": "Empfang starten",
    "stop": "Stopp",
    "idle": "BEREIT",
    "working": "VERARBEITUNG",
    "rx": "EMPFANG",
    "tx": "SENDEN",
    "stopping": "ANHALTEN",
    "ready": "Bereit",
    "processing": "Verarbeitung läuft…",
    "stopped": "Vorgang angehalten",
    "starting_rx": "Audioeingang wird geöffnet…",
    "live_receiving": "Empfang am ausgewählten Audioeingang läuft",
    "audio_gap": "Audioaussetzer · Synchronisation wird neu gesucht",
    "live_stopped": "Empfang angehalten",
    "transmitting": "Senden · {seconds:.1f} Sekunden",
    "transmitted": "Übertragung beendet",
    "wav_saved": "WAV gespeichert · {seconds:.1f} Sekunden · {path}",
    "decoded": "{count} Pakete dekodiert · gespeichert in {path}",
    "requested": "Reparaturanfrage empfangen · {count} Blöcke",
    "devices_loaded": "{inputs} Eingänge und {outputs} Ausgänge gefunden",
    "image_opened": "Bild geladen · {name}",
    "image_saved": "Empfangsbild gespeichert · {path}",
    "preference_error": "Sprache geändert, die Auswahl konnte aber nicht gespeichert werden",
    "compatibility": "Kompatibilitätsprüfung läuft",
    "about_title": "Über Open KG-STV",
    "about": "Open KG-STV {version} · MIT-Lizenz\n\nEigenständige Python-Implementierung von KG-STV.\n\nOriginalaufnahmen werden erfolgreich dekodiert. Der Empfang unserer Signale im Originalprogramm, BSR-Gegentests und Tests an Funkhardware stehen noch aus.",
    "busy_title": "Vorgang läuft",
    "busy": "Zuerst den laufenden Vorgang stoppen.",
    "missing_call": "Bitte dein Rufzeichen eintragen.",
    "invalid_call": "Das Rufzeichen muss einzeilig sein und darf kein > enthalten.",
    "missing_image": "Bitte zuerst ein Bild öffnen.",
    "missing_received": "Noch kein Empfangsbild zum Speichern vorhanden.",
    "no_missing_blocks": "Es gibt kein unvollständiges Empfangsbild.",
    "no_request": "Noch keine Reparaturanfrage empfangen.",
    "invalid_frequency": "Einen Frequenzversatz zwischen −500 und +500 Hz eingeben.",
    "invalid_text": "Text muss in CP932/Shift-JIS darstellbar sein und darf einschließlich Rufzeichenpräfix höchstens 510 Bytes enthalten.",
    "error_title": "Vorgang fehlgeschlagen",
    "open_image_error": "Das Bild konnte nicht geöffnet werden.",
    "save_image_error": "Das Empfangsbild konnte nicht gespeichert werden.",
    "decode_error": "Die Aufnahme konnte nicht dekodiert werden.",
    "encode_error": "Die Übertragung konnte nicht vorbereitet oder gesendet werden.",
    "audio_error": "Das ausgewählte Audiogerät konnte nicht verwendet werden.",
    "directory_not_empty": "Der Ausgabeordner enthält bereits Dateien. Bitte einen anderen Ordner wählen.",
    "images_filter": "Bilder",
    "audio_filter": "Audioaufnahmen",
    "all_filter": "Alle Dateien",
    "output_directory": "Ordner für Empfangsbilder und Bericht auswählen",
    "save_wav_title": "Übertragung als WAV speichern",
    "demo_image": "Lokaler Audio-Sende-/Empfangstest · {good}/300 Bildblöcke · keine CRC-Fehler",
    "demo_missing": "Lokaler Audiotest · {good}/300 Blöcke · {count} absichtlich ausgelassen",
    "demo_text": "Lokaler MSK-Audiotest · {count} Nachrichten · CRC gültig",
}

TRANSLATIONS = {"en": EN, "de": DE}


def translate(language, key, **values):
    return TRANSLATIONS[language][key].format(**values)


def settings_file():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()/"AppData"/"Roaming"))
    elif sys.platform == "darwin":
        base = Path.home()/"Library"/"Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home()/".config"))
    return base/"OpenKGSTV"/"settings.json"


def load_language(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        language = data.get("language") if isinstance(data, dict) else None
        return language if language in TRANSLATIONS else "en"
    except (OSError, ValueError, TypeError):
        return "en"


def save_language(path, language):
    if language not in TRANSLATIONS:
        raise ValueError("Unsupported interface language")
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["language"] = language
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="language-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, indent=2)
            file.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
