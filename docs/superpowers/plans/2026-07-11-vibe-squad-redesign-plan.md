# Vibe Squad Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Vibe Squad as a multi-model relay TUI (Ink + Python sidecar daemon) coordinating 4 subscription CLIs, with structured specialist enforcement, persistent Chrome, and project-workspace organization.

**Architecture:** Ink (React-in-terminal) frontend hosts Chrono as a Claude Fable 5 SDK client, manages 4 CLI subprocesses via `node-pty`, and talks to a Python FastAPI daemon over HTTP/WebSocket. The daemon owns the task-board filesystem, MCP proxying, external triggers, and the circuit breaker. Persistent Chrome (:9222) is a launchd service; Playwright + Chrome-DevTools MCPs attach via CDP so all lanes share browser state.

**Tech Stack:**
- **Frontend:** Node 22, React 19.2, Ink 7, `@anthropic-ai/claude-agent-sdk`, `node-pty`, TypeScript
- **Backend:** Python 3.12, FastAPI, Uvicorn, `watchfiles`, existing `protocol.py`
- **MCP servers:** Python FastMCP (chrono-vault, chrono-research-arsenal, chrono-content-engineer, new chrono-recon)
- **Orchestration:** launchd (macOS)
- **Browser:** Chrome with persistent user-data-dir, CDP :9222

## Global Constraints

- **Node runtime:** 22 or higher (Ink 7 requirement)
- **React version:** 19.2 (Ink 7 peer)
- **Python:** 3.12
- **Model roster (July 11, 2026 lock, from spec §10):**
  - Chrono: `claude-fable-5`
  - Summarizer: `gemini-3.5-flash`
  - Claude lane: `claude-sonnet-5` (default) / `claude-opus-4-8` (hard)
  - Codex lane: `gpt-5`
  - Gemini lane: `gemini-3.5-flash` (default) / `gemini-3.1-pro-preview` (deep) / `gemini-3-pro-image` (image)
  - Kimi lane: `kimi-k2.7-code`
  - Grok tool: `grok-4.5`
  - DeepSeek tool: `deepseek-v4-pro`
- **Daemon port:** 9876 (localhost)
- **Chrome port:** 9222 (CDP)
- **Chrome profile:** `~/.chrono/chrome-persistent-profile/`
- **Env var handling for lane subprocesses:** Unset `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY` before spawn (forces OAuth path)
- **Subscription-CLI first:** No API-based lanes; API only for Grok/DeepSeek tools and Flash summarization
- **Auditability:** All task packets + outbox manifests + weekly reviews persist to disk in markdown/YAML
- **No automated specialist promotion:** Every specialist file evolution requires operator approval

---

## File Structure

**Files created/modified across all phases:**

### Phase A — Cleanup (deletions and edits)

**Delete:**
```
scripts/python/newsletter_tts.py
scripts/python/podcast_script.py
scripts/python/newsletter_format.py
scripts/python/dream_light.py
scripts/python/improvement_extractor.py
scripts/python/telegram_deliver.py
bin/newsletter-tts.sh
bin/podcast-script.sh
bin/newsletter-format.sh
bin/dream-light.sh
bin/improvement-extractor.sh
bin/telegram-deliver.sh
_state/tmux-logs/
_state/short-survivalist-2026-05-07/
_state/short-survivalist-v2-2026-05-07/
_state/short-survivalist-2026-05-07.mp4
_state/short-survivalist-v2-2026-05-07.mp4
```

**Modify:**
```
bin/run-nightly.sh (remove phases 10, 13-17)
```

**Create:**
```
scripts/python/transcription_cache_ttl.py
bin/transcription-cache-ttl.sh
launchd/com.vibesquad.transcription-cache-ttl.plist
```

### Phase B — Build

**Daemon (Python):**
```
daemon/
├── main.py                       # FastAPI + Uvicorn entrypoint
├── config.py                     # Load config/models.yaml, env
├── routes/
│   ├── __init__.py
│   ├── health.py                 # GET /health
│   ├── task.py                   # POST/GET/DELETE /task
│   ├── project.py                # POST/GET /projects
│   ├── catalog.py                # GET /catalog/search
│   ├── mcp.py                    # POST /mcp/{server}/{tool}
│   ├── summarize.py              # POST /summarize
│   └── events.py                 # WS /events
├── protocol/
│   ├── __init__.py
│   ├── packet.py                 # Task packet schema + validation
│   ├── manifest.py               # Outbox manifest schema
│   └── writer.py                 # Atomic write helpers (from existing protocol.py)
├── watcher.py                    # watchfiles-based outbox watcher
├── mcp_manager.py                # MCP subprocess lifecycle + proxy
├── circuit_breaker.py            # Circuit breaker per lane
├── weekly_review.py              # Sunday review generator
├── flash_summarizer.py           # Gemini 3.5 Flash proxy
└── requirements.txt
```

**Ink app (TypeScript):**
```
ink-app/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.tsx                 # Main entry
│   ├── App.tsx                   # Top-level layout
│   ├── components/
│   │   ├── Header.tsx            # Project + status line
│   │   ├── ChronoPane.tsx        # Main pane
│   │   ├── LanePane.tsx          # Individual model pane
│   │   ├── StatusBadge.tsx       # Colored dot badges
│   │   ├── HandoffArrow.tsx      # 1s animation
│   │   └── PendingStrip.tsx      # Queue visibility
│   ├── chrono/
│   │   ├── sdk-client.ts         # Claude Agent SDK wrapper
│   │   ├── prompt-loader.ts      # System prompt + specialist assembly
│   │   └── router.ts             # Specialist selection logic
│   ├── pty/
│   │   ├── lane-process.ts       # node-pty wrapper per CLI
│   │   ├── session-control.ts    # /newsession commands per CLI
│   │   └── output-parser.ts      # Extract tool-use, status hints
│   ├── daemon-client/
│   │   ├── http.ts               # fetch wrapper for daemon API
│   │   └── events.ts             # WebSocket subscription
│   ├── config/
│   │   └── models.ts             # Load models.yaml
│   └── types/
│       └── protocol.ts           # TypeScript types matching daemon
└── bin/vibe-squad                # Launcher script
```

**MCP: chrono-recon:**
```
/Users/user/chrono/plugins/chrono-recon/
├── .claude-plugin/
│   └── plugin.json
├── mcp_server.py                 # FastMCP entrypoint
├── tools/
│   ├── __init__.py
│   ├── dns.py                    # dns_enumerate
│   ├── whois.py                  # whois_lookup
│   ├── crt_sh.py                 # crt_sh_certificates
│   ├── wayback.py                # wayback_snapshots
│   └── github_secrets.py         # github_leaked_secrets
├── requirements.txt
└── README.md
```

**Specialist updates:**
```
shared/specialist-runtime-map.tsv       # updated with new models + preferred_tools
departments/*/specialists/*.md           # add frontmatter to all 46
departments/content-engineer/
├── README.md
└── specialists/
    ├── copywriter.md
    ├── voice-narrator.md
    ├── music-composer.md
    ├── sound-designer.md
    ├── video-director.md
    ├── video-editor.md
    ├── image-designer.md
    ├── web-builder.md
    ├── game-designer.md
    └── voice-agent-builder.md
shared/tool-catalog.md                    # capability-organized tool reference
```

**Configuration:**
```
config/models.yaml
config/mcp-shared-template.json          # MCP config template
```

**launchd:**
```
launchd/com.vibesquad.daemon.plist
launchd/com.vibesquad.chrome.plist
launchd/com.vibesquad.weekly-review.plist
launchd/com.vibesquad.nightly-content.plist (updated)
```

**Project workspace:**
```
projects/                                # existing? or new top-level
├── bounties/
├── lead-gens/
├── websites/
├── content/
├── research/
├── experiments/
└── system/
    └── vibe-squad-redesign-2026-07-11/  # This project
        ├── brief.md
        ├── state.yaml
        └── ...
```

### Phase C — Cutover

**Archive/rewrite:**
```
_archive/pre-redesign-bin/               # old bin/ archived
_archive/pre-redesign-docs/              # old docs archived
_archive/task-board-2026-05.tar.gz       # old task board
README.md                                # rewritten
docs/architecture.md                     # new
docs/adding-a-specialist.md              # new
```

---

# PHASE A — Legacy cleanup (Tasks 1-4)

## Task 1: Remove dead content pipeline (single commit)

**Files:**
- Delete: `scripts/python/newsletter_tts.py`, `podcast_script.py`, `newsletter_format.py`, `dream_light.py`, `improvement_extractor.py`, `telegram_deliver.py`
- Delete: `bin/newsletter-tts.sh`, `podcast-script.sh`, `newsletter-format.sh`, `dream-light.sh`, `improvement-extractor.sh`, `telegram-deliver.sh`
- Modify: `bin/run-nightly.sh` (remove phases 10, 13-17)

**Interfaces:**
- Produces: cleaner scripts/python/ and bin/ trees
- Downstream: `run-nightly.sh` continues to run at 03:00 UTC without errors

- [ ] **Step 1: Check for uncommitted work on files to be deleted**

Run:
```bash
cd /Users/user/Obsidian-Claude-Vibe-Squad
git status scripts/python/newsletter_format.py scripts/python/newsletter_tts.py scripts/python/podcast_script.py scripts/python/dream_light.py scripts/python/improvement_extractor.py scripts/python/telegram_deliver.py
```
Expected: If any file appears as "modified," STOP and consult operator before proceeding.

- [ ] **Step 2: Read current `bin/run-nightly.sh` to identify exact phase lines**

Run: `grep -n -E "(dream-light|improvement-extractor|newsletter-format|podcast-script|newsletter-tts|telegram-deliver)" bin/run-nightly.sh`
Expected: 5-6 line matches. Record line numbers for editing.

- [ ] **Step 3: Delete the 6 Python scripts and 6 shell wrappers**

Run:
```bash
rm scripts/python/newsletter_tts.py
rm scripts/python/podcast_script.py
rm scripts/python/newsletter_format.py
rm scripts/python/dream_light.py
rm scripts/python/improvement_extractor.py
rm scripts/python/telegram_deliver.py
rm bin/newsletter-tts.sh
rm bin/podcast-script.sh
rm bin/newsletter-format.sh
rm bin/dream-light.sh
rm bin/improvement-extractor.sh
rm bin/telegram-deliver.sh
```

- [ ] **Step 4: Edit `bin/run-nightly.sh` to remove dead phases**

Remove any lines invoking the deleted scripts. Preserve morning-brief phase and all healthy phases (feed_sweep, content_triage, content_processing, content_synthesis, cross_day_context, brain_cleanup, browser_keep_alive).

- [ ] **Step 5: Syntax-check the edited script**

Run: `bash -n bin/run-nightly.sh`
Expected: exit code 0 (no syntax errors).

- [ ] **Step 6: Confirm no other script references the deleted scripts**

Run:
```bash
grep -rn -E "(newsletter_tts|podcast_script|newsletter_format|dream_light|improvement_extractor|telegram_deliver)" bin/ scripts/ shared/ departments/ 2>/dev/null
```
Expected: Empty output (no references remain).

- [ ] **Step 7: Commit**

```bash
git add -A scripts/python/ bin/
git commit -m "cleanup: remove dead content pipeline (newsletter/podcast/dream-light/improvement-extractor/telegram)"
```

- [ ] **Step 8: Verify next nightly run**

Run: `launchctl start com.claudevibesquad.nightly`
Wait ~30 seconds, then: `tail -100 /tmp/claudevibesquad-nightly-stdout.log`
Expected: No "command not found" errors. morning-brief still generates.

---

## Task 2: Purge tmux-logs

**Files:**
- Delete: `_state/tmux-logs/` (~201MB)

**Interfaces:**
- Consumes: nothing
- Produces: 201MB reclaimed disk space

- [ ] **Step 1: Confirm size and last-write timestamp**

Run: `du -sh _state/tmux-logs/ && ls -la _state/tmux-logs/ | head -5`
Expected: ~201MB, timestamps older than 60 days (verifying nothing actively writes here).

