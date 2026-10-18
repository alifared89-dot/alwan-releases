#!/usr/bin/env python3
"""Cumulative per-device progress for Infinix image research (never publishes)."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

import bot
import github_manifest_guard
from official_index import normalize_name

ROOT = bot.BOT / "output"


def current_published_manifest(*, opener=None) -> dict:
    """Read ONLY the GitHub main device-media manifest; never trust a stale local copy.

    Fail closed on network errors, redirects, malformed responses, or duplicate IDs.
    This function has no GitHub write permissions and creates no files.
    """
    url = github_manifest_guard.API
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Alwan-Infinix-Progress-ReadOnly/1.0",
    })
    fetch = opener or urllib.request.urlopen
    with fetch(request, timeout=15) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("live GitHub publication manifest endpoint changed")
        data = response.read(github_manifest_guard.MAX_REPLY_BYTES + 1)
    if len(data) > github_manifest_guard.MAX_REPLY_BYTES:
        raise ValueError("live GitHub manifest API response too large")
    document = json.loads(data)
    if (document.get("type") != "file"
            or document.get("path") != github_manifest_guard.PATH
            or document.get("encoding") != "base64"):
        raise ValueError("unexpected GitHub manifest response")
    payload = base64.b64decode(document["content"])
    if len(payload) > github_manifest_guard.MAX_REPLY_BYTES:
        raise ValueError("live GitHub manifest content too large")
    manifest = json.loads(payload)
    version = manifest.get("manifestVersion")
    entries = manifest.get("entries")
    if type(version) is not int or version < 1 or not isinstance(entries, list):
        raise ValueError("invalid live GitHub publication manifest")
    ids = []
    for record in entries:
        device_id = record.get("deviceId") if isinstance(record, dict) else None
        if not isinstance(device_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", device_id):
            raise ValueError("invalid live GitHub published device ID")
        ids.append(device_id)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate published device IDs in live GitHub manifest")
    return {
        "manifestVersion": version,
        "deviceIds": frozenset(ids),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "source": url,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }


def publication_coverage(catalog: list[dict], publication: dict) -> dict:
    """Recompute publication coverage; never substitute reviewed research for publication."""
    catalog_ids = [row["deviceId"] for row in catalog]
    if len(catalog_ids) != len(set(catalog_ids)):
        raise ValueError("duplicate Infinix catalog device IDs")
    published_ids = publication["deviceIds"]
    count = len(set(catalog_ids) & published_ids)
    return {
        "manifestVersion": publication["manifestVersion"],
        "publishedAllBrands": len(published_ids),
        "publishedInfinix": count,
        "remainingUnpublishedInfinix": len(catalog_ids) - count,
    }

def main():
    catalog=bot.CATALOG
    publication = current_published_manifest()
    published = publication["deviceIds"]
    coverage = publication_coverage(catalog, publication)
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
            "publicationSource":{"url":publication["source"],
                                 "manifestVersion":publication["manifestVersion"],
                                 "manifestSha256":publication["sha256"],
                                 "fetchedAt":publication["fetchedAt"],
                                 "remoteMainVerified":True,
                                 "localManifestUsed":False},
            "summary":{"catalogDevices":len(rows),
                       "published":coverage["publishedInfinix"],
                       "remainingUnpublished":coverage["remainingUnpublishedInfinix"],
                       "publishedAllBrands":coverage["publishedAllBrands"],
                       "manifestVersion":coverage["manifestVersion"],
                       **{k:v for k,v in counts.items() if k != "published"},
                       "uniqueModelsQueried":len(checked_names),
                       "historicalRunReports":len(run_reports)},
            "reports":run_reports,"perDevice":rows}
    ROOT.mkdir(exist_ok=True)
    output=ROOT/"infinix-progress.json"
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report["summary"],ensure_ascii=False))
if __name__=="__main__":
    main()
