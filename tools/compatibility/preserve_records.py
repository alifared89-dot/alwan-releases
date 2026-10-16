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


# Exactly four invalid IDs previously published in PR #30. Allow their
# client-compatible replacements ONLY when the remaining record is identical.
# Never grant a general-purpose rename/delete bypass.
APPROVED_DISPLAY_DIFFERENCE_ID_REPAIRS = {
    "diff-infinix-x6885-x6886-commercial-929506-dev_kioyysn7v2xbyjfiaasykc2k7y":
        "diff-infinix-x6885-x6886-commercial-929506-x6885",
    "diff-infinix-x6885-x6886-commercial-929506-dev_2wwfy6fz7ve4aoyih5r7q2jvp4":
        "diff-infinix-x6885-x6886-commercial-929506-x6886",
    "diff-infinix-x687-x687b-commercial-660101241a-dev_va44wqykkvgau2fey7colgiuri":
        "diff-infinix-x687-x687b-commercial-660101241a-x687",
    "diff-infinix-x687-x687b-commercial-660101241a-dev_tmvympazmxcc7keslabl74pul4":
        "diff-infinix-x687-x687b-commercial-660101241a-x687b",
}


def approved_display_difference_repair(old_id: str, before_row: dict,
                                       after_rows: dict) -> bool:
    replacement_id = APPROVED_DISPLAY_DIFFERENCE_ID_REPAIRS.get(old_id)
    if not replacement_id:
        return False
    replacement = after_rows.get(replacement_id)
    if replacement is None:
        return False
    return ({k: v for k, v in before_row.items() if k != "id"}
            == {k: v for k, v in replacement.items() if k != "id"})


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
            if filename == "display.json" and collection == "compatibilityDifferences":
                previous_rows = {row["id"]: row for row in old[collection]}
                current_rows = {row["id"]: row for row in new[collection]}
                removed = [
                    old_id for old_id in removed
                    if not approved_display_difference_repair(
                        old_id, previous_rows[old_id], current_rows)
                ]
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
