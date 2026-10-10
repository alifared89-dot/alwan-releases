#!/usr/bin/env python3
"""Strict fallback for official Infinix products whose SKU equals marketing name.

Source priority: exact official hardware SKU (catalog_first.py) -> exact unique
catalog name + corroborating hardware code in ORIGINAL OFFICIAL image basename.
Reject product pages mixing X-variant codes. This stage is REVIEW-ONLY; URL
filename is evidence of a possible hardware match, NOT full human verification.
"""
from __future__ import annotations

from collections import defaultdict,Counter
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit,unquote
import argparse
import hashlib
import json
import re
import sqlite3
import time

import bot
import catalog_first as index
import multimarket_scan as mm
import evidence_cache as ec
import quality_triage as triage
from official_index import normalize_name

MAX_MODELS=20
MAX_SOURCES_PER_MODEL=2
MAX_IMAGES_PER_MODEL=4
MAX_WORKERS=3
MODEL_TOKEN=re.compile(r"(?i)(?:^|[_.-])((?:x|xb)\d{3,6}[a-z]?)(?=[_.-]|$)")
MARKET_PRIORITY=("ph","my","iq","np","ng","id")


def gallery_model_codes(urls:list[str])->set[str]:
    """Codes MUST occur as standalone tokens in official image basenames."""
    found=set()
    for url in urls:
        basename=unquote(Path(urlsplit(url).path).name).lower()
        for code in MODEL_TOKEN.findall(basename):
            found.add(code.upper())
    return found


def index_exact_names(db_path:Path)->list[dict]:
    public={x["deviceId"] for x in json.loads(
        (bot.MEDIA/"device_media_manifest.json").read_text())["entries"]}
    audit=bot.BOT/"output/selected-review-audit.json"
    staged={x["deviceId"] for x in json.loads(audit.read_text())["items"]} if audit.exists() else set()
    known=defaultdict(list)
    for device in bot.CATALOG:
        if device["deviceId"] not in public and device["deviceId"] not in staged:
            known[normalize_name(device["name"])].append(device)
    with closing(sqlite3.connect(db_path)) as conn:
        records=conn.execute("SELECT market,product_id,name,sku FROM products").fetchall()
    leads=[]
    for market,pid,name,sku in records:
        if market not in mm.MARKETS:
            continue
        if bot.match_storefront_code(sku):
            continue  # handled by strict catalog-first SKU pipeline
        compatible=known.get(normalize_name(name),[])
        if len(compatible)!=1:
            continue
        device=compatible[0]
        if len(device["modelCodes"])!=1:
            continue  # one device may have several hardware identifiers
        code=str(device["modelCodes"][0]).upper()
        if len(bot.BY_CODE.get(code,[]))!=1:
            continue
        if not re.fullmatch(r"(?:X|XB)[0-9]{3,6}[A-Z]?",code):
            continue
        leads.append({"market":market,"productId":pid,"sourceName":name,
                      "sourceSku":sku,"deviceId":device["deviceId"],
                      "name":device["name"],"expectedCode":code})
    priority={market:i for i,market in enumerate(MARKET_PRIORITY)}
    return sorted(leads,key=lambda x:(x["deviceId"],priority[x["market"]],x["productId"]))