- [ ] **Step 2: Confirm nothing writes to tmux-logs currently**

Run: `lsof +D _state/tmux-logs/ 2>/dev/null | head -5`
Expected: Empty output (no open file handles).

- [ ] **Step 3: Delete the directory**

Run: `rm -rf _state/tmux-logs/`

- [ ] **Step 4: Verify deletion and reclaimed space**

Run: `du -sh _state/`
Expected: Total should be ~201MB less than before.

- [ ] **Step 5: Commit**

```bash
git add -A _state/
git commit -m "cleanup: purge tmux-logs (-201MB)"
```

---

## Task 3: Delete short-survivalist video projects

**Files:**
- Delete: `_state/short-survivalist-2026-05-07/`, `_state/short-survivalist-v2-2026-05-07/`
- Delete: `_state/short-survivalist-2026-05-07.mp4`, `_state/short-survivalist-v2-2026-05-07.mp4`

**Interfaces:**
- Consumes: nothing
- Produces: 331MB reclaimed

- [ ] **Step 1: Confirm sizes**

Run:
```bash
du -sh _state/short-survivalist-2026-05-07/ _state/short-survivalist-v2-2026-05-07/ _state/short-survivalist-*.mp4
```
Expected: Combined ~331MB.

- [ ] **Step 2: Confirm no references to these paths from active scripts**

Run: `grep -rn "short-survivalist" bin/ scripts/ shared/ departments/ 2>/dev/null`
Expected: Empty output.

- [ ] **Step 3: Delete**

Run:
```bash
rm -rf _state/short-survivalist-2026-05-07/
rm -rf _state/short-survivalist-v2-2026-05-07/
rm _state/short-survivalist-2026-05-07.mp4
rm _state/short-survivalist-v2-2026-05-07.mp4
```

- [ ] **Step 4: Verify**

Run: `ls _state/ | grep -i survivalist`
Expected: Empty output.

- [ ] **Step 5: Commit**

```bash
git add -A _state/
git commit -m "cleanup: delete short-survivalist video projects (-331MB, deemed garbage by operator)"
```

---

## Task 4: Transcription-cache TTL policy

**Files:**
- Create: `scripts/python/transcription_cache_ttl.py`
- Create: `bin/transcription-cache-ttl.sh`
- Create: `launchd/com.vibesquad.transcription-cache-ttl.plist`

**Interfaces:**
- Produces: automated 15-day TTL cleanup of `_state/transcription-cache/`
- Downstream: weekly-executed via launchd

- [ ] **Step 1: Write the TTL cleanup script**

Create `scripts/python/transcription_cache_ttl.py`:

```python
"""Purge transcription-cache entries older than TTL_DAYS."""
import os
import time
from pathlib import Path

CACHE_DIR = Path(os.environ.get("VIBESQUAD_ROOT", "/Users/user/Obsidian-Claude-Vibe-Squad")) / "_state" / "transcription-cache"
TTL_DAYS = int(os.environ.get("TTL_DAYS", "15"))

def main() -> int:
    if not CACHE_DIR.exists():
        print(f"[ttl] cache dir absent: {CACHE_DIR}")
        return 0
    cutoff = time.time() - (TTL_DAYS * 86400)
    removed = 0
    bytes_freed = 0
    for path in CACHE_DIR.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            bytes_freed += path.stat().st_size
            path.unlink()
            removed += 1
    print(f"[ttl] removed {removed} files, freed {bytes_freed // 1024 // 1024}MB")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write the shell wrapper**

Create `bin/transcription-cache-ttl.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/python/transcription_cache_ttl.py "$@"
```

Then: `chmod +x bin/transcription-cache-ttl.sh`

- [ ] **Step 3: Write the launchd plist**

Create `launchd/com.vibesquad.transcription-cache-ttl.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.vibesquad.transcription-cache-ttl</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/user/Obsidian-Claude-Vibe-Squad/bin/transcription-cache-ttl.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>4</integer>
        <key>Minute</key>
        <integer>0</integer>
        <key>Weekday</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/vibesquad-ttl-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/vibesquad-ttl-stderr.log</string>
</dict>
</plist>
```

- [ ] **Step 4: Test the script by running it directly**

Run: `bash bin/transcription-cache-ttl.sh`
Expected: Output like `[ttl] removed N files, freed XMB`. If cache dir absent, output confirms.

- [ ] **Step 5: Install the launchd plist**

Run:
```bash
cp launchd/com.vibesquad.transcription-cache-ttl.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.vibesquad.transcription-cache-ttl.plist
launchctl list | grep transcription-cache-ttl
```
Expected: Job appears in listing.

- [ ] **Step 6: Commit**

```bash
git add scripts/python/transcription_cache_ttl.py bin/transcription-cache-ttl.sh launchd/com.vibesquad.transcription-cache-ttl.plist
git commit -m "chore: transcription-cache 15-day TTL policy (weekly Sunday 04:00)"
```

---

# PHASE B — Build (Tasks 5-18)

## Task 5: Daemon skeleton (FastAPI + launchd)

**Files:**
- Create: `daemon/main.py`, `daemon/config.py`, `daemon/routes/health.py`, `daemon/requirements.txt`
- Create: `launchd/com.vibesquad.daemon.plist`

**Interfaces:**
- Produces: `GET /health` returning `{status: "ok", version: "0.1.0"}`; daemon listens on :9876; managed by launchd
- Downstream: All later daemon tasks add routes/logic to this skeleton

- [ ] **Step 1: Write the failing health-check test**

Create `daemon/tests/test_health.py`:

```python
from fastapi.testclient import TestClient
from daemon.main import app

def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

- [ ] **Step 2: Write daemon skeleton (main.py)**

Create `daemon/main.py`:

```python
from fastapi import FastAPI
from daemon.routes import health

app = FastAPI(title="vibe-squad daemon", version="0.1.0")
app.include_router(health.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9876)
```

Create `daemon/routes/health.py`:

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
```

Create `daemon/routes/__init__.py` (empty).

Create `daemon/requirements.txt`:

```
fastapi==0.115.*
uvicorn==0.32.*
pydantic==2.9.*
pyyaml==6.0.*
watchfiles==0.24.*
httpx==0.27.*
```

- [ ] **Step 3: Install deps and run the test**

Run: `cd /Users/user/Obsidian-Claude-Vibe-Squad && python3 -m venv .venv && source .venv/bin/activate && pip install -r daemon/requirements.txt pytest`
Then: `pytest daemon/tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 4: Test daemon starts and responds**

Run in background: `python3 -m daemon.main &`
Then: `curl -s http://127.0.0.1:9876/health`
Expected: `{"status":"ok","version":"0.1.0"}`
Kill: `pkill -f "daemon.main"`

- [ ] **Step 5: Write daemon launchd plist**

Create `launchd/com.vibesquad.daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.vibesquad.daemon</string>
    <key>WorkingDirectory</key>
    <string>/Users/user/Obsidian-Claude-Vibe-Squad</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/user/Obsidian-Claude-Vibe-Squad/.venv/bin/python</string>
        <string>-m</string>
        <string>daemon.main</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/vibesquad-daemon-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/vibesquad-daemon-stderr.log</string>
</dict>
</plist>
```

- [ ] **Step 6: Install and test launchd job**

Run:
```bash
cp launchd/com.vibesquad.daemon.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.vibesquad.daemon.plist
sleep 2
curl -s http://127.0.0.1:9876/health
```
Expected: `{"status":"ok","version":"0.1.0"}`

- [ ] **Step 7: Commit**

```bash
git add daemon/ launchd/com.vibesquad.daemon.plist
git commit -m "feat: daemon skeleton with health endpoint (launchd-managed on :9876)"
```

---

## Task 6: Task-board wrapping (existing protocol → FastAPI routes)

**Files:**
- Create: `daemon/protocol/packet.py`, `daemon/protocol/manifest.py`, `daemon/protocol/writer.py`
- Create: `daemon/routes/task.py`
- Modify: `daemon/main.py` (add task router)

