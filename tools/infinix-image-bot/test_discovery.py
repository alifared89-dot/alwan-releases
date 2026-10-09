#!/usr/bin/env python3
"""Bounded regression checks for strict Infinix SKU-to-catalog association."""
import unittest
from unittest.mock import patch
import bot

class MatchStorefrontCodeTest(unittest.TestCase):
    def test_exact_match(self):
        x = bot.match_storefront_code("X6886")
        self.assertEqual((x[0], x[2]), ("X6886", "exact"))

    def test_verified_color_suffix(self):
        x = bot.match_storefront_code("X6728B-MEADOW")
        self.assertEqual((x[0], x[1]["name"], x[2]),
                         ("X6728B", "Infinix HOT 60i", "verified_color_variant"))

    def test_unknown_suffix_must_not_pass(self):
        self.assertIsNone(bot.match_storefront_code("X6728B-OTHERHARDWARE"))

    def test_unknown_model(self):
        self.assertIsNone(bot.match_storefront_code("X999999-MEADOW"))

    def test_ambiguous_code_does_not_resolve(self):
        entry = bot.BY_CODE["X6728B"][0]
        with patch.dict(bot.BY_CODE, {"X6728B": [entry, entry]}):
            self.assertIsNone(bot.match_storefront_code("X6728B-MEADOW"))
            self.assertIsNone(bot.match_storefront_code("X6728B"))

    def test_conflicting_catalog_name_remains_unresolved_by_matching_only(self):
        # These conflicting hardware identities are deliberately NOT approved:
        # source SMART 10 HD vs catalog SMART 8 / X6525D,
        # source SMART 10 vs catalog SMART Series / X6725.
        self.assertNotIn("smart10hd", bot.normalized(bot.match_storefront_code("X6525D")[1]["name"]))
        self.assertNotIn("smart10", bot.normalized(bot.match_storefront_code("X6725")[1]["name"]))

if __name__ == "__main__":
    unittest.main()
