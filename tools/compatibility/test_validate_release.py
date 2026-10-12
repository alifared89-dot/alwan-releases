import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import validate_release as v

TYPES={
    "devices":"catalog.json","displays":"display.json","batteries":"battery.json",
    "charging":"charging.json","cameras":"camera.json","flexes":"flex.json",
    "audio":"audio.json",
}

class ContractTests(unittest.TestCase):
    def fixture(self):
        td=tempfile.TemporaryDirectory()
        root=Path(td.name)
        (root/"payloads").mkdir()

        catalog={
            "schemaVersion":3,
            "catalogId":"alwan-device-catalog",
            "brands":[{"id":"infinix","name":"Infinix","aliases":[]}],
            "devices":[{
                "id":"dev_x1","brandId":"infinix","name":"X",
                "aliases":[],"modelCodes":["X1"],"images":[]
            }],
        }

        def empty(name):
            return {
                "schemaVersion":3,"category":name,"parts":[],
                "compatibilityGroups":[],"evidence":[],
                "categoryFacts":[],"compatibilityDifferences":[],
            }

        display=empty("display")
        display["parts"]=[{
            "id":"part_x","category":"display",
            "canonicalPartNumbers":["P1"]
        }]
        display["compatibilityGroups"]=[{
            "id":"cg_x","partId":"part_x","deviceIds":["dev_x1"]
        }]
        display["evidence"]=[{
            "id":"ev_x","compatibilityGroupId":"cg_x","sourceKey":"src_x",
            "sourceType":"partsSupplier","sourceName":"S",
            "sourceUrl":"https://example.com/x",
            "checkedAt":"2026-10-11T00:00:00Z","claim":"supports",
            "citedPartNumbers":["P1"],"citedModelCodes":["X1"],
            "notes":None,
        }]

        payload={
            "devices":catalog,"displays":display,"batteries":empty("battery"),
            "charging":empty("charging"),"cameras":empty("camera"),
            "flexes":empty("flex"),"audio":empty("audio"),
        }

        ids={
            "devices":"catalog","displays":"display","batteries":"battery",
            "charging":"charging","cameras":"camera","flexes":"flex",
            "audio":"audio",
        }
        entries=[]
        for typ,fn in TYPES.items():
            b=(json.dumps(payload[typ], ensure_ascii=False, indent=2)+"\n").encode()
            (root/"payloads"/fn).write_bytes(b)
            h=hashlib.sha256(b).hexdigest()
            entries.append({
                "id":ids[typ],"type":typ,"version":f'{ids[typ]}-{h[:16]}',
                "url":v.PAYLOAD_URL_PREFIX+fn,"sha256":h,
                "compressedBytes":len(b),"uncompressedBytes":len(b),
                "archiveFormat":"rawJson",
            })

        cv=next(e["version"] for e in entries if e["type"]=="devices")
        for e in entries:
            if e["type"]!="devices":
                e["catalogDependency"]={
                    "catalogId":"alwan-device-catalog",
                    "requiredSchemaVersion":3,
                    "builtAgainstVersion":cv,
                }

        (root/"manifest.json").write_text(json.dumps({
            "manifestVersion":1,
            "generatedAt":"2026-10-11T00:00:00Z",
            "schemaVersion":3,
            "entries":entries,
        }, indent=2)+"\n")
        return td,root

    def audit(self,root,baseline=None):
        a=v.Audit()
        v.validate(root,a,baseline_manifest=baseline)
        return a

    def mutate_display(self,root,fn):
        p=root/"payloads/display.json"
        d=json.loads(p.read_text())
        fn(d)
        b=(json.dumps(d,indent=2)+"\n").encode()
        p.write_bytes(b)
        m=json.loads((root/"manifest.json").read_text())
        e=next(x for x in m["entries"] if x["type"]=="displays")
        h=hashlib.sha256(b).hexdigest()
        e.update(
            sha256=h,compressedBytes=len(b),uncompressedBytes=len(b),
            version="display-"+h[:16],
        )
        (root/"manifest.json").write_text(json.dumps(m,indent=2)+"\n")

    def test_valid_fixture(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        self.assertEqual([],self.audit(r).errors)

    def test_rejects_part_evidence_mismatch(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        self.mutate_display(
            r,lambda d:d["evidence"][0].update(citedPartNumbers=["WRONG"])
        )
        self.assertIn(
            "ALWAN-DATA-EVIDENCE-PART",
            {x["code"] for x in self.audit(r).errors},
        )

    def test_rejects_model_evidence_mismatch(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        self.mutate_display(
            r,lambda d:d["evidence"][0].update(citedModelCodes=["Y9"])
        )
        self.assertIn(
            "ALWAN-DATA-EVIDENCE-MODEL",
            {x["code"] for x in self.audit(r).errors},
        )

    def test_rejects_stale_catalog_dependency(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        m=json.loads((r/"manifest.json").read_text())
        next(
            x for x in m["entries"] if x["type"]=="displays"
        )["catalogDependency"]["builtAgainstVersion"]="catalog-old"
        (r/"manifest.json").write_text(json.dumps(m,indent=2)+"\n")
        self.assertIn(
            "ALWAN-DATA-CATALOG-VERSION",
            {x["code"] for x in self.audit(r).errors},
        )


    def test_rejects_payload_url_mismatch(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        m=json.loads((r/"manifest.json").read_text())
        next(x for x in m["entries"] if x["type"]=="displays")["url"]="https://example.com/wrong.json"
        (r/"manifest.json").write_text(json.dumps(m,indent=2)+"\n")
        self.assertIn(
            "ALWAN-DATA-PAYLOAD-URL",
            {x["code"] for x in self.audit(r).errors},
        )

    def test_rejects_uncovered_group_device(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        catalog_path=r/"payloads/catalog.json"
        catalog=json.loads(catalog_path.read_text())
        catalog["devices"].append({
            "id":"dev_x2","brandId":"infinix","name":"Y",
            "aliases":[],"modelCodes":["X2"],"images":[]
        })
        b=(json.dumps(catalog,indent=2)+"\n").encode()
        catalog_path.write_bytes(b)
        m=json.loads((r/"manifest.json").read_text())
        ce=next(x for x in m["entries"] if x["type"]=="devices")
        h=hashlib.sha256(b).hexdigest()
        ce.update(
            sha256=h,compressedBytes=len(b),uncompressedBytes=len(b),
            version="catalog-"+h[:16],
        )
        for e in m["entries"]:
            if e["type"]!="devices":
                e["catalogDependency"]["builtAgainstVersion"]=ce["version"]
        (r/"manifest.json").write_text(json.dumps(m,indent=2)+"\n")
        self.mutate_display(
            r,
            lambda d:d["compatibilityGroups"][0]["deviceIds"].append("dev_x2"),
        )
        self.assertIn(
            "ALWAN-DATA-EVIDENCE-COVERAGE",
            {x["code"] for x in self.audit(r).errors},
        )

    def test_rejects_hash_mismatch(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        m=json.loads((r/"manifest.json").read_text())
        next(x for x in m["entries"] if x["type"]=="displays")["sha256"]="0"*64
        (r/"manifest.json").write_text(json.dumps(m,indent=2)+"\n")
        self.assertIn(
            "ALWAN-DATA-HASH",
            {x["code"] for x in self.audit(r).errors},
        )

    def test_rejects_missing_version(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        p=r/"manifest.json"
        m=json.loads(p.read_text())
        m.pop("manifestVersion")
        p.write_text(json.dumps(m,indent=2)+"\n")
        self.assertIn("ALWAN-DATA-MANIFEST-VERSION",
                      {x["code"] for x in self.audit(r).errors})

    def test_rejects_unchanged_version_when_payload_changes(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        baseline=json.loads((r/"manifest.json").read_text())
        self.mutate_display(r,lambda x:x["parts"][0]["canonicalPartNumbers"].append("P2"))
        self.assertIn("ALWAN-DATA-VERSION-NOT-ADVANCED",
                      {x["code"] for x in self.audit(r,baseline).errors})

    def test_accepts_advanced_version_when_payload_changes(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        p=r/"manifest.json"
        baseline=json.loads(p.read_text())
        self.mutate_display(r,lambda x:x["parts"][0]["canonicalPartNumbers"].append("P2"))
        m=json.loads(p.read_text())
        m["manifestVersion"]+=1
        p.write_text(json.dumps(m,indent=2)+"\n")
        self.assertEqual([],self.audit(r,baseline).errors)

    def test_rejects_version_rollback_without_payload_change(self):
        td,r=self.fixture()
        self.addCleanup(td.cleanup)
        p=r/"manifest.json"
        baseline=json.loads(p.read_text())
        baseline["manifestVersion"]=2
        self.assertIn("ALWAN-DATA-VERSION-REGRESSION",
                      {x["code"] for x in self.audit(r,baseline).errors})

if __name__=="__main__":
    unittest.main()