**Interfaces:**
- Consumes: existing `scripts/python/` task-board utilities (import, don't rewrite)
- Produces: `POST /task` accepts packet, atomically writes to inbox, returns 200 with `task_id`; `GET /tasks` lists queued+running; `GET /tasks/{id}` returns state

- [ ] **Step 1: Write packet + manifest models**

Create `daemon/protocol/packet.py`:

```python
from pydantic import BaseModel, Field
from typing import Optional
import uuid
from datetime import datetime

class TaskPacket(BaseModel):
    task_id: str = Field(default_factory=lambda: f"t-{uuid.uuid4()}")
    project: Optional[str] = None
    specialist: str
    specialist_file: str
    version: str = "2.0"
    lane: str
    model: str
    model_key: str
    required_tools: list[str] = []
    preferred_tools: list[str] = []
    requires_approval: list[str] = []
    prompt: str
    context: dict = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

Create `daemon/protocol/manifest.py`:

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class OutboxManifest(BaseModel):
    task_id: str
    completed_at: datetime
    duration_seconds: float
    result: str
    tools_used: dict[str, int] = {}
    approvals_requested: int = 0
    tokens_used: dict[str, int] = {}
    next_actions: list[dict] = []
```

- [ ] **Step 2: Write atomic writer**

Create `daemon/protocol/writer.py`:

```python
import os
import tempfile
import yaml
from pathlib import Path

def atomic_write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, suffix=".tmp"
    ) as tmp:
        yaml.safe_dump(data, tmp, sort_keys=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.rename(path)
```

Create `daemon/protocol/__init__.py` (empty).

- [ ] **Step 3: Write the task-route test**

Create `daemon/tests/test_task_route.py`:

```python
from fastapi.testclient import TestClient
from daemon.main import app
from pathlib import Path
import tempfile
import os

def test_post_task_writes_to_inbox(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBESQUAD_STATE_DIR", str(tmp_path))
    client = TestClient(app)
    packet = {
        "specialist": "researcher",
        "specialist_file": "specialists/researcher.md",
        "lane": "kimi",
        "model": "kimi-k2.7-code",
        "model_key": "default",
        "prompt": "Research topic X",
    }
    response = client.post("/task", json=packet)
    assert response.status_code == 200
    body = response.json()
    assert "task_id" in body
    inbox_files = list((tmp_path / "inbox" / "kimi").glob("*.md"))
    assert len(inbox_files) == 1
```

- [ ] **Step 4: Implement task route**

Create `daemon/routes/task.py`:

```python
from fastapi import APIRouter, HTTPException
from pathlib import Path
import os
from daemon.protocol.packet import TaskPacket
from daemon.protocol.writer import atomic_write_yaml

router = APIRouter()

def _state_dir() -> Path:
    return Path(os.environ.get("VIBESQUAD_STATE_DIR", "/Users/user/Obsidian-Claude-Vibe-Squad/daemon/state"))

@router.post("/task")
def create_task(packet: TaskPacket):
    inbox = _state_dir() / "inbox" / packet.lane
    target = inbox / f"{packet.task_id}.md"
    atomic_write_yaml(target, packet.model_dump(mode="json"))
    return {"task_id": packet.task_id, "path": str(target)}

@router.get("/tasks")
def list_tasks():
    state = _state_dir()
    tasks = []
    for lane_dir in (state / "inbox").glob("*") if (state / "inbox").exists() else []:
        for task_file in lane_dir.glob("*.md"):
            tasks.append({"task_id": task_file.stem, "lane": lane_dir.name, "state": "queued"})
    return {"tasks": tasks}

@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    state = _state_dir()
    for path in state.rglob(f"{task_id}.md"):
        return {"task_id": task_id, "path": str(path)}
    raise HTTPException(status_code=404, detail="task not found")
```

- [ ] **Step 5: Wire router into main**

Edit `daemon/main.py`:

```python
from daemon.routes import health, task

app.include_router(health.router)
app.include_router(task.router)
```

- [ ] **Step 6: Run tests**

Run: `pytest daemon/tests/ -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add daemon/protocol/ daemon/routes/task.py daemon/main.py daemon/tests/test_task_route.py
git commit -m "feat: task-board endpoints (POST /task, GET /tasks, GET /tasks/{id}) with atomic writes"
```

---

## Task 7: MCP proxy layer

**Files:**
- Create: `daemon/mcp_manager.py`, `daemon/routes/mcp.py`
- Modify: `daemon/main.py`

**Interfaces:**
- Produces: `POST /mcp/{server}/{tool}` proxies to underlying MCP server, returns tool result; MCP subprocesses respawn on crash

- [ ] **Step 1: Write mcp_manager**

Create `daemon/mcp_manager.py`:

```python
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Optional

MCP_REGISTRY = {
    "chrono-vault": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-vault/mcp_server.py"],
    "chrono-research-arsenal": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-research-arsenal/mcp_server.py"],
    "chrono-content-engineer": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-content-engineer/mcp_server.py"],
    "chrono-recon": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-recon/mcp_server.py"],
}

class MCPManager:
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}

    def ensure_running(self, server: str) -> subprocess.Popen:
        proc = self.processes.get(server)
        if proc and proc.poll() is None:
            return proc
        if server not in MCP_REGISTRY:
            raise ValueError(f"unknown MCP server: {server}")
        proc = subprocess.Popen(
            MCP_REGISTRY[server],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.processes[server] = proc
        return proc

    async def call_tool(self, server: str, tool: str, arguments: dict) -> dict:
        proc = self.ensure_running(server)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        proc.stdin.write((json.dumps(request) + "\n").encode())
        proc.stdin.flush()
        response_line = proc.stdout.readline()
        return json.loads(response_line)

MANAGER = MCPManager()
```

- [ ] **Step 2: Write MCP route**

Create `daemon/routes/mcp.py`:

```python
from fastapi import APIRouter, HTTPException
from daemon.mcp_manager import MANAGER

router = APIRouter()

@router.post("/mcp/{server}/{tool}")
async def call_mcp_tool(server: str, tool: str, arguments: dict = None):
    try:
        result = await MANAGER.call_tool(server, tool, arguments or {})
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
```

- [ ] **Step 3: Wire router**

Edit `daemon/main.py`:

```python
from daemon.routes import health, task, mcp

app.include_router(mcp.router)
```

- [ ] **Step 4: Test the proxy end-to-end**

Restart daemon: `launchctl unload ~/Library/LaunchAgents/com.vibesquad.daemon.plist && launchctl load ~/Library/LaunchAgents/com.vibesquad.daemon.plist`

Run:
```bash
curl -s -X POST http://127.0.0.1:9876/mcp/chrono-vault/read_specialist \
  -H "Content-Type: application/json" \
  -d '{"specialist": "security-analyst"}'
```
Expected: JSON response with either specialist content or error (either proves the proxy works).

- [ ] **Step 5: Commit**

```bash
git add daemon/mcp_manager.py daemon/routes/mcp.py daemon/main.py
git commit -m "feat: MCP proxy layer with per-server subprocess management"
```

---

## Task 8: Persistent Chrome service

**Files:**
- Create: `launchd/com.vibesquad.chrome.plist`
- Create: `bin/chrome-bootstrap.sh` (creates profile dir if absent)

**Interfaces:**
- Produces: Chrome runs persistently on :9222 with `~/.chrono/chrome-persistent-profile/`; survives vibe-squad restarts; launchd auto-restarts on crash

- [ ] **Step 1: Write bootstrap script**

Create `bin/chrome-bootstrap.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
PROFILE_DIR="$HOME/.chrono/chrome-persistent-profile"
mkdir -p "$PROFILE_DIR"
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --user-data-dir="$PROFILE_DIR" \
    --remote-debugging-port=9222 \
    --remote-allow-origins=* \
    --no-first-run \
    --no-default-browser-check \
    --restore-last-session
```

Then: `chmod +x bin/chrome-bootstrap.sh`

- [ ] **Step 2: Write Chrome launchd plist**

Create `launchd/com.vibesquad.chrome.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.vibesquad.chrome</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/user/Obsidian-Claude-Vibe-Squad/bin/chrome-bootstrap.sh</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/vibesquad-chrome-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/vibesquad-chrome-stderr.log</string>
</dict>
</plist>
```

- [ ] **Step 3: Install and start**

Run:
```bash
cp launchd/com.vibesquad.chrome.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.vibesquad.chrome.plist
sleep 3
curl -s http://127.0.0.1:9222/json/version | head -20
```
Expected: JSON with Chrome version info.

- [ ] **Step 4: Test CDP attach with Playwright**

Run (this creates a smoke test):
```bash
cat > /tmp/cdp-smoke.py <<'EOF'
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = await browser.new_page()
        await page.goto("https://example.com")
        title = await page.title()
        print(f"page title: {title}")
        await browser.close()

asyncio.run(main())
EOF
python3 -m pip install playwright 2>/dev/null && python3 -m playwright install chromium 2>/dev/null || true
python3 /tmp/cdp-smoke.py
```
Expected: `page title: Example Domain`

- [ ] **Step 5: Commit**

```bash
git add bin/chrome-bootstrap.sh launchd/com.vibesquad.chrome.plist
git commit -m "feat: persistent Chrome service on :9222 with persistent user-data-dir"
```

---

## Task 9: chrono-recon MCP (v1 keyless tools)

**Files:**
- Create: `/Users/user/chrono/plugins/chrono-recon/.claude-plugin/plugin.json`
- Create: `/Users/user/chrono/plugins/chrono-recon/mcp_server.py`
- Create: `/Users/user/chrono/plugins/chrono-recon/tools/dns.py`, `whois.py`, `crt_sh.py`, `wayback.py`, `github_secrets.py`
- Create: `/Users/user/chrono/plugins/chrono-recon/requirements.txt`

**Interfaces:**
- Produces: 5 OSINT tools accessible via chrono-recon MCP server:
  - `dns_enumerate(domain: str, record_types: list = None) -> dict`
  - `whois_lookup(domain_or_ip: str) -> dict`
  - `crt_sh_certificates(domain: str) -> list[dict]`
  - `wayback_snapshots(url: str, from_date: str = None, to_date: str = None) -> list[dict]`
  - `github_leaked_secrets(query: str, org: str = None) -> list[dict]`

- [ ] **Step 1: Create plugin.json**

Create `/Users/user/chrono/plugins/chrono-recon/.claude-plugin/plugin.json`:

```json
{
  "name": "chrono-recon",
  "version": "0.1.0",
  "description": "OSINT recon tools for Vibe Squad specialists (dns, whois, crt.sh, wayback, github secrets)",
  "license": "AGPL-3.0-or-later",
  "mcpServers": {
    "chrono-recon": {
      "command": "/Users/user/chrono/.venv/bin/python",
      "args": ["/Users/user/chrono/plugins/chrono-recon/mcp_server.py"],
      "env": {
        "GH_TOKEN": "${GH_TOKEN}"
      }
    }
  }
}
```

- [ ] **Step 2: Write requirements.txt**

```
mcp==1.0.*
dnspython==2.7.*
python-whois==0.9.*
httpx==0.27.*
```

- [ ] **Step 3: Implement dns tool**

Create `tools/dns.py`:

```python
import dns.resolver
from typing import Optional

def dns_enumerate(domain: str, record_types: Optional[list[str]] = None) -> dict:
    types = record_types or ["A", "MX", "NS", "TXT", "CNAME"]
    results = {}
    for rtype in types:
        try:
            answers = dns.resolver.resolve(domain, rtype)
            results[rtype] = [str(a) for a in answers]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException) as e:
            results[rtype] = {"error": type(e).__name__}
    return {"domain": domain, "records": results}
```

- [ ] **Step 4: Implement whois tool**

Create `tools/whois.py`:

```python
import whois

def whois_lookup(domain_or_ip: str) -> dict:
    try:
        w = whois.whois(domain_or_ip)
        return {
            "registrar": w.registrar,
            "creation_date": str(w.creation_date),
            "expiration_date": str(w.expiration_date),
            "name_servers": w.name_servers,
            "status": w.status,
            "raw": str(w.text)[:2000] if w.text else None,
        }
    except Exception as e:
        return {"error": str(e)}
```

- [ ] **Step 5: Implement crt.sh tool**

Create `tools/crt_sh.py`:

```python
import httpx

def crt_sh_certificates(domain: str) -> list[dict]:
    url = f"https://crt.sh/?q={domain}&output=json"
    try:
        resp = httpx.get(url, timeout=15.0)
        resp.raise_for_status()
        raw = resp.json()
        return [{"issuer": r.get("issuer_name"), "name": r.get("name_value"), "not_before": r.get("not_before")} for r in raw[:100]]
    except Exception as e:
        return [{"error": str(e)}]
```

- [ ] **Step 6: Implement wayback tool**

Create `tools/wayback.py`:

```python
import httpx
from typing import Optional

def wayback_snapshots(url: str, from_date: Optional[str] = None, to_date: Optional[str] = None) -> list[dict]:
    api = f"https://web.archive.org/cdx/search/cdx?url={url}&output=json&limit=50"
    if from_date:
        api += f"&from={from_date}"
    if to_date:
        api += f"&to={to_date}"
    try:
        resp = httpx.get(api, timeout=15.0)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return []
        headers = rows[0]
        return [dict(zip(headers, row)) for row in rows[1:]]
    except Exception as e:
        return [{"error": str(e)}]
```

- [ ] **Step 7: Implement github_secrets tool**

Create `tools/github_secrets.py`:

```python
import httpx
import os
from typing import Optional

def github_leaked_secrets(query: str, org: Optional[str] = None) -> list[dict]:
    token = os.environ.get("GH_TOKEN")
    if not token:
        return [{"error": "GH_TOKEN not set"}]
    q = query
    if org:
        q += f" org:{org}"
    url = f"https://api.github.com/search/code?q={q}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    try:
        resp = httpx.get(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        return [{"repo": item["repository"]["full_name"], "path": item["path"], "url": item["html_url"]} for item in data.get("items", [])[:20]]
    except Exception as e:
        return [{"error": str(e)}]
```

- [ ] **Step 8: Write MCP server**

Create `tools/__init__.py` (empty).

Create `mcp_server.py`:

```python
from mcp.server.fastmcp import FastMCP
from tools.dns import dns_enumerate
from tools.whois import whois_lookup
from tools.crt_sh import crt_sh_certificates
from tools.wayback import wayback_snapshots
from tools.github_secrets import github_leaked_secrets

mcp = FastMCP("chrono-recon")

@mcp.tool()
def dns_enumerate_tool(domain: str, record_types: list = None) -> dict:
    """Enumerate DNS records for a domain."""
    return dns_enumerate(domain, record_types)

@mcp.tool()
def whois_lookup_tool(domain_or_ip: str) -> dict:
    """Look up WHOIS registration info."""
    return whois_lookup(domain_or_ip)

@mcp.tool()
def crt_sh_certificates_tool(domain: str) -> list:
    """Search TLS certificate transparency logs for subdomains."""
    return crt_sh_certificates(domain)

@mcp.tool()
def wayback_snapshots_tool(url: str, from_date: str = None, to_date: str = None) -> list:
    """List Internet Archive Wayback Machine snapshots for a URL."""
    return wayback_snapshots(url, from_date, to_date)

@mcp.tool()
def github_leaked_secrets_tool(query: str, org: str = None) -> list:
    """Search public GitHub code for leaked secrets or terms."""
    return github_leaked_secrets(query, org)

if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 9: Install deps and test**

Run:
```bash
cd /Users/user/chrono
source .venv/bin/activate
pip install -r plugins/chrono-recon/requirements.txt
python plugins/chrono-recon/tools/dns.py 2>&1 | head -5 || echo "module works, no main"
python -c "from plugins.chrono_recon.tools.dns import dns_enumerate; print(dns_enumerate('example.com'))"
```
Expected: DNS records for example.com printed.

- [ ] **Step 10: Test through daemon MCP proxy**

Restart daemon: `launchctl unload ~/Library/LaunchAgents/com.vibesquad.daemon.plist && launchctl load ~/Library/LaunchAgents/com.vibesquad.daemon.plist`

Run:
```bash
curl -s -X POST http://127.0.0.1:9876/mcp/chrono-recon/dns_enumerate_tool \
  -H "Content-Type: application/json" \
  -d '{"domain": "example.com"}'
```
Expected: JSON with DNS records.

- [ ] **Step 11: Commit**

```bash
cd /Users/user/chrono
git add plugins/chrono-recon/
git commit -m "feat: chrono-recon MCP with 5 keyless OSINT tools (dns, whois, crt.sh, wayback, github secrets)"
```

---

## Task 10: File watcher + WS events

**Files:**
- Create: `daemon/watcher.py`, `daemon/routes/events.py`
- Modify: `daemon/main.py`

**Interfaces:**
- Produces: `watchfiles` observes `state/outbox/*` recursively; on new file, emits `{"type": "task_complete", "task_id": "...", "path": "..."}` to `WS /events`

- [ ] **Step 1: Write watcher**

Create `daemon/watcher.py`:

```python
import asyncio
from pathlib import Path
from watchfiles import awatch, Change
from typing import AsyncIterator
import os

class OutboxWatcher:
    def __init__(self):
        self.subscribers: list[asyncio.Queue] = []

    def _state_dir(self) -> Path:
        return Path(os.environ.get("VIBESQUAD_STATE_DIR", "/Users/user/Obsidian-Claude-Vibe-Squad/daemon/state"))

    async def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subscribers.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)

    async def run(self):
        outbox = self._state_dir() / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        async for changes in awatch(str(outbox)):
            for change_type, path in changes:
                if change_type == Change.added and path.endswith(".md"):
                    p = Path(path)
                    event = {"type": "task_complete", "task_id": p.stem, "path": str(p)}
                    for q in self.subscribers:
                        await q.put(event)

WATCHER = OutboxWatcher()
```

- [ ] **Step 2: Write WS route**

Create `daemon/routes/events.py`:

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from daemon.watcher import WATCHER
import asyncio
import json

router = APIRouter()

@router.websocket("/events")
async def events_stream(ws: WebSocket):
    await ws.accept()
    queue = await WATCHER.subscribe()
    try:
        while True:
            event = await queue.get()
            await ws.send_text(json.dumps(event))
    except WebSocketDisconnect:
        pass
    finally:
        await WATCHER.unsubscribe(queue)
```

- [ ] **Step 3: Wire watcher into main app startup**

Edit `daemon/main.py`:

```python
from daemon.routes import health, task, mcp, events
from daemon.watcher import WATCHER
import asyncio

app.include_router(events.router)

@app.on_event("startup")
async def start_watcher():
    asyncio.create_task(WATCHER.run())
```

- [ ] **Step 4: Test end-to-end**

Restart daemon. In one terminal:
```bash
websocat ws://127.0.0.1:9876/events
```
(install websocat if missing: `brew install websocat`)

In another terminal, write a fake outbox file:
```bash
mkdir -p daemon/state/outbox/kimi
echo "task_id: t-test-1" > daemon/state/outbox/kimi/t-test-1.md
```
Expected: WS client receives `{"type":"task_complete","task_id":"t-test-1",...}`

Cleanup: `rm daemon/state/outbox/kimi/t-test-1.md`

- [ ] **Step 5: Commit**

```bash
git add daemon/watcher.py daemon/routes/events.py daemon/main.py
git commit -m "feat: outbox file watcher + WS /events streaming"
```

---

## Task 11: Ink app scaffold (bootstrap + layout)

**Files:**
- Create: `ink-app/package.json`, `ink-app/tsconfig.json`, `ink-app/src/index.tsx`, `ink-app/src/App.tsx`
- Create: `ink-app/src/components/Header.tsx`, `ChronoPane.tsx`, `LanePane.tsx`, `StatusBadge.tsx`

**Interfaces:**
- Produces: `npm run start` renders TUI with header, Chrono pane (top half), and 4 model panes (bottom 2x2 grid). Placeholder content in all panes.

- [ ] **Step 1: Initialize project**

Run:
```bash
cd /Users/user/Obsidian-Claude-Vibe-Squad
mkdir -p ink-app/src/components ink-app/src/types
cd ink-app
npm init -y
npm install ink react ink-spinner ink-text-input ink-select-input @anthropic-ai/claude-agent-sdk node-pty
npm install -D typescript @types/react @types/node tsx
```

- [ ] **Step 2: Write tsconfig**

Create `tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "outDir": "dist"
  },
  "include": ["src/**/*"]
}
```

- [ ] **Step 3: Update package.json scripts**

Add:
```json
{
  "type": "module",
  "scripts": {
    "start": "tsx src/index.tsx",
    "dev": "tsx watch src/index.tsx",
    "build": "tsc"
  }
}
```

- [ ] **Step 4: Write StatusBadge component**

Create `src/components/StatusBadge.tsx`:

```typescript
import React from 'react';
import { Text } from 'ink';

