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
