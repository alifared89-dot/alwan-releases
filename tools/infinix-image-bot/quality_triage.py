"""Deterministic review prioritization, not recognition or photo approval.

Image metrics are objective: decoded pixels, alpha boundary, minimum source
resolution, original bytes + SHA. Filename is only a low-confidence hint.
The result is never used to auto-publish or assert that both views are present.
"""
from __future__ import annotations
import re
from urllib.parse import urlsplit
from pathlib import PurePosixPath
from PIL import Image

SUPPORTED = {"PNG", "JPEG", "WEBP"}


def inspect(image: Image.Image, info: dict, exact_code: str) -> dict:
    if not info.get("downloadOk"):
        return {"eligibleForReview": False, "reason": "source_download_failed", "priority": 0}
    if not info.get("sourceSha256"):
        return {"eligibleForReview": False, "reason": "missing_verified_source_digest", "priority": 0}
    name = PurePosixPath(urlsplit(info["url"]).path).name.lower()
    escaped = re.escape(exact_code.lower())
    if not re.search(r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])", name):
        return {"eligibleForReview":False, "reason":"file_does_not_match_hardware_model_code",
                "priority":0, "publishable":False}
    if min(image.size) < 650:
        return {"eligibleForReview":False, "reason":"resolution_below_650px",
                "tier":"high_resolution_source_search_reference_only",
                "referenceForHighResSearch": min(image.size) >= 300,
                "doNotUpscale":True, "publishable":False, "priority":0}
    alpha = image.convert("RGBA").getchannel("A")
    if alpha.getextrema()[0] == 255:
        return {"eligibleForReview": False, "reason": "opaque_background_requires_review_or_segmentation",
                "priority": 0}
    box = alpha.point(lambda a: 255 if a > 16 else 0).getbbox()
    if not box or min(box[2] - box[0], box[3] - box[1]) < 250:
        return {"eligibleForReview": False, "reason": "tiny_or_absent_phone_foreground", "priority": 0}
    bbox_fraction = ((box[2] - box[0]) * (box[3] - box[1])) / (image.width * image.height)
    if bbox_fraction < 0.06:
        return {"eligibleForReview": False, "reason": "suspiciously_small_foreground", "priority": 0}
    # Audit metric only; do NOT claim a two-sided phone from filename or geometry.
    long_side = max(image.size)
    score = 60 + min(20, round((min(image.size) - 650) / 35))
    if bbox_fraction > .55:
        score += 5
    if long_side >= 1200:
        score += 5
    return {
        "eligibleForReview": True, "reason": "pixel_checks_passed_human_views_still_required",
        "priority": min(score, 90), "alphaBBox": list(box),
        "foregroundFraction": round(bbox_fraction, 3),
        "minimumSide": min(image.size), "geometry": [image.width, image.height],
        "frontBackHumanVerificationRequired": True,
        "colorMatchHumanVerificationRequired": True, "publishable": False,
    }
