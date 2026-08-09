#!/usr/bin/env python3
"""
Hidden Character Scene Maker
============================
A desktop tool for building dense, seek-and-find style scenes ("hidden picture"
puzzles) from YOUR OWN images, with a printable coordinate grid so finds can be
verified ("it's in F7").

QUICK START
-----------
    pip install pillow
    python scene_maker.py

On first run the app creates an `assets/` folder next to this script:

    assets/
      sprites/            <- background objects, organized however you like
        trees/            <- each subfolder is a category
        vehicles/
        creatures/
        anything_else/
      characters/         <- the characters you'll HIDE (transparent PNGs)
      sprites.json        <- optional per-category settings (see README.txt)

Drop transparent PNGs into those folders, hit "Rescan", then "Generate scene".
If you have no sprites yet, a small set of built-in placeholder scenery is used
so you can play with the tool immediately.

WORKFLOW
--------
1. Generate a scene (seed + sliders control the look; same seed = same scene).
2. Pick a character in the list and DOUBLE-CLICK the scene to place it.
3. Drag to move. Mouse wheel resizes. R / Shift+R rotates. F flips. Del removes.
4. Export the puzzle PNG (with the coordinate border) and the answer key
   (PNG with circles + JSON + on-screen list of grid cells).

The status bar always shows the grid cell under your cursor, so when a player
says "found it in K4!" you can hover there and check, or open the answer key.
"""

import json
import math
import os
import random
import sys

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
except ImportError:  # pragma: no cover
    print("This tool needs Pillow.  Install it with:\n    pip install pillow")
    sys.exit(1)

# GUI imports are optional at module level so the generator can also be used
# headlessly (e.g. from other scripts).  main() checks HAS_TK before starting.
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import ImageTk
    HAS_TK = True
except Exception:  # pragma: no cover
    HAS_TK = False

# ---------------------------------------------------------------- compat ----
RES = Image.Resampling if hasattr(Image, "Resampling") else Image
FLIP_LR = (Image.Transpose.FLIP_LEFT_RIGHT
           if hasattr(Image, "Transpose") else Image.FLIP_LEFT_RIGHT)

# ---------------------------------------------------------------- paths -----
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(APP_DIR, "assets")
SPRITE_DIR = os.path.join(ASSET_DIR, "sprites")
CHAR_DIR = os.path.join(ASSET_DIR, "characters")
OUT_DIR = os.path.join(APP_DIR, "output")

IMG_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".bmp")
MAX_SRC_SIDE = 900          # loaded sprites are downscaled to this, for speed

README_TEXT = """\
HOW TO FEED THIS TOOL
=====================
sprites/     Background objects. Every SUBFOLDER is a category (trees, cars,
             rocks, dinosaurs... anything). Transparent PNGs look best; images
             without transparency will appear as rectangles.
characters/  The things you plan to HIDE. Transparent PNGs, roughly square-ish.

TIP FOR HARD PUZZLES: also drop a few near-lookalikes of your character into a
sprites/decoys/ folder. A character that shares colors with the crowd is far
harder to spot than a unique one.

OPTIONAL sprites.json (place next to this README):
{
  "trees":    {"weight": 3, "size": 0.17, "cluster": 0.85},
  "vehicles": {"weight": 1, "size": 0.12, "cluster": 0.6, "band": [0.3, 1.0]},
  "birds":    {"weight": 0.5, "size": 0.05, "band": [0.0, 0.25]}
}
  weight   how often the category is picked (default 1)
  size     object height as a fraction of scene height (default 0.13)
  cluster  0..1 tendency to bunch into groups (default 0.5)
  band     [top, bottom] vertical zone it may occupy, 0=top 1=bottom
"""

SPRITES_JSON_EXAMPLE = {
    "trees": {"weight": 3, "size": 0.17, "cluster": 0.85},
    "vehicles": {"weight": 1, "size": 0.12, "cluster": 0.6, "band": [0.3, 1.0]},
}

# ---------------------------------------------------------------- palettes --
PALETTES = {
    "Meadow": dict(
        base=(116, 158, 78), alt=(97, 137, 65),
        blotches=[(150, 186, 102), (86, 124, 56), (134, 172, 92), (160, 190, 96)],
        water=(64, 141, 176), water_hi=(158, 212, 230), shore=(197, 179, 129),
        water_amt=0.16,
        path=(209, 191, 149), path_edge=(165, 147, 107),
        speck_dark=(58, 88, 42), speck_light=(178, 208, 134),
        tuft=(70, 108, 48),
        flowers=[(233, 90, 100), (241, 215, 92), (240, 240, 242), (181, 121, 221)],
        trail=None,
    ),
    "Beach": dict(
        base=(233, 211, 159), alt=(219, 195, 141),
        blotches=[(243, 226, 180), (206, 181, 126), (228, 205, 150)],
        water=(60, 158, 189), water_hi=(190, 233, 244), shore=(246, 234, 198),
        water_amt=0.30,
        path=(205, 181, 133), path_edge=(173, 149, 103),
        speck_dark=(168, 140, 92), speck_light=(250, 240, 205),
        tuft=(167, 151, 97),
        flowers=[],
        trail=(190, 165, 114),
    ),
    "Desert": dict(
        base=(223, 179, 121), alt=(204, 158, 102),
        blotches=[(235, 196, 140), (188, 141, 88), (214, 172, 116)],
        water=(72, 152, 161), water_hi=(180, 226, 230), shore=(232, 205, 150),
        water_amt=0.05,
        path=(191, 151, 97), path_edge=(157, 120, 74),
        speck_dark=(158, 116, 70), speck_light=(244, 213, 158),
        tuft=(151, 133, 81),
        flowers=[(221, 82, 92)],
        trail=None,
    ),
    "Snow": dict(
        base=(238, 244, 250), alt=(221, 231, 242),
        blotches=[(250, 253, 255), (206, 220, 235), (232, 240, 248)],
        water=(150, 191, 214), water_hi=(232, 246, 252), shore=(199, 216, 231),
        water_amt=0.12,
        path=(211, 223, 235), path_edge=(178, 194, 211),
        speck_dark=(173, 190, 207), speck_light=(255, 255, 255),
        tuft=None,
        flowers=[],
        trail=(196, 209, 224),
    ),
    "Autumn": dict(
        base=(173, 145, 85), alt=(147, 111, 63),
        blotches=[(197, 121, 61), (151, 97, 51), (191, 161, 91), (206, 140, 66)],
        water=(70, 130, 151), water_hi=(170, 214, 226), shore=(186, 158, 108),
        water_amt=0.14,
        path=(197, 173, 129), path_edge=(158, 133, 92),
        speck_dark=(112, 82, 44), speck_light=(224, 196, 128),
        tuft=(121, 97, 53),
        flowers=[(207, 121, 51), (181, 71, 41), (225, 171, 71)],
        trail=None,
    ),
}

