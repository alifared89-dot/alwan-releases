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
MEDIA_RAW_BASE = (
    "https://raw.githubusercontent.com/alifared89-dot/"
    "alwan-releases/main/device-media/"
)
MEDIA_MANIFEST_URL = MEDIA_RAW_BASE + "device_media_manifest.json"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def check_new_presentation(payload: bytes, *, label: str = "image") -> dict:
    """Validate pixel-safe normalized device media in two supported layouts.

    Native aspect: 1.2% symmetric transparent margin on all sides for clients
    using BoxFit.contain.
    Square fallback: same margin on the longer subject axis; short-axis
    letterboxing is symmetric and the *entire* device remains visible in older
    square BoxFit.cover clients. Neither variant stretches image pixels.
    """
    with Image.open(io.BytesIO(payload)) as source:
        if source.format != "PNG":
            raise ValueError(f"{label}: PNG required")
        source.load()
        width, height = source.size
        if min(width, height) < 180 or max(width, height) < 300:
            raise ValueError(f"{label}: output resolution too low")
        if max(width, height) > 2500:
            raise ValueError(f"{label}: output dimensions exceed budget")
        alpha = source.convert("RGBA").getchannel("A")
        if alpha.getextrema()[0] != 0:
            raise ValueError(f"{label}: transparent background required")
        box = alpha.getbbox()
        if box is None:
            raise ValueError(f"{label}: empty foreground")
        left, top, right, bottom = box
        sw, sh = right - left, bottom - top
        if min(sw, sh) < 180 or max(sw, sh) < 300:
            raise ValueError(f"{label}: visible device too small")
        margins = (left, top, width - right, height - bottom)
        expected = max(4, round(max(sw, sh) * 0.012))
        if abs(left - (width - right)) > 1 or abs(top - (height - bottom)) > 1:
            raise ValueError(f"{label}: asymmetric transparent margins")
        if width == height:
            longest_axis_margins = (left, width - right) if sw >= sh else (top, height - bottom)
            if any(abs(m - expected) > 1 for m in longest_axis_margins):
                raise ValueError(f"{label}: large subject margin on square preview")
        elif any(abs(m - expected) > 1 for m in margins):
            raise ValueError(f"{label}: excessive transparent margins")
        coverage = max(sw, sh) / max(width, height)
        if not .95 <= coverage <= .98:
            raise ValueError(f"{label}: inconsistent foreground scale {coverage:.3f}")
        return {"pixels": [width, height], "visiblePixels": [sw, sh],
                "margins": list(margins), "longAxisCoverage": round(coverage, 4)}


def presentation_check_entries(
    entries: list[dict],
    baseline: dict,
    *,
    migration_mode: bool = False,
) -> set[str]:
    """Select images that must pass the current presentation gate.

    Normal PRs remain immutable. Intentional migrations may rewrite metadata,
    but any newly introduced or content-rewritten image is still revalidated.
    Packaging-only changes such as chunkId rewrites do not retroactively impose
    new geometry rules on unchanged published image bytes.
    """
    old = {(x["deviceId"], x["revision"], x["view"]): x
           for x in baseline["entries"]}
    new = {(x["deviceId"], x["revision"], x["view"]): x for x in entries}

    if not migration_mode:
        missing = set(old) - set(new)
        if missing:
            raise ValueError(
                f"previously published media entries removed: {len(missing)}"
            )
        for key, row in old.items():
            if row != new[key]:
                raise ValueError(
                    f"immutable published media entry modified: {key}"
                )
        return {x["filename"] for key, x in new.items() if key not in old}

    content_fields = ("filename", "sha256", "bytes")
    to_check = set()
    for key, row in new.items():
        previous = old.get(key)
        if previous is None or any(
            previous.get(field) != row.get(field) for field in content_fields
        ):
            to_check.add(row["filename"])
    return to_check


