# Crew avatar house style (board-native dashboard)

Clean, width-safe ASCII crew avatars for the spawn cards. Generated from data by
`scripts/python/gen_crew_cards.py` (extend `FACES` to add the remaining specialists).

## Hard rules (the dashboard depends on these)
- **Pure ASCII in the art body.** No emoji inside `---idle---`/`---active---` frames —
  emoji are variable-width in terminals and drift alignment. The motif emoji stays in
  the card **header** only (rendered by `bin/vs-board-dashboard.py`, not in the frame).
- Every frame line is the **same width** and **≤ 24 columns**; the frame is **≤ 6 lines**.
- Consistent silhouette so a board of many avatars reads as one crew.

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
filename and `crew.tsv`), keep the anime character legible in the silhouette, run
`python3 scripts/python/gen_crew_cards.py` (or `--check` to validate widths only).
Current set: systems-engineer, security-analyst, large-context-analyst,
social-strategist, summarizer, backend-engineer.
