# Crew avatar house style (board-native dashboard)

Clean, width-safe ASCII crew avatars for the spawn cards. Generated from data by
`scripts/python/gen_crew_cards.py` (extend `FACES` to add the remaining specialists).

## Hard rules (the dashboard depends on these)
- **Emoji in the art body are ALLOWED — sparingly, as an accent.** This rule used to
  read "pure ASCII only, emoji are variable-width and drift alignment". That reason no
  longer holds: `bin/vs-board-dashboard.py` measures **display columns**, not
  characters, via `_dwidth()`, which counts emoji and CJK as 2 cells, combining marks
  as 0, and explicitly handles the U+FE0F variation selector that used to be the
  culprit. Measured 2026-08-10: `⚙️` len 2 → dwidth 2, `🔒` len 1 → dwidth 2, ASCII
  frame len 13 → dwidth 13. Padding is done by display width, so alignment holds.
  **Author for legibility, not for a constraint that was fixed in code.**
  Caveat that IS still real: an emoji occupies 2 of your ~11 usable columns and
  renders differently across terminals and fonts. Use one as an accent where it earns
  the space (a motif, a weapon, a spark); do not build a face out of emoji — that is
  what makes a card unreadable, not the width.
- Every frame line is the **same width** and **≤ 24 columns**; the frame is **≤ 6 lines**.
- Consistent silhouette so a board of many avatars reads as one crew.
- **The card must read as its character at a glance.** This is the rule that actually
  matters and the one most cards currently fail. A viewer who knows the character
  should recognise them from the silhouette alone — Killua's spiked hair and lightning
  accent, Reiner's armored plating. A frameless stack of emoji is a placeholder, not
  an avatar.

## The "terminal bust" (5 rows in a light frame → 6 lines, 13 cols)
```
.-----------.     row 0  top    — the character's signature hair / headgear / motif
|___[##]___ |     row 1  eyes   — idle: calm ( -  . = )   active: awake ( o 0 * ^ ! )
| |o.  .o|  |     row 2  mouth  — neutral set line
| |_ == _|  |     row 3  base   — collar / emblem / weapon accent
| \__||__/  |
'-----------'
```
- **idle vs active differ ONLY in the eyes row** (and a small spark), so a *running*
  spawn visibly "wakes up" without the silhouette jumping.
- Author each row as a short string centered into `FRAME_W` (11); the generator frames
  and pads it, guaranteeing equal width. Never hand-pad in the `.card` file.

## Worked example — `systems-engineer` (Reiner, Attack on Titan, ⚙️)
```
FACES["systems-engineer"] = {
    "top": "___[##]___",   # armored plating
    "eyes_i": "|-.  .-|",  # calm
    "eyes_a": "|o.  .o|",  # alert
    "mouth": "|_ == _|",
    "base": "\\__||__/",   # collar
}
```
renders idle → `| |-.  .-|  |` and active → `| |o.  .o|  |`.

## Adding the rest
Add a `FACES[<specialist>]` entry keyed by the specialist slug (matches the `.card`
filename), keep the anime character legible in the silhouette, run
`python3 scripts/python/gen_crew_cards.py` (or `--check` to validate widths only).
Current set: systems-engineer, security-analyst, large-context-analyst,
social-strategist, summarizer, backend-engineer.
