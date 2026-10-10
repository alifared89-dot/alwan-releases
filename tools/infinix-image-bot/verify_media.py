#!/usr/bin/env python3
"""Verify immutable device-media distribution and new image presentation geometry.

Existing published bytes are checked for integrity, NOT retrospectively rejected
by a new style rule. With --baseline-manifest, every newly added image must pass
the current presentation gate; published entries cannot be silently rewritten.
"""
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2] / "device-media"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def check_new_presentation(payload: bytes, *, label: str = "image") -> dict:
    """Validate small symmetric transparent margins without imposing a canvas ratio.

    Uses the complete alpha bounding box: faint nonzero pixels must not be cut.
    The image's native aspect ratio is kept so phone/tablet products are natural.
    Actual upscaling/source identity is enforced before this gate by the bot.
    """
    with Image.open(io.BytesIO(payload)) as source:
        if source.format != "PNG":
            raise ValueError(f"{label}: PNG required")
        source.load()
        width, height = source.size
        if not 180 <= min(width, height) and max(width, height) >= 300:
            raise ValueError(f"{label}: output resolution too low")
        if max(width, height) > 2500 or width * height > 6_250_000:
            raise ValueError(f"{label}: output dimensions exceed budget")
        alpha = source.convert("RGBA").getchannel("A")
        if alpha.getextrema()[0] != 0:
            raise ValueError(f"{label}: transparent background required")
        box = alpha.getbbox()
        if box is None:
            raise ValueError(f"{label}: empty foreground")
        left, top, right, bottom = box
        subject_width, subject_height = right - left, bottom - top
        if min(subject_width, subject_height) < 180 or max(subject_width, subject_height) < 300:
            raise ValueError(f"{label}: visible subject resolution too low")
        expected = max(4, round(max(subject_width, subject_height) * .015))
        margins = (left, top, width - right, height - bottom)
        if any(abs(value - expected) > 1 for value in margins):
            raise ValueError(f"{label}: asymmetric or excessive transparent margins: {margins}")
        return {
            "pixels": [width, height],
            "subjectPixels": [subject_width, subject_height],
            "margins": list(margins),
            "longAxisCoverage": round(
                max(subject_width, subject_height) / max(width, height), 4
            ),
        }


def checked_new_entries(entries: list[dict], baseline: dict) -> set[str]:
    """Fail closed on mutation/removal of immutable old media entries."""
    old = {(x["deviceId"], x["revision"], x["view"]): x
           for x in baseline["entries"]}
    new = {(x["deviceId"], x["revision"], x["view"]): x for x in entries}
    missing = set(old) - set(new)
    if missing:
        raise ValueError(f"previously published media entries removed: {len(missing)}")
    for key, row in old.items():
        if row != new[key]:
            raise ValueError(f"immutable published media entry modified: {key}")
    return {x["filename"] for key, x in new.items() if key not in old}


def verify_media(root: Path = ROOT, baseline_manifest: Path | None = None) -> tuple[int, int]:
    manifest_data = (root / "device_media_manifest.json").read_bytes()
    distribution = json.loads((root / "distribution.json").read_bytes())
    manifest = json.loads(manifest_data)
    if len(manifest_data) != distribution["mediaManifest"]["bytes"] or (
        digest(manifest_data) != distribution["mediaManifest"]["sha256"]
    ):
        raise ValueError("manifest size or SHA mismatch")

    entries = manifest["entries"]
    chunks = {x["chunkId"]: x for x in distribution["chunks"]}
    if len(chunks) != len(distribution["chunks"]):
        raise ValueError("duplicate chunk descriptor")
    if {x["chunkId"] for x in entries} != set(chunks):
        raise ValueError("media entry/chunk descriptor mismatch")
    if len({(e["deviceId"], e["revision"], e["view"]) for e in entries}) != len(entries):
        raise ValueError("duplicate media identity")

    to_check = set()
    if baseline_manifest is not None:
        to_check = checked_new_entries(
            entries, json.loads(baseline_manifest.read_bytes())
        )
    inspected = 0
    for chunk_id, descriptor in chunks.items():
        archive_file = root / "chunks" / (chunk_id + ".zip")
        archive = archive_file.read_bytes()
        if len(archive) != descriptor["compressedBytes"] or (
            digest(archive) != descriptor["sha256"]
        ):
            raise ValueError(f"invalid archive checksum: {chunk_id}")
        matching = [e for e in entries if e["chunkId"] == chunk_id]
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            if z.testzip() is not None or (
                sorted(z.namelist()) != sorted(e["filename"] for e in matching)
            ):
                raise ValueError(f"invalid ZIP contents: {chunk_id}")
            for entry in matching:
                payload = z.read(entry["filename"])
                if len(payload) != entry["bytes"] or digest(payload) != entry["sha256"]:
                    raise ValueError(f"invalid image checksum: {entry['filename']}")
                if entry["filename"] in to_check:
                    check_new_presentation(payload, label=entry["filename"])
                    inspected += 1
    if inspected != len(to_check):
        raise ValueError("one or more new images were not inspected")
    return len(entries), inspected


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-manifest", type=Path)
    args = parser.parse_args()
    count, new_count = verify_media(baseline_manifest=args.baseline_manifest)
    print(f"PASS: {count} media entries with verified hashes; {new_count} newly published images passed geometry gate")
