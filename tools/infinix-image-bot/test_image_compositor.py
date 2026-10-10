"""Independent multi-brand image-composition fixture, no provider catalog needed."""
import unittest
from PIL import Image
import image_compositor as composer
import compose_views


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


if __name__=="__main__":unittest.main()
