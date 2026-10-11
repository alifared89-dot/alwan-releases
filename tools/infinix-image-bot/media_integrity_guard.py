#!/usr/bin/env python3
"""Protect published media by default while permitting explicit one-PR migrations."""
from __future__ import annotations
import argparse
import json
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
    if not allow["entryRewrite"]:
        missing = sorted(set(old_entries) - set(new_entries))
        if missing:
            raise ValueError(f"previously published media entries removed: {len(missing)}")
        changed = sorted(k for k, v in old_entries.items() if new_entries[k] != v)
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