#!/usr/bin/env python3
"""Public-release new-file allowlist: prevent future internal bot/report leakage.

This guard is safe to run on untrusted PR data with contents:read.
It never reads private repositories, credentials, or file contents; it only
checks ADDED tracked paths against the release repository ownership boundary.
Existing published assets and previously tracked tools are untouched.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import PurePosixPath

DATA_ROOTS = ("device-media/", "compatibility/", "brand-media/")
PUBLIC_REPO_META = {".github/release_scope_guard.py"}
UNSAFE_SEGMENTS = {
    "research", "reports", "report", "private", "internal", "secrets", "output",
    "phone-runtime", "migration-evidence", "migration-reference", "source-cache",
    "cache", "__pycache__", ".env", "credentials",
}
UNSAFE_EXTENSIONS = (
    ".sqlite", ".sqlite3", ".db", ".db3", ".sql", ".env", ".log", ".tmp",
    ".tar", ".tar.gz", ".tgz", ".pyc", ".ipynb", ".key", ".pem", ".p12", ".jks",
)
UNSAFE_BASENAME_TOKENS = ("internal", "research", "handoff", "report", "audit", "private")


def violation(path: str) -> str | None:
    """Classify one newly added public path; no filesystem/network access."""
    if not path or "\\" in path:
        return "invalid path"
    pure = PurePosixPath(path)
    if (path.startswith("/") or not pure.parts
            or ".." in pure.parts or "." in pure.parts):
        return "unsafe relative path"
    lowered = path.casefold()
    pieces = [x.casefold() for x in pure.parts]
    if any(x in UNSAFE_SEGMENTS for x in pieces):
        return "internal directory"
    base = pieces[-1]
    if (base.startswith(".env") or any(base.endswith(x) for x in UNSAFE_EXTENSIONS)
            or any(x in base for x in UNSAFE_BASENAME_TOKENS)):
        return "internal file format or report name"
    if path.startswith("tools/"):
        return "new bot/validator source belongs in private control, not public releases"
    if path.startswith(DATA_ROOTS):
        # New client payloads and immutable ZIP chunks remain supported.
        if base.endswith(".json") or (
            path.startswith(("device-media/chunks/", "brand-media/chunks/"))
            and base.endswith(".zip")
        ):
            return None
        return "unexpected production data file type"
    if path.startswith(".github/workflows/"):
        return None if base.endswith((".yml", ".yaml")) else "unexpected workflow file"
    if path in PUBLIC_REPO_META:
        return None
    return "not an approved new public distribution path"


def evaluate(paths: list[str]) -> list[tuple[str, str]]:
    return [(p, reason) for p in paths if (reason := violation(p)) is not None]


def self_test():
    permitted = [
        "device-media/chunks/infinix-new.zip",
        "brand-media/chunks/brands-v2-a.zip",
        "compatibility/payloads/display.json",
        "device-media/distribution.json",
        "brand-media/distribution.json",
        ".github/workflows/contract.yml",
        ".github/release_scope_guard.py",
    ]
    rejected = [
        "tools/infinix-image-bot/new_bot.py",
        "tools/compatibility/new_validator.py",
        "research/phone-notes.md",
        "reports/staging.json",
        "migration-evidence/termux-backup.tar.gz",
        "phone-runtime/images.py",
        "compatibility/payloads/research_audit.json",
        "device-media/backup.sqlite",
        "device-media/chunks/source-cache.zip",
        "brand-media/chunks/private-photo.zip",
        "notes/internal_report.md",
        ".env.production",
        "unsafe/secrets.pem",
    ]
    if evaluate(permitted):
        raise AssertionError("valid public client paths were rejected")
    if len(evaluate(rejected)) != len(rejected):
        raise AssertionError("an internal path unexpectedly passed release gate")
    print(f"ALWAN-PUBLIC-SCOPE-SELFTEST: {len(permitted)} valid, {len(rejected)} rejected")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", help="verified 40-digit baseline commit SHA")
    group.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    base = args.base
    if (not isinstance(base, str) or len(base) != 40
            or any(c not in "0123456789abcdef" for c in base)
            or base == "0" * 40):
        ap.error("ALWAN-PUBLIC-SCOPE-BASELINE-MISSING")
    output = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", f"{base}...HEAD"],
        capture_output=True, text=True, check=True,
    )
    added = [x for x in output.stdout.splitlines() if x]
    bad = evaluate(added)
    if bad:
        for path, reason in bad:
            print(f"ALWAN-PUBLIC-INTERNAL-FILE-DENIED: {path} ({reason})")
        raise SystemExit(1)
    print(f"ALWAN-PUBLIC-SCOPE-OK: {len(added)} added files, no internal paths")


if __name__ == "__main__":
    main()
