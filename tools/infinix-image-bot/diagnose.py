#!/usr/bin/env python3
"""Read-only, bounded Infinix storefront diagnosis. No publishing and no app changes."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image
import bot

REFERENCES = {1351: "X6886", 1453: "X6876", 1555: "X6887"}
OFFICIAL_HOST = "southeast-asia.pro.infinixmobility.com"
BASE_URL = "https://wap.my.infinixmobility.com/shop/"
SKU_RE = re.compile(r'(?i)(?:\\\"|")sku(?:\\\"|")\s*:\s*(?:\\\"|")([A-Z][A-Z0-9-]{3,15})')
ALT_SKU_RE = re.compile(r"(?i)extra_info:.{0,90}?sku.{0,12}?(X[0-9]{3,6}[A-Z]?)")
IMAGE_RE = re.compile(r'https:(?:\\u002F){2}[^" ]+?\.(?:png|jpg|webp)', re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
MAX_PAGE_BYTES = 1_300_000
MAX_IMAGE_BYTES = 6_000_000


def canonical_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def page_result(page_id: int) -> dict:
    requested = f"{BASE_URL}{page_id}"
    row = {"pageId": page_id, "requestedUrl": requested, "canonicalUrl": None,
           "redirected": False, "httpStatus": None, "htmlBytes": 0, "title": "",
           "skuCodes": [], "catalogMatches": [], "acceptedImageUrls": [],
           "rejectedImageUrls": [], "status": None, "deviceId": None, "modelCode": None}
    try:
        request = urllib.request.Request(requested, headers={"User-Agent": bot.USER_AGENT})
        with urllib.request.urlopen(request, timeout=18) as response:
            row["httpStatus"] = response.status
            row["canonicalUrl"] = canonical_url(response.geturl())
            row["redirected"] = canonical_url(requested) != row["canonicalUrl"]
            row["contentType"] = response.headers.get("Content-Type", "")
            raw = response.read(MAX_PAGE_BYTES + 1)
        row["htmlBytes"] = len(raw)
        if len(raw) > MAX_PAGE_BYTES:
            raise ValueError("HTML exceeds 1.3 MB limit")
        if row["httpStatus"] != 200:
            row["status"] = "http_error"
            return row
        page = raw.decode("utf-8", "replace")
        if "<html" not in page.lower():
            raise ValueError("Response is not HTML")
        title = TITLE_RE.search(page)
        row["title"] = html.unescape(title.group(1).strip()) if title else ""
        skus = SKU_RE.findall(page) or ALT_SKU_RE.findall(page)
        skus = list(dict.fromkeys(code.upper() for code in skus))
        row["skuCodes"] = skus
        row["skuKeywordOccurrences"] = len(re.findall(r"sku", page, re.I))
        if not skus:
            row["status"] = "missing_sku"
            return row
        known = []
        ambiguous = []
        for code in skus:
            matches = bot.BY_CODE.get(code, [])
            row["catalogMatches"].append({
                "modelCode": code, "deviceIds": [d["deviceId"] for d in matches],
                "deviceNames": [d["name"] for d in matches],
                "nameMatched": [d["deviceId"] for d in matches if bot.normalized(d["name"]) in bot.normalized(row["title"])],
            })
            if len(matches) == 1:
                known.append((code, matches[0]))
            elif len(matches) > 1:
                ambiguous.append(code)
        if not known:
            row["status"] = "ambiguous_sku" if ambiguous else "sku_outside_catalog"
            return row
        named = [(code, device) for code, device in known if bot.normalized(device["name"]) in bot.normalized(row["title"])]
        if not named:
            row["status"] = "name_mismatch"
            return row
        distinct = {d["deviceId"] for _, d in named}
        if len(distinct) != 1 or ambiguous:
            row["status"] = "ambiguous_sku"
            return row
        code, device = named[0]
        row["deviceId"], row["modelCode"] = device["deviceId"], code
        marker = page.find("images:[{alt:")
        row["galleryMarkerFound"] = marker >= 0
        if marker < 0:
            row["status"] = "missing_gallery"
            return row
        gallery = page[marker:marker + 14000]
        end = gallery.find("],level_price:")
        if end >= 0:
            gallery = gallery[:end]
        raw_urls = IMAGE_RE.findall(gallery)
        row["rawImageUrlCount"] = len(raw_urls)
        if not raw_urls:
            row["status"] = "missing_extractable_images"
            return row
        for image_url in dict.fromkeys(url.replace("\\u002F", "/") for url in raw_urls):
            parsed = urllib.parse.urlsplit(image_url)
            if parsed.scheme == "https" and parsed.hostname == OFFICIAL_HOST and parsed.path.startswith("/media/catalog/product/"):
                clean = re.sub(r"/cache/[a-f0-9]+(?=/)", "", image_url)
                row["acceptedImageUrls"].append(clean)
            else:
                row["rejectedImageUrls"].append(image_url[:250])
        if not row["acceptedImageUrls"]:
            row["status"] = "image_urls_rejected"
            return row
        row["status"] = "matched_catalog"
        return row
    except urllib.error.HTTPError as error:
        row["httpStatus"] = error.code
        row["status"] = "http_error"
        row["error"] = str(error)[:220]
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        row["status"] = "network_error"
        row["error"] = f"{type(error).__name__}: {str(error)[:200]}"
    except Exception as error:
        row["status"] = "parse_error"
        row["error"] = f"{type(error).__name__}: {str(error)[:200]}"
    return row


def image_metadata(url: str) -> dict:
    info = {"sourceUrl": url, "sourceSha256": None, "downloadStatus": "failed"}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": bot.USER_AGENT})
        with urllib.request.urlopen(request, timeout=18) as response:
            body = response.read(MAX_IMAGE_BYTES + 1)
            info["httpStatus"] = response.status
            info["contentType"] = response.headers.get("Content-Type")
        if len(body) > MAX_IMAGE_BYTES:
            raise ValueError("Image over 6 MB")
        im = Image.open(io.BytesIO(body))
        im.load()
        info.update({"downloadStatus": "ok", "bytes": len(body),
                     "sourceSha256": hashlib.sha256(body).hexdigest(),
                     "width": im.width, "height": im.height, "mode": im.mode,
                     "meetsMinImageDimensions": min(im.size) >= 650,
                     "hasTransparency": "A" in im.getbands() and im.convert("RGBA").getchannel("A").getextrema()[0] == 0})
    except Exception as error:
        info["error"] = f"{type(error).__name__}: {str(error)[:200]}"
    return info


def run(start: int, stop: int) -> int:
    if start != 1322 or stop != 1572:
        raise ValueError("Diagnostic is restricted to 1322..1571 inclusive")
    manifest = json.loads((bot.MEDIA / "device_media_manifest.json").read_text())
    published = {entry["deviceId"] for entry in manifest["entries"]}
    missing = [d for d in bot.CATALOG if d["deviceId"] not in published]
    pages = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(page_result, i) for i in range(start, stop)]
        for future in as_completed(futures):
            pages.append(future.result())
    pages.sort(key=lambda row: row["pageId"])

    seen_canonical = {}
    seen_catalog_codes = defaultdict(list)
    devices_seen_by_code = defaultdict(set)
    for row in pages:
        for code in row["skuCodes"]:
            seen_catalog_codes[code].append(row["pageId"])
            for device in bot.BY_CODE.get(code, []):
                devices_seen_by_code[device["deviceId"]].add(row["status"])
        uri = row["canonicalUrl"]
        if row["httpStatus"] == 200 and uri:
            if uri in seen_canonical:
                row["duplicateCanonicalPageOf"] = seen_canonical[uri]
                row["countedCanonicalPage"] = False
            else:
                seen_canonical[uri] = row["pageId"]
                row["duplicateCanonicalPageOf"] = None
                row["countedCanonicalPage"] = True
        else:
            row["duplicateCanonicalPageOf"] = None
            row["countedCanonicalPage"] = False

    canonical_pages = [row for row in pages if row["countedCanonicalPage"]]
    device_to_records = defaultdict(list)
    for row in canonical_pages:
        if row["status"] == "matched_catalog":
            device_to_records[row["deviceId"]].append(row)
            row["status"] = "already_published" if row["deviceId"] in published else "new_candidate"
    # Each page has its own status, but counting distinct devices uses the deviceId set.
    for row in pages:
        if row["duplicateCanonicalPageOf"] is not None:
            row["status"] = "duplicate_canonical_page"

    candidate_devices = {device_id: rows for device_id, rows in device_to_records.items() if device_id not in published}
    new_candidates = []
    source_hashes = defaultdict(list)
    for device_id, rows in sorted(candidate_devices.items()):
        row = rows[0]
        image_info = image_metadata(row["acceptedImageUrls"][0])
        image_info["frontBackVisuallyVerified"] = False
        if image_info["sourceSha256"]:
            source_hashes[image_info["sourceSha256"]].append(device_id)
        new_candidates.append({
            "deviceId": device_id, "catalogName": bot.BY_ID[device_id]["name"],
            "modelCode": row["modelCode"], "sourcePageUrl": row["canonicalUrl"],
            "sourcePageIds": [r["pageId"] for r in rows],
            "officialImageUrls": row["acceptedImageUrls"],
            "firstImage": image_info, "reviewStatus": "REVIEW_NOT_APPROVED",
        })

    missing_devices = []
    for device in missing:
        code_pages = sorted({p for code in device["modelCodes"] for p in seen_catalog_codes.get(code.upper(), [])})
        if device["deviceId"] in candidate_devices:
            reason = "candidate_requires_visual_and_rights_review"
        elif code_pages:
            reason = "model_code_seen_but_no_eligible_candidate"
        else:
            reason = "model_codes_not_seen_in_scanned_pages"
        missing_devices.append({
            "deviceId": device["deviceId"], "name": device["name"],
            "modelCodes": device["modelCodes"], "reason": reason,
            "observedPageIds": code_pages, "observedRejectionStatuses": sorted(devices_seen_by_code[device["deviceId"]]),
        })

    reference_checks = []
    for pid, code in REFERENCES.items():
        row = next(x for x in pages if x["pageId"] == pid)
        candidates = [c for c in row["catalogMatches"] if c["modelCode"] == code]
        passed = (row["httpStatus"] == 200 and bool(row["acceptedImageUrls"])
                  and len(candidates) == 1 and len(candidates[0]["deviceIds"]) == 1
                  and candidates[0]["deviceIds"][0] in published
                  and row["status"] in {"already_published", "duplicate_canonical_page"})
        reference_checks.append({"pageId": pid, "expectedModelCode": code,
                                 "passed": passed, "observedStatus": row["status"],
                                 "httpStatus": row["httpStatus"], "redirected": row["redirected"],
                                 "title": row["title"], "canonicalUrl": row["canonicalUrl"]})

    summary = {
        "requestedPageCount": len(pages),
        "http200RequestedPages": sum(r["httpStatus"] == 200 for r in pages),
        "httpOrNetworkFailures": sum(r["status"] in {"http_error", "network_error"} for r in pages),
        "parseFailures": sum(r["status"] == "parse_error" for r in pages),
        "redirectedRequestedPages": sum(r["redirected"] for r in pages),
        "duplicateCanonicalPages": sum(r["status"] == "duplicate_canonical_page" for r in pages),
        "uniqueSuccessfulCanonicalPages": len(canonical_pages),
        "canonicalPageStatuses": dict(sorted(Counter(r["status"] for r in canonical_pages).items())),
        "requestedPageStatuses": dict(sorted(Counter(r["status"] for r in pages).items())),
        "catalogDevices": len(bot.CATALOG),
        "publishedDeviceIds": len(published & set(bot.BY_ID)),
        "missingCatalogDevices": len(missing),
        "uniquePublishedDevicesEncountered": len(set(device_to_records) & published),
        "uniqueNewCandidateDevices": len(candidate_devices),
        "uniqueMatchedCatalogDevices": len(device_to_records),
        "missingDeviceReasons": dict(sorted(Counter(d["reason"] for d in missing_devices).items())),
        "repeatedCandidateSourceHashes": {sha: devices for sha, devices in source_hashes.items() if len(devices) > 1},
        "referenceChecksPassed": sum(r["passed"] for r in reference_checks),
        "referenceChecksTotal": len(reference_checks),
    }
    report = {
        "schemaVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_DIAGNOSTIC", "scope": {"startInclusive": start, "stopExclusive": stop},
        "limitations": [
            "A code unseen in this 250-page interval may be available elsewhere in the official store.",
            "A qualifying candidate is not verified front+back; manual visual and rights review are required.",
            "Published-device deduplication uses deviceId; SHA is only checked among newly downloaded candidate originals.",
            "This run does not use publish, change application code, or modify media manifests.",
        ],
        "summary": summary, "referenceChecks": reference_checks,
        "pages": pages, "newCandidates": new_candidates,
        "missingDevices": missing_devices,
    }
    output = bot.BOT / "output"
    output.mkdir(exist_ok=True)
    (output / "diagnostic-pages-1322-1571.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (output / "diagnostic-summary.json").write_text(json.dumps({
        "summary": summary, "referenceChecks": reference_checks,
        "newCandidates": new_candidates,
    }, ensure_ascii=False, indent=2) + "\n")
    print("ALWAN_DIAGNOSTIC_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    valid = all(x["passed"] for x in reference_checks) and len(pages) == 250 and summary["http200RequestedPages"] > 0
    if not valid:
        print("DIAGNOSTIC FAILED: known reference pages or page coverage failed", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1322)
    parser.add_argument("--stop", type=int, default=1572)
    arguments = parser.parse_args()
    raise SystemExit(run(arguments.start, arguments.stop))
