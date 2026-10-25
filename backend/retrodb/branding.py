"""Dependency-free RetroDB brand assets for Safari, iOS Home Screen and browsers."""
import struct
import zlib
from functools import lru_cache

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter(include_in_schema=False)

SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<rect width="100" height="100" rx="22" fill="#10192d"/>
<rect x="13" y="19" width="74" height="62" rx="18" fill="#243655" stroke="#5b8eff" stroke-width="4"/>
<circle cx="31" cy="40" r="10" fill="#8ab5ff"/>
<path d="M31 33v14M24 40h14" stroke="#10213e" stroke-width="4" stroke-linecap="round"/>
<circle cx="63" cy="35" r="5" fill="#60e8c6"/>
<circle cx="72" cy="44" r="5" fill="#60e8c6"/>
<rect x="40" y="58" width="20" height="5" rx="2" fill="#99b6dd"/>
</svg>'''

def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

@lru_cache(maxsize=3)
def png_icon(size: int) -> bytes:
    """Small flat controller emblem with no external image/font dependency."""
    import math
    colors = dict(bg=(16,25,45),body=(36,54,85),edge=(91,142,255),
                  pad=(138,181,255),dark=(16,33,62),button=(96,232,198),
                  line=(153,182,221))
    def rounded_box(x, y, l, t, r, b, rad):
        dx = max(l+rad-x, 0, x-(r-rad))
        dy = max(t+rad-y, 0, y-(b-rad))
        return dx*dx+dy*dy <= rad*rad and l <= x <= r and t <= y <= b
    def inside(x, y, cx, cy, radius):
        return (x-cx)**2+(y-cy)**2 <= radius**2
    rows=[]
    for py in range(size):
        line=bytearray(b"\\x00")
        y=(py+0.5)*100/size
        for px in range(size):
            x=(px+0.5)*100/size
            c=colors["bg"]
            if rounded_box(x,y,11,17,89,83,20): c=colors["edge"]
            if rounded_box(x,y,13,19,87,81,18): c=colors["body"]
            if inside(x,y,31,40,10): c=colors["pad"]
            if 29 <= x <= 33 and 33 <= y <= 47 or 24 <= x <= 38 and 38 <= y <= 42: c=colors["dark"]
            if inside(x,y,63,35,5) or inside(x,y,72,44,5): c=colors["button"]
            if rounded_box(x,y,40,58,60,63,2): c=colors["line"]
            line.extend(c)
        rows.append(bytes(line))
    raw=b"".join(rows)
    return (b"\\x89PNG\\r\\n\\x1a\\n"+_chunk(b"IHDR",struct.pack(">IIBBBBB",size,size,8,2,0,0,0))
            +_chunk(b"IDAT",zlib.compress(raw,9))+_chunk(b"IEND",b""))

@router.get("/favicon.svg")
def favicon():
    return Response(SVG,media_type="image/svg+xml",headers={"Cache-Control":"public, max-age=86400"})

@router.get("/apple-touch-icon.png")
def apple_icon():
    return Response(png_icon(180),media_type="image/png",headers={"Cache-Control":"public, max-age=86400"})

@router.get("/icons/icon-{size}.png")
def icon(size: int):
    if size not in (192,512):
        return Response(status_code=404)
    return Response(png_icon(size),media_type="image/png",headers={"Cache-Control":"public, max-age=86400"})

@router.get("/manifest.webmanifest")
def manifest():
    return Response('{"name":"RetroDB","short_name":"RetroDB","start_url":"/","scope":"/",'
                    '"display":"standalone","background_color":"#10192d","theme_color":"#10192d",'
                    '"icons":[{"src":"/icons/icon-192.png","sizes":"192x192","type":"image/png"},'
                    '{"src":"/icons/icon-512.png","sizes":"512x512","type":"image/png"}]}',
                    media_type="application/manifest+json",headers={"Cache-Control":"public, max-age=86400"})