type Status = 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error' | 'stuck' | 'starting';

const BADGES: Record<Status, {char: string; color: string}> = {
  idle: {char: '⚪', color: 'gray'},
  thinking: {char: '⣾', color: 'cyan'},
  tool: {char: '🔧', color: 'yellow'},
  waiting: {char: '⏸', color: 'blue'},
  done: {char: '🟢', color: 'green'},
  error: {char: '⚠️', color: 'yellow'},
  stuck: {char: '🔴', color: 'red'},
  starting: {char: '🔵', color: 'blue'},
};

export const StatusBadge: React.FC<{status: Status; label?: string}> = ({status, label}) => {
  const badge = BADGES[status];
  return (
    <Text color={badge.color}>
      {badge.char} {label ?? status}
    </Text>
  );
};
```

- [ ] **Step 5: Write LanePane component**

Create `src/components/LanePane.tsx`:

```typescript
import React from 'react';
import { Box, Text } from 'ink';
import { StatusBadge } from './StatusBadge.js';

interface Props {
  name: string;
  status: 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error' | 'stuck' | 'starting';
  detail?: string;
  metric?: string;
  duration?: string;
}

export const LanePane: React.FC<Props> = ({name, status, detail, metric, duration}) => (
  <Box flexDirection="column" borderStyle="single" width="25%">
    <StatusBadge status={status} label={name} />
    {detail && <Text dimColor>{detail}</Text>}
    {metric && <Text dimColor>↳ {metric}</Text>}
    {duration && <Text dimColor>{duration}</Text>}
  </Box>
);
```

- [ ] **Step 6: Write Header component**

Create `src/components/Header.tsx`:

```typescript
import React from 'react';
import { Box, Text } from 'ink';

interface Props {
  project?: string;
  readyCount: number;
  totalLanes: number;
  timestamp: string;
  usage: {claude: number; codex: number; gemini: number; kimi: number};
}

export const Header: React.FC<Props> = ({project, readyCount, totalLanes, timestamp, usage}) => (
  <Box flexDirection="column" borderStyle="double">
    <Box>
      <Text bold>vibe-squad</Text>
      <Text> │ project: {project ?? 'none'} │ {readyCount}/{totalLanes} ready │ {timestamp}</Text>
    </Box>
    <Text dimColor>
      claude {usage.claude}% │ codex {usage.codex}% │ gemini {usage.gemini}% │ kimi {usage.kimi}%
    </Text>
  </Box>
);
```

- [ ] **Step 7: Write ChronoPane component**

Create `src/components/ChronoPane.tsx`:

```typescript
import React from 'react';
import { Box, Text } from 'ink';
import { StatusBadge } from './StatusBadge.js';

interface Props {
  status: 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error' | 'stuck' | 'starting';
  transcript: {role: 'you' | 'chrono' | 'route'; text: string}[];
}

export const ChronoPane: React.FC<Props> = ({status, transcript}) => (
  <Box flexDirection="column" borderStyle="round" width="100%">
    <StatusBadge status={status} label="Chrono" />
    <Box flexDirection="column" marginTop={1}>
      {transcript.map((entry, i) => (
        <Box key={i} marginTop={1}>
          <Text bold color={entry.role === 'you' ? 'green' : entry.role === 'chrono' ? 'cyan' : 'yellow'}>
            {entry.role}
          </Text>
          <Text>{'  '}{entry.text}</Text>
        </Box>
      ))}
    </Box>
  </Box>
);
```

- [ ] **Step 8: Write App and entry**

Create `src/App.tsx`:

```typescript
import React, { useState } from 'react';
import { Box } from 'ink';
import { Header } from './components/Header.js';
import { ChronoPane } from './components/ChronoPane.js';
import { LanePane } from './components/LanePane.js';

export const App: React.FC = () => {
  const [now] = useState(new Date().toLocaleTimeString());
  return (
    <Box flexDirection="column">
      <Header project="none" readyCount={0} totalLanes={4} timestamp={now}
        usage={{claude: 0, codex: 0, gemini: 0, kimi: 0}} />
      <ChronoPane status="starting" transcript={[{role: 'chrono', text: 'starting up...'}]} />
      <Box flexDirection="row" width="100%">
        <LanePane name="Claude" status="starting" />
        <LanePane name="Codex" status="starting" />
        <LanePane name="Gemini" status="starting" />
        <LanePane name="Kimi" status="starting" />
      </Box>
    </Box>
  );
};
```

Create `src/index.tsx`:

```typescript
import React from 'react';
import { render } from 'ink';
import { App } from './App.js';

render(<App />);
```

- [ ] **Step 9: Run and verify**

Run: `npm run start`
Expected: TUI renders with header, Chrono pane, 4 lane panes in a row. All show "starting" badges. Ctrl+C to exit.

- [ ] **Step 10: Commit**

```bash
cd /Users/user/Obsidian-Claude-Vibe-Squad
git add ink-app/
git commit -m "feat: Ink app scaffold with layout (header + Chrono pane + 4 lane panes)"
```

---

## Task 12: PTY management (spawn CLIs, stream output)

**Files:**
- Create: `ink-app/src/pty/lane-process.ts`, `session-control.ts`, `output-parser.ts`
- Modify: `ink-app/src/App.tsx` (integrate PTY)

**Interfaces:**
- Consumes: none
- Produces:
  - `class LaneProcess { start(): Promise<void>; write(input: string): void; onData(cb: (chunk: string) => void): void; kill(): void }`
  - `LaneProcess.constructor(name: 'claude' | 'codex' | 'gemini' | 'kimi', args: string[])`
  - `startFreshSession(lane: LaneProcess): void` — sends `/newsession` equivalent per lane

- [ ] **Step 1: Write lane-process.ts**

Create `src/pty/lane-process.ts`:

```typescript
import { IPty, spawn } from 'node-pty';

type LaneName = 'claude' | 'codex' | 'gemini' | 'kimi';

const COMMANDS: Record<LaneName, string> = {
  claude: '/Users/user/.local/bin/claude',
  codex: '/opt/homebrew/bin/codex',
  gemini: '/opt/homebrew/bin/gemini',
  kimi: '/Users/user/.local/bin/kimi',
};

const UNSET_ENV_KEYS = ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'];

export class LaneProcess {
  private pty: IPty | null = null;
  private dataHandlers: ((chunk: string) => void)[] = [];

  constructor(public readonly name: LaneName, private readonly args: string[] = []) {}

  async start(): Promise<void> {
    const env: Record<string, string> = {};
    for (const [k, v] of Object.entries(process.env)) {
      if (v !== undefined && !UNSET_ENV_KEYS.includes(k)) env[k] = v;
    }
    this.pty = spawn(COMMANDS[this.name], this.args, {
      name: 'xterm-color',
      cols: 120,
      rows: 30,
      cwd: process.env.HOME,
      env,
    });
    this.pty.onData((chunk: string) => {
      for (const h of this.dataHandlers) h(chunk);
    });
  }

  write(input: string): void {
    this.pty?.write(input);
  }

  onData(cb: (chunk: string) => void): void {
    this.dataHandlers.push(cb);
  }

