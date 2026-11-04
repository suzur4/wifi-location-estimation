"""Download the public CC BY 4.0 UJIIndoorLoc dataset; no school access.

Run: python scripts/download_uji.py
The URL is fixed to the verified UCI dataset archive. Only the two expected
CSV files are extracted, so archive paths cannot write outside the directory.
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile


URL = "https://archive.ics.uci.edu/static/public/310/ujiindoorloc.zip"
DEST = Path(__file__).resolve().parents[1] / "data" / "ujindoorloc"


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    request = Request(URL, headers={"User-Agent": "SubaruWiFiResearch/0.1"})
    with urlopen(request, timeout=60) as response:
        archive = response.read(10_000_001)
    if len(archive) > 10_000_000:
        raise ValueError("Unexpectedly large archive; refusing to extract")
    extracted = []
    with ZipFile(io.BytesIO(archive)) as zipped:
        for basename in ("trainingData.csv", "validationData.csv"):
            matches = [item for item in zipped.infolist() if Path(item.filename).name == basename]
            if len(matches) != 1 or matches[0].file_size > 60_000_000:
                raise ValueError(f"Unexpected archive member: {basename}")
            data = zipped.read(matches[0])
            (DEST / basename).write_bytes(data)
            extracted.append({"file": basename, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    metadata = {"url": URL, "dataset_doi": "10.24432/C5MS59", "license": "CC BY 4.0",
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "archive_sha256": hashlib.sha256(archive).hexdigest(), "files": extracted}
    (DEST / "download.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
