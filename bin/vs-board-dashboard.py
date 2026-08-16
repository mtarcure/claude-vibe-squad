#!/usr/bin/env python3
"""Board-native dashboard renderer: dynamic spawn cards + completed-history rail.

Consumes the vs-board-snapshot.py stream (@SPAWN/@SUMMARY/@DONE/@DEFECT) and renders:
  * one card per LIVE spawn (0..N) — crew avatar motif + character + specialist +
    model badge + one-line task summary + elapsed timer; a card exists ONLY while
    its spawn is live (no idle/persistent boxes),
  * a compact capacity meter when nothing is running (not empty boxes),
  * a bounded completed-CLI history rail underneath for debugging/audit.

Adaptive: card columns scale with the pane width. Reads the snapshot from stdin if
piped, else runs vs-board-snapshot.py. Pure stdlib; rendered each frame by the loop.
"""
import math
import os
import random
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
CARDS = VAULT / "shared" / "cards"
WIDTH = int(os.environ.get("VS_DASH_WIDTH", os.environ.get("COLUMNS", "72")) or "72")
NOW = int(time.time())

LANE_BADGE = {
    "gpt-codex": "codex", "codex": "codex", "claude": "claude",
    "gemini": "gemini", "kimi": "kimi",
}
# A recognizable emoji beside the model name, and a lane accent colour (256-colour).
MODEL_EMOJI = {"codex": "🤖", "claude": "✴️", "gemini": "♊", "kimi": "🌙"}
LANE_COLOR = {"codex": 78, "claude": 170, "gemini": 39, "kimi": 147}
CARD_W = 27  # inner width of a card (avatar 13 + gap 1 + info 13); 2 cols in a 61w pane

# --- ANSI colour (kept out of width math via _dwidth's stripper) --------------
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
_NO_COLOR = bool(os.environ.get("NO_COLOR")) or os.environ.get("VS_DASH_COLOR") == "0"


def _sgr(text, *codes):
    if _NO_COLOR or not codes:
        return str(text)
    return "\033[" + ";".join(str(c) for c in codes) + "m" + str(text) + "\033[0m"


def _fg(text, color256, *extra):
    return _sgr(text, 38, 5, color256, *extra)


def _snapshot_lines():
    # Read piped snapshot data only when explicitly asked (--stdin, for tests);
    # otherwise always run the snapshot. Never block on an inherited non-tty stdin
    # (e.g. a frame loop or a pipe that never sends EOF).
    if "--stdin" in sys.argv:
        return sys.stdin.read().splitlines()
    proc = subprocess.run(
        ["python3", str(VAULT / "bin" / "vs-board-snapshot.py")],
        capture_output=True, text=True, timeout=10,
    )
    return proc.stdout.splitlines()


AVATAR_W = 13  # a "terminal bust" frame is 13 cols x 6 rows


def _card_meta(specialist):
    """(character, motif, tagline, active_frame_lines) from the .card file."""
    path = CARDS / f"{specialist}.card"
    name, motif, tagline = specialist, "•", ""
    frame, section = [], None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() == "---active---":
                section = "active"
                continue
            if line.strip() in ("---idle---", "---"):
                section = None if section != "active" else section
                if line.strip() == "---idle---":
                    section = "idle"
                continue
            if section == "active":
                frame.append(line)
            elif section is None:
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip() or specialist
                elif line.startswith("motif:"):
                    motif = line.split(":", 1)[1].strip() or "•"
                elif line.startswith("tagline:"):
                    tagline = line.split(":", 1)[1].strip()
    except OSError:
        pass
    # Normalise to a fixed 6 x AVATAR_W block. Pad/truncate RAW (ljust) — never via
    # _fit, which collapses whitespace and would mangle the art's internal spacing.
    frame = [row[:AVATAR_W].ljust(AVATAR_W) for row in frame[:6]]
    while len(frame) < 6:
        frame.append(" " * AVATAR_W)
    return name, motif, tagline, frame


def _elapsed(started):
    secs = max(0, NOW - int(started))
    return f"{secs // 60}:{secs % 60:02d}"


