#!/usr/bin/env python3
"""Offline regression tests for official Infinix sitemap discovery."""
import unittest
from unittest.mock import patch
import official_index as ix


class NameTest(unittest.TestCase):
    def test_normalize_brand_and_punctuation(self):
        self.assertEqual(ix.normalize_name("Infinix HOT 60i"), ix.normalize_name("HOT-60i"))
        self.assertEqual(ix.normalize_name("GT 20 Pro"), ix.normalize_name("gt-20-pro"))

    def test_plus_is_not_silently_ignored(self):
        self.assertEqual(ix.normalize_name("HOT 50 Pro+"), ix.normalize_name("hot-50-pro%2B"))
        self.assertNotEqual(ix.normalize_name("HOT 50 Pro"), ix.normalize_name("hot-50-pro%2B"))

    def test_multi_model_code_names_are_not_hardware_identity(self):
        hot_ten = [d for d in ix.bot.CATALOG if ix.normalize_name(d["name"]) == "hot10"]
        self.assertGreater(len(hot_ten), 1)


class SourceSafetyTest(unittest.TestCase):
    def test_reject_untrusted_sitemap_urls(self):
        self.assertFalse(ix.valid_product_url("https://malware.example/HOT-60i"))
        self.assertFalse(ix.valid_product_url("http://wap.my.infinixmobility.com/HOT-60i"))
        self.assertFalse(ix.valid_product_url("https://wap.my.infinixmobility.com/shop/10"))
        self.assertFalse(ix.valid_product_url("https://wap.my.infinixmobility.com/HOT-60i?sku=X"))
        self.assertTrue(ix.valid_product_url("https://wap.my.infinixmobility.com/HOT-60i"))

    def test_reject_untrusted_preview_urls(self):
        self.assertTrue(ix.valid_preview_url(
            "https://d3o31au25zfcly.cloudfront.net/newfileadmin/usp/hot/kv.webp"))
        self.assertFalse(ix.valid_preview_url("https://evil.example/newfileadmin/usp/photo.webp"))
        self.assertFalse(ix.valid_preview_url("https://d3o31au25zfcly.cloudfront.net/other/fake.png"))
        self.assertFalse(ix.valid_preview_url("http://d3o31au25zfcly.cloudfront.net/newfileadmin/fake.png"))

    def test_xml_deduplicates_valid_product_urls(self):
        data = b'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://wap.my.infinixmobility.com/HOT-60i</loc></url>
          <url><loc>https://wap.my.infinixmobility.com/HOT-60i</loc></url>
          <url><loc>https://evil.example/HOT-60i</loc></url>
          <url><loc>https://wap.my.infinixmobility.com/shop/1665</loc></url>
        </urlset>'''
        urls, rejected = ix.parse_sitemap(data)
        self.assertEqual(urls, ["https://wap.my.infinixmobility.com/HOT-60i"])
        self.assertEqual(rejected, 3)

    def test_image_hints_are_not_approvals(self):
        obj = ix.ProductImageHints()
        obj.feed('''<title>Infinix - HOT 60i</title>
          <img data-src="https://d3o31au25zfcly.cloudfront.net/newfileadmin/a.webp">
          <img data-src="https://evil.example/newfileadmin/b.webp">
          <img data-src="https://d3o31au25zfcly.cloudfront.net/newfileadmin/a.webp">
        ''')
        self.assertEqual(obj.title, "Infinix - HOT 60i")
        self.assertEqual(len(obj.urls), 1)

    def test_official_redirect_cannot_leave_allowlist(self):
        class FakeResponse:
            status = 200
            def geturl(self):
                return "https://untrusted.example/not-a-product"
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        with patch.object(ix.urllib.request, "urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(ValueError, "redirect left"):
                ix.get_bytes("https://wap.my.infinixmobility.com/HOT-60i", 10000)


if __name__ == "__main__":
    unittest.main()
