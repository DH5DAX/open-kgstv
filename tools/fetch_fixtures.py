"""Explicitly download pinned public test data; not redistributed in the wheel."""
from pathlib import Path
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    fixtures = json.loads((ROOT/"tests"/"fixtures.json").read_text(encoding="utf-8"))
    destination = ROOT/"research"/"reference"
    destination.mkdir(parents=True, exist_ok=True)
    for entry in fixtures:
        name = entry["filename"]
        if Path(name).name != name:
            raise ValueError("Fixture filename must not contain a directory")
        path = destination/name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]:
            print(f"Verified {name}"); continue
        request = urllib.request.Request(entry["url"], headers={"User-Agent": "Open-KGSTV-fixture-check/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(10*1024*1024+1)
        if len(data) > 10*1024*1024 or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"Unexpected file content for {name}; no file replaced")
        temporary = path.with_suffix(path.suffix+".download")
        temporary.write_bytes(data)
        temporary.replace(path)
        print(f"Downloaded and verified {name}")


if __name__ == "__main__": main()