def _dwidth(text):
    """Terminal display width: emoji/CJK count as 2 cells, combining marks as 0.

    Handles the U+FE0F variation selector (turns a text glyph into a width-2 emoji),
    which is the usual cause of drifted alignment with motif emoji like ⚙️/🔒."""
    width = 0
    chars = list(_ANSI_RE.sub("", str(text)))
    i = 0
    while i < len(chars):
        ch = chars[i]
        code = ord(ch)
        nxt = ord(chars[i + 1]) if i + 1 < len(chars) else 0
        if unicodedata.combining(ch):
            i += 1
            continue
        if nxt == 0xFE0F:  # emoji presentation selector -> width 2
            width += 2
            i += 2
            continue
        ea = unicodedata.east_asian_width(ch)
        if ea in ("W", "F") or code >= 0x1F000 or 0x2600 <= code <= 0x27BF:
            width += 2
        else:
            width += 1
        i += 1
    return width


def _pad(text, width):
    """Left-justify text to a display width of `width` cells."""
    gap = width - _dwidth(text)
    return text + " " * max(0, gap)


def _fit(text, width):
    text = " ".join(str(text).split())
    if _dwidth(text) <= width:
        return text
    out = ""
    for ch in text:
        if _dwidth(out) + _dwidth(ch) > width - 1:
            break
        out += ch
    return out + "…"


def _short_model(model):
    """Compact model name for the card: first path segment (kimi-code/… -> kimi-code)."""
    return str(model).split("/")[0]


def _wrap2(text, width):
    """Wrap plain text into (line1, line2) by words, each <= width display cells. If it
    fits on one line, line2 is empty; overflow past two lines is …-truncated."""
    text = " ".join(str(text).split())
    if _dwidth(text) <= width:
        return text, ""
    words, line1, rest = text.split(" "), "", ""
    i = 0
    while i < len(words):
        cand = (line1 + " " + words[i]).strip()
        if _dwidth(cand) <= width:
            line1 = cand
            i += 1
        else:
            break
    rest = " ".join(words[i:])
    return line1, (_fit(rest, width) if rest else "")


def _render_card(spawn, cw):
    """Avatar-forward card scaled to inner width `cw`: 6-row crew bust on the left with
    short info beside it (name, lane, model, elapsed, dispatched-at, live/idle), then
    full-width specialist / tagline / 2-line summary rows."""
    name, motif, tagline, avatar = _card_meta(spawn["specialist"])
    lane = spawn["lane"]
    badge = LANE_BADGE.get(lane, lane)
    color = LANE_COLOR.get(badge, 250)
    memoji = MODEL_EMOJI.get(badge, "•")
    model = _short_model(spawn.get("model", lane))
    timer = _elapsed(spawn["started"])
    disp = time.strftime("%H:%MZ", time.gmtime(int(spawn["started"])))
    iw = cw - AVATAR_W - 1
    # Live/idle signal from the streaming log's last write — growing = producing output;
    # a long silence = maybe stuck, Chrono should check in. NOT a timeout, just a cue.
    try:
        idle_s = max(0, int(NOW - os.path.getmtime(spawn["log"])))
    except OSError:
        idle_s = -1
    if idle_s < 0:
        activity = ""
    elif idle_s > 120:
        activity = _fg(_fit(f"⚠ idle {idle_s // 60}m{idle_s % 60:02d}", iw), 203)
    else:
        activity = _fg(_fit("● live", iw), 78)
    info = [
        _sgr(_fit(f"{motif} {name}", iw), 1),                 # character
        _fg(_fit(f"{memoji} {badge}", iw), color, 1),         # lane
        _sgr(_fit(model, iw), 2),                             # the actual model
        _fg(_fit(f"⏱ {timer}", iw), 227),                    # elapsed
        _sgr(_fit(f"start {disp}", iw), 2),                   # dispatched-at (UTC)
        activity,
    ]
    edge = lambda s: _fg(s, color)
    frow = lambda s: edge("│") + _pad(s, cw) + edge("│")
    rows = [edge("╭" + "─" * cw + "╮")]
    for i in range(6):
        rows.append(edge("│") + _pad(edge(avatar[i]) + " " + info[i], cw) + edge("│"))
    rows.append(frow(_fg(_fit(spawn["specialist"], cw), 45)))
    rows.append(frow(_sgr(_fit(f"“{tagline}”", cw), 2, 3) if tagline else ""))
    s1, s2 = _wrap2("› " + (spawn.get("summary") or spawn["task_id"]), cw)
    rows.append(frow(_fg(s1, 252)))
    rows.append(frow(_fg(s2, 252)))
    rows.append(edge("╰" + "─" * cw + "╯"))
    return rows  # CARD_H rows


