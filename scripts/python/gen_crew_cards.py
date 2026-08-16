#!/usr/bin/env python3
"""Generate clean, width-safe ASCII crew avatars into shared/cards/*.card.

House style ("terminal bust"): pure ASCII only (no emoji in the art body — emoji
are variable-width and drift terminal alignment; the motif emoji lives in the card
header), a 5-row bust framed to a fixed inner width, idle vs active differing only
in the eyes/spark so a running spawn reads as "awake". Every emitted frame line is
padded to the SAME width and is <= 24 columns, satisfying the dashboard renderer.

Data-driven so the remaining ~65 cards can be added by extending FACES. Preserves
each card's existing frontmatter (name/anime/department/motif); replaces only the
---idle--- and ---active--- frames.
"""
import sys
import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARDS = ROOT / "shared" / "cards"
FRAME_W = 11  # inner content width of the bust (<= 24 with borders)

# Per-specialist bust: (top, eyes_idle, eyes_active, mouth, base). Each string is
# centered into FRAME_W, so authoring stays readable and widths stay exact.
FACES = {
    "systems-engineer": {  # Reiner — armored AoT soldier
        "top": "___[##]___", "eyes_i": "|-.  .-|", "eyes_a": "|o.  .o|",
        "mouth": "|_ == _|", "base": "\\__||__/",
    },
    "security-analyst": {  # Kento Nanami — glasses, precise sorcerer
        "top": ".--~~~~--.", "eyes_i": "[=]--[=]", "eyes_a": "[o]--[o]",
        "mouth": " |  --  |", "base": " '--||--'",
    },
    "large-context-analyst": {  # Kurapika — hooded, chain accent
        "top": "/^^^^^^^^\\", "eyes_i": "( -    - )", "eyes_a": "( 0    0 )",
        "mouth": " \\  ~~  /", "base": "o=+=[]=+=o",
    },
    "social-strategist": {  # quill / strategist
        "top": "._.--.__.", "eyes_i": "( o  o )", "eyes_a": "( ^  ^ )",
        "mouth": " \\ -- /", "base": "~<[ /// ]>~",
    },
    "summarizer": {  # Gon — spiky hair, bright
        "top": "\\|/\\|/\\|/", "eyes_i": "( O  O )", "eyes_a": "( *  * )",
        "mouth": "  \\__/", "base": " <[ /\\ ]>",
    },
    "backend-engineer": {  # Roy Mustang — flame alchemist, sharp
        "top": "~\\\\/\\//~", "eyes_i": "( >  < )", "eyes_a": "( >!!< )",
        "mouth": "  |==|", "base": " [<()>] ",
    },
    "technical-artist": {  # Deidara — explosive clay art, hair over one eye
        "top": "~<[oo]>~", "eyes_i": "(-  .>)", "eyes_a": "(*  !>)",
        "mouth": "<katsu>", "base": "\\_(><)_/",
    },
    "scout": {  # Killua — lightning assassin, spiky hair
        "top": "/\\/\\/\\", "eyes_i": "( zZz )", "eyes_a": "( o  o )",
        "mouth": "  --  ", "base": "-=[/\\]=-",
    },
    "exploit-developer": {  # Sukuna — king of curses, tattoos, extra eye
        "top": "=#=#=#=", "eyes_i": "(o'.'o)", "eyes_a": "(O'!'O)",
        "mouth": " wwww ", "base": "]<##>[",
    },
    "code-reviewer": {  # meticulous reviewer, checkmarks
        "top": ".-===-.", "eyes_i": "( o  o )", "eyes_a": "( +  + )",
        "mouth": " [ok] ", "base": "-<[==]>-",
    },
    "sol": {  # persona-blank advisor
        "top": "   ___   ", "eyes_i": "( -  - )", "eyes_a": "( o  o )",
        "mouth": "  ---  ", "base": "  [ ? ]  ",
    },
    "fable": {  # persona-blank advisor
        "top": "   ___   ", "eyes_i": "( -  - )", "eyes_a": "( o  o )",
        "mouth": "  ---  ", "base": "  [ ? ]  ",
    },
}


