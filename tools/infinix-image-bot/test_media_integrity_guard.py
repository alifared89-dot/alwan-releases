import copy
import unittest
import media_integrity_guard as guard


class MediaIntegrityGuardTests(unittest.TestCase):
    def setUp(self):
        self.old_m = {"manifestVersion": 15, "entries": [
            {"deviceId":"d1","revision":"r1","view":"frontBack","filename":"a.png","chunkId":"c1"}
        ]}
        self.old_d = {"schemaVersion":1,"mediaManifest":{"url":"stable"},"chunks":[
            {"chunkId":"c1","url":"u1","sha256":"a","compressedBytes":1,"uncompressedBytes":1}
        ]}

    def test_normal_append_keeps_old_records_immutable(self):
        new_m=copy.deepcopy(self.old_m)
        new_m["manifestVersion"]=16
        new_m["entries"].append(
            {"deviceId":"d2","revision":"r1","view":"frontBack","filename":"b.png","chunkId":"c2"}
        )
        new_d=copy.deepcopy(self.old_d)
        new_d["chunks"].append(
            {"chunkId":"c2","url":"u2","sha256":"b","compressedBytes":1,"uncompressedBytes":1}
        )
        result=guard.guard(self.old_m,self.old_d,new_m,new_d,base_commit="abc")
        self.assertFalse(result["migrationMode"])

    def test_normal_rewrite_is_rejected(self):
        new_m=copy.deepcopy(self.old_m)
        new_m["manifestVersion"]=16
        new_m["entries"][0]["filename"]="a.webp"
        with self.assertRaisesRegex(ValueError,"immutable published media"):
            guard.guard(self.old_m,self.old_d,new_m,self.old_d,base_commit="abc")

    def test_explicit_migration_can_rewrite_entries_and_chunks(self):
        new_m=copy.deepcopy(self.old_m)
        new_m["manifestVersion"]=16
        new_m["entries"][0].update(filename="a.webp",chunkId="c2")
        new_d=copy.deepcopy(self.old_d)
        new_d["chunks"]=[{"chunkId":"c2","url":"u2","sha256":"b",
                           "compressedBytes":1,"uncompressedBytes":1}]
        plan={"schemaVersion":1,"mode":"intentional-media-migration",
              "baseCommit":"abc","targetManifestVersion":16,
              "reason":"Convert published media from PNG to WebP safely",
              "allow":{"entryRewrite":True,"chunkRewrite":True}}
        result=guard.guard(self.old_m,self.old_d,new_m,new_d,
                           base_commit="abc",migration_plan=plan)
        self.assertTrue(result["migrationMode"])

    def test_stale_migration_plan_is_rejected(self):
        new_m=copy.deepcopy(self.old_m)
        new_m["manifestVersion"]=16
        plan={"schemaVersion":1,"mode":"intentional-media-migration",
              "baseCommit":"old","targetManifestVersion":16,
              "reason":"Intentional controlled format migration",
              "allow":{"entryRewrite":True}}
        with self.assertRaisesRegex(ValueError,"stale"):
            guard.guard(self.old_m,self.old_d,new_m,self.old_d,
                        base_commit="abc",migration_plan=plan)



    def test_rejects_append_without_manifest_version_increment(self):
        new_m=copy.deepcopy(self.old_m)
        new_m["entries"].append(
            {"deviceId":"d2","revision":"r1","view":"frontBack","filename":"b.png","chunkId":"c2"}
        )
        with self.assertRaisesRegex(ValueError,"ALWAN-MEDIA-VERSION-NOT-ADVANCED"):
            guard.guard(self.old_m,self.old_d,new_m,self.old_d,base_commit="abc")

    def test_rejects_version_rollback(self):
        new_m=copy.deepcopy(self.old_m)
        new_m["manifestVersion"]=14
        with self.assertRaisesRegex(ValueError,"ALWAN-MEDIA-VERSION-ROLLBACK"):
            guard.guard(self.old_m,self.old_d,new_m,self.old_d,base_commit="abc")

    def test_rejects_invalid_version(self):
        new_m=copy.deepcopy(self.old_m)
        new_m["manifestVersion"]=None
        with self.assertRaisesRegex(ValueError,"ALWAN-MEDIA-VERSION-INVALID"):
            guard.guard(self.old_m,self.old_d,new_m,self.old_d,base_commit="abc")

    def test_rejects_data_removal_even_with_migration_permission(self):
        new_m=copy.deepcopy(self.old_m)
        new_m.update(manifestVersion=16,entries=[])
        plan={"schemaVersion":1,"mode":"intentional-media-migration",
              "baseCommit":"abc","targetManifestVersion":16,
              "reason":"Explicit migration cannot remove published image data",
              "allow":{"entryRewrite":True,"chunkRewrite":True}}
        with self.assertRaisesRegex(ValueError,"previously published media entries removed"):
            guard.guard(self.old_m,self.old_d,new_m,self.old_d,
                        base_commit="abc",migration_plan=plan)

if __name__=="__main__":
    unittest.main()