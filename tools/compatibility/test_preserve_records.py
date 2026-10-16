import json
import tempfile
import unittest
from pathlib import Path

from preserve_records import FILES, compare


class ProductionRecordPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = Path(self.temp.name) / "old"
        self.new = Path(self.temp.name) / "new"
        for root in (self.old, self.new):
            folder = root / "payloads"
            folder.mkdir(parents=True)
            for name, collections in FILES.items():
                payload = {section: [] for section in collections}
                if name == "catalog.json":
                    payload["brands"] = [{"id": "infinix", "name": "Infinix"}]
                    payload["devices"] = [
                        {"id": "phone1", "brandId": "infinix",
                         "modelCodes": ["X1234"]}
                    ]
                if name == "display.json":
                    payload["parts"] = [{"id": "part1", "description": "old"}]
                    payload["categoryFacts"] = [
                        {"deviceId": "phone1", "category": "display", "size": 6.5}
                    ]
                (folder / name).write_text(json.dumps(payload))

    def read(self, root, name):
        return json.loads((root / "payloads" / name).read_text())

    def write(self, root, name, payload):
        (root / "payloads" / name).write_text(json.dumps(payload))

    def test_unmodified_payloads_pass(self):
        self.assertEqual([], compare(self.old, self.new))

    def test_additional_brand_device_and_part_pass(self):
        catalog = self.read(self.new, "catalog.json")
        catalog["brands"].append({"id": "samsung", "name": "Samsung"})
        catalog["devices"].append({"id": "phone2", "brandId": "samsung"})
        self.write(self.new, "catalog.json", catalog)
        display = self.read(self.new, "display.json")
        display["parts"].append({"id": "part2"})
        self.write(self.new, "display.json", display)
        self.assertEqual([], compare(self.old, self.new))

    def test_in_place_correction_passes(self):
        display = self.read(self.new, "display.json")
        display["parts"][0]["description"] = "corrected"
        self.write(self.new, "display.json", display)
        self.assertEqual([], compare(self.old, self.new))

    def test_exact_four_legacy_difference_id_repair_preserves_records(self):
        from preserve_records import APPROVED_DISPLAY_DIFFERENCE_ID_REPAIRS
        first_old, first_new = next(iter(APPROVED_DISPLAY_DIFFERENCE_ID_REPAIRS.items()))
        row = {"id": first_old, "partId": "part1", "deviceId": "dev_x1",
               "description": "commercial replacement is unconfirmed"}
        previous = self.read(self.old, "display.json")
        previous["compatibilityDifferences"].append(row)
        self.write(self.old, "display.json", previous)
        current = self.read(self.new, "display.json")
        current["compatibilityDifferences"].append({**row, "id": first_new})
        self.write(self.new, "display.json", current)
        self.assertEqual([], compare(self.old, self.new))

        # Replacing any content while renaming is still forbidden.
        current["compatibilityDifferences"][0]["description"] = "not the same"
        self.write(self.new, "display.json", current)
        self.assertIn("ALWAN-DATA-RECORD-REMOVED", " ".join(compare(self.old, self.new)))

    def test_other_difference_id_replacements_still_blocked(self):
        previous = self.read(self.old, "display.json")
        previous["compatibilityDifferences"].append({"id": "some-existing-id"})
        self.write(self.old, "display.json", previous)
        current = self.read(self.new, "display.json")
        current["compatibilityDifferences"].append({"id": "new-unapproved-id"})
        self.write(self.new, "display.json", current)
        self.assertIn("ALWAN-DATA-RECORD-REMOVED", " ".join(compare(self.old, self.new)))

    def test_device_deletion_rejected(self):
        catalog = self.read(self.new, "catalog.json")
        catalog["devices"].clear()
        self.write(self.new, "catalog.json", catalog)
        self.assertIn("ALWAN-DATA-RECORD-REMOVED", " ".join(compare(self.old, self.new)))

    def test_part_deletion_rejected(self):
        display = self.read(self.new, "display.json")
        display["parts"].clear()
        self.write(self.new, "display.json", display)
        self.assertIn("ALWAN-DATA-RECORD-REMOVED", " ".join(compare(self.old, self.new)))

    def test_facts_deletion_rejected(self):
        display = self.read(self.new, "display.json")
        display["categoryFacts"].clear()
        self.write(self.new, "display.json", display)
        self.assertIn("ALWAN-DATA-RECORD-REMOVED", " ".join(compare(self.old, self.new)))

    def test_missing_payload_rejected(self):
        (self.new / "payloads" / "audio.json").unlink()
        self.assertIn("ALWAN-DATA-PAYLOAD-REMOVED", " ".join(compare(self.old, self.new)))


if __name__ == "__main__":
    unittest.main()
