#!/usr/bin/env python3
"""Atomically rebuild compatibility release metadata after payload edits."""
from __future__ import annotations
import argparse, hashlib, json, shutil, tempfile
from datetime import datetime, timezone
from pathlib import Path
import validate_release

FILES={"devices":"catalog.json","displays":"display.json","batteries":"battery.json",
       "charging":"charging.json","cameras":"camera.json","flexes":"flex.json","audio":"audio.json"}

def dump(v):
    return (json.dumps(v, ensure_ascii=False, indent=2) + "\n").encode()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("compatibility"))
    ns=ap.parse_args(); root=ns.root
    manifest=json.loads((root/"manifest.json").read_text())
    entries={e["type"]:e for e in manifest["entries"]}
    payload_bytes={t:(root/"payloads"/f).read_bytes() for t,f in FILES.items()}

    for typ,b in payload_bytes.items():
        e=entries[typ]; h=hashlib.sha256(b).hexdigest()
        e["sha256"]=h
        e["compressedBytes"]=len(b)
        e["uncompressedBytes"]=len(b)
        e["version"]=f'{e["id"]}-{h[:16]}'

    catalog_version=entries["devices"]["version"]
    for typ,e in entries.items():
        if typ=="devices":
            e.pop("catalogDependency", None)
            continue
        dep=e.setdefault("catalogDependency", {})
        dep.update({
            "catalogId":"alwan-device-catalog",
            "requiredSchemaVersion":3,
            "builtAgainstVersion":catalog_version,
        })

    manifest["manifestVersion"]=int(manifest.get("manifestVersion",0))+1
    manifest["generatedAt"]=datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00","Z")
    candidate_bytes=dump(manifest)

    with tempfile.TemporaryDirectory() as td:
        tmp=Path(td)/"compatibility"
        (tmp/"payloads").mkdir(parents=True)
        (tmp/"manifest.json").write_bytes(candidate_bytes)
        for typ,f in FILES.items():
            shutil.copy2(root/"payloads"/f, tmp/"payloads"/f)
        audit=validate_release.Audit()
        validate_release.validate(tmp, audit)
        if audit.errors:
            for row in audit.errors:
                audit.emit(row)
            raise SystemExit(
                "Refusing to rebuild metadata: payload contract validation failed."
            )

    (root/"manifest.json").write_bytes(candidate_bytes)
    payload={t:json.loads(b) for t,b in payload_bytes.items()}
    catalog=payload["devices"]
    categories={}
    for typ,name in (
        ("displays","display"),("batteries","battery"),
        ("charging","charging"),("cameras","camera"),
        ("flexes","flex"),("audio","audio"),
    ):
        c=payload[typ]; b=payload_bytes[typ]
        categories[name]={
            "sha256":hashlib.sha256(b).hexdigest(),
            "bytes":len(b),
            "records":{
                "parts":len(c["parts"]),
                "compatibilityGroups":len(c["compatibilityGroups"]),
                "evidence":len(c["evidence"]),
                "categoryFacts":len(c["categoryFacts"]),
                "compatibilityDifferences":len(c["compatibilityDifferences"]),
            },
        }

    report={
        "success":True,
        "manifestVersion":manifest["manifestVersion"],
        "manifestSha256":hashlib.sha256(candidate_bytes).hexdigest(),
        "catalog":{
            "version":entries["devices"]["version"],
            "sha256":hashlib.sha256(payload_bytes["devices"]).hexdigest(),
            "bytes":len(payload_bytes["devices"]),
            "devices":len(catalog["devices"]),
            "brands":len(catalog["brands"]),
        },
        "categories":categories,
    }
    (root/"build_report.json").write_bytes(dump(report))
    print(
        f'PASS: manifestVersion={manifest["manifestVersion"]} '
        f'catalog={catalog_version}'
    )

if __name__=="__main__":
    main()
