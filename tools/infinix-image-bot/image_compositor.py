#!/usr/bin/env python3
"""Vendor-neutral rear-left/front-right RGBA phone photo compositor.

Uses only original image pixels and preserves aspect ratio. Model, color,
licensing and provenance approvals are the responsibility of brand adapters.
"""
from __future__ import annotations
from PIL import Image

CANVAS=(960,960)


def compose_photos(back: Image.Image, front: Image.Image,
                   canvas: tuple[int,int]=CANVAS, overlap_fraction:float=.09) -> Image.Image:
    if back.width <= 0 or back.height <= 0 or front.width <= 0 or front.height <= 0:
        raise ValueError("empty source")
    if len(canvas)!=2 or not (300<=canvas[0]<=2000 and 300<=canvas[1]<=2000):
        raise ValueError("unsafe export canvas")
    if not 0<=overlap_fraction<=.20:
        raise ValueError("overlap must be between 0 and 20%")
    tw,th=canvas
    height=min(round(th*.82),round(min(back.height,front.height)*1.10))
    widths=[round(back.width*height/back.height),round(front.width*height/front.height)]
    overlap=round(min(widths)*overlap_fraction)
    joined=sum(widths)-overlap
    if joined>tw*.88:
        height=round(height*(tw*.88)/joined)
    if height<=0:
        raise ValueError("sources cannot fit inside canvas")
    def scale(source:Image.Image)->Image.Image:
        nw=max(1,round(source.width*height/source.height))
        return source.convert("RGBA").resize((nw,height),Image.Resampling.LANCZOS)
    rear=scale(back)
    screen=scale(front)
    overlap=round(min(rear.width,screen.width)*overlap_fraction)
    width=rear.width+screen.width-overlap
    if width>tw-28 or height>th-28:
        raise ValueError("composite geometry outside output")
    output=Image.new("RGBA",canvas,(0,0,0,0))
    x=(tw-width)//2
    y=(th-height)//2
    output.alpha_composite(rear,(x,y))
    output.alpha_composite(screen,(x+rear.width-overlap,y))
    return output


def normalize_presentation(image: Image.Image, *, max_dimension: int = 2500) -> Image.Image:
    """Lossless geometry: trim transparent space, retain every nonzero-alpha pixel.

    Only transparent padding is replaced. Source pixels, transparency, device
    silhouette, relative front/rear scale and aspect ratio remain unchanged.
    Padding is 1.5% of the visible long axis, identical on all four sides.
    The Android UI uses BoxFit.contain to fit this native-aspect-ratio output.
    """
    if image.width <= 0 or image.height <= 0 or image.width * image.height > 12_000_000:
        raise ValueError("unsafe source image dimensions")
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] == 255:
        raise ValueError("opaque source is not verified transparent")
    # Any >0 alpha is part of the original; a higher threshold would risk
    # cropping faint anti-aliasing and shadows along the phone silhouette.
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("empty source image")
    subject = rgba.crop(bbox)
    if min(subject.size) < 180 or max(subject.size) < 300:
        raise ValueError("visible subject resolution too low")
    margin = max(4, round(max(subject.size) * .015))
    width, height = subject.width + 2 * margin, subject.height + 2 * margin
    if max(width, height) > max_dimension:
        raise ValueError("preview dimensions exceed size budget")
    result = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    result.paste(subject, (margin, margin))  # Exact RGBA copy, including faint edges
    return result
