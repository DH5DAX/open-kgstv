"""Hamlib rigctld integration. No devices, processes or sockets open on import.

Protocol: https://hamlib.sourceforge.net/html/rigctld.1.html
The daemon is an external dependency, not bundled with this MIT implementation.
"""
from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from .runtime import external_environment, external_libraries


class HamlibError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class PTTReleaseError(HamlibError):
    """PTT off was not acknowledged; the radio may still be transmitting."""


@dataclass(frozen=True)
class RadioConfig:
    connection: str = "local"
    executable: str = "rigctld"
    model: int = 3078
    device: str = ""
    baud: int = 115200
    civ: str = "0x98"
    host: str = "127.0.0.1"
    port: int = 4532

    def validate(self):
        if self.connection not in ("local", "network"):
            raise ValueError("Connection must be local or network")
        if self.connection == "network":
            if not self.host.strip() or any(c.isspace() for c in self.host) or not 1 <= self.port <= 65535:
                raise ValueError("Enter a server address and a TCP port from 1 to 65535")
        else:
            if self.model <= 0 or self.model == 2:
                raise ValueError("Choose a radio model; use network connection for NET rigctl")
            if self.model not in (1, 6) and not self.device.strip():
                raise ValueError("Select the radio's CAT serial port or device address")
            if self.baud < 0 or self.baud > 4_000_000:
                raise ValueError("Invalid serial baud rate")
            if self.civ and not 1 <= int(self.civ, 16) <= 255:
                raise ValueError("CI-V address must be hexadecimal, from 01 to FF")


@dataclass(frozen=True)
class RadioState:
    frequency: float
    mode: str | None
    passband: int | None
    ptt: int | None


def _hidden_process():
    return {"creationflags":subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}


def find_rigctld():
    found = shutil.which("rigctld")
    if found:
        return found
    if getattr(sys, 'frozen', False):
        name = 'rigctld.exe' if sys.platform == 'win32' else 'rigctld'
        base = Path(sys.executable).resolve().parent
        for local in (base/name, base/'hamlib'/'bin'/name):
            if local.is_file():
                return str(local)
    # Optional checkout-local installation made by tools/fetch_hamlib.py.
    local = Path(__file__).resolve().parents[1]/"outputs"/"hamlib"/"hamlib-w64-4.7.2"/"bin"/"rigctld.exe"
    return str(local) if local.is_file() else "rigctld"


def executable_path(value):
    found = shutil.which(value)
    path = Path(found or value).expanduser()
    if not path.is_file():
        raise HamlibError("rigctld was not found. Install Hamlib and select its rigctld executable.")
    return str(path.resolve())


def list_models(executable):
    with external_libraries():
        result = subprocess.run([executable_path(executable), "--list"], capture_output=True,
                                text=True, errors="replace", timeout=15,
                                env=external_environment(), **_hidden_process())
    if result.returncode:
        raise HamlibError(result.stderr.strip() or f"Could not list Hamlib models (exit {result.returncode})")
    models = []
    for line in result.stdout.splitlines():
        columns = re.split(r"\s{2,}", line.strip())
        if len(columns) >= 3 and columns[0].isdigit():
            models.append((int(columns[0]), f"{columns[0]} · {columns[1]} {columns[2]}"))
    if not models:
        raise HamlibError("Hamlib returned no radio models")
    return models


