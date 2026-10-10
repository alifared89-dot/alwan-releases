#!/usr/bin/env python3
"""Cumulative per-device progress for Infinix image research (never publishes)."""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import datetime,timezone
import json
from pathlib import Path

import bot
from official_index import normalize_name

ROOT=bot.BOT/"output"

def main():
    catalog=bot.CATALOG
    published={x["deviceId"] for x in json.loads((bot.MEDIA/"device_media_manifest.json").read_text())["entries"]}
    auditpath=ROOT/"selected-review-audit.json"
    audit=json.loads(auditpath.read_text()) if auditpath.is_file() else {"items":[]}
    reviewed={x["deviceId"]:x for x in audit["items"]}
    checked_names=set()
    candidates={}
    run_reports=[]
    archived=ROOT/"multimarket-history"
    sources=sorted(archived.glob("*.json")) if archived.exists() else []
    latest=ROOT/"multimarket-review.json"
    sources+=[latest] if latest.is_file() else []
    seen_runs=set()
    for path in sources:
        data=json.loads(path.read_text())
        if data.get("mode")!="MULTIMARKET_READ_ONLY":
            continue
        sid=(data.get("createdAt"),tuple((q["name"],q["market"]) for q in data.get("queryDiagnostics",[])))
        if sid in seen_runs:
            continue
        seen_runs.add(sid)
        problems=[]
        for q in data.get("queryDiagnostics",[]):
            checked_names.add(normalize_name(q["name"]))
            if q["errors"]:
                problems.append({"name":q["name"],"market":q["market"],"errors":q["errors"][:3]})
        for candidate in data.get("candidatesForReview",[]):
            key=candidate["deviceId"]
            if key not in candidates or (
                len(candidate.get("sources",[]))>len(candidates[key].get("sources",[]))
            ):
                candidates[key]=candidate
        run_reports.append({"at":data["createdAt"],"models":data["summary"]["modelNamesQueried"],
                            "markets":data["summary"]["marketsQueried"],
                            "uniqueCandidates":data["summary"]["uniqueDeviceIdsMatched"],
                            "apiFailures":data["summary"]["apiFailures"],"sourceFile":path.name,
                            "exampleErrors":problems[:4]})
    families=ROOT/"family-history"
    family_files=sorted(families.glob("*.json")) if families.exists() else []
    family_latest=ROOT/"family-inventory.json"
    if family_latest.exists():
        family_files.append(family_latest)
    family_seen=set()
    for path in family_files:
        data=json.loads(path.read_text())
        if data.get("mode")!="OFFICIAL_STORE_FAMILY_INVENTORY":
            continue
        if data["createdAt"] in family_seen:
            continue
        family_seen.add(data["createdAt"])
        for candidate in data.get("newCandidatesForVisualReview",[]):
            candidates.setdefault(candidate["deviceId"],candidate)
        run_reports.append({"at":data["createdAt"],"mode":"family-index",
                            "uniqueCandidates":data["summary"]["newUniqueCatalogDeviceIds"],
                            "sourceFile":path.name,"apiFailures":len(data["queries"])-data["summary"]["successfulFamilyQueries"]})
    model_history=ROOT/"official-model-evidence-history"
    evidence_reports=sorted(model_history.glob("*.json")) if model_history.exists() else []
    evidence_latest=ROOT/"official-model-evidence.json"
    if evidence_latest.is_file():
        evidence_reports.append(evidence_latest)
    evidence_seen=set()
    for path in evidence_reports:
        data=json.loads(path.read_text())
        if data.get("mode")!="OFFICIAL_IMAGE_FILENAME_CORROBORATION_REVIEW_ONLY":
            continue
        if data["generatedAt"] in evidence_seen:
            continue
        evidence_seen.add(data["generatedAt"])
        for source in data.get("sourceObservations",[]):
            checked_names.add(normalize_name(source["name"]))
        for candidate in data.get("candidatesForVisualReview",[]):
            candidates.setdefault(candidate["deviceId"],candidate)
        run_reports.append({"at":data["generatedAt"],"mode":"official-image-filename",
                            "uniqueCandidates":data["summary"]["newUniqueOfficialModelEvidenceCandidates"],
                            "sourceFile":path.name,"rejectedPages":data["summary"]["reasonCounts"].get("IMAGE_CODE_MISSING_OR_CONFLICTS",0)})
    rows=[]
    for device in catalog:
        id_=device["deviceId"]
        if id_ in published:
            status="published"
        elif id_ in reviewed:
            status="prepared_for_review"
        elif id_ in candidates:
            status="source_candidate_not_prepared"
        elif normalize_name(device["name"]) in checked_names:
            status="searched_no_verified_device"
        else:
            status="not_yet_searched"
        rows.append({"deviceId":id_,"name":device["name"],
                     "modelCodes":device["modelCodes"],"status":status,
                     "reviewImage":reviewed.get(id_,{}).get("stagedFile"),
                     "sourceCount":len(candidates.get(id_,{}).get("sources",[]))})
    counts=dict(sorted(Counter(x["status"] for x in rows).items()))
    report={"schemaVersion":1,"brand":"Infinix","at":datetime.now(timezone.utc).isoformat(),
            "summary":{"catalogDevices":len(rows),**counts,
                       "uniqueModelsQueried":len(checked_names),
                       "historicalRunReports":len(run_reports)},
            "reports":run_reports,"perDevice":rows}
    ROOT.mkdir(exist_ok=True)
    output=ROOT/"infinix-progress.json"
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report["summary"],ensure_ascii=False))
if __name__=="__main__":
    main()