def check_media_catalog(entries: list[dict], catalog: dict, baseline: dict | None) -> int:
    """Validate new/revised media identities against the entire multi-brand catalog."""
    devices = {d["id"]: d for d in catalog["devices"]}
    old = {} if baseline is None else {
        (x["deviceId"], x["revision"], x["view"]): x
        for x in baseline["entries"]
    }
    checked = 0
    for entry in entries:
        identity = (entry["deviceId"], entry["revision"], entry["view"])
        if old.get(identity) == entry:
            continue
        device = devices.get(entry["deviceId"])
        if device is None:
            raise ValueError(f"ALWAN-MEDIA-UNKNOWN-DEVICE: {entry[\'deviceId\']}")
        expected = {str(code).strip().upper() for code in device.get("modelCodes", [])}
        declared = entry.get("verifiedModelCodes")
        if not isinstance(declared, list) or not declared or any(
            not isinstance(code, str) or code.strip().upper() not in expected
            for code in declared
        ):
            raise ValueError(
                f"ALWAN-MEDIA-MODEL-MISMATCH: {entry[\'deviceId\']} "
                f"claims {declared}, catalog declares {sorted(expected)}"
            )
        checked += 1
    return checked


def verify_media(
    root: Path = ROOT,
    baseline_manifest: Path | None = None,
    *,
    migration_mode: bool = False,
    catalog_path: Path | None = None,
) -> tuple[int, int]:
    manifest_data = (root / "device_media_manifest.json").read_bytes()
    distribution = json.loads((root / "distribution.json").read_bytes())
    manifest = json.loads(manifest_data)
    media_descriptor = distribution["mediaManifest"]
    if media_descriptor.get("url") != MEDIA_MANIFEST_URL:
        raise ValueError(
            "invalid media manifest URL: "
            f"expected {MEDIA_MANIFEST_URL}, got {media_descriptor.get('url')}"
        )
    if len(manifest_data) != media_descriptor["bytes"] or (
        digest(manifest_data) != media_descriptor["sha256"]
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

    if migration_mode and baseline_manifest is None:
        raise ValueError("migration mode requires --baseline-manifest")

    to_check = set()
    baseline = json.loads(baseline_manifest.read_bytes()) if baseline_manifest else None
    if baseline is not None:
        to_check = presentation_check_entries(
            entries, baseline, migration_mode=migration_mode,
        )
    if catalog_path is not None:
        checked = check_media_catalog(entries, json.loads(catalog_path.read_bytes()), baseline)
        print(f"PASS: {checked} newly published or revised media catalog/model links verified")
    inspected = 0
    for chunk_id, descriptor in chunks.items():
        expected_url = MEDIA_RAW_BASE + "chunks/" + chunk_id + ".zip"
        if descriptor.get("url") != expected_url:
            raise ValueError(
                f"invalid chunk URL for {chunk_id}: "
                f"expected {expected_url}, got {descriptor.get('url')}"
            )
        archive_file = root / "chunks" / (chunk_id + ".zip")
        archive = archive_file.read_bytes()
        if len(archive) != descriptor["compressedBytes"] or (
            digest(archive) != descriptor["sha256"]
        ):
            raise ValueError(f"invalid archive checksum: {chunk_id}")
        matching = [e for e in entries if e["chunkId"] == chunk_id]
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            # Mirror DeviceMediaInstaller exactly: a fresh device accepts
            # neither missing nor extra files in any downloaded chunk.
            actual_names = z.namelist()
            expected_names = {e["filename"] for e in matching}
            if z.testzip() is not None or sorted(actual_names) != sorted(expected_names):
                missing = sorted(expected_names.difference(actual_names))
                extra = sorted(set(actual_names).difference(expected_names))
                raise ValueError(
                    f"client-incompatible ZIP contents: {chunk_id}; "
                    f"missing={missing}; extra={extra}"
                )
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
    parser.add_argument("--migration-mode", action="store_true")
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    count, new_count = verify_media(
        baseline_manifest=args.baseline_manifest,
        migration_mode=args.migration_mode,
        catalog_path=args.catalog,
    )
    print(f"PASS: {count} media entries with verified hashes; {new_count} newly published images passed geometry gate")