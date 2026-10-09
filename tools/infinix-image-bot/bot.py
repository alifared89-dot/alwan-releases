#!/usr/bin/env python3
"""Infinix image pipeline for GitHub Actions: discovery and explicitly approved publishing.

Image approval is an external human decision; this code NEVER treats an image as
front+back merely because the URL/title looks good.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BOT = Path(__file__).resolve().parent
MEDIA = ROOT / "device-media"
URL_BASE = "https://raw.githubusercontent.com/alifared89-dot/alwan-releases/main/device-media/"
HOST = "southeast-asia.pro.infinixmobility.com"
USER_AGENT = "Mozilla/5.0 (compatible; AlwanDeviceMedia/1.0)"
CATALOG = json.loads((BOT / "catalog-infinix.json").read_text())["devices"]
BY_ID = {d["deviceId"]: d for d in CATALOG}
BY_CODE = {}
for device in CATALOG:
    for model in device["modelCodes"]:
        BY_CODE.setdefault(model.upper(), []).append(device)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()

def fetch(url: str, limit: int = 6_000_000) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("HTTPS required")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=18) as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError("response over limit")
    return body

def normalized(value):
    return re.sub("[^a-z0-9]", "", value.lower())

# Color/storage storefront SKUs may suffix the immutable hardware model code.
# Only clearly identified cosmetic variants qualify; never strip arbitrary suffixes.
COLOR_VARIANTS = frozenset({
    "MEADOW", "NEON", "SHADOW", "SLEEK", "SOUL", "TITANIUM",
    "BLACK", "BLUE", "GREEN", "SILVER", "GOLD", "GREY", "GRAY",
    "WHITE", "PURPLE", "RED", "PINK", "ORANGE", "CYAN",
})

def match_storefront_code(raw_sku: str):
    sku = raw_sku.strip().upper()
    exact = BY_CODE.get(sku, [])
    if len(exact) == 1:
        return sku, exact[0], "exact"
    if exact:
        return None  # ambiguous model IDs are never auto-selected
    if "-" not in sku:
        return None
    base, suffix = sku.split("-", 1)
    matches = BY_CODE.get(base, [])
    if len(matches) == 1 and suffix in COLOR_VARIANTS:
        return base, matches[0], "verified_color_variant"
    return None

def official_page(page_id: int):
    page_url = f"https://wap.my.infinixmobility.com/shop/{page_id}"
    page = fetch(page_url, 1_300_000).decode("utf-8", "replace")
    t = re.search(r"<title>([^<]+)", page)
    title = html.unescape(t.group(1)) if t else ""
    skus = re.findall(r'(?i)(?:\\\"|")sku(?:\\\"|")\s*:\s*(?:\\\"|")([A-Z][A-Z0-9-]{3,15})', page)
    if not skus:
        skus = re.findall(r"(?i)extra_info:.{0,90}?sku.{0,12}?(X[0-9]{3,6}[A-Z]?)", page)
    matches = [match_storefront_code(c) for c in skus]
    matches = [m for m in matches if m is not None]
    if not matches:
        return None
    code, device, match_type = matches[0]
    if normalized(device["name"]) not in normalized(title):
        return None
    at = page.find("images:[{alt:")
    if at < 0:
        return None
    gallery = page[at:at + 14000]
    end = gallery.find("],level_price:")
    if end >= 0:
        gallery = gallery[:end]
    urls = re.findall(r'https:(?:\\u002F){2}[^" ]+?\.(?:png|jpg|webp)', gallery)
    unique = []
    for uri in urls:
        uri = uri.replace("\\u002F", "/")
        uri = re.sub(r"/cache/[a-f0-9]+(?=/)", "", uri)
        if uri.startswith(f"https://{HOST}/media/catalog/product/") and uri not in unique:
            unique.append(uri)
    return {"deviceId": device["deviceId"], "name": device["name"],
            "modelCode": code, "sourceSku": skus[0].upper(),
            "matchType": match_type,
            "sourcePageUrl": page_url, "imageUrls": unique[:10]}

def discover(start: int, stop: int, max_devices: int):
    if start < 1 or stop <= start or stop - start > 250:
        raise ValueError("discovery scans at most 250 pages per run")
    existing = {e["deviceId"] for e in json.loads((MEDIA / "device_media_manifest.json").read_text())["entries"]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(official_page, i): i for i in range(start, stop)}
        found = []
        failed = 0
        for task in concurrent.futures.as_completed(futures):
            try:
                result = task.result()
                if result and result["imageUrls"] and result["deviceId"] not in existing:
                    found.append(result)
            except Exception:
                failed += 1
    # Group repeated official storefront pages by exact immutable catalog ID.
    found.sort(key=lambda r: int(r["sourcePageUrl"].rsplit("/", 1)[-1]))
    unique = {r["deviceId"]: r for r in reversed(found)}
    results = list(reversed(list(unique.values())))[:max_devices]
    out = BOT / "output"
    out.mkdir(exist_ok=True)
    from PIL import ImageDraw
    thumbs = []
    for entry in results:
        try:
            body = fetch(entry["imageUrls"][0])
            entry["sourceSha256"] = sha(body)
            img = Image.open(io.BytesIO(body)).convert("RGBA")
            img.thumbnail((195, 195))
            thumbs.append((entry["name"] + " / " + entry["modelCode"], img))
        except Exception as exc:
            entry["imageError"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            continue
    # Never output an approvable candidate without a verified image hash.
    verified = [entry for entry in results if entry.get("sourceSha256")]
    rejected = [entry for entry in results if not entry.get("sourceSha256")]
    (out / "candidates.json").write_bytes(json_bytes(verified))
    (out / "rejected_candidates.json").write_bytes(json_bytes(rejected))
    cols = 5
    sheet = Image.new("RGB", (cols * 224, max(245, ((len(thumbs) + cols - 1) // cols) * 245)), "white")
    pen = ImageDraw.Draw(sheet)
    for i, (name, thumb) in enumerate(thumbs):
        x, y = (i % cols) * 224, (i // cols) * 245
        sheet.paste(thumb, (x + (224 - thumb.width) // 2, y), thumb)
        pen.text((x + 4, y + 202), name[:30], fill="#111111")
    sheet.save(out / "review_contact_sheet.jpg", quality=85)
    print(json.dumps({"matchedDevices": len(verified),
                      "discoveredBeforeImageVerification": len(results),
                      "rejectedCandidateImages": len(rejected),
                      "failedPages": failed,
                      "report": "output/candidates.json", "review": "output/review_contact_sheet.jpg"}))

def crop_png(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] != 0:
        raise ValueError("opaque source: background removal not verified, reject")
    box = alpha.point(lambda a: 255 if a > 12 else 0).getbbox()
    if box is None:
        raise ValueError("empty image")
    left, top, right, bottom = box
    margin = max(4, round(max(right - left, bottom - top) * 0.015))
    crop = rgba.crop((max(0, left - margin), max(0, top - margin),
                     min(rgba.width, right + margin), min(rgba.height, bottom + margin)))
    if min(crop.size) < 300:
        raise ValueError("crop resolution too low")
    buf = io.BytesIO()
    crop.save(buf, "PNG", optimize=True)
    return buf.getvalue()

def publish():
    approval_file = BOT / "approved.json"
    approvals = json.loads(approval_file.read_text())["items"]
    if not 1 <= len(approvals) <= 20:
        raise ValueError("approve between 1 and 20 images")
    media_path = MEDIA / "device_media_manifest.json"
    distribution_path = MEDIA / "distribution.json"
    manifest = json.loads(media_path.read_text())
    distribution = json.loads(distribution_path.read_text())
    previous = list(manifest["entries"])
    previous_chunks = list(distribution["chunks"])
    known = {entry["deviceId"] for entry in previous}
    seen = set()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    plans = []
    # Completely validate and download everything before writing publication files.
    for row in approvals:
        device_id = row["deviceId"]
        code = row["modelCode"].upper()
        image_url = row["imageUrl"]
        page = int(row["officialPageId"])
        expected_source_sha = row["sourceSha256"]
        if device_id in known or device_id in seen:
            raise ValueError("already published or duplicate device " + device_id)
        seen.add(device_id)
        device = BY_ID.get(device_id)
        if not device or code not in [c.upper() for c in device["modelCodes"]]:
            raise ValueError("catalog model code mismatch")
        if row.get("frontBackApproved") is not True:
            raise ValueError("human visual approval required")
        if not re.fullmatch("[0-9a-f]{64}", expected_source_sha):
            raise ValueError("sourceSha256 required")
        official = official_page(page)
        if not official or official["deviceId"] != device_id or image_url not in official["imageUrls"]:
            raise ValueError("official page and exact image URL mismatch")
        original = fetch(image_url)
        if sha(original) != expected_source_sha:
            raise ValueError("image content changed since review")
        im = Image.open(io.BytesIO(original))
        im.load()
        if min(im.size) < 650:
            raise ValueError("image too small")
        payload = crop_png(im)
        filename = f"infinix-{code.lower()}-frontback.png"
        chunk_id = f"infinix-{code.lower()}-{sha(payload)[:12]}"
        dest = MEDIA / "chunks" / (chunk_id + ".zip")
        if dest.exists():
            raise ValueError("chunk already exists")
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as z:
            z.writestr(filename, payload)
        archive = zipped.getvalue()
        plans.append((row, code, payload, filename, chunk_id, dest, archive))
    # Write only after passing all validations. Workflow keeps approval files out of published commit.
    for row, code, payload, filename, chunk_id, dest, archive in plans:
        dest.write_bytes(archive)
        manifest["entries"].append({
            "deviceId": row["deviceId"], "revision": f"infinix-official-{code.lower()}-frontback-v1",
            "view": "frontBack", "filename": filename, "chunkId": chunk_id,
            "sha256": sha(payload), "bytes": len(payload),
            "sourcePageUrl": f'https://wap.my.infinixmobility.com/shop/{int(row["officialPageId"])}',
            "creator": "Infinix official product image", "licenseId": "usage-rights-not-verified",
            "attribution": "Infinix official image; rights not independently verified",
            "verifiedModelCodes": [code], "checkedAt": now})
        distribution["chunks"].append({
            "chunkId": chunk_id, "url": URL_BASE + "chunks/" + dest.name,
            "compressedBytes": len(archive), "uncompressedBytes": len(payload), "sha256": sha(archive)})
    manifest["manifestVersion"] += 1
    manifest["generatedAt"] = now
    packed = json_bytes(manifest)
    distribution["mediaManifest"]["bytes"] = len(packed)
    distribution["mediaManifest"]["sha256"] = sha(packed)
    assert manifest["entries"][:len(previous)] == previous
    assert distribution["chunks"][:len(previous_chunks)] == previous_chunks
    media_path.write_bytes(packed)
    distribution_path.write_bytes(json_bytes(distribution))
    print(f"Staged publication: {len(plans)} images; total: {len(manifest['entries'])}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["discover", "publish"])
    parser.add_argument("--start", type=int, default=550)
    parser.add_argument("--stop", type=int, default=750)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.mode == "discover":
        discover(args.start, args.stop, args.limit)
    else:
        publish()
