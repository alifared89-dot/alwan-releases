"""Offline regression tests for GitHub-only published-image progress reporting."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import github_manifest_guard
import progress_report


class FakeResponse:
    status = 200

    def __init__(self, data: bytes, url: str = github_manifest_guard.API):
        self.data = data
        self.url = url

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.data[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def github_reply(ids, version=18, url=github_manifest_guard.API):
    payload = json.dumps({
        "manifestVersion": version,
        "entries": [{"deviceId": value} for value in ids],
    }).encode("utf-8")
    envelope = {
        "type": "file",
        "path": github_manifest_guard.PATH,
        "encoding": "base64",
        "content": base64.b64encode(payload).decode("ascii"),
    }
    return FakeResponse(json.dumps(envelope).encode("utf-8"), url=url)


class PublishedProgressTests(unittest.TestCase):
    def test_live_main_is_the_only_published_source(self):
        state = progress_report.current_published_manifest(
            opener=lambda *_args, **_kwargs: github_reply(
                ["infinix-1", "infinix-2", "samsung-1"]))
        coverage = progress_report.publication_coverage(
            [{"deviceId": "infinix-1"}, {"deviceId": "infinix-2"},
             {"deviceId": "infinix-3"}], state)
        self.assertEqual(18, coverage["manifestVersion"])
        self.assertEqual(3, coverage["publishedAllBrands"])
        self.assertEqual(2, coverage["publishedInfinix"])
        self.assertEqual(1, coverage["remainingUnpublishedInfinix"])
        self.assertTrue(state["source"].endswith("?ref=main"))

    def test_live_manifest_duplicate_ids_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate published"):
            progress_report.current_published_manifest(
                opener=lambda *_args, **_kwargs: github_reply(
                    ["infinix-1", "infinix-1"]))

    def test_forged_or_redirected_response_rejected(self):
        with self.assertRaisesRegex(ValueError, "endpoint changed"):
            progress_report.current_published_manifest(
                opener=lambda *_args, **_kwargs: github_reply(
                    ["infinix-1"], url="https://invalid.example/manifest"))

    def test_catalog_duplicates_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate Infinix"):
            progress_report.publication_coverage(
                [{"deviceId": "infinix-1"}, {"deviceId": "infinix-1"}],
                {"deviceIds": frozenset(["infinix-1"]), "manifestVersion": 18})

    def test_offline_error_does_not_write_or_replace_stored_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "infinix-progress.json"
            existing.write_text("PREEXISTING REPORT")
            with patch.object(progress_report, "ROOT", root), patch.object(
                    progress_report, "current_published_manifest",
                    side_effect=OSError("GitHub unavailable")):
                with self.assertRaisesRegex(OSError, "GitHub unavailable"):
                    progress_report.main()
            self.assertEqual("PREEXISTING REPORT", existing.read_text())


if __name__ == "__main__":
    unittest.main()