CARD_H = 12  # rows per rendered card (must match _render_card output length)


def _layout(width, n):
    """Choose column count, then EXPAND card width to fill the pane so fields don't
    truncate and the board scales to the terminal. Returns (cols, card_inner_width)."""
    min_w = 28
    cols = max(1, (width + 2) // (min_w + 4))
    cols = max(1, min(cols, n))
    cw = (width - (cols - 1) * 2 - cols * 2) // cols  # fill: minus gaps and borders
    return cols, max(min_w, min(cw, 46))


def _grid(cards, cols):
    if not cards:
        return []
    height = len(cards[0])
    rows = []
    for i in range(0, len(cards), cols):
        block = cards[i : i + cols]
        for r in range(height):
            rows.append("  ".join(card[r] for card in block))
    return rows


def _dcenter(text, width):
    pad = max(0, width - _dwidth(text))
    left = pad // 2
    return " " * left + text + " " * (pad - left)


# Parametric hourglass: 8 sand rows (interior widths) framed by diagonal walls, so
# the sand can drain one cell at a time for a smooth fill instead of jumping.
_HG_INTERIOR = [7, 5, 3, 1, 1, 3, 5, 7]
_HG_TEMPL = [
    "|\\{}/|", "| \\{}/ |", "|  \\{}/  |", "|   \\{}/   |",
    "|   /{}\\   |", "|  /{}\\  |", "| /{}\\ |", "|/{}\\|",
]
_HG_CAP = 16  # total sand cells in one chamber (7+5+3+1)


def _hg_row(idx, n_sand):
    w = _HG_INTERIOR[idx]
    n = max(0, min(w, n_sand))
    pad = w - n
    left = pad // 2
    return _HG_TEMPL[idx].format(" " * left + "▓" * n + " " * (pad - left))


def _hourglass_frame(drained):
    """drained = cells already fallen to the bottom (0.._HG_CAP)."""
    sand = [0] * 8
    top = _HG_CAP - drained
    for r in (3, 2, 1, 0):  # top chamber settles neck-up
        put = min(_HG_INTERIOR[r], top)
        sand[r] = put
        top -= put
    bot = drained
    for r in (7, 6, 5, 4):  # bottom chamber settles base-up
        put = min(_HG_INTERIOR[r], bot)
        sand[r] = put
        bot -= put
    return ["._________."] + [_hg_row(i, sand[i]) for i in range(8)] + ["'---------'"]


def _colorize_glass(row, amber, sand):
    return "".join(
        _fg(ch, sand) if ch == "▓" else (" " if ch == " " else _fg(ch, amber))
        for ch in row
    )


_CLOCKS = "◴◵◶◷"    # quadrant clocks — rotate through the sequence
_CLOCKS2 = "◐◓◑◒"   # half-disc dials — a second, slower ring


def _idle_state(width, cap):
    """A Chrono time-field that scales to the pane: a big draining hourglass centred
    in the canvas, orbited by rings of spinning clock dials (each glyph rotates by the
    wall clock), sparkles, and the Chrono label + live UTC clock. Fills VS_DASH_HEIGHT."""
    t = int(time.time())
    height = int(os.environ.get("VS_DASH_HEIGHT", "26") or "26")
    H = max(16, height - 3)                 # leave room for the collapsed history
    grid = [[" "] * width for _ in range(H)]
    cr, cc = H // 2, width // 2

    # central hourglass (smooth drain)
    cyc = t % 11
    drained = min(_HG_CAP, cyc * 2) if cyc <= 8 else _HG_CAP
    hg = _hourglass_frame(drained)
    ht, hl = cr - len(hg) // 2, cc - 6
    for i, row in enumerate(hg):
        for j, ch in enumerate(row):
            if ch != " " and 0 <= ht + i < H and 0 <= hl + j < width:
                grid[ht + i][hl + j] = ch

    def place(r, c, ch):
        if 0 <= r < H and 0 <= c < width and grid[r][c] == " ":
            grid[r][c] = ch

    # orbit rings of spinning clock dials (Novachrono time magic)
    for ring, (rx, ry, glyphs, n) in enumerate((
        (int(width * 0.42), int(H * 0.44), _CLOCKS, 12),
        (int(width * 0.26), int(H * 0.28), _CLOCKS2, 8),
    )):
        for k in range(n):
            ang = 2 * math.pi * k / n + ring * 0.5
            r = cr + int(round(ry * math.sin(ang)))
            c = cc + int(round(rx * math.cos(ang)))
            place(r, c, glyphs[(t + k + ring) % 4])

    # faint drifting sparkles
    rng = random.Random(7)
    for _ in range(max(4, width * H // 260)):
        place(rng.randint(0, H - 1), rng.randint(0, width - 1),
              "·" if (t + rng.randint(0, 3)) % 2 else "˙")

    # labels under the hourglass
    def overlay(text, r):
        c0 = max(0, (width - len(text)) // 2)
        for k, ch in enumerate(text):
            if 0 <= r < H and 0 <= c0 + k < width:
                grid[r][c0 + k] = ch
    base = ht + len(hg) + 1
    overlay("C H R O N O", base)
    overlay("awaiting dispatch" + (f"   ·   {cap} slots ready" if cap != "?" else ""), base + 1)
    overlay(time.strftime("%H:%M:%S UTC", time.gmtime(t)), base + 2)

    out = []
    for r in range(H):
        cells = []
        for c in range(width):
            ch = grid[r][c]
            if ch == " ":
                cells.append(" ")
            elif ch == "▓":
                cells.append(_fg(ch, 179))
            elif ch in _CLOCKS:
                cells.append(_fg(ch, 45))
            elif ch in _CLOCKS2:
                cells.append(_fg(ch, 141))
            elif ch in "·˙":
                cells.append(_fg(ch, 240))
            elif ch in ".|\\/_'-":
                cells.append(_fg(ch, 214))
            else:
                cells.append(_sgr(ch, 1, 38, 5, 252))
        out.append("".join(cells))
    return out


HIST_STATE = Path(os.environ.get("VS_DASH_HISTSTATE", "/tmp/vs-dash-history.state"))


def _history_open():
    try:
        return HIST_STATE.read_text(encoding="utf-8").strip() == "open"
    except OSError:
        return False


def _history_rail(done, width, open_, limit):
    """Collapsible 'recent spawns' dropdown. Returns (block, header_row_offset) where
    the offset locates the clickable header line inside the block (for the hit-map)."""
    total = len(done)
    if not total:
        return [""], None
    caret = "▾" if open_ else "▸"
    hint = "" if open_ else _sgr("  double-click to expand", 2)
    header = _fg(f"{caret} recent spawns ({total})", 245) + hint
    block = ["", header]
    if open_:
        for entry in done[:limit]:
            ok = entry["status"] in ("complete", "completed", "launched")
            mark = _fg("✓", 78) if ok else _fg("✗", 203)
            spec = _sgr(_pad(_fit(entry["specialist"], 20), 20), 2)
            summ = _pad(_fit(entry["summary"] or entry["task_id"], width - 46), max(0, width - 46))
            dur = _fg(f"{entry['duration']}s".rjust(5), 245)
            lc = LANE_COLOR.get(LANE_BADGE.get(entry["lane"], entry["lane"]), 245)
            lane = _fg(f"{entry['lane'][:6]:<6}", lc)
            mem = "🧠" if entry["memory_id"] not in ("-", "", None) else "  "
            block.append(f"{mark} {spec} {summ} {dur} {lane} {mem}")
    return block, 1  # header sits at block index 1 (index 0 is the spacer)


HITMAP = Path(os.environ.get("VS_DASH_HITMAP", "/tmp/vs-dash-hitmap.tsv"))


def _write_hitmap(active, header_rows, cols, cw, hist_row=None, width=0):
    """Record clickable rectangles for the double-click handler, rewritten every
    frame: each live card -> (task_id, log), plus the history header -> @HISTORY
    (a toggle target). Rows/cols are pane-relative (the pane never scrolls)."""
    stride = cw + 4  # card body (cw + 2 borders) + 2-space column gap
    rows = []
    for i, spawn in enumerate(active):
        r, c = divmod(i, max(1, cols))
        y0 = header_rows + r * CARD_H
        x0 = c * stride
        rows.append(
            f"{y0}\t{y0 + CARD_H}\t{x0}\t{x0 + cw + 2}\t{spawn['task_id']}\t{spawn['log']}"
        )
    if hist_row is not None:
        rows.append(f"{hist_row}\t{hist_row + 1}\t0\t{width}\t@HISTORY\t-")
    try:
        HITMAP.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    except OSError:
        pass


SWARM_STATUS = Path(os.environ.get("VS_SWARM_STATUS", "/tmp/vs-swarm.status"))


def _write_swarm_status(active):
    """Write the tmux status-bar segment: a coloured tag per dispatched specialist
    (character name, lane colour) — like the 'chrono' tag but for the live swarm."""
    try:
        if not active:
            SWARM_STATUS.write_text("#[fg=colour240]· idle ·#[default]")
            return
        tags = []
        for spawn in active[:4]:
            name, _motif, _tag, _frame = _card_meta(spawn["specialist"])
            color = LANE_COLOR.get(LANE_BADGE.get(spawn["lane"], spawn["lane"]), 250)
            tags.append(f"#[fg=colour{color},bold] {name} #[default]")
        if len(active) > 4:
            tags.append(f"#[fg=colour240]+{len(active) - 4}#[default]")
        SWARM_STATUS.write_text(" ".join(tags))
    except OSError:
        pass


def main():
    active, done, defects = [], [], []
    pending_summary_for = None
    for line in _snapshot_lines():
        parts = line.split("\t")
        tag = parts[0]
        if tag == "@SPAWN" and len(parts) >= 7:
            active.append({
                "task_id": parts[1], "lane": parts[2], "specialist": parts[3],
                "started": parts[4], "pid": parts[5], "log": parts[6], "summary": "",
                "model": parts[7] if len(parts) > 7 else parts[2],
            })
            pending_summary_for = active[-1]
        elif tag == "@SUMMARY" and pending_summary_for is not None:
            pending_summary_for["summary"] = parts[1] if len(parts) > 1 else ""
            pending_summary_for = None
        elif tag == "@DONE" and len(parts) >= 8:
            done.append({
                "ended": parts[1], "task_id": parts[2], "lane": parts[3],
                "specialist": parts[4], "status": parts[5],
                "duration": int(parts[6]) if parts[6].isdigit() else 0,
                "memory_id": parts[7], "summary": "",
            })
        elif tag == "@DEFECT" and len(parts) >= 5:
            defects.append(f"{parts[1]}/{parts[2]}: {parts[4]}")

    _write_swarm_status(active)  # tmux status-bar specialist tag(s)
    lines = []
    n = len(active)
    cap = os.environ.get("VS_DASH_CAPACITY", "?")
    utc = time.strftime("%H:%M:%S UTC", time.gmtime())
    title = _sgr("◢ VIBE SQUAD · SPECIALIST SWARM ◣", 1, 38, 5, 45)
    cnt = _fg(f"{n} dispatched", 78 if n else 245)
    capstr = _fg(f" / {cap}", 245) if cap != "?" else ""
    status = f"{cnt}{capstr}   {_fg('·', 240)}   {_fg(utc, 245)}"
    if defects:
        status += "   " + _fg(f"⚠ {len(defects)} process defect(s): {defects[0]}", 203)
    lines.append(_dcenter(title, WIDTH))
    lines.append(_dcenter(status, WIDTH))
    lines.append("")

    header_rows = 3  # title, status, blank — the grid starts on row 3
    if active:
        cols, cw = _layout(WIDTH, len(active))
        lines.extend(_grid([_render_card(s, cw) for s in active], cols))
    else:
        cols, cw = 1, CARD_W
        lines.extend(_idle_state(WIDTH, cap))

    # Collapsible history dropdown: short tail when cards are live, longer when idle.
    hist_limit = 5 if active else 14
    hist_start = len(lines)
    block, hdr_rel = _history_rail(done, WIDTH, _history_open(), hist_limit)
    lines.extend(block)
    hist_row = (hist_start + hdr_rel) if hdr_rel is not None else None
    _write_hitmap(active, header_rows, cols, cw, hist_row, WIDTH)
    if os.environ.get("VS_DASH_INPLACE") == "1":
        # Home the cursor, erase each line to EOL, clear below — repaint in place with
        # no full-screen clear (that's what blinks). Pad to the pane height so a shorter
        # frame overwrites a taller previous one.
        height = int(os.environ.get("VS_DASH_HEIGHT", "0") or "0")
        while height and len(lines) < height - 1:
            lines.append("")
        sys.stdout.write("\033[H" + "".join(ln + "\033[K\n" for ln in lines) + "\033[J")
    else:
        sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
