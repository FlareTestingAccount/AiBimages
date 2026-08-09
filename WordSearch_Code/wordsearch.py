#!/usr/bin/env python3
"""
wordsearch.py - build word search puzzles at any size, with your own words
and your own filler letters.

Examples
--------
    python wordsearch.py
        Interactive mode: answer a few questions, get a puzzle.

    python wordsearch.py --size 15 --words "cat,dog,heron,ice cream"
        A 15 x 15 puzzle printed to the screen with its answer key.

    python wordsearch.py --size 5000x5000 --words-file words.txt --output big.txt --solution
        A huge puzzle written to big.txt, its answer key to big_key.txt,
        and a words-only grid to big_solution.txt.

    python wordsearch.py --size 40 --words-file animals.txt --letters AEIOURSTLN
        Use only the letters A E I O U R S T L N as random filler.

Notes
-----
* --size is WIDTHxHEIGHT (columns x rows), or one number for a square grid.
* Words are uppercased, and spaces / hyphens / apostrophes are removed
  ("ice cream" is hidden as ICECREAM). Use --keep-case to keep case as typed.
* --letters accepts plain characters and ranges: A-Z, AEIOU, A-Z0-9, ...
* No accidental words: the grid is checked in every direction the puzzle
  uses, so each word appears ONLY where it was placed. (A word sitting fully
  inside another placed list word, like AT in CAT, is unavoidable and
  allowed.) Very tight letter sets automatically switch to a slower
  constrained fill. Use --allow-accidental to skip all of this for speed.
* The answer key counts rows and columns from 1, starting at the top-left.
* Use --seed to get the exact same puzzle again.
"""

from __future__ import annotations

import argparse
import os
import random
import string
import sys
import time
from bisect import bisect_right
from collections import defaultdict

MAX_CELLS = 400_000_000        # safety cap (a 20000 x 20000 grid)
SCREEN_CELLS = 3_600           # grids up to this many cells print to the screen
PROGRESS_CELLS = 4_000_000     # show progress messages above this size
MAX_CLEAN_PASSES = 6           # scan-and-repair rounds for accidental words
STRIP_CHARS = " \t-'\u2019"    # removed from words before hiding them
SEP_BYTE = b"\xff"             # line separator inside scan buffers

OPPOSITE = {
    "right": "left",
    "down": "up",
    "down-right": "up-left",
    "up-right": "down-left",
}

# The four scanning orientations. Every one of the 8 word directions lies
# along one of these lines (read forward or backward).
#   0: right (0,+1)   1: down (+1,0)   2: down-right (+1,+1)   3: down-left (+1,-1)
ORIENT_OF_DIR = {
    (0, 1): 0, (0, -1): 0,
    (1, 0): 1, (-1, 0): 1,
    (1, 1): 2, (-1, -1): 2,
    (1, -1): 3, (-1, 1): 3,
}