class RigctldClient:
    """Serialized, bounded Extended Response Protocol transactions.

    Transport failures invalidate the socket. Normal operations never reconnect
    or retry writes: a lost acknowledgement does not mean a command was ignored.
    """
    def __init__(self, host="127.0.0.1", port=4532, *, timeout=2.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.socket = None
        self.buffer = b""
        self.vfo_mode = False
        self.lock = threading.RLock()

    def connect(self):
        with self.lock:
            self.close()
            try:
                self.socket = socket.create_connection((self.host, self.port), self.timeout)
                self.socket.sendall(b"\\chk_vfo\n")
                answer = self._line(time.monotonic()+self.timeout)
                # Older releases include CHKVFO; current Hamlib returns 0/1.
                if answer not in ("CHKVFO 0", "CHKVFO 1", "0", "1"):
                    raise HamlibError("Invalid rigctld VFO handshake: "+answer)
                self.vfo_mode = answer in ("CHKVFO 1", "1")
            except (OSError, HamlibError) as exc:
                self.close()
                raise HamlibError(f"Cannot connect to rigctld at {self.host}:{self.port}: {exc}") from exc

    def close(self):
        with self.lock:
            if self.socket is not None:
                self.socket.close()
            self.socket = None
            self.buffer = b""

    def _line(self, deadline):
        while b"\n" not in self.buffer:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError("rigctld response timed out")
            self.socket.settimeout(remaining)
            chunk = self.socket.recv(4096)
            if not chunk:
                raise ConnectionError("rigctld closed the connection")
            self.buffer += chunk
            if len(self.buffer) > 65536:
                raise HamlibError("rigctld response exceeds the size limit")
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode("utf-8", errors="replace").rstrip("\r")

    def command(self, name, *args):
        if name not in ("get_freq", "set_freq", "get_mode", "set_mode", "get_ptt", "set_ptt"):
            raise ValueError("Unsupported radio command")
        tokens = (["currVFO"] if self.vfo_mode else [])+[str(arg) for arg in args]
        if any(not token or any(c.isspace() for c in token) for token in tokens):
            raise ValueError("Invalid command argument")
        request = "+\\"+name+(" "+" ".join(tokens) if tokens else "")+"\n"
        with self.lock:
            if self.socket is None:
                raise HamlibError("Hamlib is disconnected")
            try:
                self.socket.settimeout(self.timeout)
                self.socket.sendall(request.encode("ascii"))
                deadline = time.monotonic()+self.timeout
                fields = {}
                header = self._line(deadline)
                if not header.startswith(name+":"):
                    raise HamlibError("Unexpected rigctld response: "+header)
                for _ in range(128):
                    line = self._line(deadline)
                    if line.startswith("RPRT "):
                        try:
                            code = int(line[5:])
                        except ValueError as exc:
                            raise HamlibError("Invalid rigctld result code") from exc
                        if code:
                            raise HamlibError(f"Hamlib {name}: RPRT {code}", code)
                        return fields
                    key, sep, value = line.partition(": ")
                    if not sep:
                        raise HamlibError("Malformed rigctld response: "+line)
                    fields[key] = value
                raise HamlibError("Too many rigctld response lines")
            except (OSError, HamlibError) as exc:
                if not isinstance(exc, HamlibError) or exc.code is None:
                    self.close()
                if isinstance(exc, HamlibError):
                    raise
                raise HamlibError(f"Hamlib connection failed: {exc}") from exc

    def snapshot(self):
        try:
            frequency = float(self.command("get_freq")["Frequency"])
            if not math.isfinite(frequency) or frequency < 0:
                raise ValueError("Invalid frequency")
            mode = width = ptt = None
            try:
                result = self.command("get_mode")
                mode, width = result["Mode"], int(result["Passband"])
            except HamlibError as exc:
                if exc.code not in (-4, -11):
                    raise
            try:
                ptt = self.get_ptt()
            except HamlibError as exc:
                if exc.code not in (-4, -11):
                    raise
            return RadioState(frequency, mode, width, ptt)
        except (KeyError, ValueError) as exc:
            self.close()
            raise HamlibError("Invalid values in Hamlib response") from exc

    def get_ptt(self):
        try:
            value = int(self.command("get_ptt")["PTT"])
            if value not in (0, 1, 2, 3):
                raise ValueError
            return value
        except (KeyError, ValueError) as exc:
            self.close()
            raise HamlibError("Invalid PTT value from Hamlib") from exc

    def set_frequency(self, frequency):
        frequency = float(frequency)
        if not math.isfinite(frequency) or not 0 < frequency <= 1e12:
            raise ValueError("Invalid frequency in Hz")
        self.command("set_freq", f"{frequency:.0f}")

    def set_mode(self, mode, passband=0):
        if not re.fullmatch(r"[A-Z][A-Z0-9]{0,15}", mode) or not 0 <= int(passband) <= 1_000_000:
            raise ValueError("Invalid mode or passband")
        self.command("set_mode", mode, int(passband))

    def set_ptt(self, state):
        if state not in (0, 1, 2, 3):
            raise ValueError("Invalid PTT state")
        self.command("set_ptt", state)


class LocalDaemon:
    """Owns exactly one rigctld process, bound only to localhost."""
    def __init__(self, config):
        config.validate()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        args = [executable_path(config.executable), "-m", str(config.model),
                "-T", "127.0.0.1", "-t", str(self.port), "-P", "RIG"]
        if config.device:
            args += ["-r", config.device]
        if config.baud:
            args += ["-s", str(config.baud)]
        if config.civ:
            args += ["-c", str(int(config.civ, 16))]
        self.log = tempfile.TemporaryFile()
        try:
            with external_libraries():
                self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=self.log,
                                                stderr=self.log, env=external_environment(), **_hidden_process())
        except Exception:
            self.log.close()
            raise

    def error_tail(self):
        self.log.seek(0, 2)
        self.log.seek(max(0, self.log.tell()-3000))
        return self.log.read().decode("utf-8", errors="replace").strip()

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        finally:
            self.log.close()