def validate_one(lead:dict, offline:bool=False)->dict:
    row=dict(lead)
    row["reason"]="SOURCE_UNVERIFIED"
    row["images"]=[]
    row["detailCacheHit"]=False
    try:
        cached=ec.read_detail(lead["market"],lead["productId"],
                             lead["expectedCode"],lead["sourceName"])
        if cached:
            row["detailCacheHit"]=True
            page={"galleryImageUrls":cached["imageUrls"],"finalUrl":cached["pageUrl"]}
        else:
            rejected=ec.read_known_rejection(lead["market"],lead["productId"],
                                             lead["expectedCode"],lead["sourceName"])
            if rejected:
                row["reason"]="IMAGE_CODE_MISSING_OR_CONFLICTS"
                row["detailCacheHit"]=True
                row["galleryHardwareCodes"]=rejected["galleryHardwareCodes"]
                row["codeMismatchKind"]="code_absent" if not rejected["galleryHardwareCodes"] else "different_or_mixed_code"
                row["officialPageUrl"]=rejected["pageUrl"]
                return row
            if offline:
                row["reason"]="DETAIL_CACHE_MISS"
                return row
            device=bot.BY_ID[lead["deviceId"]]
            page=mm.inspect_official_detail(lead["market"],
                {"id":lead["productId"]},device,lead["expectedCode"])
        urls=page["galleryImageUrls"]
        codes=gallery_model_codes(urls)
        row["officialPageUrl"]=page["finalUrl"]
        row["galleryHardwareCodes"]=sorted(codes)
        if not urls:
            row["reason"]="NO_GALLERY"
        elif codes!={lead["expectedCode"]}:
            row["reason"]="IMAGE_CODE_MISSING_OR_CONFLICTS"
            row["codeMismatchKind"]="code_absent" if not codes else "different_or_mixed_code"
            if not row["detailCacheHit"]:
                ec.store_known_rejection(lead["market"],lead["productId"],
                                         lead["expectedCode"],lead["sourceName"],
                                         page["finalUrl"],codes)
        else:
            row["reason"]="OFFICIAL_NAME_PLUS_EXACT_IMAGE_CODE"
            row["images"]=urls
            if not row["detailCacheHit"]:
                ec.write_detail(lead["market"],lead["productId"],
                                lead["expectedCode"],lead["sourceName"],
                                page["finalUrl"],urls)
    except Exception as exc:
        row["reason"]="DETAIL_ERROR"
        row["error"]=f"{type(exc).__name__}: {str(exc)[:145]}"
    return row


