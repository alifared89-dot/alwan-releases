#!/usr/bin/env python3
"""Official Infinix family-index discovery, not guessed numeric product IDs.

Uses the public storefront app-search API once per brand family/market, matches
exact SKU and device name, corroborates the official product detail page, then
downloads a bounded photo gallery for human review. Never publishes images.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import time
from pathlib import Path

import bot
import multimarket_scan as mm
from official_index import normalize_name

FAMILIES = ("HOT", "NOTE", "SMART", "ZERO", "XPAD", "GT 20 Pro", "GT 30 Pro", "GT 50 Pro")
MAX_CONCURRENCY=4


def page_results(market:str,term:str):
    result={"market":market,"familyQuery":term,"total":0,"rows":[],"pages":0,"error":None}
    try:
        for p in range(1, mm.MAX_API_PAGES+1):
            response=mm.api_search(term,market,p)
            result["total"]=response["total"]
            result["rows"].extend(response["items"])
            result["pages"]+=1
            if len(response["items"])<mm.PAGE_SIZE or response["total"]<=p*mm.PAGE_SIZE:
                break
    except Exception as exc:
        result["error"]=f"{type(exc).__name__}: {str(exc)[:150]}"
    return result


def index_market(markets:list[str],*,workers:int=4,images_per_device:int=5):
    if not markets or any(x not in mm.MARKETS for x in markets):
        raise ValueError("unsupported official market")
    if not 1<=workers<=MAX_CONCURRENCY or not 0<=images_per_device<=7:
        raise ValueError("workers 1..4, images 0..7")
    start=time.monotonic()
    pub={x["deviceId"] for x in json.loads((bot.MEDIA/"device_media_manifest.json").read_text())["entries"]}
    audits=bot.BOT/"output/selected-review-audit.json"
    staged={x["deviceId"] for x in json.loads(audits.read_text())["items"]} if audits.exists() else set()
    inventory=[]
    jobs=[(market,term) for market in markets for term in FAMILIES]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future=[ex.submit(page_results,*job) for job in jobs]
        for result in as_completed(future):
            inventory.append(result.result())
    entries=[]
    seen=set()
    reasons=Counter()
    for survey in inventory:
        for listing in survey["rows"]:
            pid=str(listing.get("id") or "")
            marker=(survey["market"],pid)
            if marker in seen:
                continue
            seen.add(marker)
            sku=str(listing.get("sku") or "").strip().upper()
            mapped=bot.match_storefront_code(sku)
            if not mapped:
                reasons["missing_or_ambiguous_catalog_sku"]+=1
                continue
            code,device,matchtype=mapped
            if normalize_name(device["name"])!=normalize_name(str(listing.get("name") or "")):
                reasons["name_or_variant_conflict"]+=1
                continue
            if device["deviceId"] in pub:
                reasons["published"]+=1
                continue
            if device["deviceId"] in staged:
                reasons["already_prepared_for_review"]+=1
                continue
            entries.append((survey["market"],listing,device,code))
    checked=[]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        tasks={ex.submit(mm.inspect_official_detail,market,listing,device,code):
               (market,listing,device,code) for market,listing,device,code in entries}
        for future in as_completed(tasks):
            market,listing,device,code=tasks[future]
            try:
                detail=future.result()
                if not detail["galleryImageUrls"]:
                    reasons["no_valid_official_product_images"]+=1
                    continue
                reasons["verified_official_page"]+=1
                checked.append({"deviceId":device["deviceId"],"name":device["name"],
                                "modelCode":code,"market":market,
                                "officialSku":str(listing["sku"]).strip(),"sourceProductId":str(listing["id"]),
                                "sourcePageUrl":detail["finalUrl"],"sourceEvidenceLevel":detail["evidenceLevel"],
                                "galleryUrls":detail["galleryImageUrls"]})
            except Exception as exc:
                reasons["detail_rejected"]+=1
    verified=defaultdict(list)
    for item in checked:
        verified[item["deviceId"]].append(item)
    final=[]
    for device_id,lines in sorted(verified.items()):
        lines.sort(key=lambda x:(x["sourceEvidenceLevel"]!="api_and_detail_sku_and_name",x["market"]))
        chosen=lines[0]
        final.append({"deviceId":device_id,"name":chosen["name"],"modelCode":chosen["modelCode"],
                      "sourcePages":lines, "images":[],
                      "frontBackApproved":False,"publishable":False})
    photos=[]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future={}
        for candidate in final:
            selected=candidate["sourcePages"][0]
            for i,url in enumerate(selected["galleryUrls"][:images_per_device]):
                task=ex.submit(mm.read_image,url,selected["market"])
                future[task]=(candidate,i,selected["market"])
        for task in as_completed(future):
            candidate,index,market=future[task]
            metadata,image=task.result()
            metadata["galleryIndex"]=index
            metadata["market"]=market
            candidate["images"].append(metadata)
            if metadata["downloadOk"] and image is not None:
                preview=image.convert("RGBA")
                preview.thumbnail((224,220))
                photos.append((candidate["name"]+" / "+candidate["modelCode"]+" / "+str(index),preview))
    hashes=defaultdict(set)
    for row in final:
        row["images"].sort(key=lambda x:x["galleryIndex"])
        for img in row["images"]:
            if img.get("sourceSha256"):
                hashes[img["sourceSha256"]].add(row["deviceId"])
    duplicates={k:sorted(x) for k,x in hashes.items() if len(x)>1}
    reference_checks=[]
    for m in markets:
        name,code=mm.REFERENCES[m]
        try:
            rows=mm.api_search(name,m,1)["items"]
            passed=any(normalize_name(x.get("name",""))==normalize_name(name) and
                       str(x.get("sku","")).strip().upper()==code for x in rows)
        except Exception:
            passed=False
        reference_checks.append({"market":m,"passed":passed,"name":name,"sku":code})
    summary={
        "markets":markets,"familyQueries":len(inventory),
        "successfulFamilyQueries":sum(x["error"] is None for x in inventory),
        "storefrontRowsReturned":sum(len(x["rows"]) for x in inventory),
        "distinctStorefrontProducts":len(seen),
        "allVerifiedProductSourcePages":len(checked),
        "newUniqueCatalogDeviceIds":len(final),
        "sourceImagesDownloaded":sum(x["downloadOk"] for c in final for x in c["images"]),
        "sourceImagesFailed":sum(not x["downloadOk"] for c in final for x in c["images"]),
        "allAlreadyPreparedDeviceIdsSkipped":len(staged),
        "rejections":dict(sorted(reasons.items())),
        "crossDeviceImageDuplicates":len(duplicates),
        "referenceChecksPassed":sum(x["passed"] for x in reference_checks),
        "referenceChecksTotal":len(reference_checks),
        "elapsedSeconds":round(time.monotonic()-start,1),
        "publishedNewImages":0,
    }
    report={
        "schemaVersion":1,"mode":"OFFICIAL_STORE_FAMILY_INVENTORY",
        "createdAt":datetime.now(timezone.utc).isoformat(),
        "summary":summary,"queries":[{"market":x["market"],"familyQuery":x["familyQuery"],
                                   "total":x["total"],"rows":len(x["rows"]),
                                   "pages":x["pages"],"error":x["error"]} for x in inventory],
        "referenceChecks":reference_checks,"newCandidatesForVisualReview":final,
        "crossDeviceSourceImageHashes":duplicates,
        "warning":"Official data is only a source hint; each model must be visually inspected, never auto-published.",
    }
    out=bot.BOT/"output";out.mkdir(exist_ok=True)
    label=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base=out/"family-history";base.mkdir(exist_ok=True)
    payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    (out/"family-inventory.json").write_text(payload)
    (base/(label+".json")).write_text(payload)
    mm.make_sheet(photos,out/"family-inventory-sheet.jpg")
    (base/(label+".jpg")).write_bytes((out/"family-inventory-sheet.jpg").read_bytes())
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    if any(x["error"] for x in inventory) or not all(x["passed"] for x in reference_checks):
        return 2
    return 0


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--market",action="append",choices=tuple(mm.MARKETS),default=None)
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--images",type=int,default=4)
    args=parser.parse_args()
    raise SystemExit(index_market(args.market or ["my","ng","np","ph"],workers=args.workers,images_per_device=args.images))
