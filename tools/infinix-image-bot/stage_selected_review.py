#!/usr/bin/env python3
"""Stage only specifically visually-reviewed front+back images to phone Downloads.

This script NEVER adds approvals or publishes media; commercial image rights remain
unverified. Source SHA must match the official-host image observed in diagnostics.
"""
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
import bot
import multimarket_scan as mm

# Chosen by direct visual inspection of numbered official product gallery sheets.
# Index is an index within the report's verified per-device source-image list.
VISUALLY_SELECTED = {
    "X6858": 3,    # NOTE 50, gold, real front and rear in one source image
    "X6855": 4,    # NOTE 50 Pro, black, real front and rear in one image
    "X6856": 4,    # NOTE 50 Pro+ 5G, gold, real front and rear in one image
    "X6725B": 2,   # SMART 10 Plus, coral, real front and rear in one image
    "X1102": 2,    # XPAD 20, lilac, real front and rear in one image
}


def main() -> None:
    report_path = bot.BOT / "output/multimarket-review.json"
    report = json.loads(report_path.read_text())
    media = json.loads((bot.MEDIA / "device_media_manifest.json").read_text())
    published = {x["deviceId"] for x in media["entries"]}
    targets = bot.BOT / "output/staged-review-images"
    targets.mkdir(exist_ok=True)
    downloads = Path.home() / "storage/downloads"
    if not downloads.is_dir() or not downloads.stat().st_mode:
        raise RuntimeError("Shared Downloads folder is not available")
    audit = []
    for entry in report["candidatesForReview"]:
        code = entry["modelCode"]
        if code not in VISUALLY_SELECTED:
            continue
        idx = VISUALLY_SELECTED[code]
        if entry["deviceId"] in published:
            raise ValueError("device published since last discovery")
        if len(bot.BY_CODE.get(code, [])) != 1 or bot.BY_CODE[code][0]["deviceId"] != entry["deviceId"]:
            raise ValueError("model code no longer uniquely matches the catalog")
        if idx >= len(entry["images"]):
            raise ValueError(f"image index out of range for {code}")
        selected = entry["images"][idx]
        if not (selected["downloadOk"] and selected["minimum650"] and selected["transparent"]):
            raise ValueError(f"selected image does not meet quality checks: {code}")
        official = selected["market"]
        raw, final_url = mm.get(selected["url"], mm.MAX_IMAGE_BYTES, mm.MARKETS[official][1])
        digest = hashlib.sha256(raw).hexdigest()
        if digest != selected["sourceSha256"]:
            raise ValueError(f"source bytes changed: {code}")
        image = Image.open(io.BytesIO(raw))
        image.load()
        stage_data = bot.crop_png(image)
        name = f"Alwan-Infinix-{code}-front-back-REVIEW.png"
        local = targets / name
        local.write_bytes(stage_data)
        shared = downloads / name
        if shared.exists() and hashlib.sha256(shared.read_bytes()).digest() != hashlib.sha256(stage_data).digest():
            raise ValueError(f"file name conflict in Downloads for {code}")
        if not shared.exists():
            shared.write_bytes(stage_data)
        audit.append({
            "deviceId": entry["deviceId"], "name": entry["name"],
            "modelCode": code, "selectedSourceIndex": idx, "market": official,
            "officialPageUrl": next(s["officialPageUrl"] for s in entry["sources"] if s["market"] == official),
            "sourceUrl": final_url, "sourceSha256": digest,
            "stagedFile": name, "stagedSha256": hashlib.sha256(stage_data).hexdigest(),
            "frontAndBackVisualInspection": "assistant_confirmed_for_review_only",
            "userApproved": False, "redistributionRightsVerified": False,
            "publishable": False,
        })
        print("STAGED",code,entry["name"],len(stage_data),flush=True)
    if len(audit) != len(VISUALLY_SELECTED):
        raise ValueError(f"unexpected number of staged models: {len(audit)}")
    summary = {"modelsStagedForReview":len(audit), "published":0,
               "userApproved":0, "rightsVerified":0}
    (bot.BOT / "output/selected-review-audit.json").write_text(
        json.dumps({"summary":summary,"items":audit},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False))


if __name__ == "__main__":
    main()
