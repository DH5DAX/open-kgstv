# Local QSO logging

Click **Log QSO…** in the operating window. Review the proposed callsigns,
start time (UTC) and read-back frequency. Enter reports, name, locator and a
comment if desired. End date/time and a separate receive frequency are optional.
**Save QSO** appends one record to `logbook.adi` beside the settings file, or to
the `.adi`/`.adif` file chosen in the dialog. The chosen destination is remembered.
Logging opens no radio/audio connection and does not transmit or submit online.

The start timestamp is the time the dialog opens, not an automatically detected
QSO start. A recent RX callsign is only a suggestion. Offline frequency is blank;
selecting a calling-frequency preset alone does not prove the operating frequency.
Use actual RF frequencies in MHz. For QO-100, **Satellite QSO** suggests
2400.125 MHz TX, 10489.625 MHz RX and QO-100; review these for your contact. A
successfully applied QO-100 preset matching the current CAT readback preselects
these satellite fields. Manual transverter setups still require manual review.

The writer follows [ADIF 3.1.8](https://www.adif.org.uk/318/ADIF_318.htm).
It emits `MODE=SSTV` and `APP_OPENKGSTV_MODE=KG-STV`; KG-STV is not a standardized
ADIF submode. UTC dates/times, TX/RX frequencies and inferred bands are separate
fields. Satellite records include `PROP_MODE=SAT` and `SAT_NAME`. Reports are
optional and never invented. ADI text is ASCII: use Mueller rather than Müller.
Unsupported characters cause an error before the destination is changed.

## Backend boundary

`kgstv/logbook.py` defines an immutable `Qso`, a `Receipt`, and the small `Logbook`
protocol: `save(qso) -> Receipt`. `AdifLogbook` implements it without importing
Tk, Hamlib or audio. `logbook_gui.py` receives a backend factory. Future online
adapters can implement the same contract; authorization, retry queues and online
credentials belong in those adapters, not in radio or image code.

Each dialog keeps a stable QSO ID across retries. The ADIF backend records it in
`APP_OPENKGSTV_QSO_ID` and returns the existing receipt if retried. Separate new
dialogs represent separate QSOs; there is no broad callsign/time duplicate filter.
The backend serializes app writers and uses an OS advisory file lock, checks
length-delimited existing records, appends and flushes to disk. An ordinary write
failure attempts to restore the original length. An incomplete existing file is
rejected without truncating it. External programs must respect file locking;
power loss or forced termination can still leave a partial final record requiring
recovery from backup. Existing unrelated or non-ASCII files are not rewritten.

This first version is an append-only logger, not a logbook browser or editor.
Online logbooks, imports, QSL status and automated uploads are not implemented.
