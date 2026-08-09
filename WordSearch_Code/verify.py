"""Independent checker for wordsearch.py output.

Usage: python verify.py puzzle.txt puzzle_key.txt [--no-backwards] [--no-diagonals]

Checks:
 1. every word in the key is really at the stated row/col/direction
 2. NO word (or its reverse, when backwards is allowed) appears anywhere in
    the grid except inside the span of a placed list word
"""
import sys

DIRS = {"right": (0, 1), "left": (0, -1), "down": (1, 0), "up": (-1, 0),
        "down-right": (1, 1), "down-left": (1, -1),
        "up-right": (-1, 1), "up-left": (-1, -1)}
STRIP = " \t-'\u2019"

args = sys.argv[1:]
backwards = "--no-backwards" not in args
diagonals = "--no-diagonals" not in args
paths = [a for a in args if not a.startswith("--")]
puz_path, key_path = paths[0], paths[1]

rows = [ln.replace(" ", "") for ln in
        open(puz_path, encoding="utf-8").read().splitlines() if ln]
H, W = len(rows), len(rows[0])
assert all(len(r) == W for r in rows), "ragged grid"
T = "".join(rows)  # no newlines, row-major

# ---- parse key ----------------------------------------------------------
placements = []
in_table = False
for line in open(key_path, encoding="utf-8"):
    s = line.rstrip()
    if s.startswith("WORD"):
        in_table = True
        continue
    if not in_table:
        continue
    if not s:
        break
    parts = s.rsplit(None, 3)
    if len(parts) != 4:
        continue
    word, row, col, name = parts
    hidden = "".join(ch for ch in word if ch not in STRIP).upper()
    placements.append((word, hidden, int(row) - 1, int(col) - 1, name))

# ---- 1. placements really there ----------------------------------------
ok = fail = 0
for word, hidden, r, c, name in placements:
    dr, dc = DIRS[name]
    got = "".join(rows[r + dr * i][c + dc * i] for i in range(len(hidden)))
    if got == hidden:
        ok += 1
    else:
        fail += 1
        print("PLACEMENT FAIL", word, "expected", hidden, "found", got)
print(f"placements: {ok} ok, {fail} bad")

# ---- 2. no stray occurrences -------------------------------------------
# intervals per (orientation, line key), same coordinates as the generator
def key_pos(oi, r, c):
    if oi == 0:
        return r, c
    if oi == 1:
        return c, r
    if oi == 2:
        return c - r, min(r, c)
    s = r + c
    return s, r - (s - min(s, W - 1))

ORIENT_OF = {(0, 1): 0, (0, -1): 0, (1, 0): 1, (-1, 0): 1,
             (1, 1): 2, (-1, -1): 2, (1, -1): 3, (-1, 1): 3}

intervals = {}
for word, hidden, r, c, name in placements:
    dr, dc = DIRS[name]
    oi = ORIENT_OF[(dr, dc)]
    e_r, e_c = r + dr * (len(hidden) - 1), c + dc * (len(hidden) - 1)
    k, p1 = key_pos(oi, r, c)
    _, p2 = key_pos(oi, e_r, e_c)
    intervals.setdefault((oi, k), []).append((min(p1, p2), max(p1, p2)))

def excused(oi, k, a, b):
    return any(lo <= a and b <= hi for lo, hi in intervals.get((oi, k), ()))

forward = {hidden for _, hidden, *_ in placements}
pats = set(forward)
if backwards:
    pats |= {p[::-1] for p in forward}

def lines():
    for r in range(H):                       # rows
        yield 0, rows[r], (r, 0, 0, 1)
    for c in range(W):                       # columns
        yield 1, T[c::W], (0, c, 1, 0)
    if diagonals and W >= 2:
        for c0 in range(W):                  # down-right, from top edge
            n = min(H, W - c0)
            yield 2, T[c0:c0 + (n - 1) * (W + 1) + 1:W + 1], (0, c0, 1, 1)
        for r0 in range(1, H):               # down-right, from left edge
            n = min(W, H - r0)
            s = r0 * W
            yield 2, T[s:s + (n - 1) * (W + 1) + 1:W + 1], (r0, 0, 1, 1)
        for c0 in range(W):                  # down-left, from top edge
            n = min(H, c0 + 1)
            yield 3, T[c0:c0 + (n - 1) * (W - 1) + 1:W - 1], (0, c0, 1, -1)
        for r0 in range(1, H):               # down-left, from right edge
            n = min(H - r0, W)
            s = r0 * W + W - 1
            yield 3, T[s:s + (n - 1) * (W - 1) + 1:W - 1], (r0, W - 1, 1, -1)

stray = 0
counts = {p: 0 for p in pats}
for oi, line, (r0, c0, dr, dc) in lines():
    for p in pats:
        i = line.find(p)
        while i != -1:
            counts[p] += 1
            mr, mc = r0 + dr * i, c0 + dc * i
            k, pos = key_pos(oi, mr, mc)
            if not excused(oi, k, pos, pos + len(p) - 1):
                stray += 1
                print(f"STRAY: {p!r} at row {mr + 1}, col {mc + 1}, orientation {oi}")
            i = line.find(p, i + 1)

def present(w):
    if counts.get(w, 0):
        return True
    return backwards and counts.get(w[::-1], 0) > 0

missing = [p for p in forward if not present(p)]
print(f"stray occurrences outside placed words: {stray}")
if missing:
    print("words never found:", missing)
print("RESULT:", "PASS" if (fail == 0 and stray == 0 and not missing) else "FAIL")