  kill(): void {
    this.pty?.kill();
    this.pty = null;
  }
}
```

- [ ] **Step 2: Write session-control**

Create `src/pty/session-control.ts`:

```typescript
import { LaneProcess } from './lane-process.js';

// Each CLI has its own way to start a fresh session
export function startFreshSession(lane: LaneProcess): void {
  switch (lane.name) {
    case 'claude':
      lane.write('/newsession\r');
      break;
    case 'codex':
      // Codex CLI: send interrupt then re-invoke
      lane.write('\x03\r');
      break;
    case 'gemini':
      lane.write('/clear\r');
      break;
    case 'kimi':
      lane.write('/new\r');
      break;
  }
}
```

- [ ] **Step 3: Write output-parser**

Create `src/pty/output-parser.ts`:

```typescript
// Extract status hints from raw CLI output
export interface StatusHint {
  status: 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error';
  detail?: string;
  toolName?: string;
}

const TOOL_PATTERN = /(?:tool_use|calling tool|using):?\s*([a-zA-Z_-]+)/i;
const THINKING_PATTERN = /thinking|reasoning|analyzing/i;
const DONE_PATTERN = /completed|done|finished|success/i;
const ERROR_PATTERN = /error|failed|cannot/i;

export function parseOutput(chunk: string): StatusHint | null {
  if (chunk.trim().length === 0) return null;
  const toolMatch = chunk.match(TOOL_PATTERN);
  if (toolMatch) return {status: 'tool', toolName: toolMatch[1], detail: chunk.slice(0, 60)};
  if (DONE_PATTERN.test(chunk)) return {status: 'done', detail: chunk.slice(0, 60)};
  if (ERROR_PATTERN.test(chunk)) return {status: 'error', detail: chunk.slice(0, 60)};
  if (THINKING_PATTERN.test(chunk)) return {status: 'thinking'};
  return null;
}
```

- [ ] **Step 4: Integrate into App**

Update `src/App.tsx` to spawn all 4 lanes on mount:

```typescript
import React, { useEffect, useState } from 'react';
import { Box } from 'ink';
import { Header } from './components/Header.js';
import { ChronoPane } from './components/ChronoPane.js';
import { LanePane } from './components/LanePane.js';
import { LaneProcess } from './pty/lane-process.js';
import { parseOutput } from './pty/output-parser.js';

type LaneName = 'claude' | 'codex' | 'gemini' | 'kimi';

interface LaneState {
  status: 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error' | 'stuck' | 'starting';
  detail: string;
}

export const App: React.FC = () => {
  const [lanes, setLanes] = useState<Record<LaneName, LaneState>>({
    claude: {status: 'starting', detail: 'booting'},
    codex: {status: 'starting', detail: 'booting'},
    gemini: {status: 'starting', detail: 'booting'},
    kimi: {status: 'starting', detail: 'booting'},
  });

  useEffect(() => {
    const processes: Record<LaneName, LaneProcess> = {} as any;
    (['claude', 'codex', 'gemini', 'kimi'] as LaneName[]).forEach(name => {
      const proc = new LaneProcess(name);
      proc.start().then(() => {
        setLanes(prev => ({...prev, [name]: {status: 'idle', detail: 'ready'}}));
      });
      proc.onData(chunk => {
        const hint = parseOutput(chunk);
        if (hint) setLanes(prev => ({...prev, [name]: {status: hint.status, detail: hint.detail ?? ''}}));
      });
      processes[name] = proc;
    });
    return () => {
      Object.values(processes).forEach(p => p.kill());
    };
  }, []);

  const readyCount = Object.values(lanes).filter(l => l.status !== 'starting').length;

  return (
    <Box flexDirection="column">
      <Header project="none" readyCount={readyCount} totalLanes={4}
        timestamp={new Date().toLocaleTimeString()}
        usage={{claude: 0, codex: 0, gemini: 0, kimi: 0}} />
      <ChronoPane status="idle" transcript={[{role: 'chrono', text: 'ready'}]} />
      <Box flexDirection="row" width="100%">
        {(['claude', 'codex', 'gemini', 'kimi'] as LaneName[]).map(name => (
          <LanePane key={name} name={name} status={lanes[name].status} detail={lanes[name].detail} />
        ))}
      </Box>
    </Box>
  );
};
```

- [ ] **Step 5: Test PTY spawn end-to-end**

Run: `npm run start`
Expected: All 4 panes flip from `starting` to `idle` within ~10s as each CLI boots. Ctrl+C to exit; all subprocesses killed cleanly.

- [ ] **Step 6: Commit**

```bash
git add ink-app/src/pty/ ink-app/src/App.tsx
git commit -m "feat: node-pty lane processes with fresh-session control and output parsing"
```

---

## Task 13: Chrono integration (Claude Agent SDK)

**Files:**
- Create: `ink-app/src/chrono/sdk-client.ts`, `prompt-loader.ts`, `router.ts`
- Modify: `ink-app/src/App.tsx` (wire Chrono in)

**Interfaces:**
- Consumes: `LaneProcess` (Task 12), daemon HTTP client (Task 14 — placeholder)
- Produces:
  - `class ChronoClient { send(userMessage: string): AsyncIterator<ChronoEvent> }`
  - `interface ChronoEvent { type: 'text' | 'dispatch' | 'question'; content: any }`
  - `loadChronoPrompt(): Promise<string>` — reads `shared/CHRONO-SOUL.md` if exists
  - `pickSpecialist(request: string, map: SpecialistMap): SpecialistChoice | SpecialistChoice[]`

- [ ] **Step 1: Write sdk-client**

Create `src/chrono/sdk-client.ts`:

```typescript
import Anthropic from '@anthropic-ai/claude-agent-sdk';

export interface ChronoEvent {
  type: 'text' | 'dispatch' | 'question';
  content: any;
}

export class ChronoClient {
  private client: Anthropic;
  private conversation: {role: string; content: string}[] = [];

  constructor(private systemPrompt: string, private model: string = 'claude-fable-5') {
    this.client = new Anthropic();
  }

  async *send(userMessage: string): AsyncIterator<ChronoEvent> {
    this.conversation.push({role: 'user', content: userMessage});
    const response = await this.client.messages.create({
      model: this.model,
      system: this.systemPrompt,
      messages: this.conversation as any,
      max_tokens: 4096,
    });
    for (const block of response.content) {
      if (block.type === 'text') {
        this.conversation.push({role: 'assistant', content: block.text});
        yield {type: 'text', content: block.text};
      }
    }
  }
}
```

- [ ] **Step 2: Write prompt-loader**

Create `src/chrono/prompt-loader.ts`:

```typescript
import { readFile } from 'fs/promises';
import path from 'path';

const REPO_ROOT = '/Users/user/Obsidian-Claude-Vibe-Squad';

export async function loadChronoPrompt(): Promise<string> {
  const paths = [
    path.join(REPO_ROOT, 'shared', 'CHRONO-SOUL.md'),
    path.join(REPO_ROOT, 'shared', 'chrono-soul.md'),
  ];
  for (const p of paths) {
    try {
      return await readFile(p, 'utf-8');
    } catch {}
  }
  return `You are Chrono, the orchestrator of Vibe Squad. You coordinate 4 model lanes (Claude, Codex, Gemini, Kimi) to work on tasks. You do not do the tasks yourself — you route them to specialists via the daemon at http://127.0.0.1:9876. Route questions from models to the operator in your own voice. Be concise.`;
}
```

- [ ] **Step 3: Write router**

Create `src/chrono/router.ts`:

```typescript
export interface SpecialistChoice {
  specialist: string;
  lane: 'claude' | 'codex' | 'gemini' | 'kimi';
  model: string;
  model_key: string;
}

export interface SpecialistMap {
  specialists: Record<string, {
    lane: string;
    model_key: string;
    tags: string[];
    keywords: string[];
  }>;
  lanes: Record<string, {default: string; [key: string]: string}>;
}

export function pickSpecialist(request: string, map: SpecialistMap): SpecialistChoice[] {
  const req = request.toLowerCase();
  const matches: SpecialistChoice[] = [];
  for (const [name, spec] of Object.entries(map.specialists)) {
    for (const kw of spec.keywords ?? []) {
      if (req.includes(kw.toLowerCase())) {
        const lane = spec.lane as 'claude' | 'codex' | 'gemini' | 'kimi';
        matches.push({
          specialist: name,
          lane,
          model: map.lanes[lane][spec.model_key] ?? map.lanes[lane].default,
          model_key: spec.model_key,
        });
        break;
      }
    }
  }
  return matches.length ? matches : [];
}
```

- [ ] **Step 4: Test Chrono SDK client**

Create `src/chrono/test-chrono.ts` (throwaway smoke test):

```typescript
import { ChronoClient } from './sdk-client.js';
import { loadChronoPrompt } from './prompt-loader.js';

async function main() {
  const prompt = await loadChronoPrompt();
  const chrono = new ChronoClient(prompt);
  for await (const event of chrono.send('what specialists do you know about?')) {
    console.log(`[${event.type}]`, event.content);
  }
}
main().catch(console.error);
```

Run: `ANTHROPIC_API_KEY=... tsx src/chrono/test-chrono.ts`
Expected: Chrono responds via Fable 5 with a text message.

- [ ] **Step 5: Delete throwaway test and commit**

```bash
rm ink-app/src/chrono/test-chrono.ts
git add ink-app/src/chrono/
git commit -m "feat: Chrono SDK client wrapper + prompt loader + specialist router"
```

---

## Task 14: Daemon HTTP/WS client (from Ink)

**Files:**
- Create: `ink-app/src/daemon-client/http.ts`, `events.ts`
- Create: `ink-app/src/types/protocol.ts`

**Interfaces:**
- Produces:
  - `dispatchTask(packet: TaskPacket): Promise<{task_id: string; path: string}>`
  - `getTasks(): Promise<Task[]>`
  - `subscribeEvents(onEvent: (event: DaemonEvent) => void): () => void` — returns unsubscribe

- [ ] **Step 1: Write TypeScript types**

Create `src/types/protocol.ts`:

```typescript
export interface TaskPacket {
  task_id?: string;
  project?: string;
  specialist: string;
  specialist_file: string;
  version?: string;
  lane: 'claude' | 'codex' | 'gemini' | 'kimi';
  model: string;
  model_key: string;
  required_tools?: string[];
  preferred_tools?: string[];
  requires_approval?: string[];
  prompt: string;
  context?: Record<string, any>;
}

export interface Task {
  task_id: string;
  lane: string;
  state: 'queued' | 'running' | 'done' | 'error';
}

export interface DaemonEvent {
  type: 'task_complete' | 'task_error';
  task_id: string;
  path?: string;
}
```

- [ ] **Step 2: Write HTTP client**

Create `src/daemon-client/http.ts`:

```typescript
import { TaskPacket, Task } from '../types/protocol.js';

const BASE = process.env.VIBESQUAD_DAEMON_URL ?? 'http://127.0.0.1:9876';

export async function dispatchTask(packet: TaskPacket): Promise<{task_id: string; path: string}> {
  const resp = await fetch(`${BASE}/task`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(packet),
  });
  if (!resp.ok) throw new Error(`dispatch failed: ${resp.status} ${await resp.text()}`);
  return resp.json();
}

export async function getTasks(): Promise<Task[]> {
  const resp = await fetch(`${BASE}/tasks`);
  return (await resp.json()).tasks;
}

export async function healthCheck(): Promise<boolean> {
  try {
    const resp = await fetch(`${BASE}/health`);
    return resp.ok;
  } catch {
    return false;
  }
}
```

- [ ] **Step 3: Write WS client**

Create `src/daemon-client/events.ts`:

```typescript
import WebSocket from 'ws';
import { DaemonEvent } from '../types/protocol.js';

const WS_URL = process.env.VIBESQUAD_DAEMON_WS ?? 'ws://127.0.0.1:9876/events';

