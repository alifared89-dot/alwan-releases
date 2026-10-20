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
from pathlib import Path, PurePosixPath

DATA_ROOTS = ("device-media/", "compatibility/", "brand-media/")
PUBLIC_REPO_META = {".github/release_scope_guard.py"}
# Historical non-client reports are archived byte-identically in PRIVATE.
# This is the entire permitted report deletion list; all client deletions fail.
ARCHIVED_NONCLIENT_REPORTS = {
    "compatibility": (
        "compatibility/build_report.json",
        "98132171a4325b34343dd72cd4893a07cd3ea778",
    ),
    "device-media": (
        "device-media/INCIDENT_2026-10-16.md",
        "0ae7a7322cee6d13446df926eb28926bfedab398",
    ),
}

# ONLY brand-neutral production integrity code and fixtures. Never the research bot.
RELEASE_GUARD_SOURCES = {
    ".github/release-guards/" + filename for filename in (
        "validate_release.py", "preserve_records.py",
        "media_integrity_guard.py", "verify_media.py",
        "test_validate_release.py", "test_preserve_records.py",
        "test_media_integrity_guard.py", "test_verify_media_client_contract.py",
        "test_media_catalog_policy.py", "requirements.txt",
    )
}
UNSAFE_SEGMENTS = {
    "research", "reports", "report", "private", "internal", "secrets", "output",
    "phone-runtime", "migration-evidence", "migration-reference", "source-cache",
    "cache", "__pycache__", ".env", "credentials",
}
UNSAFE_EXTENSIONS = (
    ".sqlite", ".sqlite3", ".db", ".db3", ".sql", ".env", ".log", ".tmp",
    ".tar", ".tar.gz", ".tgz", ".pyc", ".ipynb", ".key", ".pem", ".p12", ".jks",
)
UNSAFE_BASENAME_TOKENS = ("internal", "research", "handoff", "report", "audit", "private", "source-cache")


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
    if path in PUBLIC_REPO_META or path in RELEASE_GUARD_SOURCES or path == "compatibility/.gitignore":
        return None
    if path.startswith(".github/release-guards/"):
        return "unapproved validator or research source (explicit release allowlist only)"
    return "not an approved new public distribution path"


def evaluate(paths: list[str]) -> list[tuple[str, str]]:
    return [(p, reason) for p in paths if (reason := violation(p)) is not None]


def check_deletions(deleted: list[str], scope: str, original_sha: str | None = None):
    """Fail closed on anything except one exact, SHA-pinned non-client report."""
    allowed, expected_sha = ARCHIVED_NONCLIENT_REPORTS[scope]
    if not deleted:
        return 0
    if deleted != [allowed] or original_sha != expected_sha:
        raise ValueError("ALWAN-PUBLIC-CLIENT-DELETE-DENIED: " + repr(deleted))
    return 1


def self_test():
    permitted = [
        "device-media/chunks/infinix-new.zip",
        "brand-media/chunks/brands-v2-a.zip",
        "compatibility/payloads/display.json",
        "device-media/distribution.json",
        "brand-media/distribution.json",
        ".github/workflows/contract.yml",
        ".github/release_scope_guard.py",
        "compatibility/.gitignore",
        *sorted(RELEASE_GUARD_SOURCES),
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
        ".github/release-guards/bot.py",
        ".github/release-guards/research_scan.py",
        ".github/release-guards/private_notes.md",
        ".github/release-guards/source-cache.zip",
        "device-media/.gitignore",
    ]
    if evaluate(permitted):
        raise AssertionError("valid public client paths were rejected")
    if len(evaluate(rejected)) != len(rejected):
        raise AssertionError("an internal path unexpectedly passed release gate")
    for scope, (path, sha) in ARCHIVED_NONCLIENT_REPORTS.items():
        if check_deletions([], scope) != 0 or check_deletions([path], scope, sha) != 1:
            raise AssertionError("non-client archival deletion not recognized")
        for paths, digest in (
            ([path], "0" * 40),
            ([path, scope + "/payloads/catalog.json"], sha),
            ([scope + "/distribution.json"], sha),
        ):
            try:
                check_deletions(paths, scope, digest)
            except ValueError:
                continue
            raise AssertionError("production deletion incorrectly permitted")
    print(f"ALWAN-PUBLIC-SCOPE-SELFTEST: {len(permitted)} valid, {len(rejected)} rejected; 2 exact report deletions, 6 client deletion rejections")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", help="verified 40-digit baseline commit SHA")
    group.add_argument("--self-test", action="store_true")
    ap.add_argument("--deletion-scope", choices=sorted(ARCHIVED_NONCLIENT_REPORTS))
    args = ap.parse_args()
    if args.self_test:
        if args.deletion_scope:
            ap.error("--deletion-scope requires --base")
        self_test()
        return
    base = args.base
    if (not isinstance(base, str) or len(base) != 40
            or any(c not in "0123456789abcdef" for c in base)
            or base == "0" * 40):
        ap.error("ALWAN-PUBLIC-SCOPE-BASELINE-MISSING")
    if args.deletion_scope:
        scope = args.deletion_scope
        removed = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=D",
             f"{base}...HEAD", "--", scope + "/"],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        original_sha = None
        if removed:
            path = ARCHIVED_NONCLIENT_REPORTS[scope][0]
            if removed == [path]:
                original_sha = subprocess.run(
                    ["git", "rev-parse", f"{base}:{path}"],
                    capture_output=True, text=True, check=True,
                ).stdout.strip()
        try:
            accepted = check_deletions(removed, scope, original_sha)
        except ValueError as exc:
            print(str(exc))
            raise SystemExit(1) from exc
        if accepted and Path(removed[0]).exists():
            raise SystemExit("ALWAN-PUBLIC-REPORT-NOT-DELETED")
        print(f"ALWAN-PUBLIC-DELETIONS-VERIFIED: {scope}: {accepted} archived non-client report")
        return
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