SIZES = {
    "1600 x 1000": (1600, 1000),
    "2000 x 1300": (2000, 1300),
    "2600 x 1700": (2600, 1700),
    "3200 x 2000": (3200, 2000),
}

# ---------------------------------------------------------------- helpers ---


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def col_name(i):
    """0 -> A, 25 -> Z, 26 -> AA ... (spreadsheet style)."""
    i += 1
    s = ""
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def cell_label(x, y, cell):
    return "%s%d" % (col_name(int(x // cell)), int(y // cell) + 1)


def cells_range(bbox, cell, W, H):
    x0, y0, x1, y1 = bbox
    x0 = clamp(x0, 0, W - 1); x1 = clamp(x1, 0, W - 1)
    y0 = clamp(y0, 0, H - 1); y1 = clamp(y1, 0, H - 1)
    a = cell_label(x0, y0, cell)
    b = cell_label(x1, y1, cell)
    return a if a == b else "%s-%s" % (a, b)


_FONT_CACHE = {}


def load_font(size):
    size = int(size)
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    candidates = ["arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf",
                  "DejaVuSans.ttf", "Arial Bold.ttf", "Arial.ttf",
                  "Helvetica.ttc", "segoeui.ttf"]
    font = None
    for name in candidates:
        try:
            font = ImageFont.truetype(name, size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size)
        except Exception:
            font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


# ---------------------------------------------------------------- noise -----


def value_noise(W, H, seed, octaves=((6, 4), (12, 8), (24, 16)),
                weights=(0.5, 0.35, 0.22)):
    """Smooth grayscale noise built from upscaled random grids (no numpy)."""
    rng = random.Random(seed)
    acc = None
    for (gw, gh), w in zip(octaves, weights):
        small = Image.new("L", (gw, gh))
        small.putdata([rng.randrange(256) for _ in range(gw * gh)])
        layer = small.resize((W, H), RES.BICUBIC)
        acc = layer if acc is None else Image.blend(acc, layer, w)
    return acc


def soft_mask(noise, lo, hi, invert=False):
    """Map noise into a 0..255 mask with a soft ramp between lo..hi (0..1)."""
    lo_i, hi_i = int(lo * 255), int(hi * 255)
    span = max(1, hi_i - lo_i)

    def f(v, lo_i=lo_i, hi_i=hi_i, span=span, invert=invert):
        if v <= lo_i:
            t = 0
        elif v >= hi_i:
            t = 255
        else:
            t = (v - lo_i) * 255 // span
        return 255 - t if invert else t

    return noise.point(f)


# ---------------------------------------------------------------- terrain ---


def make_terrain(W, H, seed, pal, detail01):
    """Layered procedural ground: tone blending, blotches, water bodies with
    shorelines and ripples, winding paths with pebbles, tufts, flowers,
    speckle grain and optional dotted trails.  Returns (RGB image, water mask).
    """
    rng = random.Random("terrain|%s" % seed)
    det = 0.35 + 1.65 * detail01

    bg = Image.new("RGB", (W, H), pal["base"])

    # --- large-scale tone variation -------------------------------------
    n1 = value_noise(W, H, rng.random())
    alt = Image.new("RGB", (W, H), pal["alt"])
    m = soft_mask(n1, 0.42, 0.72).point(lambda v: int(v * 0.6))
    bg = Image.composite(alt, bg, m)

    # --- soft organic blotches (drawn at half res: same look, 4x faster) --
    hW, hH = W // 2, H // 2
    blot = Image.new("RGBA", (hW, hH), (0, 0, 0, 0))
    db = ImageDraw.Draw(blot)
    for _ in range(int(70 * det)):
        c = rng.choice(pal["blotches"])
        a = rng.randint(26, 68)
        rx = rng.randint(int(hW * 0.03), int(hW * 0.11))
        ry = rng.randint(9, int(hH * 0.07))
        x, y = rng.randint(-30, hW + 30), rng.randint(-20, hH + 20)
        db.ellipse([x - rx, y - ry, x + rx, y + ry], fill=c + (a,))
    blot = blot.filter(ImageFilter.GaussianBlur(4))
    blot = blot.resize((W, H), RES.BILINEAR)
    bg = Image.alpha_composite(bg.convert("RGBA"), blot).convert("RGB")

    # --- water bodies ----------------------------------------------------
    wmask = Image.new("L", (W, H), 0)
    if pal.get("water") and pal["water_amt"] > 0:
        wn = value_noise(W, H, rng.random(),
                         octaves=((5, 3), (10, 6)), weights=(0.6, 0.4))
        t = pal["water_amt"]
        wmask = soft_mask(wn, t, t + 0.10, invert=True)
        wmask = wmask.filter(ImageFilter.GaussianBlur(3))

        # wet shoreline ring around the water
        edge = wmask.filter(ImageFilter.FIND_EDGES).filter(
            ImageFilter.GaussianBlur(4))
        edge = edge.point(lambda v: min(255, v * 3))
        shore = Image.new("RGB", (W, H), pal["shore"])
        bg = Image.composite(shore, bg, edge.point(lambda v: int(v * 0.75)))

        water = Image.new("RGB", (W, H), pal["water"])
        bg = Image.composite(water, bg, wmask)

        # ripples / sparkle inside the water
        rip = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(rip)
        for _ in range(int(W * H / 16000 * det)):
            x, y = rng.randrange(W), rng.randrange(H)
            if wmask.getpixel((x, y)) > 150:
                ln = rng.randint(10, 44)
                dr.line([x, y, x + ln, y + rng.randint(-2, 2)],
                        fill=pal["water_hi"] + (rng.randint(90, 170),),
                        width=rng.choice((1, 2)))
        bg = Image.alpha_composite(bg.convert("RGBA"), rip).convert("RGB")

    # --- winding path(s) -------------------------------------------------
    paths = 1 + (1 if W >= 2200 and rng.random() < 0.7 else 0)
    pth = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dp = ImageDraw.Draw(pth)
    all_pts = []
    for _ in range(paths):
        pts = []
        x = rng.uniform(W * 0.15, W * 0.85)
        y = H + 40.0
        while y > -40:
            pts.append((x, y))
            y -= (H / 9.0) * rng.uniform(0.7, 1.2)
            x = clamp(x + rng.uniform(-W * 0.13, W * 0.13), 30, W - 30)
        wpx = max(18, int(H * 0.045))
        dp.line(pts, fill=pal["path_edge"] + (255,), width=wpx + 8, joint="curve")
        dp.line(pts, fill=pal["path"] + (255,), width=wpx, joint="curve")
        all_pts.append(pts)
    pth = pth.filter(ImageFilter.GaussianBlur(1))
    bg = Image.alpha_composite(bg.convert("RGBA"), pth).convert("RGB")

    # --- fine detail pass (one RGBA overlay) -----------------------------
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    do = ImageDraw.Draw(ov)

    def on_land(x, y):
        return wmask.getpixel((int(clamp(x, 0, W - 1)),
                               int(clamp(y, 0, H - 1)))) < 110

    # speckle grain
    for _ in range(int(W * H / 850 * det)):
        x, y = rng.randrange(W), rng.randrange(H)
        c = pal["speck_dark"] if rng.random() < 0.55 else pal["speck_light"]
        s = rng.choice((1, 1, 2))
        do.ellipse([x, y, x + s, y + s], fill=c + (rng.randint(70, 150),))

    # grass tufts
    if pal.get("tuft"):
        for _ in range(int(W * H / 2400 * det)):
            x, y = rng.uniform(0, W), rng.uniform(H * 0.05, H)
            if not on_land(x, y):
                continue
            persp = 0.5 + 0.8 * (y / H)
            for k in (-1, 0, 1):
                ln = rng.uniform(5, 11) * persp
                do.line([x, y, x + k * ln * 0.45, y - ln],
                        fill=pal["tuft"] + (rng.randint(140, 210),), width=2)

    # flowers / fallen leaves
    for _ in range(int(W * H / 9000 * det)):
        if not pal["flowers"]:
            break
        x, y = rng.uniform(0, W), rng.uniform(H * 0.05, H)
        if not on_land(x, y):
            continue
        c = rng.choice(pal["flowers"])
        r = rng.uniform(1.6, 3.2)
        for a in range(4):
            ang = a * math.pi / 2 + rng.uniform(-0.3, 0.3)
            do.ellipse([x + math.cos(ang) * r - r * 0.7,
                        y + math.sin(ang) * r - r * 0.7,
                        x + math.cos(ang) * r + r * 0.7,
                        y + math.sin(ang) * r + r * 0.7],
                       fill=c + (225,))
        do.ellipse([x - r * 0.5, y - r * 0.5, x + r * 0.5, y + r * 0.5],
                   fill=(246, 224, 120, 235))

    # pebbles along paths
    for pts in all_pts:
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            for _ in range(3):
                t = rng.random()
                x = ax + (bx - ax) * t + rng.uniform(-10, 10)
                y = ay + (by - ay) * t + rng.uniform(-6, 6)
                r = rng.uniform(1.2, 3.0)
                do.ellipse([x - r, y - r, x + r, y + r],
                           fill=pal["path_edge"] + (rng.randint(90, 160),))

    # dotted footprint trails
    if pal.get("trail"):
        for _ in range(2):
            x, y = rng.uniform(W * 0.1, W * 0.9), float(H)
            side = 1
            while y > H * 0.08:
                do.ellipse([x + side * 4 - 2.5, y - 2, x + side * 4 + 2.5, y + 2],
                           fill=pal["trail"] + (160,))
                side = -side
                y -= rng.uniform(14, 22)
                x = clamp(x + rng.uniform(-14, 14), 20, W - 20)

    bg = Image.alpha_composite(bg.convert("RGBA"), ov).convert("RGB")
    return bg, wmask


# ---------------------------------------------------------------- sprites ---


def make_fallback_sprites():
    """A few built-in scenery shapes so the app works before the user adds
    any images of their own."""
    rng = random.Random(7)
    out = []

    def blank(w, h):
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))

    # round tree
    for g in ((63, 138, 69), (84, 152, 74), (52, 118, 62)):
        im = blank(220, 300)
        d = ImageDraw.Draw(im)
        d.rectangle([98, 180, 122, 300], fill=(122, 91, 52, 255))
        for cx, cy, r in ((110, 120, 78), (58, 160, 52), (162, 160, 52),
                          (110, 70, 55)):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=g + (255,))
        d.ellipse([70, 55, 120, 105], fill=(255, 255, 255, 34))
        out.append(im)

    # pine
    for g in ((47, 107, 69), (39, 92, 58)):
        im = blank(200, 320)
        d = ImageDraw.Draw(im)
        d.rectangle([88, 250, 112, 320], fill=(107, 74, 43, 255))
        for i in range(3):
            wdt = 92 - i * 22
            yb = 260 - i * 78
            d.polygon([(100 - wdt, yb), (100 + wdt, yb), (100, yb - 110)],
                      fill=g + (255,))
        out.append(im)

    # rock
    for c in ((150, 148, 142), (128, 124, 116)):
        im = blank(240, 150)
        d = ImageDraw.Draw(im)
        pts = []
        for i in range(9):
            a = i / 9 * 2 * math.pi
            r = 62 + rng.randint(-14, 16)
            pts.append((120 + math.cos(a) * r * 1.5,
                        90 + math.sin(a) * r * 0.75))
        d.polygon(pts, fill=c + (255,))
        d.polygon([(70, 60), (150, 45), (120, 85)], fill=(255, 255, 255, 40))
        out.append(im)

    # bush
    im = blank(220, 140)
    d = ImageDraw.Draw(im)
    for cx, cy, r in ((60, 90, 48), (160, 90, 48), (110, 62, 56)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(66, 122, 60, 255))
    out.append(im)

    # log
    im = blank(260, 90)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([10, 22, 250, 78], 26, fill=(139, 103, 61, 255))
    d.ellipse([222, 22, 262, 78], fill=(186, 152, 106, 255))
    d.ellipse([234, 36, 250, 64], fill=(150, 116, 74, 255))
    out.append(im)

    return {"builtin scenery": out}


