#!/usr/bin/env python3
"""Validate Alwan media distribution on disk before any GitHub Actions push."""
import hashlib
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "device-media"
manifest_data = (root / "device_media_manifest.json").read_bytes()
distribution = json.loads((root / "distribution.json").read_bytes())
manifest = json.loads(manifest_data)
digest = lambda b: hashlib.sha256(b).hexdigest()

assert len(manifest_data) == distribution["mediaManifest"]["bytes"]
assert digest(manifest_data) == distribution["mediaManifest"]["sha256"]
entries = manifest["entries"]
chunks = {chunk["chunkId"]: chunk for chunk in distribution["chunks"]}
assert len(chunks) == len(distribution["chunks"])
assert {entry["chunkId"] for entry in entries} == set(chunks)
assert len({(e["deviceId"], e["revision"], e["view"]) for e in entries}) == len(entries)
for entry in entries:
    descriptor = chunks[entry["chunkId"]]
    archive_file = root / "chunks" / (entry["chunkId"] + ".zip")
    archive = archive_file.read_bytes()
    assert len(archive) == descriptor["compressedBytes"]
    assert digest(archive) == descriptor["sha256"]
    with zipfile.ZipFile(archive_file) as z:
        assert z.testzip() is None
        assert z.namelist() == [entry["filename"]]
        content = z.read(entry["filename"])
        assert len(content) == entry["bytes"] == descriptor["uncompressedBytes"]
        assert digest(content) == entry["sha256"]
print(f"PASS: {len(entries)} media entries, checksums, zip files")
