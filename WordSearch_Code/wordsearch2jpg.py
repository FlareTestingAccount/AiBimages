#!/usr/bin/env python3
"""
wordsearch2jpg.py - render a wordsearch.py puzzle as a JPG image, so the
puzzle can be shared without the letters being searchable, copyable text.

Examples
--------
    python wordsearch2jpg.py puzzle.txt
        Makes puzzle.jpg. If puzzle_key.txt sits next to it, the word list
        is printed under the grid automatically (words only - never their
        positions).

    python wordsearch2jpg.py puzzle.txt --title "Fruit Hunt" --cell 64
    python wordsearch2jpg.py puzzle.txt --no-words --grid-lines
    python wordsearch2jpg.py puzzle.txt -o puzzle.png      # PNG works too

Needs the Pillow library:  pip install pillow
"""

import argparse
import math
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("This script needs the Pillow library. Install it with:\n"
             "    pip install pillow")

# Tried in order until one loads; bold faces first for that classic puzzle look.
FONTS = [
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "arialbd.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def find_font(size, preferred=None):
    names = ([preferred] if preferred else []) + FONTS
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)        # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def read_grid(path, sep=None):
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        sys.exit(f"{path} is empty")
    rows = []
    for ln in lines:
        if sep:
            rows.append(ln.split(sep))
        elif " " in ln.strip():
            rows.append(ln.split())
        else:
            rows.append(list(ln.strip()))
    w = len(rows[0])
    if any(len(r) != w for r in rows):
        sys.exit(f"{path} does not look like a rectangular letter grid")
    return rows


def read_words(key_path):
    """Pull just the word column out of a wordsearch.py answer key."""
    words, in_table = [], False
    with open(key_path, encoding="utf-8") as f:
        for line in f:
            s = line.rstrip()
            if s.startswith("WORD"):
                in_table = True
                continue
            if not in_table:
                continue
            if not s:
                break
            parts = s.rsplit(None, 3)
            if len(parts) == 4 and parts[1].isdigit() and parts[2].isdigit():
                words.append(parts[0])
    return sorted(set(words), key=str.upper)


def text_top_center(d, x, y, s, font, fill="black"):
    try:
        d.text((x, y), s, font=font, fill=fill, anchor="ma")
    except (ValueError, TypeError):
        b = d.textbbox((0, 0), s, font=font)
        d.text((x - (b[2] - b[0]) / 2 - b[0], y - b[1]), s, font=font, fill=fill)


def text_center(d, x, y, s, font, fill="black"):
    try:
        d.text((x, y), s, font=font, fill=fill, anchor="mm")
    except (ValueError, TypeError):
        b = d.textbbox((0, 0), s, font=font)
        d.text((x - (b[2] - b[0]) / 2 - b[0], y - (b[3] - b[1]) / 2 - b[1]),
               s, font=font, fill=fill)