DEFAULT_CAT_CFG = {"weight": 1.0, "size": 0.13, "cluster": 0.5,
                   "band": (0.0, 1.0)}


def load_sprite_library():
    """Scan assets/sprites/* ; returns (lib, cfg) where lib maps category ->
    list of RGBA images and cfg maps category -> options dict."""
    lib, cfg = {}, {}
    user_cfg = {}
    cfg_path = os.path.join(ASSET_DIR, "sprites.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
        except Exception as e:
            print("Warning: could not read sprites.json:", e)

    def load_image(path):
        try:
            im = Image.open(path).convert("RGBA")
        except Exception:
            return None
        if max(im.size) > MAX_SRC_SIDE:
            sc = MAX_SRC_SIDE / max(im.size)
            im = im.resize((max(1, int(im.width * sc)),
                            max(1, int(im.height * sc))), RES.LANCZOS)
        return im

    if os.path.isdir(SPRITE_DIR):
        loose = []
        for entry in sorted(os.listdir(SPRITE_DIR)):
            full = os.path.join(SPRITE_DIR, entry)
            if os.path.isdir(full):
                imgs = []
                for fn in sorted(os.listdir(full)):
                    if fn.lower().endswith(IMG_EXTS):
                        im = load_image(os.path.join(full, fn))
                        if im is not None:
                            imgs.append(im)
                if imgs:
                    lib[entry] = imgs
            elif entry.lower().endswith(IMG_EXTS):
                im = load_image(full)
                if im is not None:
                    loose.append(im)
        if loose:
            lib["misc"] = loose

    if not lib:
        lib = make_fallback_sprites()

    for cat in lib:
        c = dict(DEFAULT_CAT_CFG)
        u = user_cfg.get(cat, {})
        if isinstance(u, dict):
            if "weight" in u:
                c["weight"] = float(u["weight"])
            if "size" in u:
                c["size"] = float(u["size"])
            if "cluster" in u:
                c["cluster"] = clamp(float(u["cluster"]), 0.0, 1.0)
            if "band" in u and len(u["band"]) == 2:
                c["band"] = (clamp(float(u["band"][0]), 0, 1),
                             clamp(float(u["band"][1]), 0, 1))
        cfg[cat] = c
    return lib, cfg


def jitter_sprite(src, target_h, rng):
    """Per-instance variation so repeated images don't look copy-pasted."""
    img = src
    if rng.random() < 0.5:
        img = img.transpose(FLIP_LR)
    target_h = max(14, int(target_h))
    # Normalize by height, but blend in width for very wide images so a
    # 3:1 banner/log/bus doesn't balloon to 3x the intended size.
    dom = max(img.height, img.width * 0.55)
    sc = target_h / dom
    w = max(1, int(img.width * sc))
    h = max(1, int(img.height * sc))
    img = img.resize((w, h), RES.LANCZOS)

    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))
    rgb = ImageEnhance.Brightness(rgb).enhance(rng.uniform(0.9, 1.1))
    rgb = ImageEnhance.Color(rgb).enhance(rng.uniform(0.85, 1.15))
    img = rgb.convert("RGBA")
    img.putalpha(a)

    ang = rng.uniform(-5, 5)
    if abs(ang) > 1.5:
        img = img.rotate(ang, resample=RES.BICUBIC, expand=True)
    return img


