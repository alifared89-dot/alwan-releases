#!/usr/bin/env python3
"""Read-only official Infinix index discovery.

Sitemaps find real product LANDING pages by name, not verified hardware photos.
No SKU inference, front/back approval, manifest mutation, or publication.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import bot

SITEMAPS = {
    "malaysia": "https://wap.my.infinixmobility.com/sitemap.xml",
    "iraq": "https://www.infinixmobility.com/sitemap.xml",
}
HOSTS = {"wap.my.infinixmobility.com", "iq.infinixmobility.com", "www.infinixmobility.com"}
# Observed as the actual product-image CDN in official Infinix landing-page HTML.
IMAGE_HOSTS = HOSTS | {"d3o31au25zfcly.cloudfront.net"}
REFERENCES = {"malaysia": "hot-50-5g", "iraq": "smart-8"}
MAX_XML_BYTES = 350_000
MAX_HTML_BYTES = 1_500_000


def get_bytes(url: str, size: int) -> tuple[bytes, str, int]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS:
        raise ValueError("untrusted official page host")
    req = urllib.request.Request(url, headers={"User-Agent": bot.USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as response:
        redirected = response.geturl()
        dest = urllib.parse.urlsplit(redirected)
        if dest.scheme != "https" or dest.hostname not in HOSTS:
            raise ValueError("redirect left official hosts")
        payload = response.read(size + 1)
        if len(payload) > size:
            raise ValueError("official response too large")
        return payload, redirected, response.status


def normalize_name(value: str) -> str:
    name = urllib.parse.unquote(value).lower().strip()
    name = name.replace("+", "plus")
    name = re.sub(r"^\s*infinix[\s_-]*", "", name)
    return re.sub(r"[^a-z0-9]", "", name)


def valid_product_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS:
        return False
    if parsed.query or parsed.fragment or not parsed.path:
        return False
    parts = [p for p in parsed.path.split("/") if p]
    return len(parts) == 1


def parse_sitemap(data: bytes) -> tuple[list[str], int]:
    root = ET.fromstring(data)
    values = [el.text.strip() for el in root.iter()
              if el.tag.rsplit("}", 1)[-1] == "loc" and el.text]
    urls = list(dict.fromkeys(u for u in values if valid_product_url(u)))
    return urls, len(values) - len(urls)


def valid_preview_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return (parts.scheme == "https"
            and parts.hostname in IMAGE_HOSTS
            and (parts.path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
            and "/newfileadmin/" in parts.path)


class ProductImageHints(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        info = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag not in {"img", "source"}:
            return
        for field in ("data-src", "src", "data-original"):
            url = info.get(field) or ""
            if valid_preview_url(url) and url not in self.urls:
                self.urls.append(url)

    def handle_data(self, data: str):
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag: str):
        if tag == "title":
            self._in_title = False


def main(max_details: int = 12, selected_markets: tuple[str, ...] = tuple(SITEMAPS)) -> int:
    existing = {e["deviceId"] for e in json.loads(
        (bot.MEDIA / "device_media_manifest.json").read_text())["entries"]}
    catalog_by_name = defaultdict(list)
    for device in bot.CATALOG:
        catalog_by_name[normalize_name(device["name"])].append(device)

    markets: list[dict] = []
    by_slug: dict[str, dict] = {}
    for market in selected_markets:
        sitemap_url = SITEMAPS[market]
        item = {"market": market, "sitemapUrl": sitemap_url, "success": False}
        try:
            raw, final_url, status = get_bytes(sitemap_url, MAX_XML_BYTES)
            urls, rejected = parse_sitemap(raw)
            slugs = [urllib.parse.urlsplit(u).path.strip("/") for u in urls]
            item.update(success=True, httpStatus=status, sitemapPages=len(urls),
                        rejectedOrDuplicateUrls=rejected,
                        referencePresent=any(normalize_name(s) == normalize_name(REFERENCES[market])
                                             for s in slugs), finalUrl=final_url)
            for url, slug in zip(urls, slugs):
                key = normalize_name(slug)
                if key not in catalog_by_name:
                    continue
                info = by_slug.setdefault(key, {"productKey": key, "nameFromSitemap": slug,
                                                "catalogDevices": catalog_by_name[key],
                                                "sourcePages": []})
                if not any(x["url"] == url for x in info["sourcePages"]):
                    info["sourcePages"].append({"market": market, "url": url})
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        markets.append(item)

    products = []
    for key in sorted(by_slug):
        info = by_slug[key]
        all_devices = info.pop("catalogDevices")
        missing = [d for d in all_devices if d["deviceId"] not in existing]
        if not missing:
            state = "all_already_published"
        elif len(all_devices) > 1:
            state = "shared_name_requires_model_code"
        else:
            state = "name_only_requires_model_code"
        info.update(
            state=state,
            catalogDeviceIds=[d["deviceId"] for d in all_devices],
            publishedDeviceIds=[d["deviceId"] for d in all_devices if d["deviceId"] in existing],
            missingDevices=[{"deviceId": d["deviceId"], "name": d["name"],
                             "modelCodes": d["modelCodes"]} for d in missing],
            officialImageHints=[],
            modelCodeVerified=False,
            frontBackVerified=False,
            eligibleForPublication=False,
        )
        products.append(info)

    # Product landing pages contain marketing art, not trustworthy front/back media.
    # Fetch only a bounded number for REVIEW HINTS; never write approvals or archives.
    inspected = 0
    for item in products:
        if inspected >= max_details:
            break
        if not item["missingDevices"]:
            continue
        selected = item["sourcePages"][0]
        inspected += 1
        try:
            raw, redirected, status = get_bytes(selected["url"], MAX_HTML_BYTES)
            parser = ProductImageHints()
            parser.feed(raw.decode("utf-8", "replace"))
            item["landingInspection"] = {"url": selected["url"], "finalUrl": redirected,
                                         "httpStatus": status, "title": parser.title.strip()[:180],
                                         "officialImageHintsFound": len(parser.urls)}
            item["officialImageHints"] = parser.urls[:8]
        except Exception as exc:
            item["landingInspection"] = {
                "url": selected["url"], "error": f"{type(exc).__name__}: {str(exc)[:180]}"
            }

    covered_ids = {d["deviceId"] for p in products for d in p["missingDevices"]}
    missing_catalog = [d for d in bot.CATALOG if d["deviceId"] not in existing]
    coverage = [{
        "deviceId": d["deviceId"], "name": d["name"], "modelCodes": d["modelCodes"],
        "reason": ("official_name_indexed_but_hardware_code_unverified" if d["deviceId"] in covered_ids
                   else "not_listed_by_name_in_current_official_sitemaps"),
    } for d in missing_catalog]
    states = Counter(p["state"] for p in products)
    summary = {
        "catalogTotal": len(bot.CATALOG), "infinixPublished": len(existing & set(bot.BY_ID)),
        "catalogMissing": len(missing_catalog),
        "sitemapPages": sum(m.get("sitemapPages", 0) for m in markets),
        "productNamesMatched": len(products), "productNameStatuses": dict(sorted(states.items())),
        "missingDeviceIdsCoveredByOfficialNames": len(covered_ids),
        "missingDeviceIdsNotIndexedByName": len(missing_catalog) - len(covered_ids),
        "landingPagesInspected": inspected,
        "landingPagesWithPreviewHints": sum(bool(x["officialImageHints"]) for x in products),
        "hardwareVerifiedCandidates": 0, "publishableCandidates": 0,
        "referenceChecksPassed": sum(bool(x.get("referencePresent")) for x in markets),
        "referenceChecksTotal": len(selected_markets),
    }
    report = {"schemaVersion": 1, "createdAt": datetime.now(timezone.utc).isoformat(),
              "mode": "READ_ONLY_OFFICIAL_SITEMAP_DISCOVERY",
              "note": "Landing-page names and image hints are NOT sufficient to select a deviceId or publish media.",
              "markets": markets, "summary": summary,
              "products": products, "catalogMissingDeviceCoverage": coverage}
    path = bot.BOT / "output"
    path.mkdir(exist_ok=True)
    (path / "official-index-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not all(m.get("success") and m.get("referencePresent") for m in markets):
        print("ERROR: official sitemap fetch or known-reference check failed", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-details", type=int, default=12)
    args = parser.parse_args()
    if not 0 <= args.max_details <= 40:
        parser.error("--max-details must be between 0 and 40")
    raise SystemExit(main(max_details=args.max_details))