class RadioSession:
    """One explicit radio connection with background status and PTT ownership."""
    def __init__(self, callback, *, timeout=2.0, poll_interval=1.0):
        self.callback = callback
        self.timeout, self.poll_interval = timeout, poll_interval
        self.client = self.daemon = self.thread = None
        self.connected = False
        self.ptt_may_be_on = False
        self._ptt_lock = threading.RLock()
        self.stopped = threading.Event()

    def connect(self, config):
        config.validate()
        try:
            if config.connection == "local":
                self.daemon = LocalDaemon(config)
                host, port = "127.0.0.1", self.daemon.port
            else:
                host, port = config.host, config.port
            self.client = RigctldClient(host, port, timeout=self.timeout)
            deadline = time.monotonic()+10
            while True:
                if self.daemon and self.daemon.process.poll() is not None:
                    raise HamlibError("rigctld exited: "+self.daemon.error_tail())
                try:
                    self.client.connect()
                    break
                except HamlibError:
                    if not self.daemon or time.monotonic() >= deadline:
                        raise
                    time.sleep(.1)
            if self.daemon and self.daemon.process.poll() is not None:
                raise HamlibError("rigctld exited: "+self.daemon.error_tail())
            state = self.client.snapshot()
            self.connected = True
            self.callback("radio_state", state)
            self.thread = threading.Thread(target=self._monitor, daemon=True)
            self.thread.start()
        except Exception:
            self.close()
            raise

    def _monitor(self):
        while not self.stopped.wait(self.poll_interval):
            try:
                state = self.client.snapshot()
                self.callback("radio_state", state)
            except HamlibError as exc:
                self.connected = False
                self.callback("radio_lost", str(exc))
                return

    def set_frequency(self, frequency):
        with self._ptt_lock:
            self._check_ready()
            self.client.set_frequency(frequency)
            self.callback("radio_state", self.client.snapshot())

    def set_mode(self, mode, passband=0):
        with self._ptt_lock:
            self._check_ready()
            self.client.set_mode(mode, passband)
            self.callback("radio_state", self.client.snapshot())

    def tune(self, frequency, mode="PKTUSB"):
        """Explicit preset action. Never keys PTT or configures split/transverters."""
        with self._ptt_lock:
            self._check_ready()
            try:
                if self.client.get_ptt():
                    raise HamlibError("The radio is already transmitting")
            except HamlibError as exc:
                if exc.code not in (-4, -11):
                    raise
            self.client.set_frequency(frequency)
            self.client.set_mode(mode, 0)
            self.callback("radio_state", self.client.snapshot())

    def _check_ready(self):
        if not self.connected:
            raise HamlibError("Connect to the radio first")
        if self.ptt_may_be_on:
            raise HamlibError("Radio control is locked during transmission")

    def ptt(self, active):
        with self._ptt_lock:
            if active:
                self._check_ready()
                try:
                    if self.client.get_ptt():
                        raise HamlibError("The radio is already transmitting")
                except HamlibError as exc:
                    if exc.code not in (-4, -11):
                        raise
                # Set before writing: a timed-out acknowledgement is ambiguous.
                self.ptt_may_be_on = True
                self.client.set_ptt(1)
            elif self.ptt_may_be_on:
                self.release_ptt()

    def release_ptt(self):
        """Explicit RX command; one fresh connection is allowed for OFF only."""
        with self._ptt_lock:
            if self.client is None:
                raise PTTReleaseError("No Hamlib endpoint is available to release PTT")
            try:
                self.client.set_ptt(0)
            except HamlibError:
                recovery = RigctldClient(self.client.host, self.client.port, timeout=self.timeout)
                try:
                    recovery.connect()
                    recovery.set_ptt(0)
                except HamlibError as exc:
                    self.ptt_may_be_on = True
                    raise PTTReleaseError("PTT OFF was not acknowledged. Check the radio: "+str(exc)) from exc
                finally:
                    recovery.close()
            self.ptt_may_be_on = False

    def close(self):
        self.stopped.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=self.timeout*3+1)
        self.connected = False
        if self.ptt_may_be_on:
            # Keep our endpoint available for an explicit RX retry if OFF fails.
            self.release_ptt()
        if self.client:
            self.client.close()
        if self.daemon:
            self.daemon.close()
            self.daemon = None
