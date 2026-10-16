import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import verify_media

def sha(data):
    return hashlib.sha256(data).hexdigest()

class FreshDeviceMediaContractTests(unittest.TestCase):
    def make_root(self, extra=False):
        td=tempfile.TemporaryDirectory()
        root=Path(td.name)
        (root/"chunks").mkdir()
        payload=b"expected"
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w",compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("phone.png",payload)
            if extra:
                z.writestr("superseded.png",b"old")
        archive=buf.getvalue()
        chunk_id="chunk-test"
        (root/"chunks"/f"{chunk_id}.zip").write_bytes(archive)
        manifest={
            "manifestVersion":1,
            "generatedAt":"2026-10-11T00:00:00Z",
            "entries":[{
                "deviceId":"dev_x","revision":"r1","view":"frontBack",
                "filename":"phone.png","chunkId":chunk_id,
                "sha256":sha(payload),"bytes":len(payload),
            }],
        }
        manifest_bytes=(json.dumps(manifest,indent=2)+"\n").encode()
        (root/"device_media_manifest.json").write_bytes(manifest_bytes)
        distribution={
            "schemaVersion":1,
            "mediaManifest":{
                "url":verify_media.MEDIA_MANIFEST_URL,
                "bytes":len(manifest_bytes),"sha256":sha(manifest_bytes),
            },
            "chunks":[{
                "chunkId":chunk_id,"url":verify_media.MEDIA_RAW_BASE+"chunks/"+chunk_id+".zip",
                "compressedBytes":len(archive),
                "uncompressedBytes":len(payload)+(3 if extra else 0),
                "sha256":sha(archive),
            }],
        }
        (root/"distribution.json").write_text(json.dumps(distribution,indent=2)+"\n")
        return td,root

    def test_rejects_invalid_revision_in_published_manifest(self):
        td, root = self.make_root()
        self.addCleanup(td.cleanup)
        manifest_file = root / "device_media_manifest.json"
        manifest = json.loads(manifest_file.read_text())
        manifest["entries"][0]["revision"] = "invalid revision"
        raw = (json.dumps(manifest, indent=2) + "\n").encode()
        manifest_file.write_bytes(raw)
        distribution_file = root / "distribution.json"
        distribution = json.loads(distribution_file.read_text())
        distribution["mediaManifest"]["bytes"] = len(raw)
        distribution["mediaManifest"]["sha256"] = sha(raw)
        distribution_file.write_text(json.dumps(distribution, indent=2) + "\n")
        with self.assertRaisesRegex(ValueError, "ALWAN-MEDIA-INVALID-REVISION"):
            verify_media.verify_media(root=root)

    def test_metadata_only_revision_fix_does_not_require_new_image_pixels(self):
        td, root = self.make_root()
        self.addCleanup(td.cleanup)
        original = json.loads((root / "device_media_manifest.json").read_text())
        new = dict(original["entries"][0], revision="corrected-r1")
        self.assertEqual(set(), verify_media.presentation_check_entries(
            [new], original, migration_mode=True,
        ))

    def test_exact_chunk_passes_fresh_device_contract(self):
        td,root=self.make_root(extra=False)
        self.addCleanup(td.cleanup)
        self.assertEqual((1,0),verify_media.verify_media(root=root))

    def test_migration_rechecks_only_changed_image_content(self):
        baseline={"entries":[{
            "deviceId":"dev_x","revision":"r1","view":"frontBack",
            "filename":"phone.png","chunkId":"old-chunk",
            "sha256":"a"*64,"bytes":10,
        }]}
        metadata_only=[dict(baseline["entries"][0],chunkId="new-chunk")]
        self.assertEqual(
            set(),
            verify_media.presentation_check_entries(
                metadata_only,baseline,migration_mode=True
            ),
        )
        content_changed=[dict(
            baseline["entries"][0],chunkId="new-chunk",
            sha256="b"*64,bytes=11
        )]
        self.assertEqual(
            {"phone.png"},
            verify_media.presentation_check_entries(
                content_changed,baseline,migration_mode=True
            ),
        )


    def test_rejects_wrong_chunk_url(self):
        td,root=self.make_root(extra=False)
        self.addCleanup(td.cleanup)
        path=root/"distribution.json"
        distribution=json.loads(path.read_text())
        distribution["chunks"][0]["url"]="https://example.com/wrong.zip"
        path.write_text(json.dumps(distribution,indent=2)+"\n")
        with self.assertRaisesRegex(ValueError,"invalid chunk URL"):
            verify_media.verify_media(root=root)

    def test_rejects_wrong_manifest_url(self):
        td,root=self.make_root(extra=False)
        self.addCleanup(td.cleanup)
        path=root/"distribution.json"
        distribution=json.loads(path.read_text())
        distribution["mediaManifest"]["url"]="https://example.com/wrong.json"
        path.write_text(json.dumps(distribution,indent=2)+"\n")
        with self.assertRaisesRegex(ValueError,"invalid media manifest URL"):
            verify_media.verify_media(root=root)

    def test_extra_superseded_file_is_rejected(self):
        td,root=self.make_root(extra=True)
        self.addCleanup(td.cleanup)
        with self.assertRaisesRegex(ValueError,"client-incompatible ZIP contents"):
            verify_media.verify_media(root=root)

if __name__=="__main__":
    unittest.main()
