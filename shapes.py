"""Anti-aliased rounded rectangles for tkinter canvases (pure Python, no Pillow).

Tk canvases do not anti-alias, so rounded shapes drawn with ovals/polygons look jagged. Instead we draw solid
middle rectangles and place small pre-rendered corner images (PNG with alpha) that blend into whatever is behind.
"""
import base64
import struct
import tkinter as tk
import zlib

PNG_SIGNATURE = bytes([137, 80, 78, 71, 13, 10, 26, 10])
FILTER_NONE = bytes([0])

_IMG = {}   # (color, radius, corner) -> PhotoImage (kept alive here so Tk does not drop it)
_COV = {}   # radius -> coverage grid of the top-left corner


def _chunk(tag, data):
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _png_rgba(w, h, rows):
    raw = b"".join(FILTER_NONE + row for row in rows)
    return (PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b""))


def _coverage(r, ss=6):
    """Fraction (0..1) of each pixel of the top-left r x r quadrant that lies inside a circle of radius r."""
    grid = []
    for j in range(r):
        row = []
        for i in range(r):
            hit = 0
            for sj in range(ss):
                for si in range(ss):
                    x, y = i + (si + 0.5) / ss, j + (sj + 0.5) / ss
                    if (x - r) ** 2 + (y - r) ** 2 <= r * r:
                        hit += 1
            row.append(hit / (ss * ss))
        grid.append(row)
    return grid


def _corner(c, color, r, kind):
    key = (id(c.tk), color, r, kind)   # images belong to one Tk interpreter
    if key not in _IMG:
        if r not in _COV:
            _COV[r] = _coverage(r)
        cov = _COV[r]
        red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        rows = []
        for j in range(r):
            row = bytearray()
            for i in range(r):
                ci = i if kind[1] == "l" else r - 1 - i   # mirror for the right-hand corners
                cj = j if kind[0] == "t" else r - 1 - j   # mirror for the bottom corners
                row += bytes((red, green, blue, int(round(cov[cj][ci] * 255))))
            rows.append(bytes(row))
        _IMG[key] = tk.PhotoImage(master=c, data=base64.b64encode(_png_rgba(r, r, rows)))
    return _IMG[key]


def round_rect(c, x1, y1, x2, y2, r, fill="#ffffff", tags=(), **_):
    """Rounded rectangle on canvas `c`; `fill` must be a #rrggbb color."""
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    r = int(max(1, min(r, (x2 - x1) // 2, (y2 - y1) // 2)))
    kw = dict(fill=fill, outline="", width=0, tags=tags)
    c.create_rectangle(x1 + r - 1, y1, x2 - r + 1, y2, **kw)               # centre column, full height
    if y2 - y1 > 2 * r:
        c.create_rectangle(x1, y1 + r - 1, x1 + r, y2 - r + 1, **kw)       # left strip
        c.create_rectangle(x2 - r, y1 + r - 1, x2, y2 - r + 1, **kw)       # right strip
    for kind, (px, py) in (("tl", (x1, y1)), ("tr", (x2 - r, y1)), ("bl", (x1, y2 - r)), ("br", (x2 - r, y2 - r))):
        c.create_image(px, py, anchor="nw", image=_corner(c, fill, r, kind), tags=tags)


def pill_shape(c, x1, y1, x2, y2, fill, tags=()):
    """Fully rounded (stadium) shape."""
    round_rect(c, x1, y1, x2, y2, (y2 - y1) // 2, fill=fill, tags=tags)
