"""Independent multi-brand image-composition fixture, no provider catalog needed."""
import io
import unittest
from PIL import Image, ImageDraw
import image_compositor as composer
import compose_views
import bot


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


    def test_bot_trim_preserves_every_rgba_pixel_across_phone_and_tablet(self):
        for size, bounds in [
            ((500, 500), (97, 51, 404, 449)),
            ((1200, 900), (70, 250, 1130, 670)),
            ((900, 1200), (220, 55, 680, 1145)),
        ]:
            with self.subTest(size=size):
                source = Image.new("RGBA", size, (0, 0, 0, 0))
                ImageDraw.Draw(source).rectangle(
                    (bounds[0], bounds[1], bounds[2] - 1, bounds[3] - 1),
                    fill=(12, 34, 56, 255),
                )
                # Faint antialiasing pixel must not be erased by alpha threshold.
                source.putpixel((bounds[0] - 1, bounds[1]), (222, 15, 8, 1))
                actual = Image.open(io.BytesIO(bot.crop_png(source))).convert("RGBA")
                original_box = source.getchannel("A").getbbox()
                actual_box = actual.getchannel("A").getbbox()
                self.assertEqual(
                    source.crop(original_box).tobytes(),
                    actual.crop(actual_box).tobytes(),
                    "Every source pixel, including transparent RGB, must survive",
                )
                self.assertEqual(actual_box[0], actual_box[1])
                self.assertEqual(actual.width - actual_box[2], actual_box[0])
                self.assertEqual(actual.height - actual_box[3], actual_box[1])
                self.assertEqual(actual.getpixel((0, 0))[3], 0)

    def test_bot_trim_rejects_opaque_background_and_empty_subject(self):
        with self.assertRaisesRegex(ValueError, "opaque source"):
            bot.crop_png(Image.new("RGB", (900, 900), "white"))
        with self.assertRaisesRegex(ValueError, "empty image"):
            bot.crop_png(Image.new("RGBA", (900, 900), (0, 0, 0, 0)))

if __name__=="__main__":unittest.main()
