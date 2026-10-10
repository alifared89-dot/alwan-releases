"""Offline end-to-end regression of existing approved-photo publish path.

All data is synthetic and lives in a temporary directory. Never writes to
GitHub, the real device-media repository or the user's connected devices.
"""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import bot
import verify_media


class PublishingGeometryTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.root = Path(self.sandbox.name)
        self.media = self.root / "device-media"
        self.media.mkdir()
        (self.media / "chunks").mkdir()
        self.bot_dir = self.root / "bot"
        self.bot_dir.mkdir()
        self.baseline = self.root / "baseline.json"
        self.manifest = {
            "manifestVersion": 1,
            "generatedAt": "2026-10-10T00:00:00Z",
            "entries": [],
        }
        original = bot.json_bytes(self.manifest)
        self.baseline.write_bytes(original)
        (self.media / "device_media_manifest.json").write_bytes(original)
        self.distribution = {
            "mediaManifest": {"bytes": len(original), "sha256": bot.sha(original)},
            "chunks": [],
        }
        (self.media / "distribution.json").write_bytes(bot.json_bytes(self.distribution))

        self.device = bot.BY_CODE["X6739"][0]
        self.page = 575
        self.image_url = "https://southeast-asia.pro.infinixmobility.com/media/catalog/product/test-x6739.png"

    def prepare_approval(self, source: bytes):
        (self.bot_dir / "approved.json").write_bytes(bot.json_bytes({
            "items": [{
                "deviceId": self.device["deviceId"],
                "modelCode": "X6739",
                "imageUrl": self.image_url,
                "officialPageId": self.page,
                "sourceSha256": hashlib.sha256(source).hexdigest(),
                "frontBackApproved": True,
            }],
        }))

    def publish(self, data: bytes):
        official = {
            "deviceId": self.device["deviceId"],
            "modelCode": "X6739",
            "imageUrls": [self.image_url],
        }
        with patch.object(bot, "BOT", self.bot_dir), \
             patch.object(bot, "MEDIA", self.media), \
             patch.object(bot, "official_page", return_value=official), \
             patch.object(bot, "fetch", return_value=data):
            bot.publish()

    def test_publish_normalizes_existing_bot_path_and_verifies_new_archive(self):
        image = Image.new("RGBA", (960, 960), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((215, 65, 480, 895), radius=20, fill="#203448")
        draw.rounded_rectangle((465, 65, 750, 895), radius=20, fill="#485b73")
        raw = io.BytesIO()
        image.save(raw, "PNG")
        source = raw.getvalue()
        self.prepare_approval(source)
        self.publish(source)

        count, strict_count = verify_media.verify_media(self.media, self.baseline)
        self.assertEqual((count, strict_count), (1, 1))
        manifest = json.loads((self.media / "device_media_manifest.json").read_text())
        self.assertEqual(manifest["entries"][0]["view"], "frontBack")
        self.assertEqual(manifest["entries"][0]["verifiedModelCodes"], ["X6739"])
        self.assertEqual(self.baseline.read_bytes(), bot.json_bytes(self.manifest))

    def test_invalid_photo_fails_before_mutating_publication(self):
        opaque = Image.new("RGB", (900, 900), "white")
        raw = io.BytesIO()
        opaque.save(raw, "PNG")
        self.prepare_approval(raw.getvalue())
        before_manifest = (self.media / "device_media_manifest.json").read_bytes()
        before_distribution = (self.media / "distribution.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "opaque"):
            self.publish(raw.getvalue())
        self.assertEqual((self.media / "device_media_manifest.json").read_bytes(), before_manifest)
        self.assertEqual((self.media / "distribution.json").read_bytes(), before_distribution)
        self.assertEqual(list((self.media / "chunks").iterdir()), [])

    def test_baseline_refuses_immutable_overwrite_or_removal(self):
        row = {
            "deviceId": "dev_test", "revision": "v1", "view": "frontBack",
            "filename": "a.png", "sha256": "a" * 64,
        }
        with self.assertRaisesRegex(ValueError, "removed"):
            verify_media.checked_new_entries([], {"entries": [row]})
        updated = dict(row, sha256="b" * 64)
        with self.assertRaisesRegex(ValueError, "modified"):
            verify_media.checked_new_entries([updated], {"entries": [row]})


if __name__ == "__main__":
    unittest.main()