# Short anime-flavored role taglines shown under the specialist name on the card.
TAGLINES = {
    "systems-engineer": "hardened systems titan",
    "security-analyst": "by-the-book threat sorcerer",
    "large-context-analyst": "scarlet-eyed context hunter",
    "social-strategist": "narrative growth tactician",
    "summarizer": "relentless signal seeker",
    "backend-engineer": "flame-alchemy pipeline colonel",
    "technical-artist": "advanced design jutsu master",
    "scout": "lightning-fast recon assassin",
    "exploit-developer": "king of curse exploits",
    "code-reviewer": "meticulous severity arbiter",
    "sol": "unbiased second opinion",
    "fable": "unbiased second opinion",
}


def _center(text, width):
    text = text[:width]
    pad = width - len(text)
    left = pad // 2
    return " " * left + text + " " * (pad - left)


def _frame(face, active):
    rows = [face["top"], face["eyes_a"] if active else face["eyes_i"], face["mouth"], face["base"]]
    body = [_center(r, FRAME_W) for r in rows]
    bar = "." + "-" * FRAME_W + "."
    end = "'" + "-" * FRAME_W + "'"
    lines = [bar] + ["|" + r + "|" for r in body] + [end]
    return lines  # 6 lines, each FRAME_W+2 == 13 cols


def _read_frontmatter(path):
    keep = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() in ("---idle---", "---active---"):
            break
        keep.append(line)
    return keep


def build(specialist, write=True):
    path = CARDS / f"{specialist}.card"
    if not path.is_file() or specialist not in FACES:
        return None
    front = _read_frontmatter(path)
    # ensure a single tagline line (from TAGLINES), inserted right after motif
    front = [line for line in front if not line.startswith("tagline:")]
    tag = TAGLINES.get(specialist)
    if tag:
        rebuilt = []
        for line in front:
            rebuilt.append(line)
            if line.startswith("motif:"):
                rebuilt.append(f"tagline: {tag}")
        front = rebuilt
    face = FACES[specialist]
    out = list(front)
    out.append("---idle---")
    out.extend(_frame(face, active=False))
    out.append("---active---")
    out.extend(_frame(face, active=True))
    text = "\n".join(out) + "\n"
    # width invariant: every art line <= 24 and frames internally consistent
    for line in _frame(face, True) + _frame(face, False):
        assert len(line) <= 24, f"{specialist}: line >24 cols: {line!r}"
    if write:
        path.write_text(text, encoding="utf-8")
    return text


def check_cards():
    """Return false when any generator-owned card differs from its rendering."""
    clean = True
    for specialist in FACES:
        path = CARDS / f"{specialist}.card"
        display_path = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        result = build(specialist, write=False)
        if result is None:
            print(f"FAIL crew-card: missing generator-owned card: {path}", file=sys.stderr)
            clean = False
            continue
        actual = path.read_text(encoding="utf-8")
        if actual == result:
            print(f"  {specialist}: ok")
            continue
        clean = False
        print(
            f"FAIL crew-card: {display_path} is stale; "
            "run scripts/python/gen_crew_cards.py",
            file=sys.stderr,
        )
        sys.stderr.writelines(
            difflib.unified_diff(
                actual.splitlines(keepends=True),
                result.splitlines(keepends=True),
                fromfile=str(display_path),
                tofile=f"generated:{display_path}",
            )
        )
    if clean:
        print("PASS crew-card")
    return clean


def main():
    if "--check" in sys.argv:
        return 0 if check_cards() else 1
    for specialist in FACES:
        result = build(specialist, write=True)
        status = "ok" if result else "SKIP (missing card/face)"
        print(f"  {specialist}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
