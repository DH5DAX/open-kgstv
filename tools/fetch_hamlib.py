"""Download the official Windows x64 Hamlib archive after an explicit invocation.

The original archive and licenses stay in outputs/hamlib and are not committed
or included in the Open KG-STV package. Nothing is installed system-wide.
"""
import hashlib
from pathlib import Path
import sys
import urllib.request
import zipfile

VERSION = "4.7.2"
FILENAME = f"hamlib-w64-{VERSION}.zip"
URL = f"https://github.com/Hamlib/Hamlib/releases/download/{VERSION}/{FILENAME}"
SHA256 = "8553bc6c5c6032e8debf99c017e98f58fed7e07e7c25d04815dc3e8bbe3304c7"


def main():
    if sys.platform != "win32":
        raise SystemExit("Install Hamlib/rigctld with your operating system's package manager.")
    destination = Path(__file__).resolve().parents[1]/"outputs"/"hamlib"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination/FILENAME
    if not archive.exists():
        print(f"Downloading official Hamlib {VERSION}…")
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read(16*1024*1024+1)
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise SystemExit("Hamlib checksum mismatch; nothing was extracted.")
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit("Cached Hamlib archive checksum mismatch; nothing was extracted.")
    with zipfile.ZipFile(archive) as package:
        for name in package.namelist():
            if not (destination/name).resolve().is_relative_to(destination.resolve()):
                raise SystemExit("Unsafe archive member; nothing was extracted.")
        package.extractall(destination)
    executable = destination/f"hamlib-w64-{VERSION}"/"bin"/"rigctld.exe"
    if not executable.is_file():
        raise SystemExit("The archive did not contain rigctld.exe.")
    print(f"Verified Hamlib {VERSION}: {executable}")
    print("Open KG-STV will find it automatically. No radio was opened.")


if __name__ == "__main__":
    main()