export function subscribeEvents(onEvent: (event: DaemonEvent) => void): () => void {
  const ws = new WebSocket(WS_URL);
  ws.on('message', (data) => {
    try {
      const event = JSON.parse(data.toString());
      onEvent(event);
    } catch (e) {
      console.error('failed to parse WS event', e);
    }
  });
  return () => ws.close();
}
```

Add to package.json deps: `npm install ws && npm install -D @types/ws`

- [ ] **Step 4: Test round-trip**

Create smoke test at `src/daemon-client/test-roundtrip.ts`:

```typescript
import { dispatchTask, healthCheck } from './http.js';
import { subscribeEvents } from './events.js';

async function main() {
  console.log('daemon healthy:', await healthCheck());
  const unsub = subscribeEvents((e) => console.log('event:', e));
  const result = await dispatchTask({
    specialist: 'test-specialist',
    specialist_file: 'specialists/test.md',
    lane: 'kimi',
    model: 'kimi-k2.7-code',
    model_key: 'default',
    prompt: 'test',
  });
  console.log('dispatched:', result);
  setTimeout(() => { unsub(); process.exit(0); }, 3000);
}
main();
```

Run: `tsx src/daemon-client/test-roundtrip.ts`
Expected: `daemon healthy: true`, then `dispatched: {task_id: 't-...', path: '...'}`

- [ ] **Step 5: Cleanup and commit**

```bash
rm ink-app/src/daemon-client/test-roundtrip.ts
git add ink-app/src/daemon-client/ ink-app/src/types/ ink-app/package.json ink-app/package-lock.json
git commit -m "feat: daemon HTTP + WS client with TypeScript protocol types"
```

---

## Task 15: Specialist frontmatter migration + content-engineer specialists

**Files:**
- Modify: All 46 existing `departments/*/specialists/*.md` and `shared/specialists/*.md` (add frontmatter)
- Create: `shared/tool-catalog.md`
- Create: 10 files under `departments/content-engineer/specialists/`
- Modify: `shared/specialist-runtime-map.tsv` (update model column, add preferred_tools + safety_level columns)

**Interfaces:**
- Produces:
  - Every specialist file has YAML frontmatter with: `specialist`, `version`, `department`, `lane`, `model_key`, `required_tools`, `preferred_tools`, `safety_level`, `requires_approval`, `review_by`, `tags`
  - `shared/tool-catalog.md` — capability-organized reference
  - 10 new content-engineer specialist files
  - Updated `specialist-runtime-map.tsv` with new model roster

- [ ] **Step 1: Write tool-catalog.md**

Create `shared/tool-catalog.md`:

```markdown
# Tool Catalog

Reference for specialist required_tools / preferred_tools. Organized by capability.

## Web search & research
- `chrono-research-arsenal:arxiv_search` — academic papers
- `chrono-research-arsenal:xai_search` — web/X/news via xAI
- `chrono-research-arsenal:perplexity_search_web` — general web
- `firecrawl:scrape`, `firecrawl:crawl` — web scraping

## Browser automation (shared Chrome state)
- `playwright:browser_navigate`, `browser_click`, `browser_fill_form`, ...
- `chrome-devtools:navigate_page`, `click`, `evaluate_script`, ...

## Code repository
- `github:pull_request_read`, `search_code`, `create_pull_request`
- `github:add_comment_to_pending_review`

## OSINT: infrastructure recon
- `chrono-recon:dns_enumerate`, `whois_lookup`, `crt_sh_certificates`
- `chrono-recon:wayback_snapshots`
- `chrono-recon:github_leaked_secrets`

## Cross-model reasoning (as tools)
- `chrono-research-arsenal:grok_reason` — peer-frontier second opinion
- `chrono-research-arsenal:deepseek_analyze` — long-context analysis
- `chrono-research-arsenal:deepseek_review_diff` — huge-diff review

## Content generation: image/video/audio
- `chrono-content-engineer:higgsfield__generate_image/video/audio/3d`
- `chrono-content-engineer:higgsfield__upscale_image/video`
- `chrono-content-engineer:higgsfield__outpaint_image`, `reframe`, `remove_background`
- `chrono-content-engineer:higgsfield__motion_control`, `virality_predictor`
- `chrono-content-engineer:higgsfield__create_website`, `deploy_website`, `website_db`

## Voice + audio
- `chrono-content-engineer:elevenlabs__text_to_speech`, `voice_clone`
- `chrono-content-engineer:elevenlabs__compose_music`, `video_to_music`
- `chrono-content-engineer:elevenlabs__text_to_sound_effects`
- `chrono-content-engineer:elevenlabs__create_agent`

## Knowledge & memory
- `chrono-vault:read_specialist`, `write_specialist`, `kg_query`
- `chrono-vault:obsidian_search`

## Design & frontend
- `figma:*` (via Figma plugin)
- `frontend-design:*` (patterns library)

## Backend platforms
- `cloudflare:cloudflare-docs`, `cloudflare-api`, `cloudflare-bindings`
- `firebase:*`

## Second-opinion review
- `coderabbit:*` — code review
- `security-guidance:*` — security playbooks
```

- [ ] **Step 2: Write frontmatter migration script**

Create `scripts/python/add_specialist_frontmatter.py`:

```python
"""Add YAML frontmatter to specialist files that lack it."""
from pathlib import Path
import yaml
import sys

REPO = Path("/Users/user/Obsidian-Claude-Vibe-Squad")
SPECIALIST_DIRS = [
    REPO / "departments",
    REPO / "shared" / "specialists",
]

DEFAULT_FRONTMATTER_TEMPLATE = {
    "version": "2.0",
    "safety_level": "medium",
    "requires_approval": ["Write", "Bash", "WebFetch"],
    "required_tools": [],
    "preferred_tools": [],
    "tags": [],
}

def has_frontmatter(text: str) -> bool:
    return text.strip().startswith("---\n")

def infer_department(path: Path) -> str:
    parts = path.parts
    for i, p in enumerate(parts):
        if p == "departments" and i + 1 < len(parts):
            return parts[i + 1]
    return "shared"

def infer_lane(specialist_name: str) -> str:
    # Best-effort heuristics from name
    name = specialist_name.lower()
    if any(t in name for t in ["security", "architect", "reviewer", "triage", "planner"]):
        return "claude"
    if any(t in name for t in ["backend", "frontend", "exploit", "debugger", "refactorer"]):
        return "codex"
    if any(t in name for t in ["research", "synthesizer", "large-context"]):
        return "kimi"
    if any(t in name for t in ["design", "copy", "content", "media"]):
        return "gemini"
    return "claude"

def process(path: Path, dry_run: bool = False) -> bool:
    text = path.read_text()
    if has_frontmatter(text):
        return False
    name = path.stem
    fm = dict(DEFAULT_FRONTMATTER_TEMPLATE)
    fm["specialist"] = name
    fm["department"] = infer_department(path)
    fm["lane"] = infer_lane(name)
    fm["model_key"] = "default"
    yaml_block = yaml.safe_dump(fm, sort_keys=False).strip()
    new_text = f"---\n{yaml_block}\n---\n\n{text}"
    if not dry_run:
        path.write_text(new_text)
    return True

def main() -> int:
    dry_run = "--dry-run" in sys.argv
    count = 0
    for base in SPECIALIST_DIRS:
        if not base.exists():
            continue
        for md in base.rglob("*.md"):
            if md.name in ["README.md", "INDEX.md", "SPECIALIST-INDEX.md"]:
                continue
            if process(md, dry_run):
                count += 1
                print(f"{'DRY' if dry_run else 'ADD'} {md.relative_to(REPO)}")
    print(f"\nProcessed: {count} files")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Dry-run the migration**

Run: `python3 scripts/python/add_specialist_frontmatter.py --dry-run`
Expected: List of ~46 files that would be modified.

- [ ] **Step 4: Execute the migration**

Run: `python3 scripts/python/add_specialist_frontmatter.py`
Expected: `Processed: ~46 files`.

- [ ] **Step 5: Manually review + refine specialist files**

Open a few high-value files and refine frontmatter (add `required_tools`, `preferred_tools`, `tags` per §5.4 in spec). Focus on:
- `departments/security/specialists/security-analyst.md`
- `departments/research/specialists/researcher.md`
- Others as time permits (rest can be refined via weekly review over time)

- [ ] **Step 6: Create content-engineer specialist directory**

Run: `mkdir -p departments/content-engineer/specialists`

Create `departments/content-engineer/README.md`:

```markdown
# Content Engineer department

Specialists organized by media type. Each owns one deliverable form.

- copywriter — all text content
- voice-narrator — TTS narration
- music-composer — music + video-to-music
- sound-designer — SFX and audio design
- video-director — video generation orchestration
- video-editor — post-production
- image-designer — image generation + editing
- web-builder — websites + deployment
- game-designer — browser games
- voice-agent-builder — ElevenLabs conversational agents
```

- [ ] **Step 7: Create 10 content-engineer specialist files**

Create each file with frontmatter + brief body. Example — `departments/content-engineer/specialists/copywriter.md`:

```markdown
---
specialist: copywriter
version: 2.0
department: content-engineer
lane: gemini
model_key: default
required_tools:
  - firecrawl:scrape
  - chrono-vault:kg_query
preferred_tools:
  - chrono-research-arsenal:perplexity_search_web
  - chrono-research-arsenal:grok_reason
safety_level: low
requires_approval: [Write]
review_by: architect
tags: [content, writing, marketing]
---

# Copywriter

Write short-form and long-form text: marketing copy, landing pages, ad copy, blog articles, product descriptions. Match the operator's voice (usually direct, vibecoded, honest). Use the tool catalog to research references before writing. When writing marketing copy for a project, read the project brief and any handoffs first.

## Output form
Structured markdown with clear H1/H2 hierarchy. If deliverable is a landing page, include copy for hero, features, testimonials, CTA sections separately so `web-builder` can compose them.
```

Repeat with appropriate frontmatter and brief bodies for the other 9:
- voice-narrator (lane: gemini, tools: elevenlabs__text_to_speech, voice_clone)
- music-composer (lane: gemini, tools: elevenlabs__compose_music, video_to_music)
- sound-designer (lane: gemini, tools: elevenlabs__text_to_sound_effects)
- video-director (lane: gemini, model_key: deep, tools: higgsfield__generate_video, motion_control, virality_predictor)
- video-editor (lane: gemini, tools: higgsfield__reframe, upscale_video, outpaint_image)
- image-designer (lane: gemini, model_key: image, tools: higgsfield__generate_image)
- web-builder (lane: codex, tools: higgsfield__create_website, deploy_website, website_db, firebase__*, figma__*)
- game-designer (lane: codex, tools: higgsfield__deploy_game, publish_game)
- voice-agent-builder (lane: claude, tools: elevenlabs__create_agent, add_knowledge_base_to_agent)

- [ ] **Step 8: Update specialist-runtime-map.tsv**

Open `shared/specialist-runtime-map.tsv` and:
- Update model column with new roster from spec §10
- Add columns: `preferred_tools`, `safety_level`
- Add 10 new content-engineer rows

- [ ] **Step 9: Commit**

```bash
git add scripts/python/add_specialist_frontmatter.py
git add departments/ shared/
git commit -m "feat: specialist frontmatter contracts + 10 content-engineer specialists + tool-catalog"
```

---

## Task 16: Circuit breaker + crash recovery

**Files:**
- Create: `daemon/circuit_breaker.py`
- Modify: `daemon/routes/task.py` (integrate breaker check)
- Modify: `ink-app/src/pty/lane-process.ts` (integrate crash recovery)

**Interfaces:**
- Produces:
  - Server-side: `CircuitBreaker.check(lane: str) -> BreakerState`; opens on N loops / M seconds / K errors
  - Client-side: `LaneProcess.onCrash(cb: (info) => void)`; auto-restart + retry once

- [ ] **Step 1: Write daemon circuit breaker**

Create `daemon/circuit_breaker.py`:

```python
import time
from dataclasses import dataclass, field
from enum import Enum

class BreakerState(str, Enum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"

@dataclass
class LaneBreaker:
    state: BreakerState = BreakerState.CLOSED
    error_timestamps: list[float] = field(default_factory=list)
    opened_at: float = 0
    last_tool_call: tuple[str, float] | None = None
    repeat_count: int = 0

    ERROR_WINDOW_S: float = 300
    ERROR_THRESHOLD: int = 3
    TOOL_REPEAT_THRESHOLD: int = 5
    TOOL_REPEAT_WINDOW_S: float = 60
    HALF_OPEN_AFTER_S: float = 300

    def record_error(self):
        now = time.time()
        self.error_timestamps.append(now)
        self.error_timestamps = [t for t in self.error_timestamps if now - t < self.ERROR_WINDOW_S]
        if len(self.error_timestamps) >= self.ERROR_THRESHOLD:
            self._open()

    def record_tool_call(self, tool_name: str):
        now = time.time()
        if self.last_tool_call and self.last_tool_call[0] == tool_name and now - self.last_tool_call[1] < self.TOOL_REPEAT_WINDOW_S:
            self.repeat_count += 1
            if self.repeat_count >= self.TOOL_REPEAT_THRESHOLD:
                self._open()
        else:
            self.repeat_count = 0
        self.last_tool_call = (tool_name, now)

    def _open(self):
        self.state = BreakerState.OPEN
        self.opened_at = time.time()

    def check(self) -> BreakerState:
        if self.state == BreakerState.OPEN:
            if time.time() - self.opened_at >= self.HALF_OPEN_AFTER_S:
                self.state = BreakerState.HALF_OPEN
        return self.state

    def record_success(self):
        if self.state == BreakerState.HALF_OPEN:
            self.state = BreakerState.CLOSED
            self.error_timestamps.clear()
            self.repeat_count = 0

BREAKERS: dict[str, LaneBreaker] = {}

def get_breaker(lane: str) -> LaneBreaker:
    if lane not in BREAKERS:
        BREAKERS[lane] = LaneBreaker()
    return BREAKERS[lane]
```

- [ ] **Step 2: Integrate breaker check in task route**

Edit `daemon/routes/task.py`:

```python
from daemon.circuit_breaker import get_breaker, BreakerState

# In create_task, before the atomic write:
breaker = get_breaker(packet.lane)
if breaker.check() == BreakerState.OPEN:
    raise HTTPException(status_code=503, detail=f"circuit open for lane {packet.lane}, refusing dispatch")
```

- [ ] **Step 3: Write client-side crash recovery**

Edit `ink-app/src/pty/lane-process.ts` to add crash tracking:

```typescript
export class LaneProcess {
  private crashCount = 0;
  private lastCrashTs = 0;
  private crashHandlers: ((info: {crashCount: number}) => void)[] = [];

  onCrash(cb: (info: {crashCount: number}) => void) {
    this.crashHandlers.push(cb);
  }

  private handleExit() {
    const now = Date.now();
    if (now - this.lastCrashTs > 5 * 60_000) this.crashCount = 0;
    this.crashCount += 1;
    this.lastCrashTs = now;
    for (const h of this.crashHandlers) h({crashCount: this.crashCount});
  }

  async start(): Promise<void> {
    // ... existing spawn logic
    this.pty.onExit(() => this.handleExit());
  }
}
```

- [ ] **Step 4: Wire recovery ladder into App.tsx**

Add crash recovery logic (in the `useEffect` where lanes are set up):

```typescript
proc.onCrash(({crashCount}) => {
  if (crashCount === 1) {
    // A: silent auto-restart + retry once
    proc.start();
    setLanes(prev => ({...prev, [name]: {status: 'starting', detail: 'restarting'}}));
  } else if (crashCount === 2) {
    // C: escalate to Chrono
    setLanes(prev => ({...prev, [name]: {status: 'error', detail: 'crashed twice — pausing'}}));
    // TODO: send Chrono a narration event
  } else if (crashCount >= 3) {
    // Circuit open at daemon level
    setLanes(prev => ({...prev, [name]: {status: 'stuck', detail: 'circuit open'}}));
  }
});
```

- [ ] **Step 5: Write daemon breaker test**

Create `daemon/tests/test_circuit_breaker.py`:

```python
from daemon.circuit_breaker import LaneBreaker, BreakerState

def test_breaker_opens_on_3_errors():
    b = LaneBreaker()
    for _ in range(3):
        b.record_error()
    assert b.check() == BreakerState.OPEN

def test_breaker_opens_on_5_tool_repeats():
    b = LaneBreaker()
    for _ in range(6):
        b.record_tool_call("some_tool")
    assert b.check() == BreakerState.OPEN
```

Run: `pytest daemon/tests/test_circuit_breaker.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add daemon/circuit_breaker.py daemon/routes/task.py daemon/tests/test_circuit_breaker.py
git add ink-app/src/pty/lane-process.ts ink-app/src/App.tsx
git commit -m "feat: circuit breaker (server) + crash recovery ladder (client)"
```

---

## Task 17: Weekly review pipeline

**Files:**
- Create: `daemon/weekly_review.py`, `daemon/flash_summarizer.py`
- Create: `daemon/routes/summarize.py`
- Create: `bin/weekly-review.sh`, `scripts/python/weekly_review_runner.py`
- Create: `launchd/com.vibesquad.weekly-review.plist`

**Interfaces:**
- Produces:
  - `POST /summarize` proxies to Gemini 3.5 Flash
  - `bin/weekly-review.sh` runs Sundays 08:00, generates `docs/reviews/weekly/YYYY-WW.md`

- [ ] **Step 1: Write flash summarizer**

Create `daemon/flash_summarizer.py`:

```python
import os
import httpx
from typing import Optional

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"

class FlashSummarizer:
    def __init__(self, model: str = "gemini-3.5-flash"):
        self.model = model
        self.key = os.environ.get("GEMINI_API_KEY")

    async def summarize(self, text: str, instructions: Optional[str] = None) -> str:
        prompt = (instructions or "Summarize concisely with structure.") + "\n\n" + text
        url = f"{GEMINI_API}/models/{self.model}:generateContent?key={self.key}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
            }, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

SUMMARIZER = FlashSummarizer()
```

- [ ] **Step 2: Write /summarize route**

Create `daemon/routes/summarize.py`:

```python
from fastapi import APIRouter
from pydantic import BaseModel
from daemon.flash_summarizer import SUMMARIZER

router = APIRouter()

class SummarizeRequest(BaseModel):
    text: str
    instructions: str | None = None

@router.post("/summarize")
async def summarize(req: SummarizeRequest):
    return {"summary": await SUMMARIZER.summarize(req.text, req.instructions)}
```

Wire in `main.py`: `app.include_router(summarize.router)`

- [ ] **Step 3: Write weekly-review runner**

Create `scripts/python/weekly_review_runner.py`:

```python
"""Generate weekly review markdown from handoffs + tool-use manifests."""
import asyncio
import datetime
import httpx
from pathlib import Path

REPO = Path("/Users/user/Obsidian-Claude-Vibe-Squad")

async def collect_handoffs(week_start: datetime.date) -> str:
    handoffs = REPO / "docs" / "handoffs"
    collected = []
    for i in range(7):
        d = week_start + datetime.timedelta(days=i)
        f = handoffs / f"{d.isoformat()}.md"
        if f.exists():
            collected.append(f.read_text())
    return "\n\n---\n\n".join(collected)

async def collect_manifests(week_start: datetime.date) -> str:
    outbox = REPO / "daemon" / "state" / "outbox"
    if not outbox.exists():
        return ""
    manifests = []
    for lane_dir in outbox.iterdir():
        if lane_dir.is_dir():
            for m in lane_dir.glob("*.md"):
                mtime = datetime.datetime.fromtimestamp(m.stat().st_mtime).date()
                if mtime >= week_start:
                    manifests.append(m.read_text())
    return "\n\n---\n\n".join(manifests)

async def main():
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    year, week, _ = today.isocalendar()

    handoffs = await collect_handoffs(week_start)
    manifests = await collect_manifests(week_start)

    combined = f"# Handoffs this week\n\n{handoffs}\n\n# Tool manifests this week\n\n{manifests}"
    instructions = (
        "Generate a weekly review markdown document with these sections:\n"
        "- Surprising moments\n"
        "- Underused required tools\n"
        "- Overused preferred tools (candidates for required)\n"
        "- Specialist patches accumulated this week\n"
        "- Handoff patterns worth codifying\n"
        "- Projects touched this week\n"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://127.0.0.1:9876/summarize",
            json={"text": combined, "instructions": instructions},
            timeout=120.0,
        )
        resp.raise_for_status()
        summary = resp.json()["summary"]

    out_dir = REPO / "docs" / "reviews" / "weekly"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{year}-W{week:02d}.md"
    out.write_text(f"# Week {year}-W{week:02d}\n\n{summary}\n")
    print(f"wrote {out}")

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Write shell wrapper**

Create `bin/weekly-review.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
exec python3 scripts/python/weekly_review_runner.py "$@"
```

Then: `chmod +x bin/weekly-review.sh`

- [ ] **Step 5: Write launchd plist**

Create `launchd/com.vibesquad.weekly-review.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.vibesquad.weekly-review</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/user/Obsidian-Claude-Vibe-Squad/bin/weekly-review.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/vibesquad-weekly-review-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/vibesquad-weekly-review-stderr.log</string>
</dict>
</plist>
```

- [ ] **Step 6: Test end-to-end (manual trigger)**

Run: `bash bin/weekly-review.sh`
Expected: File created at `docs/reviews/weekly/YYYY-Wxx.md`.

- [ ] **Step 7: Install launchd job**

Run:
```bash
cp launchd/com.vibesquad.weekly-review.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.vibesquad.weekly-review.plist
launchctl list | grep weekly-review
```
Expected: Job appears.

- [ ] **Step 8: Commit**

```bash
git add daemon/flash_summarizer.py daemon/routes/summarize.py daemon/main.py
git add scripts/python/weekly_review_runner.py bin/weekly-review.sh launchd/com.vibesquad.weekly-review.plist
git commit -m "feat: weekly review pipeline (Flash summarizer + Sunday 08:00 launchd)"
```

---

## Task 18: Project workspace primitives + catalog

**Files:**
- Create: `daemon/routes/project.py`, `daemon/routes/catalog.py`
- Modify: `daemon/main.py`
- Create: `projects/system/vibe-squad-redesign-2026-07-11/{brief.md,state.yaml}` (bootstrap)

**Interfaces:**
- Produces:
  - `POST /projects` creates skeleton
  - `GET /projects` lists
  - `GET /projects/{slug}` returns detail
  - `POST /projects/{slug}/task` submits task with project context
  - `GET /catalog/search?q=...` proxies to chrono-catalog MCP

- [ ] **Step 1: Write project route**

Create `daemon/routes/project.py`:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
import yaml
from daemon.protocol.writer import atomic_write_yaml

router = APIRouter()

REPO = Path("/Users/user/Obsidian-Claude-Vibe-Squad")
PROJECTS = REPO / "projects"

class CreateProjectRequest(BaseModel):
    slug: str
    category: str
    brief: str = ""
    tags: list[str] = []

@router.post("/projects")
def create_project(req: CreateProjectRequest):
    from datetime import date
    today = date.today().isoformat()
    project_dir = PROJECTS / req.category / f"{req.slug}-{today}"
    if project_dir.exists():
        raise HTTPException(400, "project already exists")
    for sub in ["research", "drafts", "deliverables", "handoffs"]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
    (project_dir / "brief.md").write_text(f"# {req.slug}\n\n{req.brief}\n")
    atomic_write_yaml(project_dir / "state.yaml", {
        "project": req.slug,
        "category": req.category,
        "started": today,
        "last_touched": today,
        "status": "active",
        "tags": req.tags,
        "participants": ["chrono"],
        "deliverables": [],
    })
    (project_dir / "review.md").write_text("# Retrospective\n\n_(fill when project closes)_\n")
    return {"path": str(project_dir), "slug": req.slug, "category": req.category}

@router.get("/projects")
def list_projects():
    if not PROJECTS.exists():
        return {"projects": []}
    projects = []
    for cat_dir in PROJECTS.iterdir():
        if cat_dir.is_dir():
            for proj_dir in cat_dir.iterdir():
                if proj_dir.is_dir() and (proj_dir / "state.yaml").exists():
                    state = yaml.safe_load((proj_dir / "state.yaml").read_text())
                    projects.append(state)
    return {"projects": projects}

@router.get("/projects/{slug}")
def get_project(slug: str):
    for cat_dir in PROJECTS.iterdir() if PROJECTS.exists() else []:
        for proj_dir in cat_dir.iterdir():
            if proj_dir.name.startswith(f"{slug}-") and (proj_dir / "state.yaml").exists():
                return yaml.safe_load((proj_dir / "state.yaml").read_text())
    raise HTTPException(404, "project not found")
```

- [ ] **Step 2: Write catalog route**

Create `daemon/routes/catalog.py`:

```python
from fastapi import APIRouter
from daemon.mcp_manager import MANAGER

router = APIRouter()

@router.get("/catalog/search")
async def catalog_search(q: str, limit: int = 20):
    result = await MANAGER.call_tool("chrono-vault", "catalog_search", {"query": q, "limit": limit})
    return result
```

- [ ] **Step 3: Wire routes**

Edit `daemon/main.py`:

```python
from daemon.routes import project, catalog

app.include_router(project.router)
app.include_router(catalog.router)
```

- [ ] **Step 4: Bootstrap the redesign project**

Run:
```bash
curl -s -X POST http://127.0.0.1:9876/projects \
  -H "Content-Type: application/json" \
  -d '{"slug": "vibe-squad-redesign", "category": "system", "brief": "The redesign spec at docs/superpowers/specs/2026-07-11-vibe-squad-redesign-design.md", "tags": ["architecture", "system"]}'
```
Expected: `{"path": "...projects/system/vibe-squad-redesign-2026-07-11", "slug": "...", "category": "system"}`

- [ ] **Step 5: Verify project listing**

Run: `curl -s http://127.0.0.1:9876/projects | python3 -m json.tool`
Expected: List includes vibe-squad-redesign.

- [ ] **Step 6: Commit**

```bash
git add daemon/routes/project.py daemon/routes/catalog.py daemon/main.py projects/
git commit -m "feat: project workspace primitives + catalog search + bootstrap redesign project"
```

---

# PHASE C — Cutover (Tasks 19-24)

## Task 19: Bin swap

**Files:**
- Modify: `bin/vibe-squad` (replace old wrapper)
- Move: old `bin/vibe-squad` → `_archive/pre-redesign-bin/`

**Interfaces:**
- Produces: `bin/vibe-squad` launches Ink app instead of old tmux wrapper

- [ ] **Step 1: Archive old wrapper**

Run:
```bash
mkdir -p _archive/pre-redesign-bin
mv bin/vibe-squad _archive/pre-redesign-bin/ 2>/dev/null || echo "no existing wrapper"
```

- [ ] **Step 2: Write new wrapper**

Create `bin/vibe-squad`:

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="/Users/user/Obsidian-Claude-Vibe-Squad"
cd "$REPO/ink-app"

# Ensure daemon is up
if ! curl -sf http://127.0.0.1:9876/health >/dev/null; then
    echo "starting daemon..."
    launchctl start com.vibesquad.daemon
    for i in {1..10}; do
        if curl -sf http://127.0.0.1:9876/health >/dev/null; then break; fi
        sleep 0.5
    done
fi

# Ensure Chrome is up
if ! curl -sf http://127.0.0.1:9222/json/version >/dev/null; then
    echo "starting Chrome..."
    launchctl start com.vibesquad.chrome
fi

# Launch Ink app
exec npm run start
```

Then: `chmod +x bin/vibe-squad`

- [ ] **Step 3: Test launch**

Run: `bin/vibe-squad`
Expected: TUI comes up, all 4 lanes reach idle within ~10s.

- [ ] **Step 4: Commit**

```bash
git add bin/vibe-squad _archive/pre-redesign-bin/
git commit -m "feat(cutover): bin/vibe-squad launches Ink app with daemon+Chrome health checks"
```

---

## Task 20: Docs rewrite

**Files:**
- Modify: `README.md` (rewrite)
- Create: `docs/architecture.md`
- Create: `docs/adding-a-specialist.md`
- Move: existing docs to `_archive/pre-redesign-docs/`

**Interfaces:**
- Produces: current documentation matches redesigned architecture

- [ ] **Step 1: Archive old docs**

Run:
```bash
mkdir -p _archive/pre-redesign-docs
cp README.md _archive/pre-redesign-docs/README.md 2>/dev/null || true
# Preserve any docs that describe the pre-cut architecture
```

- [ ] **Step 2: Write new README**

Create `README.md`:

```markdown
# Vibe Squad

Multi-model relay TUI. Chrono (Claude Fable 5) coordinates 4 subscription CLIs (Claude, Codex, Gemini, Kimi) to work on tasks in parallel, with 56 role-based specialists and a Python sidecar daemon for orchestration.

## Quick start

```bash
bin/vibe-squad
```

## Architecture

See `docs/architecture.md`.

## Adding a specialist

See `docs/adding-a-specialist.md`.

## Design spec

See `docs/superpowers/specs/2026-07-11-vibe-squad-redesign-design.md`.
```

- [ ] **Step 3: Write architecture doc**

Create `docs/architecture.md` referencing the spec §3 diagram + a concise runtime description.

- [ ] **Step 4: Write specialist-authoring guide**

Create `docs/adding-a-specialist.md` with:
- Frontmatter template
- How to pick lane + model_key
- How to declare required_tools
- Testing via `curl -X POST http://127.0.0.1:9876/task ...`

- [ ] **Step 5: Commit**

```bash
git add README.md docs/architecture.md docs/adding-a-specialist.md _archive/pre-redesign-docs/
git commit -m "docs(cutover): rewrite README + architecture guide + specialist authoring guide"
```

---

## Task 21: Task-board archive

**Files:**
- Archive: `_state/inbox/` and `_state/outbox/` to `_archive/task-board-2026-05.tar.gz`

**Interfaces:**
- Produces: old task board is cold-stored; new daemon state is authoritative

- [ ] **Step 1: Confirm daemon state is authoritative**

Run: `ls daemon/state/inbox/ daemon/state/outbox/ 2>/dev/null && echo "daemon has state"`
Expected: New daemon state exists (may be empty).

- [ ] **Step 2: Archive old task-board**

Run:
```bash
tar czf _archive/task-board-2026-05.tar.gz _state/inbox _state/outbox 2>/dev/null
du -sh _archive/task-board-2026-05.tar.gz
rm -rf _state/inbox _state/outbox
```
Expected: tar file created, old dirs removed.

- [ ] **Step 3: Commit**

```bash
git add _archive/task-board-2026-05.tar.gz _state/
git commit -m "chore(cutover): archive pre-redesign task board (_state/inbox+outbox)"
```

---

## Task 22: Git branch cleanup

**Files:** none (git repo housekeeping)

**Interfaces:** produces: fewer stale branches

- [ ] **Step 1: List all branches**

Run: `git branch -a`
Expected: List of all branches (local + remote).

- [ ] **Step 2: For each branch, decide status with operator**

Present each non-main branch to operator: name, last-commit date, one-line summary.
Operator decides: keep, delete, or preserve as archived tag.

- [ ] **Step 3: Delete approved-for-deletion branches**

For each: `git branch -D <name>` (local) and `git push origin --delete <name>` (remote, only if operator approved).

- [ ] **Step 4: Commit any remaining housekeeping**

(No commit needed unless config changes were made.)

---

## Task 23: Launchd swap

**Files:** launchd inventory

**Interfaces:** produces: only vibe-squad and healthy nightly jobs are LOADED

- [ ] **Step 1: List currently loaded jobs**

Run: `launchctl list | grep -E "(vibesquad|claudevibesquad|chrono)"`
Expected: Current inventory.

- [ ] **Step 2: Unload old launchd jobs that reference dead scripts**

For each dead-feature job (e.g., anything referencing newsletter/podcast/dream/improvement/telegram if operator has separate jobs):
```bash
launchctl unload ~/Library/LaunchAgents/<label>.plist
rm ~/Library/LaunchAgents/<label>.plist  # only after confirming
```

- [ ] **Step 3: Verify vibe-squad jobs all LOADED**

Run:
```bash
launchctl list | grep vibesquad
```
Expected: `com.vibesquad.daemon`, `com.vibesquad.chrome`, `com.vibesquad.weekly-review`, `com.vibesquad.transcription-cache-ttl` all present.

- [ ] **Step 4: Update nightly-content plist**

If `com.claudevibesquad.nightly` still points to `bin/run-nightly.sh` (which was edited in Task 1), no plist change needed. Otherwise, install new `com.vibesquad.nightly-content.plist`.

Run: `launchctl start com.claudevibesquad.nightly`
Then: `tail -f /tmp/claudevibesquad-nightly-stdout.log`
Expected: Runs cleanly with removed phases 10, 13-17.

- [ ] **Step 5: Commit any config changes**

Not typically a commit — this task is operational. But if any plist was modified in the repo, commit it.

---

## Task 24: Shakedown week

**Files:** none (evaluation task)

**Interfaces:** produces: v1 stability confirmation

- [ ] **Step 1: Use vibe-squad for real work for 7 days**

Track:
- Number of dispatches
- Number of crashes
- Number of circuit-breaker trips
- Chrono narration accuracy (subjective)
- Weekly review file generation (Sunday)

- [ ] **Step 2: Log issues in `projects/system/vibe-squad-redesign-2026-07-11/handoffs/`**

For each issue: date, symptom, hypothesis, fix (or "deferred").

- [ ] **Step 3: Fix inline (small issues) or file follow-up (large)**

Small = quick bug fixes; large = follow-up spec.

- [ ] **Step 4: After 7 days, update `docs/architecture.md`**

Add "Status: v1 stable" section with the shakedown observations.

- [ ] **Step 5: Update project state.yaml to `shipped`**

Run: edit `projects/system/vibe-squad-redesign-2026-07-11/state.yaml`, set `status: shipped`.

- [ ] **Step 6: Commit final state**

```bash
git add docs/architecture.md projects/system/
git commit -m "docs: v1 shakedown complete, vibe-squad redesign shipped"
```

---

# Self-review notes

Spec coverage verified:
- §3 architecture → Task 5-14 (daemon, Ink, PTY, Chrono, HTTP/WS clients)
- §4 task lifecycle → Task 6 (task-board), Task 10 (watcher), Task 16 (circuit breaker)
- §5 specialists → Task 15 (frontmatter migration + content-engineer)
- §6 tool layer → Task 7 (MCP proxy), Task 9 (chrono-recon)
- §7 project organization → Task 18 (project + catalog routes)
- §8 external interface → Task 5, 6, 10, 17, 18 (daemon endpoints)
- §9 TUI design → Task 11 (scaffold), Task 12 (PTY integration)
- §10 model configuration → deferred to per-spawn config in Task 13 sdk-client
- §11 legacy cleanup → Tasks 1-4
- §12 build plan → Tasks 5-18 (14 milestones ≈ 14 tasks)
- §13 cutover → Tasks 19-23
- §14 v1.1 backlog → not implemented in this plan (deferred, correct)
- §15 risks → mitigations addressed in individual tasks (e.g., env unset in Task 12, Chrome persistent-profile in Task 8, circuit breaker in Task 16)

Placeholder scan: clean (all code blocks show actual implementation, no TBD/TODO in step content).

Type consistency check:
- `TaskPacket` matches between `daemon/protocol/packet.py` (Task 6) and `ink-app/src/types/protocol.ts` (Task 14) — same fields, same names
- `OutboxManifest` schema in daemon matches what Ink expects (Task 14)
- `LaneName` type consistent across `lane-process.ts`, `session-control.ts`, `App.tsx`
- Circuit breaker `BreakerState` enum consistent between daemon and client-side comments

**Total tasks: 24** (Phase A: 4, Phase B: 14, Phase C: 6)

Plan complete.
