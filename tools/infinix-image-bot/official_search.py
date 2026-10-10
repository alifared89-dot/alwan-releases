#!/usr/bin/env python3
"""Bounded Infinix official storefront search by catalog name.

Source: official xpark-app/app-search endpoint used by Infinix storefront JS.
Only catalog-verified model-code and page candidates enter visual review.
No publication, automatic front/back approval, or other brands.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from PIL import Image, ImageDraw

import bot
import official_index

SEARCH_BASES = {
    "malaysia": "https://wap.my.infinixmobility.com",
    "iraq": "https://iq.infinixmobility.com",
}
PAGE_SIZE = 12
MAX_PAGES = 2
API_LIMIT = 3_000_000
# Stable known storefront API results; test them before trusting a zero-candidate run.
SEARCH_REFERENCES = {"malaysia": ("SMART 10 Plus", "X6725B"),
                     "iraq": ("SMART 9", "X6532")}


def api_search(name: str, market: str, page: int = 1) -> dict:
    if market not in SEARCH_BASES or not 1 <= page <= MAX_PAGES:
        raise ValueError("unsupported official store or page")
    query = urlencode({"q": name, "page": page, "page_size": PAGE_SIZE})
    url = SEARCH_BASES[market] + "/api/V1/xpark-app/app-search?" + query
    body, final_url, status = official_index.get_bytes(url, API_LIMIT)
    if status != 200:
        raise ValueError(f"official API HTTP {status}")
    response = json.loads(body)
    if not isinstance(response, dict) or response.get("code") != 200:
        raise ValueError("official API response code is not 200")
    category = (response.get("data") or {}).get("category") or {}
    items = category.get("items") or []
    if not isinstance(items, list):
        raise ValueError("official API items are not a list")
    return {"total": int(category.get("total") or 0),
            "items": items, "apiUrl": final_url}


def classify_item(item: dict, requested_name: str, published: set[str]) -> dict:
    result = {"productId": str(item.get("id") or ""),
              "name": str(item.get("name") or "")[:120],
              "sku": str(item.get("sku") or "")[:90]}
    if official_index.normalize_name(result["name"]) != official_index.normalize_name(requested_name):
        result["reason"] = "name_not_exact"
        return result
    mapping = bot.match_storefront_code(result["sku"])
    if mapping is None:
        result["reason"] = "sku_not_unique_or_not_in_catalog"
        return result
    code, device, match_type = mapping
    if official_index.normalize_name(device["name"]) != official_index.normalize_name(result["name"]):
        result["reason"] = "sku_name_conflicts_with_catalog"
        return result
    result.update(deviceId=device["deviceId"], modelCode=code, matchType=match_type)
    if device["deviceId"] in published:
        result["reason"] = "device_already_published"
        return result
    if not re.fullmatch(r"[1-9]\d{0,5}", result["productId"]):
        result["reason"] = "invalid_official_product_id"
        return result
    result["reason"] = "potential_device_candidate"
    return result


def collect_image_evidence(urls: list[str], max_images: int = 4) -> list[dict]:
    images = []
    for url in urls[:max_images]:
        image = {"url": url, "sourceSha256": None, "state": "rejected"}
        try:
            body = bot.fetch(url, limit=6_000_000)
            im = Image.open(io.BytesIO(body))
            im.load()
            image.update(state="downloaded", sourceSha256=hashlib.sha256(body).hexdigest(),
                         bytes=len(body), width=im.width, height=im.height, mode=im.mode,
                         min650=min(im.size) >= 650)
            # Image metadata proves it is decodable, not that it shows front and back.
        except Exception as exc:
            image["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        images.append(image)
    return images


def make_contact_sheet(rows: list[dict], output: Path):
    previews = []
    for entry in rows:
        for x in entry.get("images", []):
            if x.get("state") != "downloaded":
                continue
            try:
                data = bot.fetch(x["url"], limit=6_000_000)
                # Verify that the preview matches the reviewed hash.
                if hashlib.sha256(data).hexdigest() != x["sourceSha256"]:
                    continue
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                img.thumbnail((220, 210))
                previews.append((entry["name"][:23] + " / " + entry["modelCode"], img))
            except Exception:
                continue
    cols = 4
    sheet = Image.new("RGB", (cols * 240, max(250, ((len(previews) + cols - 1) // cols) * 250)), "white")
    draw = ImageDraw.Draw(sheet)
    for idx, (label, im) in enumerate(previews):
        x, y = (idx % cols) * 240, (idx // cols) * 250
        sheet.paste(im, (x + (240 - im.width) // 2, y), im)
        draw.text((x + 6, y + 217), label[:33], fill="#111111")
    sheet.save(output, quality=88)


def run(names: list[str], markets: tuple[str, ...], max_images: int) -> int:
    published = {r["deviceId"] for r in json.loads(
        (bot.MEDIA / "device_media_manifest.json").read_text())["entries"]}
    missing_names = {official_index.normalize_name(d["name"]) for d in bot.CATALOG
                     if d["deviceId"] not in published}
    if not names or any(official_index.normalize_name(name) not in missing_names for name in names):
        raise ValueError("only Infinix catalog names with missing image are permitted")
    collected: list[dict] = []
    candidates: dict[str, dict] = {}
    total_api_errors = 0
    for name in names:
        for market in markets:
            query = {"name": name, "market": market, "pages": [], "itemsExamined": 0,
                     "exactNameItems": [], "failure": None}
            seen_product_ids = set()
            try:
                for page in range(1, MAX_PAGES + 1):
                    data = api_search(name, market, page=page)
                    items = data["items"]
                    query["pages"].append({"page": page, "officialTotal": data["total"],
                                           "returned": len(items), "url": data["apiUrl"]})
                    if not items:
                        break
                    for item in items:
                        product_id = str(item.get("id") or "")
                        if product_id in seen_product_ids:
                            continue
                        seen_product_ids.add(product_id)
                        query["itemsExamined"] += 1
                        match = classify_item(item, name, published)
                        if match["reason"] == "name_not_exact":
                            continue
                        if match["reason"] != "potential_device_candidate":
                            query["exactNameItems"].append(match)
                            continue
                        # API index is a lead. A live official detail page MUST agree.
                        product = bot.official_page(int(match["productId"]))
                        if not product or (product["deviceId"], product["modelCode"]) != (
                                match["deviceId"], match["modelCode"]):
                            match["reason"] = "official_product_detail_disagrees"
                            query["exactNameItems"].append(match)
                            continue
                        if not product["imageUrls"]:
                            match["reason"] = "official_product_has_no_approved_host_images"
                            query["exactNameItems"].append(match)
                            continue
                        match.update(reason="requires_visual_rights_review",
                                     officialPageUrl=product["sourcePageUrl"],
                                     imageUrls=product["imageUrls"])
                        query["exactNameItems"].append(match)
                        candidate = candidates.setdefault(match["deviceId"], {
                            "deviceId": match["deviceId"], "name": product["name"],
                            "modelCode": match["modelCode"], "sourceSku": match["sku"],
                            "officialPageId": int(match["productId"]),
                            "officialPageUrl": product["sourcePageUrl"],
                            "matchType": match["matchType"],
                            "allOfficialImages": product["imageUrls"],
                            "sourceMarkets": [], "images": [],
                            "frontBackApproved": False, "rightsVerified": False,
                            "publishable": False,
                        })
                        if market not in candidate["sourceMarkets"]:
                            candidate["sourceMarkets"].append(market)
                    if len(items) < PAGE_SIZE or data["total"] <= page * PAGE_SIZE:
                        break
            except Exception as exc:
                query["failure"] = f"{type(exc).__name__}: {str(exc)[:180]}"
                total_api_errors += 1
            collected.append(query)

    sha_to_ids = {}
    for c in candidates.values():
        c["images"] = collect_image_evidence(c["allOfficialImages"], max_images)
        hashes = [x["sourceSha256"] for x in c["images"] if x["sourceSha256"]]
        for digest in hashes:
            if digest in sha_to_ids and sha_to_ids[digest] != c["deviceId"]:
                c.setdefault("sameImageHashOtherDevices", []).append(sha_to_ids[digest])
            else:
                sha_to_ids[digest] = c["deviceId"]
        c["reviewState"] = "image_evidence_available" if hashes else "image_download_failed"
        # Human must verify front and back, source copyright/redistribution rights, and duplicates.

    reference_checks = []
    for market in markets:
        ref_name, expected_code = SEARCH_REFERENCES[market]
        check = {"market": market, "name": ref_name, "expectedSku": expected_code,
                 "passed": False}
        try:
            probe = api_search(ref_name, market, page=1)
            check["passed"] = any(
                official_index.normalize_name(x.get("name", "")) ==
                official_index.normalize_name(ref_name)
                and str(x.get("sku", "")).strip().upper() == expected_code
                for x in probe["items"])
        except Exception as exc:
            check["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        reference_checks.append(check)

    totals = Counter(v["reason"] for q in collected for v in q["exactNameItems"])
    summary = {"catalogDevices": len(bot.CATALOG), "publishedDevices": len(published & bot.BY_ID.keys()),
               "missingDevices": sum(x["deviceId"] not in published for x in bot.CATALOG),
               "namesQueried": len(names), "officialMarketsQueried": len(markets),
               "apiQueries": len(collected), "apiErrors": total_api_errors,
               "exactNameMatchReasons": dict(sorted(totals.items())),
               "uniqueDevicesWithVerifiedOfficialPage": len(candidates),
               "devicesWithDownloadedImageEvidence": sum(bool(c["images"]) and
                   any(x["state"] == "downloaded" for x in c["images"]) for c in candidates.values()),
               "photosApprovedForPublication": 0,
               "referenceChecksPassed": sum(x["passed"] for x in reference_checks),
               "referenceChecksTotal": len(reference_checks),
               "imageDuplicatesAcrossDevices": sum(len(c.get("sameImageHashOtherDevices", [])) for c in candidates.values())}
    report = {
        "schemaVersion": 1, "mode": "READ_ONLY_OFFICIAL_STORE_SEARCH",
        "at": datetime.now(timezone.utc).isoformat(), "summary": summary,
        "note": "sourceSha256 is only for successfully downloaded images. No images approved as frontBack.",
        "queries": collected, "referenceChecks": reference_checks,
        "candidatesForVisualReview": list(candidates.values()),
    }
    out = bot.BOT / "output"
    out.mkdir(exist_ok=True)
    (out / "official-search-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    make_contact_sheet(list(candidates.values()), out / "official-search-review.jpg")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    # Zero results can be a valid source gap, but API errors or broken known references are NOT success.
    return 2 if total_api_errors or not all(x["passed"] for x in reference_checks) else 0


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", action="append", dest="names", help="Exact catalog name; repeat for more")
    parser.add_argument("--limit", type=int, default=8, help="Max distinct catalog model names; 1-20")
    parser.add_argument("--image-limit", type=int, default=3, help="Max gallery image hashes per verified device; 0-5")
    parser.add_argument("--market", choices=("malaysia", "iraq", "both"), default="malaysia")
    args = parser.parse_args()
    if not 1 <= args.limit <= 20 or not 0 <= args.image_limit <= 5:
        parser.error("limit 1..20, image-limit 0..5 required")
    published = {r["deviceId"] for r in json.loads(
        (bot.MEDIA / "device_media_manifest.json").read_text())["entries"]}
    if args.names:
        names = list(dict.fromkeys(args.names))[:args.limit]
    else:
        # Official indexed missing-model leads are preferred, not numeric page ranges.
        index_path = bot.BOT / "output/official-index-report.json"
        if not index_path.exists():
            parser.error("Run indexed-discover first, or pass --name")
        index = json.loads(index_path.read_text())
        names = list(dict.fromkeys(
            p["missingDevices"][0]["name"] for p in index["products"] if p["missingDevices"]
        ))[:args.limit]
    markets = ("malaysia", "iraq") if args.market == "both" else (args.market,)
    raise SystemExit(run(names, markets, args.image_limit))


if __name__ == "__main__":
    cli()
