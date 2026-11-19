"""Generate assets/icon.ico (16-256 px) and assets/icon.png for Pico Companion. Pure Python, no Pillow.

Run:  python tools/make_icon.py

The icon is a rounded square in the app's blue-to-purple gradient with three white sliders (the app changes settings).
Each size is rendered separately with supersampling so the edges are smooth.
"""
import math
import os
import struct
import zlib

SIZES = (16, 24, 32, 48, 64, 128, 256)
TOP, BOTTOM = (0x66, 0x7E, 0xEA), (0x76, 0x4B, 0xA2)     # the app's gradient
WHITE = (255, 255, 255)
# slider rows: (y centre, thumb x, all as fractions of the icon size)
SLIDERS = ((0.30, 0.66), (0.50, 0.36), (0.70, 0.74))


def inside_round_rect(x, y, x1, y1, x2, y2, r):
    if x < x1 or x > x2 or y < y1 or y > y2:
        return False
    cx = min(max(x, x1 + r), x2 - r)
    cy = min(max(y, y1 + r), y2 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def sample(x, y):
    """RGBA at a point of the unit square (x, y in 0..1), or None if transparent."""
    if not inside_round_rect(x, y, 0.04, 0.04, 0.96, 0.96, 0.22):
        return None
    t = (x + y) / 2                                   # diagonal gradient
    color = tuple(a + (b - a) * t for a, b in zip(TOP, BOTTOM))
    for cy, tx in SLIDERS:
        half = 0.035                                  # track half-height
        if inside_round_rect(x, y, 0.20, cy - half, 0.80, cy + half, half):
            filled = x <= tx
            alpha = 1.0 if filled else 0.38
            color = tuple(c + (w - c) * alpha for c, w in zip(color, WHITE))
        if (x - tx) ** 2 + (y - cy) ** 2 <= 0.085 ** 2:   # round thumb
            color = WHITE
    return color


def render(size, ss=4):
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0.0
            for sy in range(ss):
                for sx in range(ss):
                    c = sample((px + (sx + 0.5) / ss) / size, (py + (sy + 0.5) / ss) / size)
                    if c:
                        r += c[0]; g += c[1]; b += c[2]; a += 1
            n = ss * ss
            if a:
                row += bytes((round(r / a), round(g / a), round(b / a), round(255 * a / n)))
            else:
                row += bytes((0, 0, 0, 0))
        rows.append(bytes(row))
    return rows


def png(size, rows):
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(bytes([0]) + r for r in rows)
    return (bytes([137, 80, 78, 71, 13, 10, 26, 10]) + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(images):
    """images: list of (size, png_bytes). PNG-compressed entries are supported by Windows Vista and later."""
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return head + entries + blobs


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
    os.makedirs(out, exist_ok=True)
    images = [(s, png(s, render(s))) for s in SIZES]
    with open(os.path.join(out, "icon.ico"), "wb") as f:
        f.write(ico(images))
    with open(os.path.join(out, "icon.png"), "wb") as f:
        f.write(images[-1][1])
    print("wrote", os.path.normpath(out), [s for s, _ in images])
