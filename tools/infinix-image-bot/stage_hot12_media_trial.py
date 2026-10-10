#!/usr/bin/env python3
"""One-device reversible HOT 12 media trial, preserving every published entry.

Only reuses the immutable previously published X6817 source photo. Creates a
distinct v2 revision BEFORE v1 in the media manifest, so the existing Alwan
v1.0.9 first-frontBack selector uses the new image without an APK update.
Old image and chunk stay untouched and referenced. No camera/phone access.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2] / "device-media"
CODE = "X6817"
DEVICE = "dev_dvflnk7xy26zkvzyrsssm74qmu"
SOURCE_CHUNK = "infinix-user-reviewed-batch06-cb885872ede7"
SOURCE_NAME = "infinix-x6817-frontback.png"
SOURCE_SHA = "65b01207790d53ad15122fe753caf73b091b3af37a3cc20469a69b9bc3857bf7"
REVISION = "infinix-approved-x6817-frontback-v2-trial"
FILENAME = "infinix-x6817-frontback-v2-trial.png"
BASE_URL = "https://raw.githubusercontent.com/alifared89-dot/alwan-releases/main/device-media/chunks/"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def packed(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_trial(media: Path = ROOT) -> dict:
    manifest_file = media / "device_media_manifest.json"
    dist_file = media / "distribution.json"
    manifest_bytes = manifest_file.read_bytes()
    dist_bytes = dist_file.read_bytes()
    manifest = json.loads(manifest_bytes)
    distribution = json.loads(dist_bytes)
    if len(manifest["entries"]) != 61:
        raise ValueError("trial baseline changed; review required")
    if any(row.get("revision") == REVISION for row in manifest["entries"]):
        raise ValueError("trial revision already exists; do not repeat")
    if sha(manifest_bytes) != distribution["mediaManifest"]["sha256"] or (
        len(manifest_bytes) != distribution["mediaManifest"]["bytes"]
    ):
        raise ValueError("baseline manifest SHA/length mismatch")

    matching = [row for row in manifest["entries"]
                if row["deviceId"] == DEVICE and row["revision"] ==
                "infinix-approved-x6817-frontback-v1" and row["view"] == "frontBack"]
    if len(matching) != 1:
        raise ValueError("original HOT12 media entry missing or ambiguous")
    source_entry = matching[0]
    if (source_entry["chunkId"], source_entry["filename"], source_entry["sha256"],
            source_entry["verifiedModelCodes"]) != (
            SOURCE_CHUNK, SOURCE_NAME, SOURCE_SHA, [CODE]):
        raise ValueError("HOT12 source provenance changed")
    source_archive = media / "chunks" / (SOURCE_CHUNK + ".zip")
    with zipfile.ZipFile(source_archive) as z:
        if z.testzip() is not None:
            raise ValueError("corrupt source ZIP")
        original_bytes = z.read(SOURCE_NAME)
    if sha(original_bytes) != SOURCE_SHA or len(original_bytes) != source_entry["bytes"]:
        raise ValueError("corrupt or unexpected original HOT12 PNG")

    # True alpha bounding box (threshold >0, *not* >12) protects faint edges.
    with Image.open(io.BytesIO(original_bytes)) as image:
        if image.format != "PNG":
            raise ValueError("original is not PNG")
        original = image.convert("RGBA")
    if original.getchannel("A").getextrema()[0] != 0:
        raise ValueError("unverified opaque source")
    box = original.getchannel("A").getbbox()
    if box is None:
        raise ValueError("no visible phone content")
    visible = original.crop(box)
    long_axis = max(visible.size)
    if min(visible.size) < 180 or long_axis < 300:
        raise ValueError("visible image resolution too low")
    margin = max(4, round(long_axis * 0.015))
    # Square canvas remains necessary for the CURRENT production application's
    # 40px BoxFit.cover thumbnail; visible device pixels are never stretched.
    side = long_axis + 2 * margin
    if side > 2500:
        raise ValueError("unsafe output size")
    result = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    origin = ((side - visible.width) // 2, (side - visible.height) // 2)
    result.paste(visible, origin)  # Exact RGBA copy, including invisible RGB channels
    assert result.crop((*origin, origin[0] + visible.width,
                        origin[1] + visible.height)).tobytes() == visible.tobytes()
    final_box = result.getchannel("A").getbbox()
    if final_box is None or any(abs((final_box[0] + final_box[2]) / 2 - side / 2) > 1 for _ in [0]):
        raise ValueError("output centering failed")
    coverage = max(final_box[2] - final_box[0], final_box[3] - final_box[1]) / side
    if not 0.95 <= coverage <= 0.98:
        raise ValueError(f"unexpected normalized coverage {coverage}")
    out = io.BytesIO()
    result.save(out, format="PNG", optimize=True)
    payload = out.getvalue()

    chunk_id = f"infinix-x6817-preview2-{sha(payload)[:12]}"
    chunk_file = media / "chunks" / (chunk_id + ".zip")
    if chunk_file.exists():
        raise ValueError("immutable output chunk already exists")
    archive_io = io.BytesIO()
    with zipfile.ZipFile(archive_io, "w", zipfile.ZIP_DEFLATED, compresslevel=8) as z:
        z.writestr(FILENAME, payload)
    archive = archive_io.getvalue()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        if z.testzip() is not None or z.namelist() != [FILENAME]:
            raise ValueError("trial ZIP preflight failed")
        if sha(z.read(FILENAME)) != sha(payload):
            raise ValueError("trial ZIP payload mismatch")

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    new = dict(source_entry)
    new.update({
        "revision": REVISION,
        "filename": FILENAME,
        "chunkId": chunk_id,
        "sha256": sha(payload),
        "bytes": len(payload),
        "checkedAt": timestamp,
    })
    old_entries = list(manifest["entries"])
    old_chunks = list(distribution["chunks"])
    # Current device resolver chooses first frontBack; the old entry remains
    # intact and reachable for a reversible rollback.
    manifest["entries"].insert(0, new)
    manifest["manifestVersion"] += 1
    manifest["generatedAt"] = timestamp
    distribution["chunks"].append({
        "chunkId": chunk_id,
        "url": BASE_URL + chunk_id + ".zip",
        "compressedBytes": len(archive),
        "uncompressedBytes": len(payload),
        "sha256": sha(archive),
    })
    if manifest["entries"][1:] != old_entries or distribution["chunks"][:-1] != old_chunks:
        raise ValueError("another media entry changed")
    updated_manifest = packed(manifest)
    distribution["mediaManifest"]["bytes"] = len(updated_manifest)
    distribution["mediaManifest"]["sha256"] = sha(updated_manifest)
    updated_distribution = packed(distribution)

    # All validation BEFORE any filesystem mutation.
    if not (new["deviceId"] == DEVICE and
            all(row == old for row, old in zip(manifest["entries"][1:], old_entries))):
        raise ValueError("unexpected manifest mutation")
    chunk_file.write_bytes(archive)
    manifest_file.write_bytes(updated_manifest)
    dist_file.write_bytes(updated_distribution)
    return {
        "model": "Infinix HOT 12",
        "code": CODE,
        "revisions": [new["revision"], source_entry["revision"]],
        "originalCanvas": list(original.size),
        "originalSubject": [visible.width, visible.height],
        "newCanvas": [side, side],
        "subjectCoverageLongAxis": round(coverage, 4),
        "newSha256": sha(payload),
        "oldSha256": SOURCE_SHA,
        "allOtherMediaEntriesUnchanged": True,
        "mediaEntriesAfter": len(manifest["entries"]),
        "onlyOneNewMediaFile": True,
        "phoneDataAccess": False,
    }


if __name__ == "__main__":
    print(json.dumps(build_trial(), ensure_ascii=False))