def main():
    ap = argparse.ArgumentParser(
        prog="wordsearch2jpg.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    ap.add_argument("puzzle", help="puzzle text file from wordsearch.py")
    ap.add_argument("-o", "--output",
                    help="image file to write (default: <puzzle>.jpg; "
                         "use a .png name for PNG)")
    ap.add_argument("--title", help="heading printed above the grid")
    ap.add_argument("--key",
                    help="answer key to take the word list from "
                         "(default: <puzzle>_key.<ext> if it exists)")
    ap.add_argument("--no-words", action="store_true",
                    help="don't print the word list under the grid")
    ap.add_argument("--cell", type=int, default=48,
                    help="cell size in pixels (default 48; use 90+ for print)")
    ap.add_argument("--grid-lines", action="store_true",
                    help="draw light lines between cells")
    ap.add_argument("--font", help="path to a .ttf font file to use")
    ap.add_argument("--quality", type=int, default=92,
                    help="JPEG quality 1-95 (default 92)")
    ap.add_argument("--max-size", type=int, default=12000,
                    help="cap on image width/height in pixels (default 12000)")
    ap.add_argument("--sep",
                    help="text between letters in the puzzle file, if it was "
                         "made with a custom --sep")
    args = ap.parse_args()

    grid = read_grid(args.puzzle, args.sep)
    H, W = len(grid), len(grid[0])

    words = []
    if not args.no_words:
        key = args.key
        if key is None:
            base, ext = os.path.splitext(args.puzzle)
            cand = f"{base}_key{ext or '.txt'}"
            if os.path.exists(cand):
                key = cand
        if key:
            if not os.path.exists(key):
                sys.exit(f"Key file not found: {key}")
            words = read_words(key)

    # ---- sizes -----------------------------------------------------------
    margin, gap = 40, 28
    cell = args.cell
    fit = (args.max_size - 2 * margin) // max(W, H)
    if fit < cell:
        cell = fit
        if cell >= 10:
            print(f"note: cell size reduced to {cell} px so the image stays "
                  f"under {args.max_size} px (--max-size)")
    if cell < 10:
        sys.exit(f"A {W} x {H} grid will not fit readably in one "
                 f"{args.max_size} px image (each letter would get only "
                 f"{max(fit, 0)} px). Use a smaller grid, or raise --max-size "
                 f"if you really want a huge image.")

    if args.font:
        try:
            ImageFont.truetype(args.font, 12)
        except Exception:
            print(f"note: could not load font {args.font!r}, using a standard one")
            args.font = None

    letter_font = find_font(max(int(cell * 0.62), 8), args.font)
    list_size = max(16, int(cell * 0.42))
    list_font = find_font(list_size, args.font)
    title_size = max(26, int(cell * 0.85))
    title_font = find_font(title_size, args.font)

    meas = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    gw, gh = W * cell, H * cell

    width = gw
    if args.title:
        width = max(width, int(meas.textlength(args.title, font=title_font)))
    maxw = 0
    if words:
        maxw = int(max(meas.textlength(w, font=list_font) for w in words))
        width = max(width, maxw)
    width = max(width + 2 * margin, 420)

    y = margin
    title_y = y
    if args.title:
        b = meas.textbbox((0, 0), args.title, font=title_font)
        y += (b[3] - b[1]) + gap
    grid_top = y
    y += gh
    line_h = int(list_size * 1.55)
    ncols = nrows = 0
    if words:
        col_w = maxw + int(list_size * 1.8)
        ncols = max(1, min(len(words), (width - 2 * margin) // col_w))
        nrows = math.ceil(len(words) / ncols)
        y += gap
        list_top = y
        y += line_h                      # "Find these N words:" header
        y += nrows * line_h
    height = y + margin

    # ---- draw ------------------------------------------------------------
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)

    if args.title:
        text_top_center(d, width / 2, title_y, args.title, title_font)

    ox = (width - gw) // 2
    oy = grid_top
    if args.grid_lines:
        for i in range(W + 1):
            d.line([ox + i * cell, oy, ox + i * cell, oy + gh],
                   fill=(205, 205, 205), width=1)
        for j in range(H + 1):
            d.line([ox, oy + j * cell, ox + gw, oy + j * cell],
                   fill=(205, 205, 205), width=1)
    d.rectangle([ox, oy, ox + gw, oy + gh], outline="black", width=2)

    for r, row in enumerate(grid):
        cy = oy + r * cell + cell / 2
        for c, ch in enumerate(row):
            text_center(d, ox + c * cell + cell / 2, cy, ch, letter_font)

    if words:
        lx = margin
        header = (f"Find these {len(words)} words:" if len(words) != 1
                  else "Find this word:")
        d.text((lx, list_top), header,
               font=list_font, fill="black")
        wy = list_top + line_h
        col_w = maxw + int(list_size * 1.8)
        for i, wd in enumerate(words):
            col, row_i = i // nrows, i % nrows
            d.text((lx + col * col_w, wy + row_i * line_h), wd,
                   font=list_font, fill="black")

    # ---- save ------------------------------------------------------------
    out = args.output or os.path.splitext(args.puzzle)[0] + ".jpg"
    ext = os.path.splitext(out)[1].lower()
    if ext in (".jpg", ".jpeg"):
        img.save(out, quality=min(max(args.quality, 1), 95), optimize=True)
    else:
        img.save(out)
    kb = os.path.getsize(out) / 1024
    extra = f", {len(words)} words listed" if words else ""
    print(f"Wrote {out}  ({width} x {height} px, {kb:,.0f} KB, "
          f"{W} x {H} grid{extra})")


if __name__ == "__main__":
    main()