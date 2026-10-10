"""Fail-closed CPU-only tests for 2-view composition."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import bot
import compose_views as cv


class ComposeTest(unittest.TestCase):
    def test_back_left_front_right_fixed_canvas(self):
        rear=Image.new("RGBA",(180,450),(255,40,40,255))
        face=Image.new("RGBA",(180,450),(30,40,255,255))
        out=cv.compose(rear,face)
        self.assertEqual(out.size,(960,960))
        self.assertEqual(out.getpixel((0,0))[3],0)
        # Fixed geometry: red back is on the left, blue screen on the right.
        self.assertEqual(out.getpixel((380,480))[:3],(255,40,40))
        self.assertEqual(out.getpixel((570,480))[:3],(30,40,255))

    def test_white_background_segmentation_does_not_remove_internal_white(self):
        original=Image.new("RGBA",(600,700),"white")
        draw=ImageDraw.Draw(original)
        draw.rounded_rectangle((175,60,425,640),radius=15,fill="#181818")
        draw.rectangle((190,80,405,625),fill="white")
        result=cv.remove_white_background(original)
        self.assertEqual(result.getpixel((0,0))[3],0)
        self.assertEqual(result.getpixel((300,300))[3],255)
        self.assertEqual(result.getpixel((175,300))[3],255)

    def test_reject_nonwhite_opaque_source(self):
        im=Image.new("RGBA",(600,700),"#aabbcc")
        with self.assertRaisesRegex(cv.UnsafeImage,"non-white"):
            cv.remove_white_background(im)

    def test_reject_bad_inputs_before_mutation(self):
        for value in [
            {"modelCode":"X6858","deviceId":"wrong","colorKey":"GOLD","sources":[]},
            {"modelCode":"X6858","deviceId":bot.BY_CODE["X6858"][0]["deviceId"],
             "colorKey":"UNKNOWN","sources":[]},
            {"modelCode":"X6858","deviceId":bot.BY_CODE["X6858"][0]["deviceId"],
             "colorKey":"GOLD","sources":[{"role":"front"},{"role":"front"}]},
        ]:
            with self.assertRaises(cv.UnsafeImage):
                cv.execute(value)

    def test_evidence_identity_sha_and_color_enforced(self):
        with tempfile.TemporaryDirectory(dir=bot.BOT/"output") as directory:
            directory=Path(directory)
            samples={}
            for role,fill in (("front","#3388ff"),("back","#33ff88")):
                image=Image.new("RGBA",(620,720),(0,0,0,0))
                ImageDraw.Draw(image).rounded_rectangle((175,80,445,630),radius=22,fill=fill)
                path=directory/(role+".png")
                image.save(path)
                samples[role]={"role":role,"localPath":str(path),
                               "sourceSha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                               "modelCode":"X6858","deviceId":bot.BY_CODE["X6858"][0]["deviceId"],
                               "colorKey":"GOLD",
                               "productEvidenceUrl":"https://wap.ph.infinixmobility.com/shop/750",
                               "visualRoleVerified":True,"modelMatchVerified":True}
            record={"modelCode":"X6858","deviceId":bot.BY_CODE["X6858"][0]["deviceId"],
                    "colorKey":"GOLD","sources":[samples["front"],samples["back"]]}
            with patch.object(cv,"OUTPUT_DIR",directory/"composites"):
                output=cv.execute(record)
                self.assertFalse(output["publishable"])
                self.assertEqual(output["size"],[960,960])
                self.assertTrue(Path(output["outputFile"]).exists())
            altered=json.loads(json.dumps(record))
            altered["sources"][1]["colorKey"]="RED"
            with self.assertRaisesRegex(cv.UnsafeImage,"color mismatch"):
                cv.execute(altered)
            altered=json.loads(json.dumps(record))
            altered["sources"][1]["sourceSha256"]="0"*64
            with self.assertRaisesRegex(cv.UnsafeImage,"digest mismatch"):
                cv.execute(altered)
            altered=json.loads(json.dumps(record))
            altered["sources"][0]["visualRoleVerified"]=False
            with self.assertRaisesRegex(cv.UnsafeImage,"verification"):
                cv.execute(altered)


if __name__=="__main__":
    unittest.main()
