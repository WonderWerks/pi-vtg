#!/usr/bin/env python3
"""Projector / display alignment patterns, drawn at the display's native
resolution so every line lands on a real pixel.

Each pattern is drawn inside an "active area" of the chosen aspect ratio,
centered in the raster (letterboxed or pillarboxed, black outside), so a
2.39:1 screen can be framed on a 16:9 projector, etc.

Generated on demand with Pillow and cached in /tmp (RAM), so nothing is
written to the SD card. Run directly to test:
    python3 patterns.py grid 2.39 1920 1080
"""
import sys
from pathlib import Path

CACHE = Path("/tmp/vtg-patterns")

# (key, label, ratio or None for the full raster)
ASPECTS = [
    ("full", "Full screen (native)", None),
    ("16x9", "16:9 (1.78:1)", 16 / 9),
    ("16x10", "16:10 (1.60:1)", 16 / 10),
    ("4x3", "4:3 (1.33:1)", 4 / 3),
    ("5x4", "5:4 (1.25:1)", 5 / 4),
    ("1.85", "1.85:1 (flat)", 1.85),
    ("1.90", "1.90:1 (DCI 17:9)", 256 / 135),
    ("2.00", "2.00:1 (Univisium)", 2.0),
    ("2.35", "2.35:1 (scope)", 2.35),
    ("2.39", "2.39:1 (scope)", 2.39),
    ("21x9", "21:9 (2.37:1)", 64 / 27),
    ("32x9", "32:9 (3.56:1)", 32 / 9),
]

PATTERNS = [
    ("grid", "Alignment grid (squares, circles, center)"),
    ("frame", "Screen framing (edges + corner marks)"),
    ("overscan", "Overscan / safe areas (1, 2.5, 5, 10%)"),
    ("crosshatch", "Crosshatch (convergence / keystone)"),
    ("focus", "Focus (fine lines + text)"),
    ("steps", "Grayscale steps (brightness / contrast)"),
    ("white", "Full white (uniformity / hot spots)"),
    ("gray", "50% gray"),
    ("red", "Red field"),
    ("green", "Green field"),
    ("blue", "Blue field"),
    ("black", "Full black (black level / light leak)"),
]

FIELDS = {"white": (255, 255, 255), "gray": (128, 128, 128), "red": (255, 0, 0),
          "green": (0, 255, 0), "blue": (0, 0, 255), "black": (0, 0, 0)}
WHITE, GRAY, BLACK = (255, 255, 255), (110, 110, 110), (0, 0, 0)
ACCENT = (255, 200, 0)


def active_area(w, h, ratio):
    if ratio is None:
        return 0, 0, w, h
    if w / h > ratio:           # pillarbox
        aw, ah = round(h * ratio), h
    else:                        # letterbox
        aw, ah = w, round(w / ratio)
    return (w - aw) // 2, (h - ah) // 2, aw, ah


def font(size):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)   # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def label(draw, cx, cy, text, size, fill=WHITE, bg=BLACK):
    f = font(size)
    l, t, r, b = draw.textbbox((0, 0), text, font=f)
    tw, th = r - l, b - t
    pad = size // 3
    x, y = cx - tw // 2, cy - th // 2
    draw.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], fill=bg)
    draw.text((x - l, y - t), text, font=f, fill=fill)


def rect(draw, x0, y0, x1, y1, fill, width=1):
    """Outline whose outer edge is exactly x0..x1-1 / y0..y1-1."""
    draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=fill, width=width)


