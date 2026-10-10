#!/usr/bin/env python3
"""Verified Infinix storefront discovery across explicit official regional markets.

READ-ONLY: catalog match, product-detail corroboration, source image SHA, contact
sheet for human review. Never publishes or modifies approved.json/media manifests.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import re
import shutil
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

from PIL import Image, ImageDraw
import bot
import media_core
from official_index import normalize_name

# Explicitly inspected official product pages and gallery-CDN domains.
MARKETS = {
    "my": ("wap.my.infinixmobility.com", "southeast-asia.pro.infinixmobility.com"),
    "iq": ("iq.infinixmobility.com", "middle-east.pro.infinixmobility.com"),
    "np": ("wap.np.infinixmobility.com", "south-asia.pro.infinixmobility.com"),
    "ng": ("wap.ng.infinixmobility.com", "west-africa.pro.infinixmobility.com"),
    "ph": ("wap.ph.infinixmobility.com", "ph.pro.infinixmobility.com"),
    "id": ("wap.id.infinixmobility.com", "id.pro.infinixmobility.com"),
}
# Known live result in each country's catalog (check first-page API response).
REFERENCES = {
    "my": ("SMART 10 Plus", "X6725B"),
    "iq": ("HOT 60 Pro+", "X6886"),
    "np": ("HOT 60 Pro+", "X6886"),
    "ng": ("HOT 50 Pro+", "X6880"),
    "ph": ("GT 30 Pro", "X6873"),
    "id": ("HOT 60 Pro", "X6885"),
}
SOURCE_POLICY = media_core.SourcePolicy(
    brand='infinix',
    hosts=frozenset(host for pair in MARKETS.values() for host in pair),
    user_agent=bot.USER_AGENT,
)
PAGE_SIZE, MAX_API_PAGES = 30, 2
GALLERY_RE = re.compile(r'https:(?:\\u002F){2}[^" ]+?\.(?:png|jpg|webp)', re.I)
SKU_RE = re.compile(r'(?i)(?:\\\"|")sku(?:\\\"|")\s*:\s*(?:\\\"|")([A-Z][A-Z0-9-]{3,30})')
TITLE_RE = re.compile(r'<title[^>]*>([^<]+)', re.I)
MAX_HTML_BYTES, MAX_API_BYTES, MAX_IMAGE_BYTES = 1_500_000, 3_000_000, 6_000_000


def get(url: str, limit: int, expected_host: str) -> tuple[bytes, str]:
    """Infinix host-policy adapter for the vendor-neutral HTTP engine."""
    return media_core.fetch_https(url, limit, expected_host, SOURCE_POLICY)


def api_search(name: str, market: str, page: int = 1) -> dict:
    if market not in MARKETS or not 1 <= page <= MAX_API_PAGES:
        raise ValueError("market or API page not allowed")
    host = MARKETS[market][0]
    query = urllib.parse.urlencode({"q": name, "page": page, "page_size": PAGE_SIZE})
    data, final = get(f"https://{host}/api/V1/xpark-app/app-search?{query}", MAX_API_BYTES, host)
    obj = json.loads(data)
    if obj.get("code") != 200:
        raise ValueError("official API returned non-200 application code")
    listing = (obj.get("data") or {}).get("category") or {}
    items = listing.get("items") or []
    if not isinstance(items, list):
        raise ValueError("invalid official API schema")
    return {"items": items, "total": int(listing.get("total") or 0), "url": final}


def normalize_store_title(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"(?i)^.{0,12}infinix\s*-\s*", "", text)
    text = re.sub(r"\s*-\s*(malaysia|iraq|nepal|nigeria|philippines|indonesia)\s*$", "", text, flags=re.I)
    return normalize_name(text)


def valid_gallery_urls(document: str, market: str) -> tuple[list[str], int]:
    i = document.find("images:[{alt:")
    if i < 0:
        return [], 0
    section = document[i:i + 23000]
    terminator = section.find("],level_price:")
    if terminator >= 0:
        section = section[:terminator]
    wanted_host = MARKETS[market][1]
    urls, rejected = [], 0
    for original in GALLERY_RE.findall(section):
        url = original.replace("\\u002F", "/")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != wanted_host or not parsed.path.startswith("/media/catalog/product/"):
            rejected += 1
            continue
        # The storefront cache serves ~88x110 thumbnails. Strip only its known
        # content-hash cache segment to fetch the official original on SAME host.
        url = re.sub(r"/cache/[a-f0-9]{16,64}(?=/)", "", url)
        if url not in urls:
            urls.append(url)
    return urls[:12], rejected


def inspect_official_detail(market: str, item: dict, device: dict, hardware_code: str) -> dict:
    pid = str(item.get("id") or "")
    if not re.fullmatch(r"[1-9][0-9]{0,5}", pid):
        raise ValueError("invalid official product ID")
    host = MARKETS[market][0]
    data, final = get(f"https://{host}/shop/{pid}", MAX_HTML_BYTES, host)
    page = data.decode("utf8", "replace")
    title_found = TITLE_RE.search(page)
    title = html.unescape(title_found.group(1).strip()) if title_found else ""
    page_name = normalize_store_title(title)
    expected_name = normalize_name(device["name"])
    if page_name != expected_name:
        raise ValueError(f"product detail title conflicts with catalog: {title[:75]}")
    page_skus = list(dict.fromkeys(s.upper() for s in SKU_RE.findall(page)))
    # Conflicting codes indicate the API item and HTML detail may not be the same hardware.
    unique_page_codes = {x[0] for raw in page_skus if (x := bot.match_storefront_code(raw))}
    if unique_page_codes and (hardware_code not in unique_page_codes or len(unique_page_codes) > 1):
        raise ValueError("official HTML SKU conflicts with API SKU")
    image_urls, rejected_urls = valid_gallery_urls(page, market)
    return {"finalUrl": final, "title": title, "htmlSkuCodes": page_skus[:8],
            "evidenceLevel": "api_and_detail_sku_and_name" if hardware_code in unique_page_codes
                             else "api_sku_and_exact_detail_title",
            "galleryImageUrls": image_urls, "galleryUrlsRejected": rejected_urls}


def inspect_query(name: str, market: str, published: set[str]) -> dict:
    result = {"name": name, "market": market, "pagesChecked": 0,
              "apiProductsChecked": 0, "reasons": {}, "candidates": [], "errors": []}
    already_seen = set()
    counts = Counter()
    try:
        for page_number in range(1, MAX_API_PAGES + 1):
            listing = api_search(name, market, page_number)
            result["pagesChecked"] += 1
            for row in listing["items"]:
                pid = str(row.get("id") or "")
                if pid in already_seen:
                    continue
                already_seen.add(pid)
                result["apiProductsChecked"] += 1
                product_name = str(row.get("name") or "")
                if normalize_name(product_name) != normalize_name(name):
                    continue
                sku = str(row.get("sku") or "").strip().upper()
                mapped = bot.match_storefront_code(sku)
                if not mapped:
                    counts["unmatched_or_ambiguous_sku"] += 1
                    continue
                code, device, match_type = mapped
                if normalize_name(device["name"]) != normalize_name(product_name):
                    counts["catalog_device_name_conflict"] += 1
                    continue
                if device["deviceId"] in published:
                    counts["already_published_device"] += 1
                    continue
                try:
                    detail = inspect_official_detail(market, row, device, code)
                except Exception as exc:
                    counts["product_detail_rejected"] += 1
                    result["errors"].append({"id": pid, "code": code, "reason": str(exc)[:150]})
                    continue
                if not detail["galleryImageUrls"]:
                    counts["missing_official_gallery_images"] += 1
                    continue
                counts["catalog_device_candidate"] += 1
                result["candidates"].append({
                    "deviceId": device["deviceId"], "name": device["name"],
                    "modelCode": code, "market": market,
                    "sourceSku": sku, "sourceProductId": int(pid),
                    "officialPageUrl": detail["finalUrl"],
                    "sourceEvidenceLevel": detail["evidenceLevel"],
                    "officialPageTitle": detail["title"],
                    "pageSkuCodes": detail["htmlSkuCodes"],
                    "galleryImageUrls": detail["galleryImageUrls"],
                    "galleryUrlsRejected": detail["galleryUrlsRejected"],
                })
            if len(listing["items"]) < PAGE_SIZE or listing["total"] <= page_number * PAGE_SIZE:
                break
    except Exception as exc:
        result["errors"].append({"apiError": f"{type(exc).__name__}: {str(exc)[:180]}"})
        counts["api_or_fetch_failure"] += 1
    result["reasons"] = dict(sorted(counts.items()))
    return result


def read_image(url: str, market: str):
    image_host = MARKETS[market][1]
    info = {"url": url, "downloadOk": False, "sourceSha256": None}
    try:
        raw, final = get(url, MAX_IMAGE_BYTES, image_host)
        pic = Image.open(io.BytesIO(raw))
        pic.load()
        alpha = pic.convert("RGBA").getchannel("A").getextrema()
        info.update(downloadOk=True, finalUrl=final,
                    sourceSha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw), size=list(pic.size), mode=pic.mode,
                    transparent=alpha[0] == 0,
                    minimum650=min(pic.size) >= 650)
        return info, pic
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return info, None


def make_sheet(thumbs: list[tuple[str, Image.Image]], path: Path):
    cols, width, height = 4, 240, 270
    canvas = Image.new("RGB", (width * cols, max(1, (len(thumbs) + cols - 1) // cols) * height), "white")
    pen = ImageDraw.Draw(canvas)
    for n, (label, image) in enumerate(thumbs):
        x, y = (n % cols) * width, (n // cols) * height
        canvas.paste(image, (x + (width - image.width) // 2, y), image)
        pen.text((x + 3, y + 245), label[:35], fill="#171717")
    canvas.save(path, quality=88)


def scan(names: list[str], markets: list[str], *, workers: int = 4, images_per_device: int = 5) -> dict:
    if not 1 <= len(names) <= 20 or not 1 <= workers <= 4 or not 0 <= images_per_device <= 7:
        raise ValueError("1-20 names; 1-4 workers; 0-7 images")
    if not markets or any(m not in MARKETS for m in markets):
        raise ValueError("unknown official market")
    manifest = json.loads((bot.MEDIA / "device_media_manifest.json").read_text())
    published = {r["deviceId"] for r in manifest["entries"]}
    missing = {normalize_name(d["name"]) for d in bot.CATALOG if d["deviceId"] not in published}
    if any(normalize_name(n) not in missing for n in names):
        raise ValueError("all names must be missing Infinix catalog names")
    start = time.monotonic()
    cases = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = [pool.submit(inspect_query, name, market, published) for name in names for market in markets]
        for future in as_completed(pending):
            cases.append(future.result())
    devices = {}
    for case in cases:
        for x in case["candidates"]:
            d = devices.setdefault(x["deviceId"], {
                "deviceId": x["deviceId"], "name": x["name"], "modelCode": x["modelCode"],
                "sources": [], "images": [], "frontBackApproved": False,
                "rightsVerified": False, "publishable": False,
            })
            d["sources"].append(x)
    images_to_get = []
    for d in devices.values():
        seen = set()
        for src in sorted(d["sources"], key=lambda x: (x["sourceEvidenceLevel"] != "api_and_detail_sku_and_name", x["market"])):
            for url in src["galleryImageUrls"][:images_per_device]:
                if url not in seen and len(images_to_get) < 200:
                    seen.add(url)
                    images_to_get.append((d, src["market"], url))
                if len(seen) >= images_per_device:
                    break
            if len(seen) >= images_per_device:
                break
    thumbs = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(read_image, u, market): (device, market) for device, market, u in images_to_get}
        for f in as_completed(pending):
            device, market = pending[f]
            result, pic = f.result()
            result["market"] = market
            device["images"].append(result)
            if pic and result["downloadOk"]:
                preview = pic.convert("RGBA")
                preview.thumbnail((224, 222))
                thumbs.append((f'{device["name"]} / {device["modelCode"]}', preview))
    by_sha = defaultdict(set)
    for d in devices.values():
        for img in d["images"]:
            if img.get("sourceSha256"):
                by_sha[img["sourceSha256"]].add(d["deviceId"])
    cross_duplicates = {h: sorted(x) for h, x in by_sha.items() if len(x) > 1}
    references = []
    for market in markets:
        refname, code = REFERENCES[market]
        try:
            page = api_search(refname, market)
            valid = any(normalize_name(row.get("name", "")) == normalize_name(refname)
                        and str(row.get("sku", "")).strip().upper() == code
                        for row in page["items"])
            references.append({"market": market, "name": refname, "modelCode": code, "passed": valid})
        except Exception as exc:
            references.append({"market": market, "passed": False, "error": str(exc)[:150]})
    errors = sum(any("apiError" in e for e in x["errors"]) for x in cases)
    summary = {
        "catalogTotal": len(bot.CATALOG), "previouslyPublished": len(published & bot.BY_ID.keys()),
        "catalogMissing": sum(d["deviceId"] not in published for d in bot.CATALOG),
        "modelNamesQueried": len(names), "marketsQueried": markets,
        "totalNameMarketQueries": len(cases), "apiFailures": errors,
        "uniqueDeviceIdsMatched": len(devices),
        "officialSourcesValidated": sum(len(x["sources"]) for x in devices.values()),
        "imagesDownloaded": sum(i["downloadOk"] for d in devices.values() for i in d["images"]),
        "imageDownloadFailures": sum(not i["downloadOk"] for d in devices.values() for i in d["images"]),
        "referenceChecksPassed": sum(x["passed"] for x in references),
        "referenceChecksTotal": len(references),
        "duplicateImageShaAcrossDevices": len(cross_duplicates),
        "frontBackApproved": 0, "published": 0,
        "elapsedSeconds": round(time.monotonic() - start, 1),
    }
    report = {"schemaVersion": 1, "mode": "MULTIMARKET_READ_ONLY", "createdAt": datetime.now(timezone.utc).isoformat(),
              "summary": summary, "referenceChecks": references, "queryDiagnostics": cases,
              "candidatesForReview": list(devices.values()), "crossDeviceDuplicateSha": cross_duplicates,
              "limits": {"modelNames": 20, "maxWorkers": 4},
              "notice": "Model-code/official-source verification is not front+back or redistribution-rights approval."}
    out = bot.BOT / "output"
    out.mkdir(exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (out / "multimarket-review.json").write_text(serialized)
    make_sheet(thumbs, out / "multimarket-sheet.jpg")
    # Keep immutable per-run evidence while retaining short latest-file paths.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    signature = hashlib.sha256(("|".join(names) + "|" + ",".join(markets)).encode()).hexdigest()[:8]
    archive = out / "multimarket-history"
    archive.mkdir(exist_ok=True)
    prefix = f"{stamp}-{signature}"
    (archive / f"{prefix}.json").write_text(serialized)
    shutil.copyfile(out / "multimarket-sheet.jpg", archive / f"{prefix}.jpg")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--market", action="append", choices=tuple(MARKETS), default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--images", type=int, default=5)
    parser.add_argument("--name", action="append")
    args = parser.parse_args()
    if args.name:
        names = list(dict.fromkeys(args.name))
    else:
        # Prefer names where official sitemaps already show a matching product page.
        src = bot.BOT / "output/official-index-report.json"
        if not src.exists():
            parser.error("Run bot.py indexed-discover first or supply --name")
        indexed = json.loads(src.read_text())
        all_names = list(dict.fromkeys(x["missingDevices"][0]["name"] for x in indexed["products"] if x["missingDevices"]))
        names = all_names[args.offset:args.offset + args.limit]
    markets = args.market or ["my", "ng", "np", "ph"]
    report = scan(names, markets, workers=args.workers, images_per_device=args.images)
    if report["summary"]["apiFailures"] or report["summary"]["referenceChecksPassed"] != len(markets):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
