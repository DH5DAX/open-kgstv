"""QSO domain and interchangeable logbook destinations; no UI or radio imports.

The initial backend appends ADIF 3.1.8 ADI records. Future online adapters can
implement Logbook.save without changing the QSO dialog or the radio code.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
import threading
from typing import Protocol
import uuid

from . import __version__


class LogbookError(ValueError):
    def __init__(self, key, detail=""):
        self.key, self.detail = key, detail
        super().__init__(key+(": "+detail if detail else ""))


def frequency_hz(mhz):
    try:
        value = Decimal(str(mhz).replace(",", "."))*1_000_000
        if not value.is_finite() or not 0 < value <= 1_000_000_000_000:
            raise InvalidOperation
        return int(value.to_integral_value())
    except (InvalidOperation, ValueError):
        raise LogbookError("qso_frequency_error") from None


def band_for(hz):
    # ADIF band enumeration boundaries in MHz, independent of licence allocations.
    for name, low, high in (("2190m", .1357, .1378), ("630m", .472, .479),
        ("160m", 1.8, 2), ("80m", 3.5, 4), ("60m", 5.06, 5.45), ("40m", 7, 7.3),
        ("30m", 10.1, 10.15), ("20m", 14, 14.35), ("17m", 18.068, 18.168),
        ("15m", 21, 21.45), ("12m", 24.89, 24.99), ("10m", 28, 29.7),
        ("6m", 50, 54), ("4m", 70, 71), ("2m", 144, 148), ("1.25m", 222, 225),
        ("70cm", 420, 450), ("33cm", 902, 928), ("23cm", 1240, 1300),
        ("13cm", 2300, 2450), ("9cm", 3300, 3500), ("6cm", 5650, 5925),
        ("3cm", 10000, 10500), ("1.25cm", 24000, 24250)):
        if low*1_000_000 <= hz <= high*1_000_000:
            return name
    return ""


@dataclass(frozen=True)
class Qso:
    call: str
    station_call: str
    time_on: datetime
    frequency: int
    time_off: datetime | None = None
    frequency_rx: int | None = None
    rst_sent: str = ""
    rst_received: str = ""
    name: str = ""
    grid: str = ""
    comment: str = ""
    satellite: str = ""
    id: str = field(default_factory=lambda:str(uuid.uuid4()))

    def validate(self):
        for call in (self.call, self.station_call):
            if not re.fullmatch(r"[A-Z0-9]+(?:/[A-Z0-9]+)*", call) or len(call) > 32:
                raise LogbookError("qso_call_error")
        for value in (self.time_on, self.time_off):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None or value.year < 1930):
                raise LogbookError("qso_time_error")
        if self.time_off and self.time_off < self.time_on:
            raise LogbookError("qso_time_error")
        for value in (self.frequency, self.frequency_rx):
            if value is not None and (not isinstance(value, int) or not 0 < value <= 1_000_000_000_000):
                raise LogbookError("qso_frequency_error")
        if self.grid and not re.fullmatch(r"[A-R]{2}[0-9]{2}(?:[A-X]{2}(?:[0-9]{2})?)?", self.grid.upper()):
            raise LogbookError("qso_grid_error")
        if not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", self.id):
            raise LogbookError("qso_invalid")
        if any(len(v) > 4000 for v in (self.name, self.comment, self.rst_sent, self.rst_received, self.satellite)):
            raise LogbookError("qso_invalid")


@dataclass(frozen=True)
class Receipt:
    qso_id: str
    destination: str
    already_saved: bool = False


class Logbook(Protocol):
    def save(self, qso: Qso) -> Receipt: ...


def _field(name, value):
    value = str(value)
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise LogbookError("qso_ascii_error", name)
    return f"<{name}:{len(value)}>{value}"


def adif_record(qso):
    qso.validate()
    start = qso.time_on.astimezone(timezone.utc)
    values = {
        "CALL":qso.call, "STATION_CALLSIGN":qso.station_call,
        "QSO_DATE":start.strftime("%Y%m%d"), "TIME_ON":start.strftime("%H%M%S"),
        "FREQ":f"{Decimal(qso.frequency)/1_000_000:.6f}", "BAND":band_for(qso.frequency),
        "MODE":"SSTV", "APP_OPENKGSTV_MODE":"KG-STV", "APP_OPENKGSTV_QSO_ID":qso.id,
        "RST_SENT":qso.rst_sent, "RST_RCVD":qso.rst_received,
        "NAME":qso.name, "GRIDSQUARE":qso.grid.upper(), "COMMENT":qso.comment,
    }
    if qso.time_off:
        end = qso.time_off.astimezone(timezone.utc)
        values.update(QSO_DATE_OFF=end.strftime("%Y%m%d"), TIME_OFF=end.strftime("%H%M%S"))
    if qso.frequency_rx:
        values.update(FREQ_RX=f"{Decimal(qso.frequency_rx)/1_000_000:.6f}", BAND_RX=band_for(qso.frequency_rx))
    if qso.satellite:
        values.update(PROP_MODE="SAT", SAT_NAME=qso.satellite)
    # KG-STV has no standardized ADIF submode. Keep SSTV interoperable and
    # preserve the exact protocol in an application field, not a made-up SUBMODE.
    return (" ".join(_field(key, value) for key, value in values.items() if value)+" <EOR>\r\n").encode("ascii")


def _existing_ids(data):
    """Length-aware scan: a literal '<EOR>' in a comment is not a record end."""
    if not data:
        return set()
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise LogbookError("qso_file_error") from None
    index, last, ids = 0, None, set()
    while (index := text.find("<", index)) >= 0:
        token = re.match(r"<([A-Za-z][A-Za-z0-9_]*)(?::([0-9]+)(?::[A-Za-z])?)?>", text[index:])
        if not token:
            raise LogbookError("qso_file_error")
        key, size = token.group(1).upper(), token.group(2)
        index += token.end()
        if size is None:
            if key not in ("EOH", "EOR"):
                raise LogbookError("qso_file_error")
        else:
            end = index+int(size)
            if end > len(text):
                raise LogbookError("qso_file_error")
            if key == "APP_OPENKGSTV_QSO_ID":
                ids.add(text[index:end])
            index = end
        last = key
    if last not in ("EOH", "EOR") or not text.rstrip().upper().endswith("<"+last+">"):
        raise LogbookError("qso_file_error")
    return ids


_WRITE_LOCK = threading.Lock()


@contextmanager
def _locked_file(path):
    with _WRITE_LOCK, path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield stream
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class AdifLogbook:
    def __init__(self, path):
        self.path = Path(path).expanduser()

    def save(self, qso):
        record = adif_record(qso)  # Validate before touching the destination.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _locked_file(self.path) as stream:
            previous = stream.read()
            if qso.id in _existing_ids(previous):
                return Receipt(qso.id, str(self.path), already_saved=True)
            header = b"" if previous else ("Open KG-STV logbook\r\n"+_field("ADIF_VER", "3.1.8")+" "+
                _field("PROGRAMID", "OPENKGSTV")+" "+_field("PROGRAMVERSION", __version__)+" <EOH>\r\n").encode("ascii")
            try:
                stream.seek(0, 2)
                stream.write(header+(b"\r\n" if previous and not previous.endswith(b"\n") else b"")+record)
                stream.flush()
                os.fsync(stream.fileno())
            except OSError:
                stream.seek(len(previous))
                stream.truncate()
                stream.flush()
                raise
        return Receipt(qso.id, str(self.path))
