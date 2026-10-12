#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re, sys
from datetime import datetime
from pathlib import Path

TYPE_FILES={
 "devices":"catalog.json","displays":"display.json","batteries":"battery.json",
 "charging":"charging.json","cameras":"camera.json","flexes":"flex.json","audio":"audio.json",
}
TYPE_CATEGORY={"displays":"display","batteries":"battery","charging":"charging",
               "cameras":"camera","flexes":"flex","audio":"audio"}
PAYLOAD_URL_PREFIX=(
    "https://raw.githubusercontent.com/alifared89-dot/"
    "alwan-releases/main/compatibility/payloads/"
)
STABLE=re.compile(r"^[A-Za-z0-9._-]+$")
def norm_model(s): return re.sub(r"[^A-Za-z0-9]","",str(s)).lower()
def load(path):
    try: return json.loads(path.read_text())
    except Exception as e: raise ValueError(f"{path}: invalid JSON: {e}")

class Audit:
    def __init__(self): self.errors=[]; self.warnings=[]
    def err(self,code,path,msg,fix=None):
        row={"severity":"error","code":code,"path":path,"message":msg}
        if fix: row["fix"]=fix
        self.errors.append(row)
    def warn(self,code,path,msg): self.warnings.append({"severity":"warning","code":code,"path":path,"message":msg})
    def emit(self,row):
        message=f"[{row['code']}] {row['path']}: {row['message']}"
        if row.get("fix"): message+=f" | FIX: {row['fix']}"
        print(message)
        if os.getenv("GITHUB_ACTIONS")=="true":
            print(f"::error title={row['code']}::{message}")