class WordSearch:
    """Generate a word search grid of arbitrary size.

    The grid is stored as one bytearray of letter indices (1 byte per cell),
    so even a 5000 x 5000 puzzle needs only ~25 MB. Three layers keep the
    words from appearing anywhere by accident:

      1. placements are rejected if crossing words would spell a list word
      2. after random filling, the grid is scanned along every enabled
         orientation and chance appearances are repaired
      3. if repair cannot converge (very small letter sets), the filler is
         rebuilt cell by cell with backtracking so no word can be completed
    """

    def __init__(self, width, height, letters=string.ascii_uppercase,
                 diagonals=True, backwards=True, keep_case=False,
                 seed=None, attempts=2000, prevent_accidental=True):
        if width < 1 or height < 1:
            raise ValueError("width and height must both be at least 1")
        if width * height > MAX_CELLS:
            raise ValueError(
                f"{width} x {height} = {width * height:,} cells is above the safety "
                f"cap of {MAX_CELLS:,}; raise MAX_CELLS in the script if you really "
                f"want a grid that large")
        if not letters:
            raise ValueError("letters must contain at least one character")

        self.width = width
        self.height = height
        self.keep_case = keep_case
        pool = letters if keep_case else letters.upper()
        self.letters = list(dict.fromkeys(pool))       # filler set, deduped
        self.attempts = max(1, attempts)
        self.rng = random.Random(seed)
        self.diagonals = diagonals
        self.backwards = backwards
        self.prevent_accidental = prevent_accidental

        dirs = [("right", 0, 1), ("down", 1, 0)]
        if diagonals:
            dirs += [("down-right", 1, 1), ("up-right", -1, 1)]
        if backwards:
            dirs += [(OPPOSITE[n], -dr, -dc) for n, dr, dc in list(dirs)]
        self.dirs = dirs

        # scan orientations actually in use
        self._orients = [(0, (0, 1)), (1, (1, 0))]
        if diagonals:
            self._orients += [(2, (1, 1)), (3, (1, -1))]

        self.cells = {}          # (row, col) -> letter, word letters only
        self.placements = []     # (word as given, hidden form, row, col, direction)
        self.unplaced = []       # (word as given, reason)
        self._intervals = defaultdict(list)   # (orient, line key) -> [(a, b)]
        self._patterns = []      # every string that must not appear by chance
        self._maxlen = 0

        self._buf = None         # bytearray of letter indices, once filled
        self._all = None         # index -> letter (filler letters first)
        self.accidental_fixed = 0
        self.accidental_left = 0
        self.used_constrained = False

    # ------------------------------------------------------------ lines

    def _line_key_pos(self, oi, r, c):
        """(line key, position along line) of a cell, per orientation."""
        if oi == 0:
            return r, c
        if oi == 1:
            return c, r
        if oi == 2:                      # down-right, key = c - r
            return c - r, min(r, c)
        s = r + c                        # down-left, key = r + c
        c0 = min(s, self.width - 1)
        return s, r - (s - c0)

    def _excused(self, oi, key, a, b):
        """True if span [a, b] on this line sits inside one placed word."""
        for lo, hi in self._intervals.get((oi, key), ()):
            if lo <= a and b <= hi:
                return True
        return False

    # ------------------------------------------------------------ words

    def add_words(self, words):
        """Clean, dedupe and place a list of words (longest first)."""
        queue, seen = [], set()
        for raw in words:
            shown = raw.strip()
            if not shown:
                continue
            hidden = "".join(ch for ch in shown if ch not in STRIP_CHARS)
            if not self.keep_case:
                hidden = hidden.upper()
            if len(hidden) < 2:
                self.unplaced.append((shown, "needs at least 2 letters"))
                continue
            if hidden in seen:
                continue
            seen.add(hidden)
            queue.append((shown, hidden))

        # Build the full "must not appear by chance" pattern list up front so
        # every placement can be checked against every word, including ones
        # that have not been placed yet.
        pats = set()
        for _, hidden in queue:
            pats.add(hidden)
            if self.backwards:
                pats.add(hidden[::-1])
        self._patterns = sorted(pats)
        self._maxlen = max((len(p) for p in pats), default=0)

        queue.sort(key=lambda pair: len(pair[1]), reverse=True)
        for shown, hidden in queue:
            self._place(shown, hidden)

    def _place(self, shown, hidden):
        n = len(hidden)
        if n > self.width and n > self.height:
            self.unplaced.append((shown, f"{n} letters, longer than both grid sides"))
            return False

        rng, cells = self.rng, self.cells
        for _ in range(self.attempts):
            name, dr, dc = rng.choice(self.dirs)

            if dc == 0:
                cmin, cmax = 0, self.width - 1
            elif dc > 0:
                cmin, cmax = 0, self.width - n
            else:
                cmin, cmax = n - 1, self.width - 1
            if dr == 0:
                rmin, rmax = 0, self.height - 1
            elif dr > 0:
                rmin, rmax = 0, self.height - n
            else:
                rmin, rmax = n - 1, self.height - 1
            if cmin > cmax or rmin > rmax:     # word too long for this direction
                continue

            r0 = rng.randint(rmin, rmax)
            c0 = rng.randint(cmin, cmax)

            r, c, ok = r0, c0, True
            for ch in hidden:
                cur = cells.get((r, c))
                if cur is not None and cur != ch:
                    ok = False
                    break
                r += dr
                c += dc
            if not ok:
                continue

            # Tentatively write the word, then make sure the letters already
            # on the board plus this word don't spell any OTHER list word
            # along a line (crossing words can do that by accident).
            added, word_cells = [], []
            r, c = r0, c0
            for ch in hidden:
                if (r, c) not in cells:
                    cells[(r, c)] = ch
                    added.append((r, c))
                word_cells.append((r, c))
                r += dr
                c += dc

            oi = ORIENT_OF_DIR[(dr, dc)]
            key, p1 = self._line_key_pos(oi, r0, c0)
            _, p2 = self._line_key_pos(oi, word_cells[-1][0], word_cells[-1][1])
            span = (min(p1, p2), max(p1, p2))
            self._intervals[(oi, key)].append(span)

            if self._placed_runs_clean(word_cells):
                self.placements.append((shown, hidden, r0, c0, name))
                return True

            self._intervals[(oi, key)].remove(span)
            for cell in added:
                del cells[cell]

        self.unplaced.append((shown, f"no clean spot found in {self.attempts} tries"))
        return False

    def _placed_runs_clean(self, new_cells):
        """Check every run of placed letters touching new_cells for stray words."""
        cells = self.cells
        for oi, (dr, dc) in self._orients:
            seen = set()
            for (r, c) in new_cells:
                while (r - dr, c - dc) in cells:
                    r -= dr
                    c -= dc
                if (r, c) in seen:
                    continue
                seen.add((r, c))
                sr, sc, chars = r, c, []
                while (r, c) in cells:
                    chars.append(cells[(r, c)])
                    r += dr
                    c += dc
                s = "".join(chars)
                for p in self._patterns:
                    i = s.find(p)
                    while i != -1:
                        mr, mc = sr + dr * i, sc + dc * i
                        key, pos = self._line_key_pos(oi, mr, mc)
                        if not self._excused(oi, key, pos, pos + len(p) - 1):
                            return False
                        i = s.find(p, i + 1)
        return True

    # ------------------------------------------------------- fill + clean

    def fill(self):
        """Fill filler letters, then remove chance appearances of the words."""
        if self._buf is not None:
            return
        extras = sorted({ch for ch in self.cells.values()} - set(self.letters))
        self._all = self.letters + extras
        if len(self._all) > 255:
            raise ValueError("more than 255 distinct letters are not supported")
        index = {ch: i for i, ch in enumerate(self._all)}

        W, H = self.width, self.height
        buf = bytearray(W * H)
        pool = list(range(len(self.letters)))
        choices = self.rng.choices
        for r in range(H):
            buf[r * W:(r + 1) * W] = bytes(choices(pool, k=W))
        for (r, c), ch in self.cells.items():
            buf[r * W + c] = index[ch]
        self._buf = buf

        if self.prevent_accidental and self._patterns:
            pats = sorted({bytes(index[ch] for ch in p) for p in self._patterns},
                          key=len)
            plist = [(pb, len(pb)) for pb in pats]
            self._clean(plist)
            if self.accidental_left:
                if self._fill_constrained():
                    self.used_constrained = True
                    self.accidental_left = len(self._find_accidental(plist))

    def _diag_lines(self):
        W, H = self.width, self.height
        for c0 in range(W):
            yield 0, c0, min(H, W - c0)
        for r0 in range(1, H):
            yield r0, 0, min(W, H - r0)

    def _anti_lines(self):
        W, H = self.width, self.height
        for c0 in range(W):
            yield 0, c0, min(H, c0 + 1)
        for r0 in range(1, H):
            yield r0, W - 1, min(H - r0, W)

    def _find_accidental(self, pats):
        """Scan the whole grid; return matches not inside a placed word."""
        buf, W, H = self._buf, self.width, self.height
        minlen = pats[0][1]
        found = []

        def record(oi, key, pos, L, cells, pb):
            if not self._excused(oi, key, pos, pos + L - 1):
                found.append((cells, pb, oi))

        # rows
        big = bytes(buf)
        for pb, L in pats:
            i = big.find(pb)
            while i != -1:
                c = i % W
                if c + L <= W:
                    r = i // W
                    record(0, r, c, L, tuple((r, c + k) for k in range(L)), pb)
                i = big.find(pb, i + 1)

        # columns
        if H >= minlen:
            tbig = b"".join(bytes(buf[c::W]) for c in range(W))
            for pb, L in pats:
                i = tbig.find(pb)
                while i != -1:
                    r = i % H
                    if r + L <= H:
                        c = i // H
                        record(1, c, r, L, tuple((r + k, c) for k in range(L)), pb)
                    i = tbig.find(pb, i + 1)

        # diagonals
        if self.diagonals and W >= 2:
            for oi, step, lines in ((2, W + 1, self._diag_lines()),
                                    (3, W - 1, self._anti_lines())):
                parts, starts, metas, off = [], [], [], 0
                for r0, c0, n in lines:
                    if n < minlen:
                        continue
                    s0 = r0 * W + c0
                    parts.append(bytes(buf[s0:s0 + (n - 1) * step + 1:step]))
                    parts.append(SEP_BYTE)
                    starts.append(off)
                    metas.append((r0, c0, n))
                    off += n + 1
                if not parts:
                    continue
                dbig = b"".join(parts)
                cd = 1 if oi == 2 else -1
                for pb, L in pats:
                    i = dbig.find(pb)
                    while i != -1:
                        j = bisect_right(starts, i) - 1
                        r0, c0, n = metas[j]
                        pos = i - starts[j]
                        if pos + L <= n:
                            key = (c0 - r0) if oi == 2 else (r0 + c0)
                            cells = tuple((r0 + pos + k, c0 + cd * (pos + k))
                                          for k in range(L))
                            record(oi, key, pos, L, cells, pb)
                        i = dbig.find(pb, i + 1)
        return found

    def _local_ok(self, r, c, pats):
        """After changing cell (r, c), no un-excused match may cover it."""
        buf, W, H = self._buf, self.width, self.height
        reach = self._maxlen - 1
        for oi, (dr, dc) in self._orients:
            nb = 0
            while nb < reach and 0 <= r - (nb + 1) * dr < H and 0 <= c - (nb + 1) * dc < W:
                nb += 1
            nf = 0
            while nf < reach and 0 <= r + (nf + 1) * dr < H and 0 <= c + (nf + 1) * dc < W:
                nf += 1
            r0, c0 = r - nb * dr, c - nb * dc
            win = bytes(buf[(r0 + k * dr) * W + (c0 + k * dc)]
                        for k in range(nb + nf + 1))
            for pb, L in pats:
                if L > len(win):
                    continue
                i = win.find(pb)
                while i != -1:
                    if i <= nb <= i + L - 1:
                        key, pos = self._line_key_pos(oi, r0 + i * dr, c0 + i * dc)
                        if not self._excused(oi, key, pos, pos + L - 1):
                            return False
                    i = win.find(pb, i + 1)
        return True

    def _repair(self, cells, pb, pats):
        """Change one filler letter of an accidental match, safely."""
        buf, W = self._buf, self.width
        filler = [(k, rc) for k, rc in enumerate(cells) if rc not in self.cells]
        if not filler:
            return False                      # should not happen: placement-checked
        mid = (len(cells) - 1) / 2
        filler.sort(key=lambda t: abs(t[0] - mid))
        n_fill = len(self.letters)
        for _, (r, c) in filler:
            pos = r * W + c
            orig = buf[pos]
            options = [li for li in range(n_fill) if li != orig]
            self.rng.shuffle(options)
            for li in options:
                buf[pos] = li
                if self._local_ok(r, c, pats):
                    return True
            buf[pos] = orig
        return False

    def _clean(self, pats):
        """Repeatedly scan and repair until no accidental words remain."""
        W = self.width
        big = W * self.height >= PROGRESS_CELLS
        left = None
        for pass_no in range(1, MAX_CLEAN_PASSES + 1):
            if big:
                print(f"\r  scanning for accidental words (pass {pass_no})...",
                      end="", file=sys.stderr, flush=True)
            matches = self._find_accidental(pats)
            if not matches:
                left = 0
                break
            fixed = 0
            for cells, pb, _ in matches:
                if any(self._buf[r * W + c] != pb[k]
                       for k, (r, c) in enumerate(cells)):
                    continue                  # already broken by an earlier fix
                if self._repair(cells, pb, pats):
                    fixed += 1
            self.accidental_fixed += fixed
            if fixed == 0:
                break                         # no progress possible this way
        if left is None:
            left = len(self._find_accidental(pats))
        self.accidental_left = left
        if big:
            print("\r" + " " * 60 + "\r", end="", file=sys.stderr, flush=True)

    def _fill_constrained(self):
        """Backtracking fill for tight letter sets where repair gets stuck.

        Rebuilds every filler cell in reading order, choosing letters so no
        pattern is ever completed: looking backward along each orientation,
        and forward through runs of placed word letters (a filler letter must
        not combine with fixed word letters ahead of it to finish a word).
        Uses one byte per cell for backtracking state, so it works at any size.
        """
        buf, W, H = self._buf, self.width, self.height
        placed = self.cells
        n_fill = len(self.letters)
        index = {ch: i for i, ch in enumerate(self._all)}
        pats = {bytes(index[ch] for ch in p) for p in self._patterns}
        lengths = sorted({len(p) for p in pats})
        by_len = {L: {p for p in pats if len(p) == L} for L in lengths}
        Lmax = self._maxlen
        orients = [d for _, d in self._orients]
        total = W * H
        n_filler = total - len(placed)
        big = total >= PROGRESS_CELLS
        snapshot = bytes(buf)

        def conflict(r, c):
            """None if cell (r, c) completes no pattern; otherwise the linear
            indices of the OTHER filler cells in the first violating window
            (the cells a backjump could change to resolve it)."""
            here = r * W + c
            for dr, dc in orients:
                back_idx = []
                rr, cc = r - dr, c - dc
                while len(back_idx) < Lmax - 1 and 0 <= rr < H and 0 <= cc < W:
                    back_idx.append(rr * W + cc)
                    rr -= dr
                    cc -= dc
                back_idx.reverse()
                back_idx.append(here)          # oldest ... newest, ends here
                back = bytes(buf[i] for i in back_idx)
                nb = len(back)
                for L in lengths:
                    if L <= nb and back[nb - L:] in by_len[L]:
                        return {i for i in back_idx[nb - L:]
                                if i != here and divmod(i, W) not in placed}
                k = 1                          # forward through placed letters
                rr, cc = r + dr, c + dc
                fwd = []
                while k < Lmax and (rr, cc) in placed:
                    fwd.append(rr * W + cc)
                    idxs = back_idx + fwd
                    s = back + bytes(buf[i] for i in fwd)
                    ns = len(s)
                    for L in lengths:
                        if k < L <= ns and s[ns - L:] in by_len[L]:
                            return {i for i in idxs[ns - L:]
                                    if i != here and divmod(i, W) not in placed}
                    k += 1
                    rr += dr
                    cc += dc
            return None

        def bail(success):
            if big:
                print("\r" + " " * 60 + "\r", end="", file=sys.stderr, flush=True)
            if not success:
                buf[:] = snapshot
            return success

        def cand_at(cur, t, salt):
            h = (cur * 0x9E3779B97F4A7C15 + salt) & 0xFFFFFFFFFFFFFFFF
            h ^= h >> 31
            h = (h * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
            h ^= h >> 27
            return (h + t) % n_fill

        restarts = 6 if total <= 1_000_000 else 2
        per_limit = min(40 * n_filler + 100_000, 60_000_000)
        for attempt in range(restarts):
            tried = bytearray(total)           # options already tried per cell
            hint = {}                          # cell -> inherited conflict cells
            salt = self.rng.randrange(1 << 60)
            steps = 0
            cur = 0
            while True:
                while cur < total and divmod(cur, W) in placed:
                    cur += 1
                if cur >= total:
                    return bail(True)
                r, c = divmod(cur, W)
                t = tried[cur]
                found = False
                tried_here = 0
                blockers = set(hint.pop(cur, ()))
                while t < n_fill:
                    steps += 1
                    if big and steps % 200_000 == 0:
                        print(f"\r  constrained fill (try {attempt + 1}): "
                              f"cell {cur:,}/{total:,}",
                              end="", file=sys.stderr, flush=True)
                    buf[cur] = cand_at(cur, t, salt)
                    t += 1
                    tried_here += 1
                    cset = conflict(r, c)
                    if cset is None:
                        found = True
                        break
                    blockers |= cset
                tried[cur] = t
                if found:
                    cur += 1
                    continue
                if steps > per_limit:
                    break                      # this attempt is thrashing
                if not blockers:
                    if tried_here:             # every letter completes a word
                        return bail(False)     # using fixed word letters only
                    # arrived at an exhausted cell with no conflict info:
                    # fall back to one chronological step
                    tried[cur] = 0
                    cur -= 1
                    while cur >= 0 and divmod(cur, W) in placed:
                        cur -= 1
                    if cur < 0:
                        return bail(False)
                    continue
                # Conflict-directed backjump: go straight to the most recent
                # filler cell that took part in a violating window, wiping the
                # tried-counts (and hints) of everything after it.
                target = max(blockers)
                hint[target] = hint.get(target, set()) | (blockers - {target})
                for k in [k for k in hint if target < k <= cur]:
                    del hint[k]
                tried[target + 1:cur + 1] = bytes(cur - target)
                cur = target
        return bail(False)

    # -------------------------------------------------------------- grid

    def rows(self):
        """Yield each row as a list of characters (words + filler)."""
        self.fill()
        getl = self._all.__getitem__
        W = self.width
        for r in range(self.height):
            yield [getl(i) for i in self._buf[r * W:(r + 1) * W]]

    def _row_text(self, sep=" "):
        self.fill()
        W = self.width
        if all(ord(ch) < 128 for ch in self._all):
            table = bytes(ord(self._all[i]) if i < len(self._all) else 63
                          for i in range(256))
            for r in range(self.height):
                s = self._buf[r * W:(r + 1) * W].translate(table).decode("ascii")
                yield sep.join(s) if sep else s
        else:
            getl = self._all.__getitem__
            for r in range(self.height):
                s = "".join(map(getl, self._buf[r * W:(r + 1) * W]))
                yield sep.join(s) if sep else s

    def solution_rows(self, blank="."):
        """Yield each row with only the hidden words shown."""
        by_row = defaultdict(list)
        for (r, c), ch in self.cells.items():
            by_row[r].append((c, ch))
        for r in range(self.height):
            row = [blank] * self.width
            for c, ch in by_row.get(r, ()):
                row[c] = ch
            yield row

    def render(self, sep=" "):
        """The whole puzzle as one string (fine for small grids)."""
        return "\n".join(self._row_text(sep))

    # ------------------------------------------------------------ output

    def _write_lines(self, path, line_iter):
        show_progress = self.width * self.height >= PROGRESS_CELLS
        with open(path, "w", encoding="utf-8") as f:
            for i, line in enumerate(line_iter, 1):
                f.write(line)
                f.write("\n")
                if show_progress and i % 500 == 0:
                    print(f"\r  {path}: {i:,}/{self.height:,} rows",
                          end="", file=sys.stderr, flush=True)
        if show_progress:
            print("\r" + " " * 60 + "\r", end="", file=sys.stderr, flush=True)

    def write_puzzle(self, path, sep=" "):
        self._write_lines(path, self._row_text(sep))

    def write_solution(self, path, sep=" ", blank="."):
        self._write_lines(path, (sep.join(row) for row in self.solution_rows(blank)))

    def key_lines(self):
        total = len(self.placements) + len(self.unplaced)
        yield (f"Answer key - {self.width} x {self.height} grid, "
               f"{len(self.placements)} of {total} words placed")
        yield "Rows and columns are numbered from 1, starting at the top-left."
        yield ""
        if self.placements:
            w = max(max(len(p[0]) for p in self.placements), 4)
            yield f"{'WORD':<{w}}  {'ROW':>7}  {'COL':>7}  DIRECTION"
            for shown, hidden, r, c, name in sorted(self.placements,
                                                    key=lambda p: p[1]):
                yield f"{shown:<{w}}  {r + 1:>7}  {c + 1:>7}  {name}"
        if self.unplaced:
            yield ""
            yield "Not placed:"
            for shown, reason in self.unplaced:
                yield f"  {shown} - {reason}"

    def write_key(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.key_lines()))
            f.write("\n")


