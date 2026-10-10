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


    def test_normalization_preserves_pixels_and_fit_on_phone_or_tablet(self):
        # Portrait phone, wide tablet, legacy 500x500 source and regular phone.
        for width, height, box in [
            (900, 1200, (250, 80, 650, 1120)),
            (1200, 800, (90, 150, 1110, 650)),
            (500, 500, (97, 51, 404, 449)),
            (720, 826, (12, 12, 708, 814)),
        ]:
            with self.subTest(size=(width, height)):
                original=Image.new("RGBA", (width, height), (0, 0, 0, 0))
                ImageDraw.Draw(original).rectangle(
                    (box[0], box[1], box[2]-1, box[3]-1),
                    fill=(12, 45, 90, 255),
                )
                image=composer.normalize_presentation(original)
                self.assertEqual(image.width, image.height)
                self.assertEqual(image.getchannel("A").getbbox()[2] - image.getchannel("A").getbbox()[0], box[2]-box[0])
                self.assertEqual(image.getchannel("A").getbbox()[3] - image.getchannel("A").getbbox()[1], box[3]-box[1])
                self.assertEqual(image.getchannel("A").getpixel((0, 0)), 0)
                prepared=io.BytesIO()
                image.save(prepared, "PNG")
                metrics=verify_media.check_new_presentation(prepared.getvalue())
                self.assertAlmostEqual(metrics["longAxisCoverage"], .90, delta=.005)
                # Square ensures existing BoxFit.cover at any square thumbnail
                # dimension never removes any of the normalized subject.
                for thumbnail_size in (40, 80, 240):
                    self.assertEqual(image.resize((thumbnail_size, thumbnail_size)).size,
                                     (thumbnail_size, thumbnail_size))

    def test_quality_gate_rejects_legacy_small_subject_and_non_square(self):
        legacy=Image.new("RGBA", (500, 500), (0, 0, 0, 0))
        ImageDraw.Draw(legacy).rectangle((97, 51, 403, 448),fill="black")
        buf=io.BytesIO()
        legacy.save(buf, "PNG")
        with self.assertRaisesRegex(ValueError, "foreground scale"):
            verify_media.check_new_presentation(buf.getvalue())
        tall=Image.new("RGBA", (300, 600), (0, 0, 0, 0))
        ImageDraw.Draw(tall).rectangle((30, 30, 270, 570),fill="black")
        buf=io.BytesIO()
        tall.save(buf,"PNG")
        with self.assertRaisesRegex(ValueError, "square"):
            verify_media.check_new_presentation(buf.getvalue())

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