def make_shadow(sprite, strength=80):
    """Soft squashed silhouette to sit under the sprite's feet."""
    a = sprite.getchannel("A")
    sh_h = max(3, int(sprite.height * 0.20))
    a2 = a.resize((sprite.width, sh_h), RES.BILINEAR)
    a2 = a2.filter(ImageFilter.GaussianBlur(3))
    a2 = a2.point(lambda v, s=strength: v * s // 255)
    sh = Image.new("RGBA", (sprite.width, sh_h), (14, 18, 14, 0))
    sh.putalpha(a2)
    return sh


# ---------------------------------------------------------------- scene -----


class Scene(object):
    def __init__(self, bg, wmask, items, W, H, horizon, counts):
        self.bg = bg
        self.wmask = wmask
        self.items = items
        self.W = W
        self.H = H
        self.horizon = horizon
        self.counts = counts


def generate_scene(seed, W, H, palette_key, density, clustering, detail,
                   lib, cfg):
    rng = random.Random("%s|%dx%d|%s" % (seed, W, H, palette_key))
    pal = PALETTES[palette_key]
    bg, wmask = make_terrain(W, H, "%s|%s" % (seed, palette_key), pal,
                             detail / 100.0)
    horizon = int(H * 0.04)

    cats = sorted(lib.keys())
    weights = [cfg[c]["weight"] for c in cats]

    # cluster centers per category
    centers = {}
    for c in cats:
        k = 1 + int(clustering / 40)
        centers[c] = [(rng.uniform(W * 0.08, W * 0.92),
                       horizon + rng.uniform(0.12, 0.95) * (H - horizon))
                      for _ in range(k)]

    total = int((W * H) / 6200.0 * density / 100.0 * 1.08)
    items = []
    placed = {c: 0 for c in cats}
    for _ in range(total):
        cat = rng.choices(cats, weights=weights)[0]
        c = cfg[cat]
        b0, b1 = c["band"]
        ymin = horizon + b0 * (H - horizon)
        ymax = horizon + b1 * (H - horizon)

        p_cluster = clamp(c["cluster"] * (clustering / 100.0) * 1.5, 0, 0.95)
        if rng.random() < p_cluster:
            cx, cy = rng.choice(centers[cat])
            x = rng.gauss(cx, W * 0.055)
            y = rng.gauss(cy, H * 0.05)
        else:
            x = rng.uniform(-W * 0.02, W * 1.02)
            y = rng.uniform(ymin, ymax)
        x = clamp(x, -W * 0.02, W * 1.02)
        y = clamp(y, ymin, max(ymin + 1, ymax))

        # avoid dropping things in deep water (mostly)
        wx = int(clamp(x, 0, W - 1))
        wy = int(clamp(y, 0, H - 1))
        if wmask.getpixel((wx, wy)) > 200 and rng.random() < 0.85:
            continue

        depth = (y - horizon) / float(H - horizon)
        h = H * c["size"] * (0.5 + 0.8 * depth) * rng.uniform(0.78, 1.28)
        src = rng.choice(lib[cat])
        spr = jitter_sprite(src, h, rng)
        items.append(dict(img=spr, sh=make_shadow(spr),
                          x=int(x), y=int(y)))
        placed[cat] += 1

    items.sort(key=lambda e: e["y"])
    return Scene(bg, wmask, items, W, H, horizon, placed)


def _paste_entry(canvas, e):
    spr, sh = e["img"], e["sh"]
    w, h = spr.size
    px = e["x"] - w // 2
    py = e["y"] - h
    if sh is not None:
        sw, shh = sh.size
        canvas.paste(sh, (e["x"] - sw // 2 + max(2, h // 28),
                          e["y"] - shh // 2), sh)
    canvas.paste(spr, (px, py), spr)


def compose_scene(scene, chars, occlude):
    """Paint background + all sprites (+ hidden characters, depth-sorted if
    occlude=True so scenery can genuinely stand in front of them)."""
    img = scene.bg.copy()
    char_entries = []
    for c in chars:
        ensure_char_render(c)
        char_entries.append(dict(img=c["_img"], sh=c["_sh"],
                                 x=int(c["x"]), y=int(c["y"])))
    if occlude:
        entries = sorted(scene.items + char_entries, key=lambda e: e["y"])
    else:
        entries = scene.items + char_entries
    for e in entries:
        _paste_entry(img, e)
    return img


# ---------------------------------------------------------------- frame -----


def frame_scene(img, cell, margin, grid_lines):
    """Add the parchment border with letter columns / numbered rows, tick
    marks, and (optionally) faint grid lines across the scene itself."""
    W, H = img.size
    frW, frH = W + 2 * margin, H + 2 * margin
    out = Image.new("RGB", (frW, frH), (246, 241, 229))
    out.paste(img, (margin, margin))
    d = ImageDraw.Draw(out, "RGBA")

    label_col = (72, 58, 40)
    font = load_font(margin * 0.42)
    cols = int(math.ceil(W / float(cell)))
    rows = int(math.ceil(H / float(cell)))

    for ci in range(cols):
        x0 = margin + ci * cell
        cw = min(cell, W - ci * cell)
        cx = x0 + cw / 2.0
        d.text((cx, margin * 0.5), col_name(ci), fill=label_col,
               font=font, anchor="mm")
        d.text((cx, frH - margin * 0.5), col_name(ci), fill=label_col,
               font=font, anchor="mm")
        d.line([(x0, margin - 10), (x0, margin)], fill=label_col, width=2)
        d.line([(x0, frH - margin), (x0, frH - margin + 10)],
               fill=label_col, width=2)
    for ri in range(rows):
        y0 = margin + ri * cell
        ch = min(cell, H - ri * cell)
        cy = y0 + ch / 2.0
        d.text((margin * 0.5, cy), str(ri + 1), fill=label_col,
               font=font, anchor="mm")
        d.text((frW - margin * 0.5, cy), str(ri + 1), fill=label_col,
               font=font, anchor="mm")
        d.line([(margin - 10, y0), (margin, y0)], fill=label_col, width=2)
        d.line([(frW - margin, y0), (frW - margin + 10, y0)],
               fill=label_col, width=2)

    if grid_lines:
        ga = 34
        for ci in range(1, cols):
            x0 = margin + ci * cell
            d.line([(x0, margin), (x0, margin + H)], fill=(0, 0, 0, ga))
        for ri in range(1, rows):
            y0 = margin + ri * cell
            d.line([(margin, y0), (margin + W, y0)], fill=(0, 0, 0, ga))

    d.rectangle([margin - 2, margin - 2, margin + W + 1, margin + H + 1],
                outline=(60, 48, 34), width=3)
    d.rectangle([2, 2, frW - 3, frH - 3], outline=(60, 48, 34), width=2)
    return out


def draw_answer_overlay(framed, chars, cell, margin):
    """Magenta rings + numbered badges on a copy of the framed puzzle."""
    d = ImageDraw.Draw(framed)
    font = load_font(margin * 0.5)
    ring = (255, 40, 150)
    for i, c in enumerate(chars, 1):
        ensure_char_render(c)
        w, h = c["_img"].size
        cx = margin + c["x"]
        cy = margin + c["y"] - h / 2.0
        r = max(w, h) * 0.62 + 10
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ring,
                  width=max(4, framed.width // 500))
        bx, by = cx - r * 0.85, cy - r * 0.85
        br = margin * 0.34
        d.ellipse([bx - br, by - br, bx + br, by + br], fill=ring)
        d.text((bx, by), str(i), fill=(255, 255, 255), font=font, anchor="mm")
    return framed


# ---------------------------------------------------------------- chars -----


def ensure_char_render(c):
    if not c.get("_dirty", True):
        return
    img = c["src"]
    if c["flip"]:
        img = img.transpose(FLIP_LR)
    size = max(14, int(c["h"]))
    dom = max(img.height, img.width * 0.55)
    sc = size / dom
    w = max(1, int(img.width * sc))
    h = max(1, int(img.height * sc))
    img = img.resize((w, h), RES.LANCZOS)
    if c["rot"] % 360:
        img = img.rotate(c["rot"], resample=RES.BICUBIC, expand=True)
    c["_img"] = img
    c["_sh"] = make_shadow(img, 60)
    c["_dirty"] = False


def char_bbox(c):
    ensure_char_render(c)
    w, h = c["_img"].size
    return (c["x"] - w // 2, c["y"] - h, c["x"] + w // 2, c["y"])


# ---------------------------------------------------------------- app -------


class SceneMakerApp(object):
    MARGIN = 72

    def __init__(self, root):
        self.root = root
        root.title("Hidden Character Scene Maker")
        root.geometry("1320x860")

        self.lib, self.libcfg = load_sprite_library()
        self.scene = None
        self.chars = []
        self.selected = None
        self.pending_src = None      # PIL image armed for placement
        self.pending_name = ""
        self._char_id = 0
        self._src_cache = {}
        self._drag = None
        self._after_full = None
        self._tkimg = None
        self.comp_nochar = None
        self.framed_nochar = None
        self.framed_full = None

        self._build_ui()
        self._refresh_char_list()
        self._set_status("Loaded %d sprite images in %d categories. "
                         "Generate a scene to begin."
                         % (sum(len(v) for v in self.lib.values()),
                            len(self.lib)))

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        root = self.root
        left = ttk.Frame(root, padding=8)
        left.pack(side="left", fill="y")

        def section(text):
            ttk.Label(left, text=text, font=("TkDefaultFont", 9, "bold")
                      ).pack(anchor="w", pady=(10, 2))

        section("SCENE")
        row = ttk.Frame(left); row.pack(fill="x")
        self.seed_var = tk.StringVar(value="mulberry-fair")
        ttk.Entry(row, textvariable=self.seed_var, width=16).pack(
            side="left", fill="x", expand=True)
        ttk.Button(row, text="🎲", width=3, command=self._random_seed).pack(
            side="left", padx=(4, 0))

        self.pal_var = tk.StringVar(value="Meadow")
        ttk.Combobox(left, textvariable=self.pal_var, state="readonly",
                     values=list(PALETTES)).pack(fill="x", pady=2)
        self.size_var = tk.StringVar(value="2000 x 1300")
        ttk.Combobox(left, textvariable=self.size_var, state="readonly",
                     values=list(SIZES)).pack(fill="x", pady=2)

        self.density = tk.IntVar(value=70)
        self.cluster = tk.IntVar(value=45)
        self.detail = tk.IntVar(value=60)
        for label, var, a, b in (("Object density", self.density, 15, 170),
                                 ("Clustering", self.cluster, 0, 100),
                                 ("Ground detail", self.detail, 0, 100)):
            ttk.Label(left, text=label).pack(anchor="w")
            tk.Scale(left, from_=a, to=b, orient="horizontal",
                     variable=var, showvalue=True, length=200).pack(fill="x")

        ttk.Button(left, text="Generate scene",
                   command=self.on_generate).pack(fill="x", pady=(6, 0))
        ttk.Button(left, text="Rescan sprite folders",
                   command=self.on_rescan).pack(fill="x", pady=(4, 0))

        section("CHARACTERS TO HIDE")
        lb_frame = ttk.Frame(left); lb_frame.pack(fill="x")
        self.char_list = tk.Listbox(lb_frame, height=6, exportselection=False)
        self.char_list.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lb_frame, command=self.char_list.yview)
        sb.pack(side="left", fill="y")
        self.char_list.config(yscrollcommand=sb.set)

        ttk.Button(left, text="Load character from file…",
                   command=self.on_load_char_file).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="Arm placement (then click scene)",
                   command=self.on_arm_place).pack(fill="x", pady=(2, 0))
        ttk.Label(left, foreground="#666", wraplength=210, justify="left",
                  text="Tip: double-click the scene to place the character "
                       "selected above at that spot.").pack(anchor="w")

        section("OPTIONS")
        self.occlude = tk.BooleanVar(value=True)
        self.gridlines = tk.BooleanVar(value=True)
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="Scenery can overlap characters",
                        variable=self.occlude,
                        command=self.full_refresh).pack(anchor="w")
        ttk.Checkbutton(left, text="Grid lines across scene",
                        variable=self.gridlines,
                        command=self.on_frame_setting).pack(anchor="w")
        ttk.Checkbutton(left, text="Show answer circles (preview)",
                        variable=self.show_key,
                        command=self._draw_canvas).pack(anchor="w")
        row2 = ttk.Frame(left); row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Grid cell (px)").pack(side="left")
        self.cell_var = tk.IntVar(value=100)
        cb = ttk.Combobox(row2, textvariable=self.cell_var, width=6,
                          state="readonly", values=(80, 100, 125, 160, 200))
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_frame_setting())

        section("EXPORT")
        ttk.Button(left, text="Export puzzle PNG",
                   command=self.on_export_puzzle).pack(fill="x")
        ttk.Button(left, text="Export answer key (PNG + JSON)",
                   command=self.on_export_answers).pack(fill="x", pady=(4, 0))

        self.sel_lbl = ttk.Label(left, text="", foreground="#0a6",
                                 wraplength=210, justify="left")
        self.sel_lbl.pack(anchor="w", pady=(10, 0))

        # ---- right: canvas + status bar
        right = ttk.Frame(root)
        right.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(right, bg="#2b2b29", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.status = ttk.Label(right, anchor="w",
                                text="", padding=(8, 3))
        self.status.pack(fill="x")

        c = self.canvas
        c.bind("<Button-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)
        c.bind("<Motion>", self.on_motion)
        c.bind("<MouseWheel>", self.on_wheel)          # Windows / macOS
        c.bind("<Button-4>", lambda e: self.on_wheel(e, 120))   # Linux
        c.bind("<Button-5>", lambda e: self.on_wheel(e, -120))
        c.bind("<Configure>", lambda e: self._draw_canvas())

        for key in ("r", "R", "f", "F"):
            root.bind(key, self.on_key)
        root.bind("<Delete>", self.on_key)
        root.bind("<BackSpace>", self.on_key)
        root.bind("<Escape>", self.on_key)
        root.bind("<bracketleft>", self.on_key)
        root.bind("<bracketright>", self.on_key)

    # ---------------------------------------------------------- utilities --
    def _set_status(self, txt):
        self.status.config(text=txt)

    def _random_seed(self):
        self.seed_var.set("".join(random.choice("abcdefghjkmnpqrstuvwxyz23456789")
                                  for _ in range(7)))

    def _refresh_char_list(self):
        self.char_list.delete(0, "end")
        self._char_files = []
        if os.path.isdir(CHAR_DIR):
            for fn in sorted(os.listdir(CHAR_DIR)):
                if fn.lower().endswith(IMG_EXTS):
                    self._char_files.append(os.path.join(CHAR_DIR, fn))
                    self.char_list.insert("end", fn)
        if not self._char_files:
            self.char_list.insert("end", "(put PNGs in assets/characters)")

    def _selected_char_source(self):
        sel = self.char_list.curselection()
        if not sel or not self._char_files:
            return None, ""
        idx = sel[0]
        if idx >= len(self._char_files):
            return None, ""
        path = self._char_files[idx]
        return self._load_src(path), os.path.basename(path)

    def _load_src(self, path):
        if path not in self._src_cache:
            try:
                im = Image.open(path).convert("RGBA")
            except Exception as e:
                messagebox.showerror("Could not open image", str(e),
                                     parent=self.root)
                return None
            if max(im.size) > 1600:
                sc = 1600.0 / max(im.size)
                im = im.resize((int(im.width * sc), int(im.height * sc)),
                               RES.LANCZOS)
            self._src_cache[path] = im
        return self._src_cache[path]

    # ------------------------------------------------------ view pipeline --
    def rebuild_nochar(self):
        self.comp_nochar = compose_scene(self.scene, [], False)
        self.framed_nochar = frame_scene(self.comp_nochar,
                                         self.cell_var.get(), self.MARGIN,
                                         self.gridlines.get())

    def full_refresh(self):
        """Recomposite with characters (respecting occlusion) and redraw."""
        if self.scene is None:
            return
        comp = compose_scene(self.scene, self.chars, self.occlude.get())
        self.framed_full = frame_scene(comp, self.cell_var.get(), self.MARGIN,
                                       self.gridlines.get())
        self._draw_canvas()

    def quick_refresh(self):
        """Fast preview during drags: characters pasted on top of the cached
        character-free frame (occlusion is re-applied on release)."""
        if self.framed_nochar is None:
            return
        img = self.framed_nochar.copy()
        M = self.MARGIN
        for c in self.chars:
            ensure_char_render(c)
            spr, sh = c["_img"], c["_sh"]
            w, h = spr.size
            sw, shh = sh.size
            img.paste(sh, (M + c["x"] - sw // 2, M + c["y"] - shh // 2), sh)
            img.paste(spr, (M + c["x"] - w // 2, M + c["y"] - h), spr)
        self.framed_full = img
        self._draw_canvas(fast=True)

    def _draw_canvas(self, fast=False):
        c = self.canvas
        c.delete("all")
        img = self.framed_full
        if img is None:
            c.create_text(c.winfo_width() // 2, c.winfo_height() // 2,
                          text="Generate a scene to begin",
                          fill="#999", font=("TkDefaultFont", 14))
            return
        cw = max(50, c.winfo_width())
        ch = max(50, c.winfo_height())
        scale = min(cw / img.width, ch / img.height, 1.6)
        dw, dh = int(img.width * scale), int(img.height * scale)
        disp = img.resize((dw, dh),
                          RES.BILINEAR if fast else RES.LANCZOS)
        self._tkimg = ImageTk.PhotoImage(disp)
        ox, oy = (cw - dw) // 2, (ch - dh) // 2
        c.create_image(ox, oy, anchor="nw", image=self._tkimg)
        self._view = (scale, ox, oy)

        # vector overlays: selection box + answer rings
        M = self.MARGIN
        if self.show_key.get():
            for i, ch_ in enumerate(self.chars, 1):
                ensure_char_render(ch_)
                w, h = ch_["_img"].size
                r = (max(w, h) * 0.62 + 10) * scale
                cx = ox + (M + ch_["x"]) * scale
                cy = oy + (M + ch_["y"] - h / 2.0) * scale
                c.create_oval(cx - r, cy - r, cx + r, cy + r,
                              outline="#ff2896", width=3)
                c.create_text(cx - r * 0.8, cy - r * 0.8, text=str(i),
                              fill="#ff2896", font=("TkDefaultFont", 11, "bold"))
        if self.selected is not None:
            s = self.selected
            ensure_char_render(s)
            w, h = s["_img"].size
            x0 = ox + (M + s["x"] - w / 2.0) * scale
            y0 = oy + (M + s["y"] - h) * scale
            c.create_rectangle(x0, y0, x0 + w * scale, y0 + h * scale,
                               outline="#19d0ff", width=2, dash=(6, 4))

    # -------------------------------------------------------- coordinates --
    def canvas_to_scene(self, cx, cy):
        if self.scene is None or self.framed_full is None:
            return None
        scale, ox, oy = self._view
        sx = (cx - ox) / scale - self.MARGIN
        sy = (cy - oy) / scale - self.MARGIN
        if 0 <= sx < self.scene.W and 0 <= sy < self.scene.H:
            return sx, sy
        return None

    # ------------------------------------------------------------- events --
    def on_generate(self):
        seed = self.seed_var.get().strip() or "seed"
        W, H = SIZES[self.size_var.get()]
        self._set_status("Generating… (this can take a few seconds)")
        self.root.update_idletasks()
        self.scene = generate_scene(seed, W, H, self.pal_var.get(),
                                    self.density.get(), self.cluster.get(),
                                    self.detail.get(), self.lib, self.libcfg)
        # keep characters but clamp them inside the (possibly new) canvas
        for c in self.chars:
            c["x"] = clamp(c["x"], 0, W - 1)
            c["y"] = clamp(c["y"], 10, H - 1)
        self.rebuild_nochar()
        self.full_refresh()
        n = sum(self.scene.counts.values())
        cats = ", ".join("%s ×%d" % kv for kv in
                         sorted(self.scene.counts.items()))
        self._set_status("Placed %d objects  (%s)" % (n, cats))

    def on_rescan(self):
        self.lib, self.libcfg = load_sprite_library()
        self._refresh_char_list()
        self._set_status("Rescanned: %d sprite images in %d categories."
                         % (sum(len(v) for v in self.lib.values()),
                            len(self.lib)))

    def on_load_char_file(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="Choose a character image",
            filetypes=[("Images", "*.png *.webp *.jpg *.jpeg *.gif *.bmp")])
        if not path:
            return
        src = self._load_src(path)
        if src is None:
            return
        self.pending_src = src
        self.pending_name = os.path.basename(path)
        self._set_status("Placement armed: click the scene to drop '%s'."
                         % self.pending_name)

    def on_arm_place(self):
        src, name = self._selected_char_source()
        if src is None:
            messagebox.showinfo(
                "No character selected",
                "Put transparent PNGs into assets/characters (then Rescan), "
                "or use 'Load character from file…'.", parent=self.root)
            return
        self.pending_src, self.pending_name = src, name
        self._set_status("Placement armed: click the scene to drop '%s'."
                         % name)

    def _place_char(self, src, name, sx, sy):
        self._char_id += 1
        c = dict(id=self._char_id, name=name, src=src,
                 x=int(sx), y=int(sy),
                 h=int(self.scene.H * 0.09), rot=0, flip=False, _dirty=True)
        self.chars.append(c)
        self.selected = c
        self.full_refresh()
        self._update_sel_info()

    def on_press(self, event):
        self.root.focus_set()
        pt = self.canvas_to_scene(event.x, event.y)
        if pt is None:
            self.selected = None
            self._draw_canvas()
            self._update_sel_info()
            return
        if self.pending_src is not None:
            self._place_char(self.pending_src, self.pending_name, *pt)
            self.pending_src = None
            return
        # topmost hit first
        for c in reversed(self.chars):
            x0, y0, x1, y1 = char_bbox(c)
            if x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1:
                self.selected = c
                self._drag = (c, pt[0] - c["x"], pt[1] - c["y"])
                self._draw_canvas()
                self._update_sel_info()
                return
        self.selected = None
        self._draw_canvas()
        self._update_sel_info()

    def on_drag(self, event):
        if not self._drag:
            return
        pt = self.canvas_to_scene(event.x, event.y)
        if pt is None:
            return
        c, dx, dy = self._drag
        c["x"] = int(clamp(pt[0] - dx, 0, self.scene.W - 1))
        c["y"] = int(clamp(pt[1] - dy, 10, self.scene.H - 1))
        self.quick_refresh()
        self._update_sel_info()

    def on_release(self, event):
        if self._drag:
            self._drag = None
            self.full_refresh()

    def on_double(self, event):
        if self.scene is None:
            return
        pt = self.canvas_to_scene(event.x, event.y)
        if pt is None:
            return
        src, name = self._selected_char_source()
        if src is None:
            return
        self._place_char(src, name, *pt)

    def on_motion(self, event):
        pt = self.canvas_to_scene(event.x, event.y)
        if pt is None:
            self._set_cursor_cell(None)
        else:
            self._set_cursor_cell(pt)

    def _set_cursor_cell(self, pt):
        base = ("drag = move · wheel = resize · R/Shift+R = rotate · "
                "F = flip · Del = remove")
        if pt is None:
            self.status.config(text=base)
        else:
            cellpx = self.cell_var.get()
            self.status.config(text="Cursor: %s   (%d, %d px)    |   %s"
                               % (cell_label(pt[0], pt[1], cellpx),
                                  pt[0], pt[1], base))

    def on_wheel(self, event, delta=None):
        if self.selected is None:
            return
        d = delta if delta is not None else event.delta
        f = 1.09 if d > 0 else 1 / 1.09
        c = self.selected
        c["h"] = int(clamp(c["h"] * f, 16, self.scene.H * 0.8))
        c["_dirty"] = True
        self.quick_refresh()
        self._update_sel_info()
        self._debounced_full()

    def on_key(self, event):
        if event.keysym == "Escape":
            self.pending_src = None
            self.selected = None
            self._draw_canvas()
            self._update_sel_info()
            return
        c = self.selected
        if c is None:
            return
        if event.keysym in ("Delete", "BackSpace"):
            self.chars.remove(c)
            self.selected = None
            self.full_refresh()
        elif event.keysym == "r":
            c["rot"] = (c["rot"] - 15) % 360
            c["_dirty"] = True
            self.full_refresh()
        elif event.keysym == "R":
            c["rot"] = (c["rot"] + 15) % 360
            c["_dirty"] = True
            self.full_refresh()
        elif event.keysym in ("f", "F"):
            c["flip"] = not c["flip"]
            c["_dirty"] = True
            self.full_refresh()
        elif event.keysym == "bracketleft":
            c["h"] = int(clamp(c["h"] / 1.09, 16, self.scene.H * 0.8))
            c["_dirty"] = True
            self.full_refresh()
        elif event.keysym == "bracketright":
            c["h"] = int(clamp(c["h"] * 1.09, 16, self.scene.H * 0.8))
            c["_dirty"] = True
            self.full_refresh()
        self._update_sel_info()

    def _debounced_full(self):
        if self._after_full:
            self.root.after_cancel(self._after_full)
        self._after_full = self.root.after(350, self.full_refresh)

    def on_frame_setting(self):
        if self.scene is None:
            return
        self.rebuild_nochar()
        self.full_refresh()
        self._update_sel_info()

    def _update_sel_info(self):
        if self.selected is None:
            n = len(self.chars)
            self.sel_lbl.config(
                text="%d character(s) placed." % n if n else "")
            return
        c = self.selected
        cellpx = self.cell_var.get()
        rng_ = cells_range(char_bbox(c), cellpx, self.scene.W, self.scene.H)
        self.sel_lbl.config(text="Selected: %s\nGrid: %s   size %dpx  rot %d°"
                            % (c["name"], rng_, c["h"], c["rot"]))

    # ------------------------------------------------------------- export --
    def _export_paths(self, suffix):
        os.makedirs(OUT_DIR, exist_ok=True)
        seed = "".join(ch if ch.isalnum() or ch in "-_" else "_"
                       for ch in self.seed_var.get().strip()) or "scene"
        return os.path.join(OUT_DIR, "%s%s" % (seed, suffix))

    def on_export_puzzle(self):
        if self.scene is None:
            return
        comp = compose_scene(self.scene, self.chars, self.occlude.get())
        framed = frame_scene(comp, self.cell_var.get(), self.MARGIN,
                             self.gridlines.get())
        path = self._export_paths(".png")
        framed.save(path)
        self._set_status("Saved puzzle -> %s" % path)
        messagebox.showinfo("Exported", "Puzzle saved to:\n%s" % path,
                            parent=self.root)

    def on_export_answers(self):
        if self.scene is None:
            return
        if not self.chars:
            messagebox.showinfo("Nothing to verify",
                                "Place at least one character first.",
                                parent=self.root)
            return
        cellpx = self.cell_var.get()
        comp = compose_scene(self.scene, self.chars, self.occlude.get())
        framed = frame_scene(comp, cellpx, self.MARGIN, self.gridlines.get())
        draw_answer_overlay(framed, self.chars, cellpx, self.MARGIN)
        png_path = self._export_paths("_answers.png")
        framed.save(png_path)

        data = {
            "seed": self.seed_var.get(),
            "palette": self.pal_var.get(),
            "canvas": [self.scene.W, self.scene.H],
            "cell_px": cellpx,
            "margin_px": self.MARGIN,
            "characters": [],
        }
        lines = []
        for i, c in enumerate(self.chars, 1):
            bb = char_bbox(c)
            cell = cell_label(c["x"], c["y"] - c["_img"].size[1] // 2, cellpx)
            rng_ = cells_range(bb, cellpx, self.scene.W, self.scene.H)
            data["characters"].append(dict(
                n=i, name=c["name"], cell=cell, range=rng_,
                center_px=[int(c["x"]), int(c["y"] - c["_img"].size[1] / 2)],
                bbox_px=[int(v) for v in bb], height=c["h"],
                rot=c["rot"], flip=c["flip"]))
            lines.append("%d. %s — %s   (range %s)" % (i, c["name"], cell, rng_))
        json_path = self._export_paths("_answers.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self._set_status("Saved answer key -> %s" % png_path)
        messagebox.showinfo(
            "Answer key exported",
            "Saved:\n%s\n%s\n\n%s" % (png_path, json_path, "\n".join(lines)),
            parent=self.root)


# ---------------------------------------------------------------- boot ------


def ensure_dirs():
    created = not os.path.isdir(ASSET_DIR)
    for d in (ASSET_DIR, SPRITE_DIR, CHAR_DIR, OUT_DIR,
              os.path.join(SPRITE_DIR, "trees"),
              os.path.join(SPRITE_DIR, "vehicles"),
              os.path.join(SPRITE_DIR, "creatures")):
        os.makedirs(d, exist_ok=True)
    readme = os.path.join(ASSET_DIR, "README.txt")
    if not os.path.isfile(readme):
        with open(readme, "w", encoding="utf-8") as f:
            f.write(README_TEXT)
    example = os.path.join(ASSET_DIR, "sprites.example.json")
    if not os.path.isfile(example):
        with open(example, "w", encoding="utf-8") as f:
            json.dump(SPRITES_JSON_EXAMPLE, f, indent=2)
    return created


def main():
    if not HAS_TK:
        print("Tkinter is not available in this Python install.\n"
              "  Windows/macOS: reinstall Python from python.org (Tk is "
              "included by default).\n"
              "  Debian/Ubuntu: sudo apt install python3-tk\n"
              "  Fedora:        sudo dnf install python3-tkinter")
        sys.exit(1)
    first = ensure_dirs()
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    app = SceneMakerApp(root)
    if first:
        messagebox.showinfo(
            "Welcome",
            "Created an assets/ folder next to this script.\n\n"
            "Drop transparent PNGs into assets/sprites/<category>/ for "
            "scenery, and into assets/characters/ for the things you want "
            "to hide. See assets/README.txt for details.\n\n"
            "Built-in placeholder scenery is used until you add your own.",
            parent=root)
    root.mainloop()


if __name__ == "__main__":
    main()