def validate(root:Path,a:Audit,baseline_manifest:dict|None=None):
    mfpath=root/"manifest.json"; manifest=load(mfpath)
    version=manifest.get("manifestVersion")
    if type(version) is not int or version<1:
        a.err("ALWAN-DATA-MANIFEST-VERSION","manifest.json",
              "manifestVersion must be a positive integer")
    if baseline_manifest is not None:
        previous=baseline_manifest.get("manifestVersion")
        if type(previous) is not int or previous<1:
            a.err("ALWAN-DATA-BASELINE-VERSION","manifest.json",
                  "previous production manifestVersion is invalid")
        elif type(version) is int:
            if version<previous:
                a.err("ALWAN-DATA-VERSION-REGRESSION","manifest.json",
                      f"manifestVersion decreased from {previous} to {version}")
            elif manifest.get("entries")!=baseline_manifest.get("entries") and version<=previous:
                a.err("ALWAN-DATA-VERSION-NOT-ADVANCED","manifest.json",
                      "dataset metadata changed without increasing manifestVersion",
                      "run tools/compatibility/rebuild_release.py before publishing")
    if manifest.get("schemaVersion")!=3:
        a.err("ALWAN-DATA-MANIFEST-SCHEMA","manifest.json","schemaVersion must be 3")
    try: datetime.fromisoformat(str(manifest.get("generatedAt","")).replace("Z","+00:00"))
    except: a.err("ALWAN-DATA-MANIFEST-TIME","manifest.json","generatedAt must be ISO-8601")
    entries=manifest.get("entries")
    if not isinstance(entries,list) or not entries:
        a.err("ALWAN-DATA-MANIFEST-ENTRIES","manifest.json","entries must be a non-empty list"); return {}
    ids=[e.get("id") for e in entries if isinstance(e,dict)]
    if len(ids)!=len(set(ids)): a.err("ALWAN-DATA-MANIFEST-DUPLICATE","manifest.json","duplicate entry id")
    by_type={}
    payloads={}
    for i,e in enumerate(entries):
        p=f"manifest.json#/entries/{i}"
        if not isinstance(e,dict): a.err("ALWAN-DATA-MANIFEST-ENTRY",p,"entry must be an object"); continue
        typ=e.get("type")
        if typ not in TYPE_FILES:
            a.err("ALWAN-DATA-TYPE",p,f"unsupported type {typ!r}"); continue
        if typ in by_type: a.err("ALWAN-DATA-TYPE-DUPLICATE",p,f"duplicate dataset type {typ}")
        by_type[typ]=e
        expected_url=PAYLOAD_URL_PREFIX+TYPE_FILES[typ]
        if e.get("url")!=expected_url:
            a.err(
                "ALWAN-DATA-PAYLOAD-URL",p,
                f"url must be {expected_url!r}; got {e.get('url')!r}",
                "use the canonical main-branch raw payload URL",
            )
        if e.get("archiveFormat")!="rawJson":
            a.err(
                "ALWAN-DATA-ARCHIVE-FORMAT",p,
                f"archiveFormat must be 'rawJson'; got {e.get('archiveFormat')!r}",
            )
        f=root/"payloads"/TYPE_FILES[typ]
        if not f.exists(): a.err("ALWAN-DATA-PAYLOAD-MISSING",str(f),f"payload for {typ} is missing"); continue
        b=f.read_bytes(); payloads[typ]=load(f)
        sha=hashlib.sha256(b).hexdigest()
        if e.get("sha256")!=sha: a.err("ALWAN-DATA-HASH",p,f"sha256 mismatch for {TYPE_FILES[typ]}","rebuild manifest metadata after changing payload")
        if e.get("compressedBytes")!=len(b) or e.get("uncompressedBytes")!=len(b):
            a.err("ALWAN-DATA-SIZE",p,f"byte size mismatch for {TYPE_FILES[typ]}","rebuild manifest metadata after changing payload")
        expected=f"{e.get('id')}-{sha[:16]}"
        if e.get("version")!=expected:
            a.err("ALWAN-DATA-VERSION",p,f"version must be {expected}","derive version from payload SHA-256")
    required=set(TYPE_FILES)
    if set(by_type)!=required:
        a.err("ALWAN-DATA-MANIFEST-COVERAGE","manifest.json",f"types must be exactly {sorted(required)}; got {sorted(by_type)}")
    catalog=payloads.get("devices")
    if not isinstance(catalog,dict): return payloads
    if catalog.get("schemaVersion")!=3: a.err("ALWAN-DATA-CATALOG-SCHEMA","payloads/catalog.json","schemaVersion must be 3")
    if catalog.get("catalogId")!="alwan-device-catalog": a.err("ALWAN-DATA-CATALOG-ID","payloads/catalog.json","catalogId must be alwan-device-catalog")
    brands=catalog.get("brands",[]); devices=catalog.get("devices",[])
    brand_ids=[]; dev_ids=[]; devmap={}
    for i,b in enumerate(brands):
        bid=b.get("id") if isinstance(b,dict) else None
        if not isinstance(bid,str) or not bid or not STABLE.fullmatch(bid): a.err("ALWAN-DATA-BRAND-ID",f"payloads/catalog.json#/brands/{i}",f"invalid brand id {bid!r}")
        brand_ids.append(bid)
    if len(brand_ids)!=len(set(brand_ids)): a.err("ALWAN-DATA-BRAND-DUPLICATE","payloads/catalog.json","duplicate brand id")
    for i,d in enumerate(devices):
        did=d.get("id") if isinstance(d,dict) else None
        path=f"payloads/catalog.json#/devices/{i}"
        if not isinstance(did,str) or not did or not STABLE.fullmatch(did): a.err("ALWAN-DATA-DEVICE-ID",path,f"invalid device id {did!r}")
        dev_ids.append(did)
        if isinstance(did,str): devmap[did]=d
        if isinstance(d,dict) and d.get("brandId") not in set(brand_ids): a.err("ALWAN-DATA-DEVICE-BRAND",path,f"unknown brandId {d.get('brandId')!r}")
        codes=d.get("modelCodes") if isinstance(d,dict) else None
        if not isinstance(codes,list) or not codes or any(not isinstance(x,str) or not x.strip() for x in codes):
            a.err("ALWAN-DATA-MODEL-CODES",path,"modelCodes must be a non-empty list of non-empty strings")
    if len(dev_ids)!=len(set(dev_ids)): a.err("ALWAN-DATA-DEVICE-DUPLICATE","payloads/catalog.json","duplicate device id")
    catalog_version=(by_type.get("devices") or {}).get("version")
    for typ,catname in TYPE_CATEGORY.items():
        e=by_type.get(typ); c=payloads.get(typ)
        if not isinstance(c,dict) or not e: continue
        base=f"payloads/{TYPE_FILES[typ]}"
        dep=e.get("catalogDependency")
        if not isinstance(dep,dict):
            a.err("ALWAN-DATA-CATALOG-DEPENDENCY",f"manifest:{e.get('id')}","category requires catalogDependency")
        else:
            if dep.get("catalogId")!="alwan-device-catalog" or dep.get("requiredSchemaVersion")!=3:
                a.err("ALWAN-DATA-CATALOG-DEPENDENCY",f"manifest:{e.get('id')}","catalog dependency id/schema mismatch")
            if dep.get("builtAgainstVersion")!=catalog_version:
                a.err("ALWAN-DATA-CATALOG-VERSION",f"manifest:{e.get('id')}",
                      f"builtAgainstVersion={dep.get('builtAgainstVersion')!r} but current catalog={catalog_version!r}",
                      "validate against current catalog and rebuild manifest metadata")
        if c.get("schemaVersion")!=3: a.err("ALWAN-DATA-CATEGORY-SCHEMA",base,"schemaVersion must be 3")
        if c.get("category")!=catname: a.err("ALWAN-DATA-CATEGORY-NAME",base,f"category must be {catname}")
        for key in ("parts","compatibilityGroups","evidence","categoryFacts","compatibilityDifferences"):
            if not isinstance(c.get(key),list): a.err("ALWAN-DATA-COLLECTION",base,f"{key} must be a list")
        parts=c.get("parts",[]) if isinstance(c.get("parts"),list) else []
        groups=c.get("compatibilityGroups",[]) if isinstance(c.get("compatibilityGroups"),list) else []
        evidence=c.get("evidence",[]) if isinstance(c.get("evidence"),list) else []
        facts=c.get("categoryFacts",[]) if isinstance(c.get("categoryFacts"),list) else []
        diffs=c.get("compatibilityDifferences",[]) if isinstance(c.get("compatibilityDifferences"),list) else []
        pmap={}; gmap={}
        for i,p in enumerate(parts):
            pid=p.get("id") if isinstance(p,dict) else None; path=f"{base}#/parts/{i}"
            if pid in pmap: a.err("ALWAN-DATA-PART-DUPLICATE",path,f"duplicate part id {pid}")
            if isinstance(pid,str): pmap[pid]=p
            if not isinstance(pid,str) or not STABLE.fullmatch(pid): a.err("ALWAN-DATA-PART-ID",path,f"invalid part id {pid!r}")
            if isinstance(p,dict) and str(p.get("category","")).lower()!=catname: a.err("ALWAN-DATA-PART-CATEGORY",path,f"part category must be {catname}")
            nums=p.get("canonicalPartNumbers") if isinstance(p,dict) else None
            if not isinstance(nums,list) or not nums or any(not isinstance(x,str) or not x.strip() for x in nums):
                a.err("ALWAN-DATA-PART-NUMBERS",path,"canonicalPartNumbers must be non-empty")
            elif len(nums)!=len(set(nums)): a.err("ALWAN-DATA-PART-NUMBERS-DUPLICATE",path,"duplicate canonicalPartNumbers")
        for i,g in enumerate(groups):
            gid=g.get("id") if isinstance(g,dict) else None; path=f"{base}#/compatibilityGroups/{i}"
            if gid in gmap: a.err("ALWAN-DATA-GROUP-DUPLICATE",path,f"duplicate group id {gid}")
            if isinstance(gid,str): gmap[gid]=g
            if not isinstance(gid,str) or not STABLE.fullmatch(gid): a.err("ALWAN-DATA-GROUP-ID",path,f"invalid group id {gid!r}")
            if not isinstance(g,dict) or g.get("partId") not in pmap: a.err("ALWAN-DATA-GROUP-PART",path,f"unknown partId {g.get('partId') if isinstance(g,dict) else None!r}")
            ds=g.get("deviceIds") if isinstance(g,dict) else None
            if not isinstance(ds,list) or not ds: a.err("ALWAN-DATA-GROUP-DEVICES",path,"deviceIds must be non-empty")
            else:
                if len(ds)!=len(set(ds)): a.err("ALWAN-DATA-GROUP-DEVICE-DUPLICATE",path,"duplicate deviceIds")
                for did in ds:
                    if did not in devmap: a.err("ALWAN-DATA-GROUP-DEVICE",path,f"device {did!r} is not in catalog")
        evseen=set()
        for i,ev in enumerate(evidence):
            path=f"{base}#/evidence/{i}"
            evid=ev.get("id") if isinstance(ev,dict) else None
            if evid in evseen: a.err("ALWAN-DATA-EVIDENCE-DUPLICATE",path,f"duplicate evidence id {evid}")
            evseen.add(evid)
            g=gmap.get(ev.get("compatibilityGroupId")) if isinstance(ev,dict) else None
            if not g: a.err("ALWAN-DATA-EVIDENCE-GROUP",path,f"{evid}: unknown compatibilityGroupId"); continue
            p=pmap.get(g.get("partId"))
            cited=ev.get("citedPartNumbers") if isinstance(ev,dict) else None
            canon=p.get("canonicalPartNumbers",[]) if p else []
            if not isinstance(cited,list) or not cited:
                a.err("ALWAN-DATA-EVIDENCE-PART",path,f"{evid}: citedPartNumbers must be non-empty")
            else:
                canon_norm={str(x).strip().lower() for x in canon}
                if not any(str(x).strip().lower() in canon_norm for x in cited):
                    a.err("ALWAN-DATA-EVIDENCE-PART",path,
                          f"{evid}: citedPartNumbers={cited} do not match part {g.get('partId')} canonicalPartNumbers={canon}",
                          "put the evidence on the correct part, or add the verified supplier identifier to that same part")
            cited_models=ev.get("citedModelCodes") if isinstance(ev,dict) else None
            if not isinstance(cited_models,list) or not cited_models:
                a.err("ALWAN-DATA-EVIDENCE-MODEL",path,f"{evid}: citedModelCodes must be non-empty")
            else:
                cm={norm_model(x) for x in cited_models if norm_model(x)}
                ok=False
                for did in g.get("deviceIds",[]):
                    d=devmap.get(did)
                    if d and any(norm_model(x) in cm for x in d.get("modelCodes",[])): ok=True; break
                if not ok: a.err("ALWAN-DATA-EVIDENCE-MODEL",path,f"{evid}: no cited model code matches any device in group {g.get('id')}")
        support_by_group={}
        for ev in evidence:
            if isinstance(ev,dict) and ev.get("claim")=="supports":
                support_by_group.setdefault(
                    ev.get("compatibilityGroupId"),[]
                ).append(ev)
        for i,g in enumerate(groups):
            if not isinstance(g,dict):
                continue
            path=f"{base}#/compatibilityGroups/{i}"
            cited_models={
                norm_model(code)
                for ev in support_by_group.get(g.get("id"),[])
                for code in ev.get("citedModelCodes",[])
                if norm_model(code)
            }
            uncovered=[]
            for device_id in g.get("deviceIds",[]):
                device=devmap.get(device_id)
                if device is None:
                    continue
                if not any(
                    norm_model(code) in cited_models
                    for code in device.get("modelCodes",[])
                ):
                    uncovered.append({
                        "deviceId":device_id,
                        "modelCodes":device.get("modelCodes",[]),
                    })
            if uncovered:
                a.err(
                    "ALWAN-DATA-EVIDENCE-COVERAGE",path,
                    f"group {g.get('id')} has devices without supporting "
                    f"model-code evidence: {uncovered}",
                    "add verified supports evidence for every grouped device "
                    "or remove unsupported devices from the group",
                )
        factkeys=set()
        for i,f in enumerate(facts):
            path=f"{base}#/categoryFacts/{i}"; did=f.get("deviceId") if isinstance(f,dict) else None
            if did not in devmap: a.err("ALWAN-DATA-FACT-DEVICE",path,f"unknown device {did!r}")
            if isinstance(f,dict) and str(f.get("category","")).lower()!=catname: a.err("ALWAN-DATA-FACT-CATEGORY",path,f"category must be {catname}")
            key=(did,str(f.get("category","")).lower()) if isinstance(f,dict) else (did,"")
            if key in factkeys: a.err("ALWAN-DATA-FACT-DUPLICATE",path,f"duplicate facts for {key}")
            factkeys.add(key)
        diffseen=set()
        for i,d in enumerate(diffs):
            path=f"{base}#/compatibilityDifferences/{i}"; did=d.get("id") if isinstance(d,dict) else None
            if did in diffseen: a.err("ALWAN-DATA-DIFF-DUPLICATE",path,f"duplicate difference id {did}")
            diffseen.add(did)
            pid=d.get("partId") if isinstance(d,dict) else None; device=d.get("deviceId") if isinstance(d,dict) else None
            if pid not in pmap: a.err("ALWAN-DATA-DIFF-PART",path,f"unknown part {pid!r}")
            if device not in devmap: a.err("ALWAN-DATA-DIFF-DEVICE",path,f"unknown device {device!r}")
            if not any(g.get("partId")==pid and device in g.get("deviceIds",[]) for g in groups):
                a.err("ALWAN-DATA-DIFF-RELATION",path,f"difference {did} has no matching group relationship")
    return payloads

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,default=Path("compatibility")); ap.add_argument("--report",type=Path)
    ap.add_argument("--baseline-manifest",type=Path)
    ns=ap.parse_args(); a=Audit()
    try: validate(ns.root,a,load(ns.baseline_manifest) if ns.baseline_manifest else None)
    except Exception as e: a.err("ALWAN-DATA-VALIDATOR",str(ns.root),str(e))
    report={"success":not a.errors,"errors":a.errors,"warnings":a.warnings,
            "summary":{"errors":len(a.errors),"warnings":len(a.warnings)}}
    if ns.report:
        ns.report.parent.mkdir(parents=True,exist_ok=True)
        ns.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    for row in a.errors: a.emit(row)
    print(json.dumps(report["summary"],ensure_ascii=False))
    raise SystemExit(0 if not a.errors else 1)
if __name__=="__main__": main()
