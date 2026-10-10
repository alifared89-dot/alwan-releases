"""Independent multi-brand image-composition fixture, no provider catalog needed."""
import unittest
from PIL import Image, ImageDraw
import io
import image_compositor as composer
import compose_views
import verify_media


class CompositorTests(unittest.TestCase):
    def test_synthetic_two_vendor_images_share_one_engine(self):
        for brand,back_hex,front_hex in [
            ("tecno",(255,80,20),(20,160,255)),
            ("samsung",(160,20,220),(50,255,50)),
        ]:
            with self.subTest(brand=brand):
                back=Image.new("RGBA",(400,850),(*back_hex,255))
                front=Image.new("RGBA",(370,840),(*front_hex,255))
                export=composer.compose_photos(back,front)
                self.assertEqual(export.size,(960,960))
                self.assertEqual(export.getpixel((0,0))[3],0)
                locations=[(x,480,export.getpixel((x,480))) for x in range(960)]
                xs_back=[x for x,y,p in locations if p[:3]==back_hex]
                xs_front=[x for x,y,p in locations if p[:3]==front_hex]
                self.assertTrue(xs_back and xs_front)
                self.assertLess(min(xs_back), min(xs_front))
                self.assertEqual(compose_views.compose(back,front).tobytes(),export.tobytes())

    def test_reject_excessive_canvas_and_overlap(self):
        original=Image.new("RGBA",(400,800),"black")
        with self.assertRaisesRegex(ValueError,"unsafe"):
            composer.compose_photos(original,original,canvas=(8000,8000))
        with self.assertRaisesRegex(ValueError,"overlap"):
            composer.compose_photos(original,original,overlap_fraction=.5)


    def test_normalization_preserves_every_visible_pixel_and_original_aspect(self):
        # Portrait, landscape tablet, old 500px photo, thin phone.
        for width, height, box in [
            (900, 1200, (250, 80, 650, 1120)),
            (1200, 800, (90, 150, 1110, 650)),
            (500, 500, (97, 51, 404, 449)),
            (720, 826, (12, 12, 708, 814)),
        ]:
            with self.subTest(size=(width, height)):
                source = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                ImageDraw.Draw(source).rectangle(
                    (box[0], box[1], box[2] - 1, box[3] - 1),
                    fill=(12, 45, 90, 255),
                )
                # Anti-alias/shadow-like transparent pixel MUST survive trim.
                source.putpixel((box[0] - 1, box[1]), (1, 2, 3, 1))
                normalized = composer.normalize_presentation(source)
                subject = source.crop(source.getchannel("A").getbbox())
                normalized_box = normalized.getchannel("A").getbbox()
                self.assertEqual(normalized.crop(normalized_box).tobytes(), subject.tobytes())
                self.assertEqual(normalized.getpixel((0, 0))[3], 0)
                self.assertEqual(
                    normalized.width - normalized_box[2],
                    normalized_box[0],
                )
                self.assertEqual(
                    normalized.height - normalized_box[3],
                    normalized_box[1],
                )
                encoded = io.BytesIO()
                normalized.save(encoded, "PNG")
                metrics = verify_media.check_new_presentation(encoded.getvalue())
                self.assertLessEqual(max(metrics["margins"]) - min(metrics["margins"]), 1)
                self.assertGreater(metrics["longAxisCoverage"], .96)

    def test_quality_gate_rejects_legacy_big_margins_not_rectangular_images(self):
        legacy = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
        ImageDraw.Draw(legacy).rectangle((97, 51, 403, 448), fill="black")
        raw = io.BytesIO()
        legacy.save(raw, "PNG")
        with self.assertRaisesRegex(ValueError, "margins"):
            verify_media.check_new_presentation(raw.getvalue())

        rectangular = Image.new("RGBA", (400, 600), (0, 0, 0, 0))
        ImageDraw.Draw(rectangular).rectangle((8, 8, 391, 591), fill="black")
        normalized = composer.normalize_presentation(rectangular)
        raw = io.BytesIO()
        normalized.save(raw, "PNG")
        verify_media.check_new_presentation(raw.getvalue())

    def test_normalization_fails_closed_on_invalid_or_oversized_sources(self):
        with self.assertRaisesRegex(ValueError, "opaque"):
            composer.normalize_presentation(Image.new("RGB", (700, 700), "white"))
        with self.assertRaisesRegex(ValueError, "empty"):
            composer.normalize_presentation(Image.new("RGBA", (700, 700), (0,0,0,0)))
        with self.assertRaisesRegex(ValueError, "resolution"):
            tiny=Image.new("RGBA", (700, 700), (0,0,0,0))
            ImageDraw.Draw(tiny).rectangle((200,200,300,300),fill="black")
            composer.normalize_presentation(tiny)


if __name__=="__main__":unittest.main()
