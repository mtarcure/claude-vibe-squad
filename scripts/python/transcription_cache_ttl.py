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
