#!/usr/bin/env python3
"""Concurrent, bounded, review-only Infinix device image discovery.

Uses official sitemap model names and the official storefront search API;
strictly verifies deviceId + SKU against live official product-detail pages.
Never approves or publishes images. 1-20 names, at most 4 workers.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from collections import Counter, defaultdict
import hashlib
import io
import json
import time
from pathlib import Path

from PIL import Image, ImageDraw
import bot
import official_search as search
import official_index as idx

MAX_NAMES = 20
MAX_WORKERS = 4
MAX_IMAGES = 3


def source_names(limit: int) -> list[str]:
    path = bot.BOT / "output/official-index-report.json"
    if not path.is_file():
        raise FileNotFoundError("Run indexed-discover first for official indexed model names.")
    report = json.loads(path.read_text())
    names = []
    seen = set()
    for item in report["products"]:
        for device in item["missingDevices"]:
            name = device["name"]
            key = idx.normalize_name(name)
            if key and key not in seen:
                seen.add(key)
                names.append(name)
    return names[:limit]


def search_name(name: str, market: str, published: set[str]) -> dict:
    info = {"name": name, "market": market, "checked": 0,
            "apiPages": 0, "reasonCounts": {}, "matches": [], "error": None}
    candidates = {}
    seen_ids = set()
    try:
        reasons = Counter()
        for page in range(1, search.MAX_PAGES + 1):
            results = search.api_search(name, market, page=page)
            info["apiPages"] += 1
            items = results["items"]
            for item in items:
                product_id = str(item.get("id") or "")
                if product_id in seen_ids:
                    continue
                seen_ids.add(product_id)
                info["checked"] += 1
                matched = search.classify_item(item, name, published)
                reason = matched["reason"]
                if reason == "name_not_exact":
                    continue
                if reason == "potential_device_candidate":
                    # Never infer identity from name or API list alone.
                    detail = bot.official_page(int(matched["productId"]))
                    if not detail or (detail["deviceId"], detail["modelCode"]) != (
                            matched["deviceId"], matched["modelCode"]):
                        reason = "detail_disagrees_or_parse_failed"
                    elif not detail["imageUrls"]:
                        reason = "no_trusted_product_images"
                    else:
                        candidate = {
                            "deviceId": detail["deviceId"],
                            "name": detail["name"], "modelCode": detail["modelCode"],
                            "officialSku": matched["sku"], "officialPageUrl": detail["sourcePageUrl"],
                            "officialPageId": int(matched["productId"]),
                            "officialImageUrls": detail["imageUrls"],
                            "frontBackApproved": False,
                            "rightsVerified": False, "publishable": False,
                            "market": market,
                        }
                        candidates[detail["deviceId"]] = candidate
                        reason = "verified_detail_requires_image_review"
                matched["reason"] = reason
                info["matches"].append({k: matched.get(k) for k in
                    ("productId", "name", "sku", "reason", "deviceId", "modelCode") if k in matched})
                reasons[reason] += 1
            if len(items) < search.PAGE_SIZE or results["total"] <= page * search.PAGE_SIZE:
                break
        info["reasonCounts"] = dict(reasons)
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
    return {"query": info, "candidates": list(candidates.values())}


def download_image(url: str) -> tuple[dict, Image.Image | None]:
    item = {"url": url, "sourceSha256": None, "status": "failed"}
    try:
        raw = bot.fetch(url, limit=6_000_000)
        img = Image.open(io.BytesIO(raw))
        img.load()
        digest = hashlib.sha256(raw).hexdigest()
        alpha = img.convert("RGBA").getchannel("A")
        item.update({"sourceSha256": digest, "status": "downloaded",
                     "width": img.width, "height": img.height,
                     "mode": img.mode, "bytes": len(raw),
                     "minDimension650": min(img.size) >= 650,
                     "transparentBackground": alpha.getextrema()[0] == 0})
        img.thumbnail((240, 240))
        return item, img.convert("RGBA")
    except Exception as exc:
        item["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        return item, None


def contact_sheet(images: list[tuple[str, Image.Image]], path: Path):
    cols = 4
    cell_w, cell_h = 250, 275
    rows = max(1, (len(images) + cols - 1) // cols)
    sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (title, img) in enumerate(images):
        x, y = (i % cols) * cell_w, (i // cols) * cell_h
        sheet.paste(img, (x + (cell_w - img.width) // 2, y), img)
        draw.text((x + 5, y + 245), title[:38], fill="#111111")
    sheet.save(path, quality=88)


def execute(names: list[str], market: str, workers: int = 4, images_per_device: int = 3):
    if not names or len(names) > MAX_NAMES or not 1 <= workers <= MAX_WORKERS:
        raise ValueError("1..20 model names; 1..4 workers")
    if not 0 <= images_per_device <= MAX_IMAGES:
        raise ValueError("0..3 images per candidate")
    if market not in search.SEARCH_BASES:
        raise ValueError("unapproved market")
    manifest = json.loads((bot.MEDIA / "device_media_manifest.json").read_text())
    published = {e["deviceId"] for e in manifest["entries"]}
    allowed_names = {idx.normalize_name(x["name"]) for x in bot.CATALOG if x["deviceId"] not in published}
    if any(idx.normalize_name(n) not in allowed_names for n in names):
        raise ValueError("All names must be missing Infinix catalog models")
    now = time.monotonic()
    query_results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(search_name, name, market, published): name for name in names}
        for job in as_completed(jobs):
            query_results.append(job.result())
    order = {idx.normalize_name(name): i for i, name in enumerate(names)}
    query_results.sort(key=lambda x: order[idx.normalize_name(x["query"]["name"])])

    unique_candidates = {}
    for result in query_results:
        for device in result["candidates"]:
            unique_candidates.setdefault(device["deviceId"], device)
    visual_items = []
    hash_seen = defaultdict(set)
    # Download only after exact model code and official page confirmation.
    candidates = list(unique_candidates.values())
    jobs = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, device in enumerate(candidates):
            device["images"] = [None] * min(images_per_device, len(device["officialImageUrls"]))
            for j, image_url in enumerate(device["officialImageUrls"][:images_per_device]):
                jobs[pool.submit(download_image, image_url)] = (i, j)
        for fut in as_completed(jobs):
            i, j = jobs[fut]
            metadata, thumb = fut.result()
            candidates[i]["images"][j] = metadata
            if metadata["sourceSha256"]:
                hash_seen[metadata["sourceSha256"]].add(candidates[i]["deviceId"])
            if thumb is not None:
                visual_items.append((candidates[i]["name"] + " / " + candidates[i]["modelCode"], thumb))
    # Only for fast human triage. Order is not evidence of priority.
    duplicates = {digest: sorted(list(ids)) for digest, ids in hash_seen.items() if len(ids) > 1}
    refs = []
    try:
        name, expected_sku = search.SEARCH_REFERENCES[market]
        ref_result = search.api_search(name, market)
        passed = any(idx.normalize_name(x.get("name", "")) == idx.normalize_name(name)
                     and str(x.get("sku", "")).strip().upper() == expected_sku
                     for x in ref_result["items"])
        refs.append({"name": name, "sku": expected_sku, "passed": passed})
    except Exception as exc:
        refs.append({"passed": False, "error": str(exc)[:140]})
    api_failures = [r["query"] for r in query_results if r["query"]["error"]]
    summary = {
        "requestedModelNames": len(names),
        "officialStoreQueries": len(query_results),
        "requestedMarket": market, "parallelWorkers": workers,
        "apiFailures": len(api_failures),
        "uniqueCatalogDevicesWithVerifiedOfficialPage": len(candidates),
        "imagesDownloaded": sum(i["status"] == "downloaded" for c in candidates for i in c["images"]),
        "imagesFailed": sum(i["status"] == "failed" for c in candidates for i in c["images"]),
        "sameOriginalHashAcrossDifferentDevices": len(duplicates),
        "alreadyPublishedByDeviceIdSkipped": True,
        "frontBackVisuallyApproved": 0,
        "referenceTestsPassed": sum(bool(r["passed"]) for r in refs),
        "referenceTestsTotal": len(refs),
        "elapsedSeconds": round(time.monotonic() - now, 1),
    }
    report = {
        "schemaVersion": 1, "mode": "LOCAL_INFINIX_PARALLEL_READ_ONLY",
        "generatedAt": datetime.now(timezone.utc).isoformat(), "summary": summary,
        "notes": [
            "Candidates are not approved images. A person must inspect front and back.",
            "No rights to redistribute official product images have been established.",
            "Image SHA is of the downloaded source bytes, not the cropped published PNG.",
            "Shared model names are NOT used to bypass the exact-SKU catalog match.",
        ],
        "referenceTests": refs, "queryResults": [r["query"] for r in query_results],
        "candidatesForReview": candidates, "duplicateSourceHashes": duplicates,
    }
    out = bot.BOT / "output"
    out.mkdir(exist_ok=True)
    (out / "batch-review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    contact_sheet(visual_items, out / "batch-review-sheet.jpg")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 2 if api_failures or not all(r["passed"] for r in refs) else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20, help="Max model names 1..20")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many indexed names; batches resume without repetition")
    parser.add_argument("--name", action="append", help="Explicit Infinix missing-catalog name, repeat to fill the batch")
    parser.add_argument("--market", choices=tuple(search.SEARCH_BASES), default="malaysia")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--images", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_NAMES or args.offset < 0:
        parser.error("limit must be 1..20, offset must be nonnegative")
    names = list(dict.fromkeys(args.name))[:args.limit] if args.name else source_names(args.limit + args.offset)[args.offset:]
    if not names:
        parser.error("no missing-catalog indexed names remain at this offset")
    raise SystemExit(execute(names, args.market, args.workers, args.images))


if __name__ == "__main__":
    main()
