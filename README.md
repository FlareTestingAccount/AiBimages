# AiBimages

Assets and source for a set of *Alice in Borderland*–style game events run in Discord.

Most of the games are [YAGPDB](https://yagpdb.xyz/) custom commands, which can't store images
themselves — so the images live here and are served over `raw.githubusercontent.com`, where the
bot embeds them by URL:

```
https://raw.githubusercontent.com/FlareTestingAccount/AiBimages/main/<folder>/<file>
```

That means **paths in this repo are load-bearing.** Renaming or moving an image will break the
game that points at it.

The `_Code` folders are the custom commands themselves, kept here as readable backups — YAGPDB's
editor is a browser textarea, and this is version control for it.

## Layout

| Folder | What's in it |
| --- | --- |
| `Verify_Code/` | Eight of Spades — the timed captcha-typing game (3 CCs) |
| `aos_captchas/` | Its image bank: 15 word sets × 10 progressive frames, plus `ANSWERS.txt` |
| `HeartOfGlass/` | Hearts of Glass — the button/coin-flip elimination game (5 CCs) |
| `KoD_Code/` | King of Diamonds: Mixology — the poison/antidote puzzle (9 CCs + a GM index page) |
| `BurgerFlip_Code/` | Burger Shift — the two-player rule-following game (3 CCs) |
| `WheresWaldo_Code/` | `scene_maker.py`, a desktop tool for building hidden-character scenes |
| `WordSearch_Code/` | Word search generator, renderer and verifier |
| `CardImages/` | Card artwork, `1.png`–`14.png` |

## The games

**Eight of Spades** (`Verify_Code`) — Players are shown a string and must retype it exactly, fifteen
prompts deep, against a five-minute timer. Each player gets a random offset into the word list, so
two people in the same room don't see the same sequence. `Start8oS` opens the room; a separate
death-timer CC handles the clock.

**Hearts of Glass** (`HeartOfGlass`) — Enrollment happens through a button on the opening embed.
Each player picks ☠ or ¥; the ¥ coin flip decides whether their cube breaks or fills with smoke,
and if 10% of players pick ☠, every *other* cube breaks. Start is gated behind Manage Server.

**King of Diamonds: Mixology** (`KoD_Code`) — Eight unmarked bottles, four of which form a cure in
the right order. Players mix to observe reactions and drink to commit, with three failed courses
ending the run and a 90-minute clock. Bottles are shuffled per player, so answers don't transfer.
`Index.html` is a standalone GM reference for the reaction table.

**Burger Shift** (`BurgerFlip_Code`) — Two players share a channel and work a shift against a task
key keyed to primes and multiples. Run with `-burger start @partner`; `-burger key`, `-burger status`
and `-burger abort` do the rest.

## Tools

Both are standalone Python — nothing to do with the bot, they just make the puzzle images.

**`WheresWaldo_Code/scene_maker.py`** — A Tkinter app that builds dense seek-and-find scenes from
your own sprites, with a coordinate border so finds can be checked ("it's in F7"). Place characters
by double-clicking, then export the puzzle PNG alongside an answer key. Scenes are seeded, so the
same seed rebuilds the same scene.

```bash
pip install pillow
python scene_maker.py
```

It creates an `assets/` folder on first run — drop transparent PNGs into `assets/sprites/<category>/`
and `assets/characters/`, then hit Rescan. The six character PNGs in `Characters/` are the ones
currently in use. `assets/` and `output/` are gitignored.

**`WordSearch_Code/`** — `wordsearch.py` generates puzzles at any grid size with a custom filler
alphabet and guarantees no accidental words; `verify.py` independently re-checks a puzzle against
its key; `wordsearch2jpg.py` renders to an image.

```bash
python wordsearch.py --size 15 --words "cat,dog,heron,ice cream"
python verify.py puzzle.txt puzzle_key.txt
```

Output lands in `Creations/`, which is gitignored.

## Editing the captcha bank

`aos_captchas/ANSWERS.txt` is the answer key, one `w<n>` set per line. If you regenerate the images,
the strings have to be updated in **two** places — that file *and* the `$WORDS` slice at the top of
`Verify cc1 start`. They're duplicated because a custom command can't read a text file at runtime.

## License

<p>
  <a href="https://github.com/FlareTestingAccount/AiBimages">AiBimages</a> © 2026 by
  <a href="https://github.com/flare199">Flare199</a> is licensed under
  <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a><img src="https://mirrors.creativecommons.org/presskit/icons/cc.svg" alt="" height="16"><img src="https://mirrors.creativecommons.org/presskit/icons/by.svg" alt="" height="16"><img src="https://mirrors.creativecommons.org/presskit/icons/sa.svg" alt="" height="16">
</p>
