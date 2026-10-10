"""No-network checks for bounded concurrent review discovery."""
import json
import unittest
from unittest.mock import patch

import batch_scan as batch


class BatchTest(unittest.TestCase):
    def test_20_indexed_names_and_no_duplicates(self):
        names = batch.source_names(20)
        self.assertEqual(len(names), 20)
        self.assertEqual(len({batch.idx.normalize_name(n) for n in names}), 20)

    def test_model_code_must_appear_on_official_detail(self):
        item = {"id": "1311", "name": "SMART 10 Plus", "sku": "X6725B"}
        result = {"items": [item], "total": 1, "apiUrl": "https://wap.my.infinixmobility.com/api/V1/xpark-app/app-search"}
        with patch.object(batch.search, "api_search", return_value=result), \
             patch.object(batch.bot, "official_page", return_value=None):
            observed = batch.search_name("SMART 10 Plus", "malaysia", set())
        self.assertEqual(observed["candidates"], [])
        self.assertEqual(observed["query"]["reasonCounts"], {"detail_disagrees_or_parse_failed": 1})

    def test_published_device_excluded_from_candidates(self):
        item = {"id": "1311", "name": "SMART 10 Plus", "sku": "X6725B"}
        result = {"items": [item], "total": 1, "apiUrl": "https://wap.my.infinixmobility.com/api/V1/xpark-app/app-search"}
        dev = batch.bot.match_storefront_code("X6725B")[1]
        with patch.object(batch.search, "api_search", return_value=result), \
             patch.object(batch.bot, "official_page", side_effect=AssertionError("should not fetch")):
            observed = batch.search_name("SMART 10 Plus", "malaysia", {dev["deviceId"]})
        self.assertEqual(observed["candidates"], [])
        self.assertEqual(observed["query"]["reasonCounts"], {"device_already_published": 1})

    def test_limits_must_fail_closed(self):
        with self.assertRaises(ValueError):
            batch.execute(["SMART 10 Plus"]*21, "malaysia")
        with self.assertRaises(ValueError):
            batch.execute(["SMART 10 Plus"], "unknown")


if __name__ == "__main__":
    unittest.main()
