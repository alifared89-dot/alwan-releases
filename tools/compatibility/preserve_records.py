#!/usr/bin/env python3
"""Preserve every published catalog/category record across remote-data updates.

Corrections are permitted in-place; deletion or identity replacement is not.
This gate is intentionally brand-neutral so future phone brands use the same policy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

FILES = {
    "catalog.json": ("brands", "devices"),
    "display.json": ("parts", "compatibilityGroups", "evidence",
                     "categoryFacts", "compatibilityDifferences"),
    "battery.json": ("parts", "compatibilityGroups", "evidence",
                     "categoryFacts", "compatibilityDifferences"),
    "charging.json": ("parts", "compatibilityGroups", "evidence",
                      "categoryFacts", "compatibilityDifferences"),
    "camera.json": ("parts", "compatibilityGroups", "evidence",
                    "categoryFacts", "compatibilityDifferences"),
    "flex.json": ("parts", "compatibilityGroups", "evidence",
                  "categoryFacts", "compatibilityDifferences"),
    "audio.json": ("parts", "compatibilityGroups", "evidence",
                   "categoryFacts", "compatibilityDifferences"),
}


def identifier(collection: str, row: dict):
    if collection == "categoryFacts":
        # Facts have device/category identity rather than a stable id field.
        return (row["deviceId"], row["category"])
    return row["id"]


def record_keys(payload: dict, collection: str, file: str) -> set:
    rows = payload.get(collection)
    if not isinstance(rows, list):
        raise ValueError(
            f"ALWAN-DATA-RECORD-COLLECTION: {file}#{collection} is not a list"
        )
    keys = [identifier(collection, row) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(
            f"ALWAN-DATA-DUPLICATE-ID: {file}#{collection} has duplicate IDs"
        )
    return set(keys)


def compare(previous: Path, current: Path) -> list[str]:
    errors = []
    for filename, collections in FILES.items():
        old_file = previous / "payloads" / filename
        new_file = current / "payloads" / filename
        if not old_file.is_file() or not new_file.is_file():
            errors.append(f"ALWAN-DATA-PAYLOAD-REMOVED: {filename} missing")
            continue
        old = json.loads(old_file.read_text(encoding="utf-8"))
        new = json.loads(new_file.read_text(encoding="utf-8"))
        for collection in collections:
            before = record_keys(old, collection, filename)
            after = record_keys(new, collection, filename)
            removed = sorted(before - after, key=str)
            if removed:
                errors.append(
                    f"ALWAN-DATA-RECORD-REMOVED: {filename}#{collection}: "
                    f"{len(removed)} published record(s) missing: {removed[:12]}"
                )
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, default=Path("compatibility"))
    args = parser.parse_args()
    try:
        errors = compare(args.previous, args.current)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        errors = [f"ALWAN-DATA-PRESERVATION-ERROR: {exc}"]
    for error in errors:
        print(error)
    if errors:
        raise SystemExit(1)
    print("PASS: all previously published device, brand and parts records retained")


if __name__ == "__main__":
    main()