def run(db_path:Path=index.DB_PATH,max_models:int=20,sources_per_model:int=2,
        images_per_model:int=3,offline:bool=False,
        device_ids:set[str]|None=None)->dict:
    if not db_path.is_file():
        raise FileNotFoundError("catalog-first.sqlite is missing: run catalog_first.py first")
    if not 1<=max_models<=MAX_MODELS or not 1<=sources_per_model<=MAX_SOURCES_PER_MODEL:
        raise ValueError("bounded sample: max 20 models, 2 sources per model")
    if not 0<=images_per_model<=MAX_IMAGES_PER_MODEL:
        raise ValueError("images_per_model must be between 0 and 4")
    start=time.monotonic()
    leads=index_exact_names(db_path)
    if device_ids is not None:
        leads=[item for item in leads if item["deviceId"] in device_ids]
    by_id=defaultdict(list)
    for item in leads:
        by_id[item["deviceId"]].append(item)
    selected=[]
    for device_id in sorted(by_id)[:max_models]:
        selected.extend(by_id[device_id][:sources_per_model])
    results=[]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures=[pool.submit(validate_one,row,offline=offline) for row in selected]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda x:(x["deviceId"],x["market"]))
    valid=defaultdict(list)
    for row in results:
        if row["reason"]=="OFFICIAL_NAME_PLUS_EXACT_IMAGE_CODE":
            valid[row["deviceId"]].append(row)
    visual=[]
    candidates=[]
    for dev_id, sources in sorted(valid.items()):
        first=sources[0]
        candidates.append({"deviceId":dev_id,"name":first["name"],
                           "modelCode":first["expectedCode"],
                           "verifiedOfficialPageSource":sources,
                           "evidenceStrength":"official_page_name_plus_model_code_in_image_filename",
                           "frontBackApproved":False,"publishable":False,
                           "images":[]})
    hashes=defaultdict(set)
    if images_per_model:
        # Each verified device fetches at most N official source assets, no
        # image-galleries for mismatched codes and no repeated URLs per device.
        downloads={}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for candidate in candidates:
                sources=candidate["verifiedOfficialPageSource"]
                chosen=sources[0]
                for gallery_index,url in enumerate(list(dict.fromkeys(chosen["images"]))[:images_per_model]):
                    job=pool.submit(ec.safe_image,url,chosen["market"],offline=offline)
                    downloads[job]=(candidate,chosen["market"],gallery_index)
            for task in as_completed(downloads):
                candidate,market,gallery_index=downloads[task]
                info,original=task.result()
                info["market"]=market
                info["galleryIndex"]=gallery_index
                if original is not None:
                    info["quality"] = triage.inspect(original, info, candidate["modelCode"])
                else:
                    info["quality"] = {"eligibleForReview":False,"reason":info.get("error","no_image"),"priority":0}
                candidate["images"].append(info)
                if info.get("sourceSha256"):
                    hashes[info["sourceSha256"]].add(candidate["deviceId"])
                if original is not None and info.get("downloadOk"):
                    prev=original.convert("RGBA");prev.thumbnail((220,210))
                    visual.append((candidate["deviceId"],gallery_index,candidate["name"]+" / "+candidate["modelCode"],prev))
    for candidate in candidates:
        candidate["images"].sort(key=lambda item:item.get("galleryIndex",0))
        candidate["qualityReviewImageIndices"]=[
            x["galleryIndex"] for x in candidate["images"]
            if x.get("quality",{}).get("eligibleForReview")
        ]
    visual.sort(key=lambda row:(row[0],row[1]))
    reasons=dict(sorted(Counter(x["reason"] for x in results).items()))
    code_mismatch_reasons=dict(sorted(Counter(x["codeMismatchKind"] for x in results
        if x.get("codeMismatchKind")).items()))
    summary={"sourceCatalogModelNames":len(by_id),"modelsSelected":len({x["deviceId"] for x in selected}),
             "officialDetailPagesExamined":len(results),"reasonCounts":reasons,
             "modelCodeMismatchReasons":code_mismatch_reasons,
             "newUniqueOfficialModelEvidenceCandidates":len(candidates),
             "originalImagesDownloaded":sum(i.get("downloadOk",False) for c in candidates for i in c["images"]),
             "downloadErrors":sum(not i.get("downloadOk",False) for c in candidates for i in c["images"]),
             "crossDeviceDuplicateSourceHashes":sum(len(x)>1 for x in hashes.values()),
             "detailCacheHits":sum(bool(x.get("detailCacheHit")) for x in results),
             "detailHttpRequests":sum(not x.get("detailCacheHit",False) and x["reason"]!="DETAIL_CACHE_MISS" for x in results),
             "imageCacheHits":sum(bool(i.get("cacheHit")) for c in candidates for i in c["images"]),
             "imageHttpRequests":sum(not i.get("cacheHit",False) and (not offline) for c in candidates for i in c["images"]),
             "qualityEligibleImages":sum(i.get("quality",{}).get("eligibleForReview",False) for c in candidates for i in c["images"]),
             "qualityEligibleDevices":sum(bool(c["qualityReviewImageIndices"]) for c in candidates),
             "frontBackApproved":0,"published":0,"elapsedSeconds":round(time.monotonic()-start,1)}
    report={"mode":"OFFICIAL_IMAGE_FILENAME_CORROBORATION_REVIEW_ONLY",
            "generatedAt":datetime.now(timezone.utc).isoformat(),
            "summary":summary,"sourceObservations":results,
            "candidatesForVisualReview":candidates,
            "notes":["No photos were published. Filename alone does not prove same color or front/back.",
                     "Conflicting/missing image model-code variants are rejected.",
                     "Original page title is checked against the exact normalized catalog name."]}
    out=bot.BOT/"output";out.mkdir(exist_ok=True)
    filename=out/"official-model-evidence.json"
    serialized=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    filename.write_text(serialized)
    mm.make_sheet([(label,photo) for _,_,label,photo in visual],out/"official-model-evidence-sheet.jpg")
    folder=out/"official-model-evidence-history";folder.mkdir(exist_ok=True)
    key=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (folder/(key+".json")).write_text(serialized)
    (folder/(key+".jpg")).write_bytes((out/"official-model-evidence-sheet.jpg").read_bytes())
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--max-models",type=int,default=20)
    parser.add_argument("--sources-per-model",type=int,default=2)
    parser.add_argument("--images",type=int,default=3)
    parser.add_argument("--offline",action="store_true",help="Only integrity checked on-disk evidence; no HTTP")
    args=parser.parse_args()
    run(max_models=args.max_models,sources_per_model=args.sources_per_model,
        images_per_model=args.images,offline=args.offline)
