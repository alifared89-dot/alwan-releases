"""No-network validation for marketing-SKU fallback and wrong-variant rejection."""
import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import bot
import official_model_evidence as ev


class OfficialNameEvidenceTest(unittest.TestCase):
    def test_exact_image_hardware_code_tokens(self):
        self.assertEqual(ev.gallery_model_codes(
            ["https://ph.pro.infinixmobility.com/media/catalog/product/x/6/x6816_hot12_base1.png"]
        ), {"X6816"})
        self.assertNotIn("X6816D",ev.gallery_model_codes(
            ["https://ph.pro.infinixmobility.com/media/catalog/product/x/6/x6816_hot12_base1.png"]
        ))
        self.assertEqual(ev.gallery_model_codes(
            ["https://middle-east.pro.infinixmobility.com/media/catalog/product/x/6/x6850_note_base1.webp"]
        ), {"X6850"})
        self.assertEqual(ev.gallery_model_codes(
            ["https://x.invalid/myx6850ish.png"]
        ), set())

    def test_reject_nfc_variant_mismatch(self):
        dev=next(x for x in bot.CATALOG if x["modelCodes"]==["X6816D"])
        lead={"market":"ph","productId":"101","sourceName":"HOT 12 PLAY NFC",
              "sourceSku":"HOT 12 PLAY NFC","deviceId":dev["deviceId"],
              "name":dev["name"],"expectedCode":"X6816D"}
        detail={"finalUrl":"https://wap.ph.infinixmobility.com/shop/101",
                "galleryImageUrls":["https://ph.pro.infinixmobility.com/media/catalog/product/x/6/x6816_hot12_base1.png"]}
        with patch.object(ev.mm,"inspect_official_detail",return_value=detail):
            result=ev.validate_one(lead)
        self.assertEqual(result["reason"],"IMAGE_CODE_MISSING_OR_CONFLICTS")
        self.assertEqual(result["codeMismatchKind"],"different_or_mixed_code")
        self.assertEqual(result["images"],[])

    def test_accept_strict_same_product_filename_for_review_only(self):
        dev=bot.BY_CODE["X6853"][0]
        lead={"market":"my","productId":"767","sourceName":"NOTE 40",
              "sourceSku":"NOTE 40","deviceId":dev["deviceId"],
              "name":dev["name"],"expectedCode":"X6853"}
        detail={"finalUrl":"https://wap.my.infinixmobility.com/shop/767",
                "galleryImageUrls":["https://southeast-asia.pro.infinixmobility.com/media/catalog/product/x/6/x6853_note40_frontback.png"]}
        with patch.object(ev.mm,"inspect_official_detail",return_value=detail):
            result=ev.validate_one(lead)
        self.assertEqual(result["reason"],"OFFICIAL_NAME_PLUS_EXACT_IMAGE_CODE")
        self.assertEqual(len(result["images"]),1)

    def test_only_unpublished_exact_unique_catalog_names(self):
        device=bot.BY_CODE["X6816D"][0]
        with tempfile.TemporaryDirectory(dir=bot.BOT/"output") as tmp:
            db=Path(tmp)/"test.sqlite"
            with closing(sqlite3.connect(db)) as c:
                c.execute("CREATE TABLE products(market TEXT,product_id TEXT,name TEXT,sku TEXT)")
                c.execute("INSERT INTO products VALUES(?,?,?,?)",("my","101",device["name"],device["name"]))
                c.commit()
            matches=ev.index_exact_names(db)
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]["deviceId"],device["deviceId"])


if __name__=="__main__":
    unittest.main()