def draw_grid(d, x, y, w, h, s):
    cell = h / 8                      # square cells, 8 rows tall
    cols = max(2, round(w / cell))
    cw = w / cols
    for i in range(cols + 1):
        X = min(x + round(i * cw), x + w - 1)
        d.line([X, y, X, y + h - 1], fill=WHITE)
    for j in range(9):
        Y = min(y + round(j * cell), y + h - 1)
        d.line([x, Y, x + w - 1, Y], fill=WHITE)
    cx, cy = x + w // 2, y + h // 2
    r = h // 2 - 1                    # big circle touches top and bottom
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACCENT, width=max(1, s // 2))
    rc = round(cell * 0.9)            # corner circles: check linearity
    for qx in (x + rc, x + w - 1 - rc):
        for qy in (y + rc, y + h - 1 - rc):
            d.ellipse([qx - rc, qy - rc, qx + rc, qy + rc], outline=ACCENT, width=max(1, s // 2))
    t = max(3, s)                     # center cross
    d.rectangle([cx - t // 2, y, cx + t // 2, y + h - 1], fill=ACCENT)
    d.rectangle([x, cy - t // 2, x + w - 1, cy + t // 2], fill=ACCENT)
    rect(d, x, y, x + w, y + h, WHITE, width=max(2, s))


def draw_frame(d, x, y, w, h, s):
    rect(d, x, y, x + w, y + h, WHITE, width=1)            # exact 1px edge
    L, t = h // 6, max(4, s * 2)                           # corner L marks
    for (px, sx) in ((x, 1), (x + w - 1, -1)):
        for (py, sy) in ((y, 1), (y + h - 1, -1)):
            d.rectangle(sorted_box(px, py, px + sx * L, py + sy * t), fill=ACCENT)
            d.rectangle(sorted_box(px, py, px + sx * t, py + sy * L), fill=ACCENT)
    cx, cy = x + w // 2, y + h // 2                        # center + edge midpoints
    d.line([cx - L // 2, cy, cx + L // 2, cy], fill=WHITE, width=max(1, s // 2))
    d.line([cx, cy - L // 2, cx, cy + L // 2], fill=WHITE, width=max(1, s // 2))
    for (ax, ay, bx, by) in ((cx, y, cx, y + L // 2), (cx, y + h - 1, cx, y + h - 1 - L // 2),
                             (x, cy, x + L // 2, cy), (x + w - 1, cy, x + w - 1 - L // 2, cy)):
        d.line([ax, ay, bx, by], fill=ACCENT, width=t)


def sorted_box(x0, y0, x1, y1):
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def draw_overscan(d, x, y, w, h, s):
    for pct, col in ((0, WHITE), (1, (255, 80, 80)), (2.5, ACCENT), (5, (80, 220, 80)), (10, (80, 160, 255))):
        ix, iy = round(w * pct / 100), round(h * pct / 100)
        rect(d, x + ix, y + iy, x + w - ix, y + h - iy, col, width=1 if pct == 0 else max(1, s // 2))
    cx, cy = x + w // 2, y + h // 2
    # Labels just inside each box's left edge, stepped down so they don't collide
    for k, (pct, col) in enumerate(((1, (255, 80, 80)), (2.5, ACCENT), (5, (80, 220, 80)), (10, (80, 160, 255)))):
        ix = round(w * pct / 100)
        label(d, x + ix + s * 22, cy - s * 30 + k * s * 20, f"{pct}%", s * 9, fill=col)
    d.line([cx - s * 10, cy, cx + s * 10, cy], fill=WHITE)
    d.line([cx, cy - s * 10, cx, cy + s * 10], fill=WHITE)


def draw_crosshatch(d, x, y, w, h, s):
    n = 16
    for i in range(n + 1):
        X = min(x + round(i * w / n), x + w - 1)
        d.line([X, y, X, y + h - 1], fill=WHITE)
    rows = max(2, round(n * h / w))
    for j in range(rows + 1):
        Y = min(y + round(j * h / rows), y + h - 1)
        d.line([x, Y, x + w - 1, Y], fill=WHITE)


def draw_focus(d, x, y, w, h, s):
    b = h // 5                                 # patch size
    spots = [(x + w // 2, y + h // 2), (x + b, y + b), (x + w - b, y + b),
             (x + b, y + h - b), (x + w - b, y + h - b)]
    for (cx, cy) in spots:
        # Four quadrants of 1px-on / 1px-off lines: vertical in top-left and
        # bottom-right, horizontal in top-right and bottom-left. Sharp focus
        # = every line distinct; soft = gray mush.
        half = b // 2
        for i in range(0, half, 2):
            d.line([cx - half + i, cy - half, cx - half + i, cy - 1], fill=WHITE)   # TL vertical
            d.line([cx + i, cy, cx + i, cy + half - 1], fill=WHITE)                 # BR vertical
            d.line([cx, cy - half + i, cx + half - 1, cy - half + i], fill=WHITE)   # TR horizontal
            d.line([cx - half, cy + i, cx - 1, cy + i], fill=WHITE)                 # BL horizontal
        rect(d, cx - half - 1, cy - half - 1, cx + half + 1, cy + half + 1, GRAY)
    for k, size in enumerate((s * 5, s * 7, s * 10)):
        label(d, x + w // 2, y + h // 2 + b // 2 + size * 2 + k * size * 2,
              "The quick brown fox jumps over the lazy dog 0123456789", size)


def draw_steps(d, x, y, w, h, s):
    n = 11                                     # 0, 10, ... 100%
    for i in range(n):
        v = round(255 * i / (n - 1))
        x0, x1 = x + round(i * w / n), x + round((i + 1) * w / n)
        d.rectangle([x0, y, x1 - 1, y + h * 2 // 3 - 1], fill=(v, v, v))
        label(d, (x0 + x1) // 2, y + h * 2 // 3 + s * 8, f"{i * 10}%", s * 7)
    ramp_y = y + h * 2 // 3 + s * 17            # smooth ramp underneath
    for X in range(x, x + w):
        v = round(255 * (X - x) / max(1, w - 1))
        d.line([X, ramp_y, X, y + h - 1], fill=(v, v, v))


DRAW = {"grid": draw_grid, "frame": draw_frame, "overscan": draw_overscan,
        "crosshatch": draw_crosshatch, "focus": draw_focus, "steps": draw_steps}


def make(pattern, aspect, w, h):
    """Return the path to a PNG for this pattern/aspect at w x h."""
    from PIL import Image, ImageDraw
    ratios = {k: r for k, _, r in ASPECTS}
    if pattern not in dict(PATTERNS) or aspect not in ratios:
        raise ValueError("unknown pattern or aspect")
    w, h = int(w), int(h)
    out = CACHE / f"{pattern}_{aspect}_{w}x{h}.png"
    if out.exists():
        return out
    CACHE.mkdir(exist_ok=True)

    img = Image.new("RGB", (w, h), BLACK)
    d = ImageDraw.Draw(img)
    x, y, aw, ah = active_area(w, h, ratios[aspect])
    s = max(1, h // 540)                       # line/text scale: 2 at 1080p, 4 at 2160p

    if pattern in FIELDS:
        d.rectangle([x, y, x + aw - 1, y + ah - 1], fill=FIELDS[pattern])
    else:
        DRAW[pattern](d, x, y, aw, ah, s)
        if pattern not in ("focus", "steps"):  # info label, center-low
            name = dict((k, l) for k, l, _ in ASPECTS)[aspect]
            label(d, x + aw // 2, y + ah * 3 // 4, f"{name}   active {aw}x{ah}   output {w}x{h}", s * 10)

    tmp = out.with_suffix(".tmp.png")
    img.save(tmp, optimize=False)
    tmp.replace(out)
    return out


if __name__ == "__main__":
    print(make(*sys.argv[1:5]))
