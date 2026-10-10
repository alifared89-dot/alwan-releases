"""Offline tests: SHA-256 verified source cache and conservative quality gates."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from PIL import Image, ImageDraw

import bot
import evidence_cache as ec
import quality_triage as q


class CacheAndQualityTests(unittest.TestCase):
    def test_valid_official_only(self):
        self.assertTrue(ec.is_official_gallery_url(
            "https://middle-east.pro.infinixmobility.com/media/catalog/product/x/a/x6853_note.png","iq"))
        for url in ("https://middle-east.pro.infinixmobility.com.evil.org/media/catalog/product/a.png",
                    "http://middle-east.pro.infinixmobility.com/media/catalog/product/a.png",
                    "https://middle-east.pro.infinixmobility.com/private/other.png",
                    "https://other.pro.infinixmobility.com/media/catalog/product/a.png"):
            self.assertFalse(ec.is_official_gallery_url(url,"iq"))

    def test_detail_cache_expiry_and_code_cross_check(self):
        market, pid, code, name="iq","720","X6853","NOTE 40"
        urls=["https://middle-east.pro.infinixmobility.com/media/catalog/product/x/6/x6853_note.png"]
        with TemporaryDirectory(dir=bot.BOT/"output") as tmp, patch.object(ec,"ROOT",Path(tmp)):
            ec.write_detail(market,pid,code,name,
                            "https://iq.infinixmobility.com/shop/720",urls)
            record=ec.read_detail(market,pid,code,name)
            self.assertEqual(record["imageUrls"],urls)
            self.assertIsNone(ec.read_detail(market,pid,"X6850",name))
            self.assertIsNone(ec.read_detail(market,pid,code,"NOTE 50"))
            self.assertIsNone(ec.read_detail(market,pid,code,name,now=record["fetchedAt"]+ec.DETAIL_TTL_SECONDS+5))
            path,_=ec.record_paths("details",ec.cache_key(market,pid,code,name))
            data=json.loads(path.read_text())
            data["imageUrls"]=["https://evil.test/image.png"]
            path.write_text(json.dumps(data))
            self.assertIsNone(ec.read_detail(market,pid,code,name))

    def test_known_wrong_model_is_negatively_cached_but_expires(self):
        with TemporaryDirectory(dir=bot.BOT/"output") as tmp, patch.object(ec,"ROOT",Path(tmp)):
            ec.store_known_rejection("ph","101","X6816D","HOT 12 PLAY NFC",
                                     "https://wap.ph.infinixmobility.com/shop/101",{"X6816"})
            observed=ec.read_known_rejection("ph","101","X6816D","HOT 12 PLAY NFC")
            self.assertEqual(observed["galleryHardwareCodes"],["X6816"])
            self.assertIsNone(ec.read_known_rejection("ph","101","X6816C","HOT 12 PLAY NFC"))
            self.assertIsNone(ec.read_known_rejection("ph","101","X6816D","HOT 12 PLAY NFC",
                                                        now=observed["fetchedAt"]+12*3600+1))
            with self.assertRaises(ec.CacheIntegrityError):
                ec.store_known_rejection("ph","101","X6816D","HOT 12 PLAY NFC",
                                         "https://wap.ph.infinixmobility.com/shop/101",{"X6816D"})

    def test_image_cache_integrity_and_corrupted_sha_refused(self):
        url="https://middle-east.pro.infinixmobility.com/media/catalog/product/x/6/x6853_note.png"
        raw_image=Image.new("RGBA",(850,850),(0,0,0,0))
        ImageDraw.Draw(raw_image).rectangle((100,100,700,800),fill="green")
        import io
        buffer=io.BytesIO()
        raw_image.save(buffer,format="PNG")
        raw=buffer.getvalue()
        with TemporaryDirectory(dir=bot.BOT/"output") as tmp, patch.object(ec,"ROOT",Path(tmp)):
            with patch.object(ec.market,"get",return_value=(raw,url)) as downloader:
                first, _ = ec.cached_image(url,"iq")
                second, _ = ec.cached_image(url,"iq",offline=True)
            self.assertEqual(downloader.call_count,1)
            self.assertTrue(first["downloadOk"])
            self.assertFalse(first["cacheHit"])
            self.assertTrue(second["cacheHit"])
            self.assertEqual(first["sourceSha256"],second["sourceSha256"])
            _, file = ec.record_paths("assets",ec.cache_key("iq",url))
            file.write_bytes(b"tampered source")
            failure, image=ec.cached_image(url,"iq",offline=True)
            self.assertFalse(failure["downloadOk"])
            self.assertIsNone(image)

    def test_quality_does_not_claim_front_back(self):
        url="https://middle-east.pro.infinixmobility.com/media/catalog/product/x/6/x6853_note.png"
        valid=Image.new("RGBA",(1000,1000),(0,0,0,0))
        ImageDraw.Draw(valid).rectangle((100,100,480,920),fill="gold")
        sample={"url":url,"downloadOk":True,"sourceSha256":"a"*64}
        passed=q.inspect(valid,sample,"X6853")
        self.assertTrue(passed["eligibleForReview"])
        self.assertTrue(passed["frontBackHumanVerificationRequired"])
        self.assertFalse(passed["publishable"])
        self.assertFalse(q.inspect(valid,sample,"X6850")["eligibleForReview"])
        self.assertFalse(q.inspect(valid.resize((500,500)),sample,"X6853")["eligibleForReview"])
        self.assertFalse(q.inspect(Image.new("RGB",(1000,1000),"white"),sample,"X6853")["eligibleForReview"])

    def test_500px_verified_phone_is_only_a_high_res_search_reference(self):
        url="https://middle-east.pro.infinixmobility.com/media/catalog/product/x/6/x6853_note.png"
        from PIL import ImageDraw
        photo=Image.new("RGBA",(500,500),(0,0,0,0))
        ImageDraw.Draw(photo).rectangle((140,25,350,475),fill="black")
        metadata={"url":url,"downloadOk":True,"sourceSha256":"e"*64}
        ref=q.inspect(photo,metadata,"X6853")
        self.assertFalse(ref["eligibleForReview"])
        self.assertEqual(ref["tier"],"high_resolution_source_search_reference_only")
        self.assertTrue(ref["referenceForHighResSearch"])
        self.assertTrue(ref["doNotUpscale"])
        self.assertFalse(ref["publishable"])
        wrong=q.inspect(photo,metadata,"X6850")
        self.assertEqual(wrong["reason"],"file_does_not_match_hardware_model_code")
        self.assertFalse(wrong.get("referenceForHighResSearch",False))


if __name__=="__main__":
    unittest.main()
