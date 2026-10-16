#!/usr/bin/env python3
"""Protect published media by default while permitting explicit one-PR migrations."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path


def load(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return value


def migration_permissions(plan: dict | None, *, base_commit: str,
                          old_manifest: dict, new_manifest: dict) -> dict:
    deny = {
        "entryRewrite": False,
        "chunkRewrite": False,
        "schemaVersionChange": False,
        "manifestUrlChange": False,
    }
    if plan is None:
        return deny
    if plan.get("schemaVersion") != 1 or plan.get("mode") != "intentional-media-migration":
        raise ValueError("invalid migration plan schema or mode")
    if plan.get("baseCommit") != base_commit:
        raise ValueError("migration plan is stale or targets another PR base")
    reason = str(plan.get("reason") or "").strip()
    if len(reason) < 20:
        raise ValueError("migration plan requires a meaningful reason")
    if plan.get("targetManifestVersion") != new_manifest.get("manifestVersion"):
        raise ValueError("migration targetManifestVersion does not match current manifest")
    if int(new_manifest.get("manifestVersion", 0)) <= int(old_manifest.get("manifestVersion", 0)):
        raise ValueError("intentional migration must increase manifestVersion")
    allow = plan.get("allow") or {}
    return {
        "entryRewrite": allow.get("entryRewrite") is True,
        "chunkRewrite": allow.get("chunkRewrite") is True,
        "schemaVersionChange": allow.get("schemaVersionChange") is True,
        "manifestUrlChange": allow.get("manifestUrlChange") is True,
    }


def guard(old_manifest: dict, old_distribution: dict,
          new_manifest: dict, new_distribution: dict, *,
          base_commit: str, migration_plan: dict | None = None) -> dict:
    allow = migration_permissions(
        migration_plan, base_commit=base_commit,
        old_manifest=old_manifest, new_manifest=new_manifest,
    )

    old_version = old_manifest.get("manifestVersion")
    new_version = new_manifest.get("manifestVersion")
    if type(old_version) is not int or old_version < 1 or type(new_version) is not int or new_version < 1:
        raise ValueError("ALWAN-MEDIA-VERSION-INVALID: manifestVersion must be a positive integer")
    if new_version < old_version:
        raise ValueError("ALWAN-MEDIA-VERSION-ROLLBACK: manifestVersion may not decrease")
    if (new_manifest != old_manifest or new_distribution != old_distribution) and new_version <= old_version:
        raise ValueError("ALWAN-MEDIA-VERSION-NOT-ADVANCED: changed delivery must advance manifestVersion")

    if (old_distribution.get("schemaVersion") != new_distribution.get("schemaVersion")
            and not allow["schemaVersionChange"]):
        raise ValueError("distribution schemaVersion changed without migration permission")

    old_url = (old_distribution.get("mediaManifest") or {}).get("url")
    new_url = (new_distribution.get("mediaManifest") or {}).get("url")
    if old_url != new_url and not allow["manifestUrlChange"]:
        raise ValueError("stable mediaManifest URL changed without migration permission")

    old_entries = {(x["deviceId"], x["revision"], x["view"]): x
                   for x in old_manifest["entries"]}
    new_entries = {(x["deviceId"], x["revision"], x["view"]): x
                   for x in new_manifest["entries"]}
    # Exception limited to exact, explicitly listed identity corrections.
    # No image bytes, chunk ID, filename, source or model metadata may change.
    declared = [] if migration_plan is None else migration_plan.get("revisionCorrections", [])
    if not isinstance(declared, list):
        raise ValueError("revisionCorrections must be a list")
    approved_old, approved_new = set(), set()
    for correction in declared:
        if not isinstance(correction, dict) or set(correction) != {
            "deviceId", "view", "oldRevision", "newRevision"
        }:
            raise ValueError("invalid revision correction fields")
        device_id, view = correction["deviceId"], correction["view"]
        old_rev, new_rev = correction["oldRevision"], correction["newRevision"]
        old_key, new_key = (device_id, old_rev, view), (device_id, new_rev, view)
        if old_key in approved_old or new_key in approved_new:
            raise ValueError("duplicate revision correction")
        if not isinstance(new_rev, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", new_rev):
            raise ValueError("corrected revision is not client-compatible")
        if old_key not in old_entries or new_key not in new_entries:
            raise ValueError("revision correction identity missing")
        old_row = old_entries[old_key]
        expected = dict(old_row, revision=new_rev)
        if new_entries[new_key] != expected:
            raise ValueError("revision correction changes protected image metadata")
        if old_key in new_entries or new_key in old_entries:
            raise ValueError("revision correction duplicates an existing identity")
        approved_old.add(old_key)
        approved_new.add(new_key)
    missing = set(old_entries) - set(new_entries)
    if missing != approved_old:
        raise ValueError(f"previously published media entries removed: {len(missing - approved_old)}")
    if not allow["entryRewrite"]:
        changed = sorted(k for k, v in old_entries.items()
                         if k not in approved_old and new_entries[k] != v)
        unexpected = set(new_entries) - set(old_entries) - approved_new
        # Additional entries are allowed in ordinary append-only publishing;
        # only declared corrections may alter an existing identity.
        if changed:
            raise ValueError(f"immutable published media entries changed: {len(changed)}")

    old_chunks = {x["chunkId"]: x for x in old_distribution["chunks"]}
    new_chunks = {x["chunkId"]: x for x in new_distribution["chunks"]}
    if not allow["chunkRewrite"]:
        missing = sorted(set(old_chunks) - set(new_chunks))
        if missing:
            raise ValueError(f"previously published chunks removed: {len(missing)}")
        changed = sorted(k for k, v in old_chunks.items() if new_chunks[k] != v)
        if changed:
            raise ValueError(f"immutable chunk descriptors changed: {len(changed)}")

    return {
        "migrationMode": migration_plan is not None,
        "protectedEntries": len(old_entries),
        "protectedChunks": len(old_chunks),
        "permissions": allow,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--baseline-distribution", type=Path, required=True)
    parser.add_argument("--current-manifest", type=Path, required=True)
    parser.add_argument("--current-distribution", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--migration-plan", type=Path)
    args = parser.parse_args()
    plan = load(args.migration_plan) if args.migration_plan else None
    result = guard(
        load(args.baseline_manifest), load(args.baseline_distribution),
        load(args.current_manifest), load(args.current_distribution),
        base_commit=args.base_commit, migration_plan=plan,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()