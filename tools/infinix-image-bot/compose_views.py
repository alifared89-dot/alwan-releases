#!/usr/bin/env python3
"""One transparent front+rear composition from two human-labelled source photos.

Fail closed on SKU, photo identity, color, untrusted evidence, insufficient image
quality, and non-uniform backgrounds. Never generate physical device details.
Both source roles must be explicitly confirmed; do not infer from filename.
No manifest changes, no publication; outputs are REVIEW ONLY.
"""
from __future__ import annotations
from collections import deque
from hashlib import sha256
import argparse
import io
import json
from pathlib import Path

from PIL import Image, ImageOps

import bot
import image_compositor

CANVAS = (960, 960)
MIN_SOURCE_SIDE = 450
MAX_PIXELS = 8_000_000
MAX_BG_PIXELS = 2_500_000  # Python flood-fill must remain bounded on Termux
MAX_SOURCE_BYTES = 10_000_000
COLOR_DIST = 23
OUTPUT_DIR = bot.BOT / "output" / "composites"


class UnsafeImage(ValueError):
    pass


def load_verified_photo(record: dict, required_role: str, model_code: str, device_id: str,
                        color_key: str) -> tuple[Image.Image, dict]:
    if record.get("role") != required_role or record.get("modelCode") != model_code:
        raise UnsafeImage("image role or model code mismatch")
    if record.get("deviceId") != device_id or record.get("colorKey") != color_key:
        raise UnsafeImage("device identity or color mismatch")
    if not record.get("productEvidenceUrl") or not str(record["productEvidenceUrl"]).startswith("https://"):
        raise UnsafeImage("verified product evidence URL required")
    if record.get("visualRoleVerified") is not True or record.get("modelMatchVerified") is not True:
        raise UnsafeImage("front/rear/model evidence needs explicit human verification")
    source = Path(record.get("localPath", "")).expanduser().resolve()
    if not source.is_relative_to(bot.BOT / "output") or not source.is_file():
        raise UnsafeImage("source must be an already-downloaded file inside the private staging output")
    if source.stat().st_size > MAX_SOURCE_BYTES:
        raise UnsafeImage("source image exceeds byte budget")
    data = source.read_bytes()
    digest = sha256(data).hexdigest()
    if digest != record.get("sourceSha256"):
        raise UnsafeImage("photo source digest mismatch")
    try:
        pic = Image.open(io.BytesIO(data))
        if pic.width * pic.height > MAX_PIXELS:
            raise UnsafeImage("source image dimensions exceed processing budget")
        pic.load()
    except (OSError, Image.DecompressionBombError) as exc:
        raise UnsafeImage("invalid source image") from exc
    if min(pic.size) < MIN_SOURCE_SIDE:
        raise UnsafeImage("original photo resolution too low")
    pic = ImageOps.exif_transpose(pic).convert("RGBA")
    if pic.getchannel("A").getextrema()[0] == 255:
        pic = remove_white_background(pic)
    return crop_object(pic), {"role":required_role,"sourceSha256":digest,"sourceFile":source.name,
                              "evidence":record["productEvidenceUrl"],"colorKey":color_key}


