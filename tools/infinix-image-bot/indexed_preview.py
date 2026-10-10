"""Create explicit numbered source-image comparison sheets for HUMAN visual review.

Never claims front/back automatically. Only previously verified official model pages.
"""
import json
import hashlib
import io
from pathlib import Path

from PIL import Image, ImageDraw
import bot
import multimarket_scan as mm


def main():
    report = json.loads((bot.BOT / "output/multimarket-review.json").read_text())
    base = bot.BOT / "output" / "numbered-review"
    base.mkdir(exist_ok=True)
    success = 0
    for entry in report["candidatesForReview"]:
        slides = []
        code = entry["modelCode"]
        for n, info in enumerate(entry["images"]):
            if not (info.get("downloadOk") and info.get("minimum650")
                    and info.get("sourceSha256")):
                continue
            region = info["market"]
            raw, actual = mm.get(info["url"], mm.MAX_IMAGE_BYTES, mm.MARKETS[region][1])
            if hashlib.sha256(raw).hexdigest() != info["sourceSha256"]:
                raise ValueError("image changed after initial audit")
            photo = Image.open(io.BytesIO(raw))
            photo.load()
            photo.thumbnail((270, 250))
            slides.append((n, photo.convert("RGBA"), info))
        sheet = Image.new("RGB", (5 * 282, 310), "white")
        pen = ImageDraw.Draw(sheet)
        for i, (n, im, info) in enumerate(slides[:5]):
            x = i * 282
            sheet.paste(im, (x + (282 - im.width) // 2, 3), im)
            pen.text((x + 4, 262), f"{code} | IMAGE INDEX {n}", fill="#111")
            pen.text((x + 4, 282), f"{info['size'][0]}x{info['size'][1]} | {info['market']}", fill="#111")
        target = base / f"{code}-source-options.jpg"
        sheet.save(target, quality=88)
        success += 1
        print("REVIEW_SHEET",entry["name"],code,str(target),len(slides),flush=True)
    print("COMPLETED",success)


if __name__ == "__main__":
    main()
