#!/usr/bin/env python3
"""Human-selected verified Infinix photo -> staged transparent PNG.

This is not publish, does not alter manifest/approved.json, and appends an audit.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
import bot
import multimarket_scan as mm


def stage(model_code: str, index: int) -> dict:
    review_path=bot.BOT/"output/multimarket-review.json"
    data=json.loads(review_path.read_text())
    candidates=[c for c in data["candidatesForReview"] if c["modelCode"]==model_code]
    if len(candidates)!=1:
        raise ValueError("expected one verified candidate for model code")
    device=candidates[0]
    if len(bot.BY_CODE.get(model_code,[]))!=1 or bot.BY_CODE[model_code][0]["deviceId"]!=device["deviceId"]:
        raise ValueError("model code is ambiguous or identity changed")
    if index<0 or index>=len(device["images"]):
        raise ValueError("image index not found")
    image=device["images"][index]
    if not(image.get("downloadOk") and image.get("minimum650") and image.get("transparent")):
        raise ValueError("image is not fully downloaded, transparent, or high resolution")
    published={x["deviceId"] for x in json.loads(
        (bot.MEDIA/"device_media_manifest.json").read_text())["entries"]}
    if device["deviceId"] in published:
        raise ValueError("already published, refusing duplicate stage")
    if not any(s["market"]==image["market"] and s["sourceEvidenceLevel"]=="api_and_detail_sku_and_name"
               for s in device["sources"]):
        raise ValueError("no authoritative source supporting product code")
    raw,url=mm.get(image["url"],mm.MAX_IMAGE_BYTES,mm.MARKETS[image["market"]][1])
    source_digest=hashlib.sha256(raw).hexdigest()
    if source_digest!=image["sourceSha256"]:
        raise ValueError("source bytes changed after review")
    im=Image.open(io.BytesIO(raw))
    im.load()
    cropped=bot.crop_png(im)
    prepared_sha=hashlib.sha256(cropped).hexdigest()
    target_name=f"Alwan-Infinix-{model_code}-front-back-REVIEW.png"
    target_path=bot.BOT/"output/staged-review-images"/target_name
    target_path.parent.mkdir(exist_ok=True)
    downloads=Path.home()/"storage/downloads"/target_name
    for file in (target_path,downloads):
        if file.exists() and hashlib.sha256(file.read_bytes()).hexdigest()!=prepared_sha:
            raise ValueError("existing file differs; no silent overwrite: "+str(file))
        file.write_bytes(cropped)
    audit_file=bot.BOT/"output/selected-review-audit.json"
    audit=json.loads(audit_file.read_text()) if audit_file.exists() else {"items":[],"summary":{}}
    previous=[x for x in audit["items"] if x["deviceId"]==device["deviceId"]]
    if previous and previous[0]["stagedSha256"]!=prepared_sha:
        raise ValueError("existing audited image differs; manual review needed")
    if not previous:
        official_page=next(s["officialPageUrl"] for s in device["sources"] if s["market"]==image["market"])
        audit["items"].append({
            "deviceId":device["deviceId"],"name":device["name"],"modelCode":model_code,
            "selectedSourceIndex":index,"market":image["market"],"officialPageUrl":official_page,
            "sourceUrl":url,"sourceSha256":source_digest,
            "stagedFile":target_name,"stagedSha256":prepared_sha,
            "frontAndBackVisualInspection":"assistant_confirmed_for_review_only",
            "userApproved":False,"redistributionRightsVerified":False,"publishable":False,
        })
    audit["summary"]={"modelsStagedForReview":len(audit["items"]), "published":0,
                      "userApproved":0,"rightsVerified":0}
    audit_file.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n")
    return {"modelCode":model_code, "deviceId":device["deviceId"],
            "file":str(downloads),"sha256":prepared_sha}


def stage_model_evidence(model_code: str, index: int) -> dict:
    """Stage an explicitly visually inspected composite from corroborated
    OFFICIAL model-code image filenames; publication remains disabled.
    """
    import official_model_evidence as evidence
    report=json.loads((bot.BOT/"output/official-model-evidence.json").read_text())
    matches=[x for x in report["candidatesForVisualReview"] if x["modelCode"]==model_code]
    if len(matches)!=1:
        raise ValueError("exactly one verified model-evidence candidate required")
    candidate=matches[0]
    if len(bot.BY_CODE.get(model_code,[]))!=1 or bot.BY_CODE[model_code][0]["deviceId"]!=candidate["deviceId"]:
        raise ValueError("modelCode/deviceId do not match the unique Infinix catalog entry")
    published={x["deviceId"] for x in json.loads(
        (bot.MEDIA/"device_media_manifest.json").read_text())["entries"]}
    if candidate["deviceId"] in published:
        raise ValueError("already published")
    if index<0 or index>=len(candidate["images"]):
        raise ValueError("invalid visual review image index")
    image=candidate["images"][index]
    if not(image.get("downloadOk") and image.get("minimum650") and image.get("transparent")):
        raise ValueError("source image insufficient resolution / transparency")
    source=next((s for s in candidate["verifiedOfficialPageSource"]
                 if s["market"]==image["market"] and image["url"] in s["images"]
                 and s["reason"]=="OFFICIAL_NAME_PLUS_EXACT_IMAGE_CODE"),None)
    if source is None:
        raise ValueError("image URL has no corroborating official source")
    if evidence.gallery_model_codes(source["images"])!={model_code}:
        raise ValueError("official gallery has conflicting or missing hardware model codes")
    if model_code not in evidence.gallery_model_codes([image["url"]]):
        raise ValueError("selected image filename does not prove exact hardware code")
    if source["deviceId"]!=candidate["deviceId"]:
        raise ValueError("source device identity differs from reviewed model")
    raw,url=mm.get(image["url"],mm.MAX_IMAGE_BYTES,mm.MARKETS[image["market"]][1])
    original_sha=hashlib.sha256(raw).hexdigest()
    if original_sha!=image["sourceSha256"]:
        raise ValueError("source changed since photo evidence scan")
    photo=Image.open(io.BytesIO(raw));photo.load()
    if min(photo.size)<650:
        raise ValueError("source dimensions changed / too small")
    compressed=bot.crop_png(photo)
    png_sha=hashlib.sha256(compressed).hexdigest()
    fname=f"Alwan-Infinix-{model_code}-front-back-REVIEW.png"
    staged=bot.BOT/"output/staged-review-images"/fname
    shared=Path.home()/"storage/downloads"/fname
    audit_file=bot.BOT/"output/selected-review-audit.json"
    audit=json.loads(audit_file.read_text())
    previous=[x for x in audit["items"] if x["deviceId"]==candidate["deviceId"]]
    if previous:
        if previous[0]["stagedSha256"]!=png_sha:
            raise ValueError("previous review image differs: no silent replacement")
        return {"modelCode":model_code,"file":str(shared),"alreadyPrepared":True}
    for target in (staged,shared):
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=png_sha:
            raise ValueError("filename already taken by a different review image")
    staged.parent.mkdir(exist_ok=True)
    for target in (staged,shared):
        target.write_bytes(compressed)
    audit["items"].append({
        "deviceId":candidate["deviceId"],"name":candidate["name"],
        "modelCode":model_code,"market":image["market"],
        "sourceEvidenceType":"official_name_plus_exact_model_code_in_gallery",
        "selectedSourceIndex":index,"officialPageUrl":source["officialPageUrl"],
        "sourceUrl":url,"sourceSha256":original_sha,
        "stagedFile":fname,"stagedSha256":png_sha,
        "frontAndBackVisualInspection":"assistant_confirmed_for_review_only",
        "userApproved":False,"redistributionRightsVerified":False,"publishable":False,
    })
    audit["summary"]={"modelsStagedForReview":len(audit["items"]),"published":0,
                      "userApproved":0,"rightsVerified":0}
    audit_file.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n")
    return {"modelCode":model_code,"file":str(shared),"preparedBytes":len(compressed),
            "reviewOnly":True,"sha256":png_sha}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--code",required=True)
    parser.add_argument("--image-index",type=int,required=True)
    parser.add_argument("--official-model-evidence",action="store_true",help="Use official model-code filename corroboration review report")
    arg=parser.parse_args()
    if arg.official_model_evidence:
        print(json.dumps(stage_model_evidence(arg.code,arg.image_index),ensure_ascii=False))
    else:
        print(json.dumps(stage(arg.code,arg.image_index),ensure_ascii=False))
