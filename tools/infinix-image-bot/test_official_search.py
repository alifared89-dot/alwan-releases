#!/usr/bin/env python3
"""Offline regression tests for catalog-to-official-store search discovery."""
import unittest
from unittest.mock import patch
import json
import tempfile
from pathlib import Path

import official_search as search


class MatchingTest(unittest.TestCase):
    def setUp(self):
        self.published = {r["deviceId"] for r in json.loads(
            (search.bot.MEDIA / "device_media_manifest.json").read_text())["entries"]}

    def test_exact_code_and_name_is_cautious_candidate(self):
        r = search.classify_item({"id": "1311", "name": "SMART 10 Plus", "sku": "X6725B"},
                                 "Infinix SMART 10 Plus", self.published)
        self.assertEqual(r["reason"], "potential_device_candidate")
        self.assertEqual(r["modelCode"], "X6725B")
        self.assertTrue(r["deviceId"] not in self.published)

    def test_name_only_sku_cannot_claim_device(self):
        r = search.classify_item({"id": "792", "name": "GT 20 Pro", "sku": "GT 20 Pro"},
                                 "GT 20 Pro", self.published)
        self.assertEqual(r["reason"], "sku_not_unique_or_not_in_catalog")

    def test_storefront_device_name_is_not_enough(self):
        r = search.classify_item({"id": "1311", "name": "HOT 50", "sku": "X6725B"},
                                 "HOT 50", self.published)
        self.assertEqual(r["reason"], "sku_name_conflicts_with_catalog")

    def test_official_published_device_is_excluded(self):
        r = search.classify_item({"id": "1373", "name": "HOT 60i", "sku": "X6728"},
                                 "HOT 60i", self.published)
        self.assertEqual(r["reason"], "device_already_published")

    def test_item_must_be_exact_name(self):
        r = search.classify_item({"id": "1311", "name": "SMART 9", "sku": "X6725B"},
                                 "SMART 10 Plus", self.published)
        self.assertEqual(r["reason"], "name_not_exact")

    def test_invalid_product_id_rejected(self):
        r = search.classify_item({"id": "../1311", "name": "SMART 10 Plus", "sku": "X6725B"},
                                 "SMART 10 Plus", self.published)
        self.assertEqual(r["reason"], "invalid_official_product_id")


class PipelineTest(unittest.TestCase):
    def test_verified_detail_is_required(self):
        mock_item = {"id": "1311", "name": "SMART 10 Plus", "sku": "X6725B"}
        mock_result = {"total": 1, "items": [mock_item], "apiUrl": "https://wap.my.infinixmobility.com/api/V1/xpark-app/app-search?q=SMART"}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(search.bot, "BOT", Path(directory)), \
                 patch.object(search, "api_search", return_value=mock_result), \
                 patch.object(search.bot, "official_page", return_value=None), \
                 patch.object(search, "make_contact_sheet", return_value=None):
                status = search.run(["SMART 10 Plus"], ("malaysia",), 0)
                data = json.loads((Path(directory) / "output/official-search-report.json").read_text())
        self.assertEqual(status, 0)
        self.assertEqual(data["summary"]["uniqueDevicesWithVerifiedOfficialPage"], 0)
        self.assertEqual(data["queries"][0]["exactNameItems"][0]["reason"], "official_product_detail_disagrees")

    def test_successful_evidence_requires_review(self):
        mock_item = {"id": "1311", "name": "SMART 10 Plus", "sku": "X6725B"}
        mock_result = {"total": 1, "items": [mock_item], "apiUrl": "https://wap.my.infinixmobility.com/api/V1/xpark-app/app-search"}
        mock_official = {"deviceId": search.bot.match_storefront_code("X6725B")[1]["deviceId"],
                         "modelCode": "X6725B", "name": "SMART 10 PLUS",
                         "imageUrls": ["https://southeast-asia.pro.infinixmobility.com/media/catalog/product/example.png"],
                         "sourcePageUrl": "https://wap.my.infinixmobility.com/shop/1311"}
        fake_images = [{"url": mock_official["imageUrls"][0], "state": "downloaded",
                        "sourceSha256": "f" * 64, "width": 1000, "height": 1000}]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(search.bot, "BOT", Path(directory)), \
                 patch.object(search, "api_search", return_value=mock_result), \
                 patch.object(search.bot, "official_page", return_value=mock_official), \
                 patch.object(search, "collect_image_evidence", return_value=fake_images), \
                 patch.object(search, "make_contact_sheet", return_value=None):
                status = search.run(["SMART 10 Plus"], ("malaysia",), 1)
                data = json.loads((Path(directory) / "output/official-search-report.json").read_text())
        candidate = data["candidatesForVisualReview"][0]
        self.assertEqual(status, 0)
        self.assertEqual(data["summary"]["missingDevices"], 217)
        self.assertEqual(candidate["modelCode"], "X6725B")
        self.assertFalse(candidate["frontBackApproved"])
        self.assertFalse(candidate["rightsVerified"])
        self.assertFalse(candidate["publishable"])

    def test_broken_reference_is_not_functional_success(self):
        fake = {"total": 0, "items": [], "apiUrl": "https://wap.my.infinixmobility.com/api/V1/xpark-app/app-search"}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(search.bot, "BOT", Path(directory)), \
                 patch.object(search, "api_search", return_value=fake), \
                 patch.object(search, "make_contact_sheet", return_value=None):
                result = search.run(["SMART 10 Plus"], ("malaysia",), 0)
        self.assertEqual(result, 2)

    def test_all_api_errors_are_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(search.bot, "BOT", Path(directory)), \
                 patch.object(search, "api_search", side_effect=TimeoutError("offline")), \
                 patch.object(search, "make_contact_sheet", return_value=None):
                code = search.run(["SMART 10 Plus"], ("malaysia",), 0)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
