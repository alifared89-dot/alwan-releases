import copy
import unittest

from verify_media import check_media_catalog


class MediaCatalogLinkTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"devices": [
            {"id": "infinix1", "brandId": "infinix", "modelCodes": ["X6857"]},
            {"id": "samsung1", "brandId": "samsung", "modelCodes": ["SM-A123"]},
        ]}
        self.image = {
            "deviceId": "infinix1", "revision": "v1",
            "view": "frontBack", "filename": "frontback.png",
            "verifiedModelCodes": ["X6857"],
        }

    def test_new_image_with_matching_model_passes(self):
        self.assertEqual(1, check_media_catalog([self.image], self.catalog, {"entries": []}))

    def test_wrong_model_code_is_rejected(self):
        bad = dict(self.image, verifiedModelCodes=["X9999"])
        with self.assertRaisesRegex(ValueError, "ALWAN-MEDIA-MODEL-MISMATCH"):
            check_media_catalog([bad], self.catalog, {"entries": []})

    def test_unregistered_device_id_is_rejected(self):
        bad = dict(self.image, deviceId="other")
        with self.assertRaisesRegex(ValueError, "ALWAN-MEDIA-UNKNOWN-DEVICE"):
            check_media_catalog([bad], self.catalog, {"entries": []})

    def test_existing_unchanged_media_is_not_retroactively_rejected(self):
        old = dict(self.image, verifiedModelCodes=["LEGACY"])
        self.assertEqual(0, check_media_catalog(
            [old], self.catalog, {"entries": [copy.deepcopy(old)]}
        ))

    def test_other_brands_use_same_validation(self):
        samsung = dict(self.image, deviceId="samsung1", verifiedModelCodes=["SM-A123"])
        self.assertEqual(1, check_media_catalog([samsung], self.catalog, {"entries": []}))


if __name__ == "__main__":
    unittest.main()
