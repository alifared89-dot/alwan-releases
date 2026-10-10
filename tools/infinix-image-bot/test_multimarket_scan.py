"""Offline checks for strict official-source multi-market Infinix discovery."""
import io
import unittest
from unittest.mock import patch
import multimarket_scan as mm
import bot


class MultiMarketTest(unittest.TestCase):
    def test_regional_hostname_allowlist(self):
        self.assertNotIn("other", mm.MARKETS)
        self.assertIn("np", mm.MARKETS)
        for page_host, image_host in mm.MARKETS.values():
            self.assertTrue(page_host.endswith(".infinixmobility.com"))
            self.assertTrue(image_host.endswith(".pro.infinixmobility.com"))

    def test_official_gallery_cache_decompressed_and_untrusted_urls_removed(self):
        raw = ('images:[{alt:"",src:"https:\\u002F\\u002F'
               'ph.pro.infinixmobility.com\\u002Fmedia\\u002Fcatalog\\u002Fproduct'
               '\\u002Fcache\\u002Fe97e30f46ad3af2c4402aa864120074b\\u002Fgt\\u002Ffrontback.png"},'
               '{src:"https:\\u002F\\u002Fevil.example\\u002Fmedia\\u002Fcatalog\\u002Fproduct\\u002Fevil.png"}'
               '],level_price:')
        urls, rejected = mm.valid_gallery_urls(raw, "ph")
        self.assertEqual(urls, ["https://ph.pro.infinixmobility.com/media/catalog/product/gt/frontback.png"])
        self.assertEqual(rejected, 1)

    def test_official_hostname_redirect_blocked(self):
        class Response:
            status = 200
            def geturl(self):
                return "https://evil.example/secret"
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with patch.object(mm.media_core._OPENER, "open", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "untrusted"):
                mm.get("https://wap.ph.infinixmobility.com/shop/1311", 20000,
                       "wap.ph.infinixmobility.com")

    def test_product_page_name_and_sku_conflict_rejected(self):
        device = bot.match_storefront_code("X6725B")[1]
        html = b'<html><title>Infinix - HOT 50 - Philippines</title><div>images:[{alt:}</div></html>'
        with patch.object(mm, "get", return_value=(html, "https://wap.ph.infinixmobility.com/shop/1311")):
            with self.assertRaisesRegex(ValueError, "title conflicts"):
                mm.inspect_official_detail("ph", {"id":"1311"}, device, "X6725B")

    def test_transient_502_gets_one_retry(self):
        from urllib.error import HTTPError
        class Response:
            status = 200
            def geturl(self):
                return "https://wap.ph.infinixmobility.com/shop/12"
            def read(self, length):
                return b"<html>ok</html>"
            def __enter__(self): return self
            def __exit__(self, *args): return False
        url = "https://wap.ph.infinixmobility.com/shop/12"
        error = HTTPError(url, 502, "upstream", {}, io.BytesIO())
        try:
            with patch.object(mm.media_core._OPENER, "open",
                              side_effect=[error, Response()]) as opened, \
                 patch.object(mm.media_core, "_retry_delay", return_value=0):
                data, actual = mm.get(url, 20000, "wap.ph.infinixmobility.com")
        finally:
            error.close()
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(data, b"<html>ok</html>")

    def test_page_name_normalization(self):
        self.assertEqual(mm.normalize_store_title("Infinix - SMART 10 Plus - Malaysia"),
                         mm.normalize_store_title("SMART 10 Plus"))
        self.assertEqual(mm.normalize_store_title("إإنفيينكس - HOT 60 Pro+ - Iraq"),
                         mm.normalize_store_title("HOT 60 Pro+"))

    def test_model_count_constraints(self):
        with self.assertRaises(ValueError):
            mm.scan(["HOT 40"]*21, ["my"], workers=4)
        with self.assertRaises(ValueError):
            mm.scan(["HOT 40"], ["invalid-market"])
        with self.assertRaises(ValueError):
            mm.scan(["HOT 40"], ["my"], workers=12)


if __name__ == "__main__":
    unittest.main()
