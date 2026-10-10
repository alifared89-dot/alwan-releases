#!/usr/bin/env python3
"""Small deterministic, integrity-checked source cache for local Termux processing.

Caches ONLY official allowlisted source URL evidence validated by existing
multimarket_scan. No scraping restriction bypass, no publication or deletions.
Cache is an optimization: integrity checks run on EVERY read. Incomplete cache
files never count as successes. All output is under ignored bot/output.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import io
import json
import os
import time
import uuid

from PIL import Image
import bot
import multimarket_scan as market

ROOT = bot.BOT / "output" / "source-cache"
DETAIL_TTL_SECONDS = 24 * 3600
IMAGE_TTL_SECONDS = 30 * 24 * 3600
MAX_IMAGE_BYTES = 6_000_000


class CacheIntegrityError(ValueError):
    pass


def cache_key(*parts: str) -> str:
    return sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def record_paths(kind: str, key: str) -> tuple[Path, Path]:
    if kind not in ("details", "assets"):
        raise ValueError("only official detail or asset evidence is cacheable")
    folder = ROOT / kind
    return folder / (key + ".json"), folder / (key + ".bin")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    try:
        with open(temp, "xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def read_detail(market_code: str, product_id: str, model_code: str, source_name: str,
                now: float | None = None) -> dict | None:
    key = cache_key(market_code, product_id, model_code, source_name)
    meta_path, _ = record_paths("details", key)
    if not meta_path.is_file():
        return None
    try:
        raw = meta_path.read_bytes()
        entry = json.loads(raw)
        date = time.time() if now is None else now
        if date - entry["fetchedAt"] > DETAIL_TTL_SECONDS:
            return None
        if entry["market"] != market_code or entry["productId"] != product_id:
            return None
        if entry["code"] != model_code or entry["sourceName"] != source_name:
            return None
        urls = entry["imageUrls"]
        if not urls or not all(is_official_gallery_url(u, market_code) for u in urls):
            return None
        # IMPORTANT: once more validate the filename codes before trusting cache.
        import official_model_evidence as ev
        if ev.gallery_model_codes(urls) != {model_code}:
            return None
        if entry["pageUrl"] != f"https://{market.MARKETS[market_code][0]}/shop/{product_id}":
            return None
        return entry
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_detail(market_code: str, product_id: str, model_code: str, source_name: str,
                 page_url: str, image_urls: list[str]) -> None:
    host = market.MARKETS[market_code][0]
    if page_url != f"https://{host}/shop/{product_id}":
        raise CacheIntegrityError("product page URL does not match verified official storefront")
    if not image_urls or not all(is_official_gallery_url(u, market_code) for u in image_urls):
        raise CacheIntegrityError("detail source has a foreign image domain")
    key = cache_key(market_code, product_id, model_code, source_name)
    meta, _ = record_paths("details", key)
    record = {"market": market_code, "productId": product_id, "code": model_code,
              "sourceName": source_name, "pageUrl": page_url, "imageUrls": image_urls,
              "fetchedAt": time.time()}
    _atomic_write(meta, json.dumps(record, ensure_ascii=False, sort_keys=True).encode())


def read_known_rejection(market_code: str, product_id: str, model_code: str,
                         source_name: str, now: float | None = None) -> dict | None:
    """Bounded negative cache: only actual official-page hardware code conflicts."""
    key = cache_key(market_code, product_id, model_code, source_name)
    filename = ROOT / "rejections" / (key + ".json")
    if not filename.is_file():
        return None
    try:
        row = json.loads(filename.read_text())
        t = time.time() if now is None else now
        if not (0 <= t - row["fetchedAt"] < 12 * 3600):
            return None
        if (row["market"], row["productId"], row["code"], row["sourceName"]) != \
           (market_code, product_id, model_code, source_name):
            return None
        if row["reason"] != "IMAGE_CODE_MISSING_OR_CONFLICTS":
            return None
        if row["pageUrl"] != f"https://{market.MARKETS[market_code][0]}/shop/{product_id}":
            return None
        return row
    except (OSError, ValueError, KeyError, TypeError):
        return None


def store_known_rejection(market_code: str, product_id: str, model_code: str,
                          source_name: str, page_url: str, gallery_codes: set[str]) -> None:
    if page_url != f"https://{market.MARKETS[market_code][0]}/shop/{product_id}":
        raise CacheIntegrityError("not an official product page")
    if gallery_codes == {model_code}:
        raise CacheIntegrityError("cannot reject correctly corroborated image gallery")
    key = cache_key(market_code, product_id, model_code, source_name)
    filename = ROOT / "rejections" / (key + ".json")
    record = {"market": market_code, "productId": product_id, "code": model_code,
              "sourceName": source_name, "pageUrl": page_url,
              "reason": "IMAGE_CODE_MISSING_OR_CONFLICTS",
              "galleryHardwareCodes": sorted(gallery_codes), "fetchedAt": time.time()}
    _atomic_write(filename, json.dumps(record, ensure_ascii=False, sort_keys=True).encode())


def is_official_gallery_url(url: str, market_code: str) -> bool:
    from urllib.parse import urlsplit
    if market_code not in market.MARKETS:
        return False
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname == market.MARKETS[market_code][1] and \
        parsed.path.startswith("/media/catalog/product/") and \
        parsed.path.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))


def cached_image(url: str, market_code: str, *, offline: bool = False,
                 now: float | None = None) -> tuple[dict, Image.Image | None]:
    """Returns mm.read_image-compatible metadata and a source PIL image.

    Cache miss must fetch via allowlisted official image transport. A corrupt
    cache is never accepted and in offline mode returns a failed evidence item.
    """
    if not is_official_gallery_url(url, market_code):
        raise ValueError("image URL must belong to the explicit official market CDN")
    key = cache_key(market_code, url)
    meta_path, data_path = record_paths("assets", key)
    now = time.time() if now is None else now
    if meta_path.is_file() and data_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            if (meta["url"] == url and meta["market"] == market_code
                    and now - meta["fetchedAt"] < IMAGE_TTL_SECONDS
                    and meta["sourceSha256"] and 0 < data_path.stat().st_size <= MAX_IMAGE_BYTES):
                raw = data_path.read_bytes()
                if sha256(raw).hexdigest() == meta["sourceSha256"]:
                    image = Image.open(io.BytesIO(raw))
                    image.load()
                    if list(image.size) == meta["size"]:
                        result = dict(meta["imageInfo"])
                        result["cacheHit"] = True
                        return result, image
        except (OSError, ValueError, KeyError, TypeError, Image.DecompressionBombError):
            pass
    if offline:
        return {"url": url, "downloadOk": False, "sourceSha256": None,
                "error": "no valid cached official image", "cacheHit": False}, None
    raw, destination = market.get(url, MAX_IMAGE_BYTES, market.MARKETS[market_code][1])
    pic = Image.open(io.BytesIO(raw))
    if pic.width * pic.height > 8_000_000:
        raise CacheIntegrityError("original image pixel budget exceeded")
    pic.load()
    alpha = pic.convert("RGBA").getchannel("A").getextrema()
    digest = sha256(raw).hexdigest()
    result = {"url": url, "downloadOk": True, "finalUrl": destination,
              "sourceSha256": digest, "bytes": len(raw), "size": list(pic.size),
              "mode": pic.mode, "transparent": alpha[0] == 0,
              "minimum650": min(pic.size) >= 650, "cacheHit": False}
    record = {"url": url, "market": market_code, "fetchedAt": now,
              "size": list(pic.size), "sourceSha256": digest, "imageInfo": result}
    # Data first; corrupted/incomplete metadata will never be reused.
    _atomic_write(data_path, raw)
    _atomic_write(meta_path, json.dumps(record, ensure_ascii=False, sort_keys=True).encode())
    return result, pic


def safe_image(url: str, market_code: str, *, offline: bool = False):
    try:
        return cached_image(url, market_code, offline=offline)
    except Exception as exc:
        return {"url": url, "downloadOk": False, "sourceSha256": None,
                "cacheHit": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}, None