def generate(width, height, words, **kwargs):
    """Convenience helper for imports:  ws = generate(50, 50, ["cat", "dog"])."""
    ws = WordSearch(width, height, **kwargs)
    ws.add_words(words)
    ws.fill()
    return ws


# ---------------------------------------------------------------- CLI

def parse_size(text):
    t = text.lower().replace(" ", "").replace("*", "x")
    try:
        if "x" in t:
            w, h = t.split("x", 1)
            return int(w), int(h)
        n = int(t)
        return n, n
    except ValueError:
        raise SystemExit(f"Could not read size {text!r}; use e.g. 20 or 5000x5000")


def expand_letters(spec):
    """Expand ranges like A-Z or 0-9; everything else is taken literally."""
    out, i = [], 0
    while i < len(spec):
        if i + 2 < len(spec) and spec[i + 1] == "-" and ord(spec[i]) <= ord(spec[i + 2]):
            out.extend(chr(o) for o in range(ord(spec[i]), ord(spec[i + 2]) + 1))
            i += 3
        else:
            out.append(spec[i])
            i += 1
    return "".join(out)


def collect_words(args):
    words = []
    if args.words_file:
        try:
            with open(args.words_file, encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            raise SystemExit(f"Could not read {args.words_file}: {exc}")
        words.extend(text.replace(",", "\n").splitlines())
    if args.words:
        words.extend(args.words.split(","))
    return [w.strip() for w in words if w.strip()]


def build_parser():
    p = argparse.ArgumentParser(
        prog="wordsearch.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    p.add_argument("--size", default="15",
                   help="WIDTHxHEIGHT or one number for a square (default 15)")
    p.add_argument("--words",
                   help='comma separated words, e.g. "cat,dog,ice cream"')
    p.add_argument("--words-file",
                   help="text file of words (one per line; commas also work)")
    p.add_argument("--letters", default="A-Z",
                   help="filler letter set, ranges allowed: A-Z, AEIOU, A-Z0-9 "
                        "(default A-Z)")
    p.add_argument("--no-diagonals", action="store_true",
                   help="horizontal and vertical words only")
    p.add_argument("--no-backwards", action="store_true",
                   help="no reversed words")
    p.add_argument("--keep-case", action="store_true",
                   help="keep letter case as typed instead of uppercasing")
    p.add_argument("--seed", type=int,
                   help="random seed for a reproducible puzzle")
    p.add_argument("--attempts", type=int, default=2000,
                   help="placement tries per word before giving up (default 2000)")
    p.add_argument("--allow-accidental", action="store_true",
                   help="skip the checks that remove chance appearances of the "
                        "words (faster on huge grids)")
    p.add_argument("--output", "-o", metavar="FILE",
                   help="write the puzzle here (default: screen for small grids, "
                        "wordsearch.txt for big ones)")
    p.add_argument("--solution", action="store_true",
                   help="also write a grid showing only the hidden words")
    p.add_argument("--sep", default=" ",
                   help="text between letters in the output (default: one space)")
    return p


def run(args):
    width, height = parse_size(args.size)
    letters = expand_letters(args.letters)
    words = collect_words(args)
    if not words:
        raise SystemExit("No words given - use --words, --words-file, or run with "
                         "no arguments for interactive mode.")

    start = time.time()
    try:
        ws = WordSearch(width, height, letters=letters,
                        diagonals=not args.no_diagonals,
                        backwards=not args.no_backwards,
                        keep_case=args.keep_case,
                        seed=args.seed, attempts=args.attempts,
                        prevent_accidental=not args.allow_accidental)
    except ValueError as exc:
        raise SystemExit(str(exc))
    ws.add_words(words)

    total = len(ws.placements) + len(ws.unplaced)
    print(f"Placed {len(ws.placements)} of {total} words in a {width} x {height} grid.")
    for shown, reason in ws.unplaced:
        print(f"  ! {shown}: {reason}")

    used = {ch for _, hidden, *_ in ws.placements for ch in hidden}
    outside = sorted(used - set(ws.letters))
    if outside:
        print(f"  note: {', '.join(outside)} appear(s) only inside words, not in the "
              f"filler set, so those words may stand out a little.")

    try:
        ws.fill()
    except ValueError as exc:
        raise SystemExit(str(exc))
    if args.allow_accidental:
        print("  filler check skipped (--allow-accidental).")
    elif ws.accidental_left:
        print(f"  ! warning: {ws.accidental_left} chance appearance(s) could not be "
              f"removed - try more or different filler letters, or --allow-accidental.")
    elif ws.used_constrained:
        print("  filler check: clean (tight letter set - used constrained fill).")
    elif ws.accidental_fixed:
        print(f"  filler check: removed {ws.accidental_fixed} chance "
              f"appearance(s) of the words; grid is clean.")
    else:
        print("  filler check: clean, no chance appearances of the words.")

    if args.output is None and width * height <= SCREEN_CELLS:
        print()
        print(ws.render(args.sep))
        print()
        print("\n".join(ws.key_lines()))
        print("\n(add --output FILE to save the puzzle and key to disk)")
        return

    out = args.output or "wordsearch.txt"
    base, ext = os.path.splitext(out)
    ext = ext or ".txt"
    ws.write_puzzle(out, args.sep)
    key_path = f"{base}_key{ext}"
    ws.write_key(key_path)
    written = [out, key_path]
    if args.solution:
        sol_path = f"{base}_solution{ext}"
        ws.write_solution(sol_path, args.sep)
        written.append(sol_path)

    took = time.time() - start
    names = ", ".join(
        f"{p} ({os.path.getsize(p) / 1e6:,.1f} MB)" if os.path.getsize(p) >= 1e6
        else p
        for p in written)
    print(f"Wrote {names}  [{took:.1f}s]")


def interactive(parser):
    print("Word search generator - press Enter to accept a [default]\n")
    args = parser.parse_args([])

    args.size = input("Grid size, one number or WIDTHxHEIGHT [15]: ").strip() or "15"

    raw = ""
    while not raw:
        raw = input("Words, comma separated (or @file.txt to load a file):\n> ").strip()
    if raw.startswith("@"):
        args.words_file = raw[1:].strip()
    else:
        args.words = raw

    args.letters = (input("Filler letters, ranges ok (A-Z, AEIOU, ...) [A-Z]: ")
                    .strip() or "A-Z")
    args.no_diagonals = input("Allow diagonal words? [Y/n]: ").strip().lower().startswith("n")
    args.no_backwards = input("Allow backwards words? [Y/n]: ").strip().lower().startswith("n")
    args.output = input("Save to file (Enter = screen for small grids): ").strip() or None
    if args.output:
        args.solution = input("Also write a solution grid? [y/N]: ").strip().lower().startswith("y")
    print()
    run(args)


def main(argv=None):
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        if sys.stdin.isatty():
            try:
                interactive(parser)
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
            return
        parser.print_help()
        return
    run(parser.parse_args(argv))


if __name__ == "__main__":
    main()