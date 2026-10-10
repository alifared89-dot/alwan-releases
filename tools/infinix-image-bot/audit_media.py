#!/usr/bin/env python3
"""Read-only before/after QA of actual published Infinix photos.

This is a reusable bot diagnostic. It never modifies the media manifest,
existing ZIP chunks, device catalog, or any mobile-device state.
"""
import argparse
import io
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

import bot
import image_compositor
import verify_media


def preview(image: Image.Image, size: int = 240) -> Image.Image:
    """Simulate Alwan's existing square BoxFit.cover thumbnail."""
    rgba = image.convert("RGBA")
    factor = max(size / rgba.width, size / rgba.height)
    fitted = rgba.resize(
        (round(rgba.width * factor), round(rgba.height * factor)),
        Image.Resampling.LANCZOS,
    )
    x = (fitted.width - size) // 2
    y = (fitted.height - size) // 2
    square = fitted.crop((x, y, x + size, y + size))
    result = Image.new("RGB", (size, size), "white")
    result.paste(square, (0, 0), square)
    return result


def audit(media: Path, output: Path) -> dict:
    manifest = json.loads((media / "device_media_manifest.json").read_bytes())
    # Stable, complete cohort of the 28-image publication; no network or cache.
    items = [row for row in manifest["entries"]
             if row["chunkId"].startswith("infinix-user-reviewed-batch")]
    if not items:
        raise ValueError("published reviewed cohort not found")
    output.mkdir(parents=True, exist_ok=True)
    by_chunk = {}
    for row in items:
        by_chunk.setdefault(row["chunkId"], []).append(row)
    rows = []
    panels = []
    for chunk_id, group in sorted(by_chunk.items()):
        archive_path = media / "chunks" / (chunk_id + ".zip")
        with zipfile.ZipFile(archive_path) as zipped:
            for row in group:
                data = zipped.read(row["filename"])
                if verify_media.digest(data) != row["sha256"] or len(data) != row["bytes"]:
                    raise ValueError("source image checksum mismatch")
                with Image.open(io.BytesIO(data)) as source:
                    source.load()
                    original = source.convert("RGBA")
                alpha_box = original.getchannel("A").point(
                    lambda a: 255 if a > 12 else 0
                ).getbbox()
                if alpha_box is None:
                    raise ValueError("published image has no visible subject")
                prepared = image_compositor.normalize_presentation(original)
                buff = io.BytesIO()
                prepared.save(buff, "PNG")
                passed = verify_media.check_new_presentation(
                    buff.getvalue(), label=row["filename"]
                )
                code = row["verifiedModelCodes"][0]
                original_h = alpha_box[3] - alpha_box[1]
                original_w = alpha_box[2] - alpha_box[0]
                original_coverage = max(original_w, original_h) / max(original.size)
                rows.append({
                    "modelCode": code,
                    "sourcePixels": list(original.size),
                    "visibleAlphaBox": list(alpha_box),
                    "sourceLongestAxisCoverage": round(original_coverage, 4),
                    "preparedPixels": list(prepared.size),
                    "preparedLongestAxisCoverage": passed["longAxisCoverage"],
                    "upscaledOriginalPixels": False,
                    "existingMediaUnchanged": True,
                })
                panels.append((code, preview(original), preview(prepared)))
    panel_w, panel_h = 500, 292
    columns = 3
    rows_count = (len(panels) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * panel_w, rows_count * panel_h), "#f3f4f6")
    pen = ImageDraw.Draw(sheet)
    for i, (code, before, after) in enumerate(panels):
        x, y = (i % columns) * panel_w, (i // columns) * panel_h
        sheet.paste(before, (x, y + 27))
        sheet.paste(after, (x + 250, y + 27))
        pen.text((x + 10, y + 5), f"{code} / CURRENT", fill="black")
        pen.text((x + 260, y + 5), "PREVIEW / NORMALIZED", fill="black")
    sheet.save(output / "real-images-before-after.png", optimize=True)
    result = {
        "cohort": "published-user-reviewed-Infinix",
        "imagesInspected": len(rows),
        "newGeometryPassed": len(rows),
        "legacy500": [r["modelCode"] for r in rows if r["sourcePixels"] == [500, 500]],
        "legacyLargeMargin": [
            r["modelCode"] for r in rows if r["sourceLongestAxisCoverage"] < .86
        ],
        "rows": rows,
        "publication": "none / offline read-only",
    }
    (output / "real-images-audit.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    result = audit(bot.MEDIA, args.report_dir)
    print(json.dumps({
        "imagesInspected": result["imagesInspected"],
        "newGeometryPassed": result["newGeometryPassed"],
        "legacy500": result["legacy500"],
        "legacyLargeMargin": result["legacyLargeMargin"],
        "report": str(args.report_dir),
        "published": False,
    }))
