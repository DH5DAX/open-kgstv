from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from kgstv.logbook import Qso, AdifLogbook, LogbookError, adif_record, frequency_hz, _existing_ids
from kgstv.activity import ACTIVITIES


class LogbookTests(unittest.TestCase):
    def qso(self, **changes):
        record = Qso("DL1ABC", "DH5DAX", datetime(2026,11,9,23,59,55,tzinfo=timezone.utc),14233000)
        return replace(record, **changes)

    def test_utc_midnight_satellite_and_adif_mode_mapping(self):
        qso = self.qso(time_off=datetime(2026,11,10,0,2,tzinfo=timezone.utc), frequency=2400125000,
                      frequency_rx=10489625000, satellite="QO-100", grid="jo31aa", comment="literal <EOR> text")
        data = adif_record(qso).decode()
        for value in ("<QSO_DATE:8>20261109", "<QSO_DATE_OFF:8>20261110", "<TIME_OFF:6>000200",
                      "<BAND:4>13cm", "<BAND_RX:3>3cm", "<PROP_MODE:3>SAT", "<FREQ:11>2400.125000",
                      "<MODE:4>SSTV", "<APP_OPENKGSTV_MODE:6>KG-STV", "<GRIDSQUARE:6>JO31AA"):
            self.assertIn(value, data)
        self.assertNotIn("SUBMODE", data)
        offset = timezone(timedelta(hours=2))
        self.assertIn("<TIME_ON:6>215955", adif_record(self.qso(time_on=qso.time_on.replace(tzinfo=offset))).decode())

    def test_append_and_retry_are_idempotent_preserving_existing_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"log.adi"
            store = AdifLogbook(path)
            qso = self.qso(comment="<EOR> is allowed inside a length-delimited comment")
            self.assertFalse(store.save(qso).already_saved)
            first = path.read_bytes()
            self.assertTrue(store.save(qso).already_saved)
            self.assertEqual(path.read_bytes(), first)
            second = self.qso(call="TEST2")
            store.save(second)
            self.assertTrue(path.read_bytes().startswith(first))
            self.assertEqual(_existing_ids(path.read_bytes()), {qso.id, second.id})
            self.assertEqual(path.read_bytes().count(b"<EOH>"), 1)

    def test_invalid_data_cannot_create_file_or_damage_existing_log(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"log.adi"
            store = AdifLogbook(path)
            for change in (dict(call=""), dict(call="A\nB"), dict(grid="ZZ99"), dict(frequency=-1),
                           dict(name="Müller"), dict(time_on=datetime(2026,11,9)),
                           dict(time_off=datetime(2026,11,8,tzinfo=timezone.utc))):
                with self.subTest(change=change), self.assertRaises(LogbookError):
                    store.save(self.qso(**change))
                self.assertFalse(path.exists())
            for data in (b"unrelated notes", b"<CALL:20>TRUNCATED <EOR>", b"<CALL:4>TEST"):
                path.write_bytes(data)
                with self.assertRaises(LogbookError):
                    store.save(self.qso())
                self.assertEqual(path.read_bytes(), data)

    def test_disk_failure_rolls_back_and_retry_appends_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"log.adi"
            store = AdifLogbook(path)
            store.save(self.qso())
            before = path.read_bytes()
            qso = self.qso(call="TEST2")
            with patch("kgstv.logbook.os.fsync", side_effect=OSError("disk full")), self.assertRaises(OSError):
                store.save(qso)
            self.assertEqual(path.read_bytes(), before)
            store.save(qso)
            self.assertEqual(len(_existing_ids(path.read_bytes())), 2)

    def test_concurrent_local_writers_do_not_interleave_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"log.adi"
            records = [self.qso(call=f"TEST{n}") for n in range(12)]
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda qso:AdifLogbook(path).save(qso), records))
            self.assertEqual(_existing_ids(path.read_bytes()), {q.id for q in records})

    def test_presets_and_frequency_parser_do_not_confuse_rf_with_cat_if(self):
        self.assertEqual([p.hz for p in ACTIVITIES[:4]], [14233000,3733000,7173000,21340000])
        self.assertEqual(frequency_hz("14,233"), 14233000)
        for invalid in ("nan", "inf", "0", "-14", "nonsense"):
            with self.assertRaises(LogbookError):
                frequency_hz(invalid)
        satellite = ACTIVITIES[-1]
        with self.assertRaises(ValueError):
            satellite.dial_hz()
        self.assertEqual(satellite.dial_hz("28,125"), 28125000)
        self.assertEqual(satellite.hz, 10489625000)