def remove_white_background(pic: Image.Image) -> Image.Image:
    """Conservative connected-background removal, never erase interior whites.

    Only nearly-white neutral flat studio backdrops. No segmentation guessing
    on complex/colorful/gradient backgrounds: those stay in human review.
    """
    w,h = pic.size
    if w*h > MAX_BG_PIXELS:
        raise UnsafeImage("opaque image too large for safe CPU segmentation")
    pixels = pic.load()
    corners = [pixels[x,y][:3] for x,y in ((0,0),(w-1,0),(0,h-1),(w-1,h-1))]
    if not all(min(c)>=242 and max(c)-min(c)<=12 for c in corners):
        raise UnsafeImage("opaque source has non-white or non-uniform background")
    reference = tuple(round(sum(c[i] for c in corners)/4) for i in range(3))
    def is_bg(x:int,y:int)->bool:
        r,g,b,_ = pixels[x,y]
        return max(abs(r-reference[0]),abs(g-reference[1]),abs(b-reference[2]))<=COLOR_DIST
    # Detect edges that aren't uniform before destructive changes.
    edge = [(x,0) for x in range(0,w,max(1,w//16))]
    edge += [(x,h-1) for x in range(0,w,max(1,w//16))]
    edge += [(0,y) for y in range(0,h,max(1,h//16))]
    edge += [(w-1,y) for y in range(0,h,max(1,h//16))]
    if sum(is_bg(x,y) for x,y in edge)/len(edge)<.93:
        raise UnsafeImage("object touches edge / backdrop is not homogeneous")
    # Flood fill from all four true corners: white parts inside device remain.
    visited = bytearray(w*h)
    queue=deque()
    for x,y in ((0,0),(w-1,0),(0,h-1),(w-1,h-1)):
        n=y*w+x
        visited[n]=1
        queue.append((x,y))
    cleared=0
    while queue:
        x,y=queue.popleft()
        if not is_bg(x,y):
            continue
        pixels[x,y]=(0,0,0,0)
        cleared+=1
        for xx,yy in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if 0<=xx<w and 0<=yy<h:
                pos=yy*w+xx
                if not visited[pos]:
                    visited[pos]=1
                    if is_bg(xx,yy):
                        queue.append((xx,yy))
    if not .06 < cleared/(w*h) < .97:
        raise UnsafeImage("uncertain background/object coverage")
    return pic


def crop_object(pic: Image.Image) -> Image.Image:
    alpha=pic.getchannel("A")
    box=alpha.point(lambda x: 255 if x>16 else 0).getbbox()
    if not box:
        raise UnsafeImage("photo has no visible object")
    cropped=pic.crop(box)
    if min(cropped.size)<180:
        raise UnsafeImage("cropped device is too small")
    return cropped


def compose(back: Image.Image, front: Image.Image) -> Image.Image:
    """Compatibility wrapper around the brand-neutral media compositor."""
    return image_compositor.compose_photos(back,front,canvas=CANVAS)


def execute(evidence:dict,output_name:str|None=None)->dict:
    code=str(evidence.get("modelCode") or "").upper()
    device_id=str(evidence.get("deviceId") or "")
    matches=bot.BY_CODE.get(code,[])
    if len(matches)!=1 or matches[0]["deviceId"]!=device_id:
        raise UnsafeImage("model code is not unique or does not match the Infinix catalog")
    approved={x["deviceId"] for x in json.loads(
        (bot.MEDIA/"device_media_manifest.json").read_text())["entries"]}
    if device_id in approved:
        raise UnsafeImage("already published: refusing silent replacement")
    color_key=str(evidence.get("colorKey") or "").strip().upper()
    if not color_key or color_key in ("UNKNOWN","N/A","MULTICOLOR"):
        raise UnsafeImage("exact color must be specified and verified")
    sources=evidence.get("sources") or []
    if len(sources)!=2 or {s.get("role") for s in sources}!={"front","back"}:
        raise UnsafeImage("two distinct front and rear evidence records required")
    photos={}
    metadata={}
    for role in ("front","back"):
        record=next(s for s in sources if s["role"]==role)
        photos[role],metadata[role]=load_verified_photo(record,role,code,device_id,color_key)
    if metadata["front"]["sourceSha256"]==metadata["back"]["sourceSha256"]:
        raise UnsafeImage("front/back files have identical bytes; wrong input pairing")
    # Both confirmed pictures can be from different retailers but must share model and color.
    im=compose(photos["back"],photos["front"])
    buff=io.BytesIO()
    im.save(buff,"PNG",optimize=True)
    payload=buff.getvalue()
    filename=output_name or f"{code}-front-back-composite-REVIEW.png"
    if Path(filename).name!=filename or not filename.endswith(".png"):
        raise UnsafeImage("invalid destination filename")
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    path=OUTPUT_DIR/filename
    if path.exists() and path.read_bytes()!=payload:
        raise UnsafeImage("existing output differs; no overwrite without review")
    path.write_bytes(payload)
    audit={"deviceId":device_id,"modelCode":code,"name":matches[0]["name"],
           "colorKey":color_key,"outputFile":str(path),
           "outputSha256":sha256(payload).hexdigest(),"size":list(im.size),
           "sourceEvidence":[metadata["back"],metadata["front"]],
           "humanReviewNeeded":True,"publishable":False,"published":False}
    (OUTPUT_DIR/(filename+".json")).write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n")
    return audit


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("evidence_json",type=Path)
    args=parser.parse_args()
    print(json.dumps(execute(json.loads(args.evidence_json.read_text())),ensure_ascii=False))
