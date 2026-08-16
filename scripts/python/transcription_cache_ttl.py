"""Report transcription-cache age observations without removing entries."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

from repo_root import resolve_vault_root

# VIBESQUAD_ROOT stays a legacy alias consulted only when VAULT_ROOT is unset;
# resolve_vault_root() owns VAULT_ROOT and the location-derived default.
_LEGACY_ROOT = os.environ.get("VIBESQUAD_ROOT")
REPO = (
    Path(_LEGACY_ROOT)
    if _LEGACY_ROOT and not os.environ.get("VAULT_ROOT")
    else resolve_vault_root()
)
CACHE_DIR = REPO / "_state" / "transcription-cache"
TTL_DAYS = int(os.environ.get("TTL_DAYS", "15"))


def audit_cache(
    *,
    cache_dir: Path | None = None,
    ttl_days: int = TTL_DAYS,
    now: float | None = None,
    sample_limit: int = 20,
) -> dict:
    """Count old-looking files and retain only a bounded diagnostic sample."""
    observed_cache_dir = CACHE_DIR if cache_dir is None else cache_dir
    observed_at = time.time() if now is None else now
    cutoff = observed_at - (ttl_days * 86400)
    effective_limit = min(20, max(0, sample_limit))
    candidate_count = 0
    samples: list[dict[str, object]] = []
    scan_errors: list[OSError] = []
    if observed_cache_dir.is_dir():
        for root, directories, files in os.walk(
            observed_cache_dir, onerror=scan_errors.append, followlinks=False
        ):
            directories.sort()
            for name in sorted(files):
                path = Path(root) / name
                try:
                    metadata = os.stat(path, follow_symlinks=False)
                except OSError as exc:
                    scan_errors.append(exc)
                    continue
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_mtime >= cutoff:
                    continue
                candidate_count += 1
                if len(samples) < effective_limit:
                    samples.append(
                        {
                            "path": str(path),
                            "observed_age_days": int(
                                (observed_at - metadata.st_mtime) // 86400
                            ),
                            "observed_bytes": metadata.st_size,
                            "storage_class": "unknown",
                            "effective_storage_class": "DURABLE",
                            "cleanup_eligible": False,
                        }
                    )
    return {
        "mode": "report-only",
        "cache_present": observed_cache_dir.is_dir(),
        "scan_complete": not scan_errors,
        "candidate_count": candidate_count,
        "candidates": samples,
        "sample_limit": effective_limit,
        "omitted_candidate_count": candidate_count - len(samples),
        "removed_count": 0,
        "bytes_freed": 0,
        "threshold_days": ttl_days,
        "age_basis": "mtime observation only; non-authoritative",
        "storage_class": "unknown",
        "effective_storage_class": "DURABLE",
        "cleanup_eligible": False,
    }


def main() -> int:
    report = audit_cache()
    if not report["cache_present"]:
        print(f"[ttl] report-only: cache dir absent: {CACHE_DIR}")
        return 0
    print(f"[ttl] age_basis={report['age_basis']}")
    print(f"[ttl] scan_complete={str(report['scan_complete']).lower()}")
    for candidate in report["candidates"]:
        print(
            f"[ttl] candidate path={candidate['path']!r}; "
            f"observed_age_days={candidate['observed_age_days']}; "
            "storage_class=unknown; effective_storage_class=DURABLE; "
            "cleanup_eligible=false"
        )
    print(
        "[ttl] report-only: "
        f"{report['candidate_count']} age-observed candidates; "
        f"showing at most {report['sample_limit']}; "
        "0 removed, 0 bytes freed; unknown storage class defaults DURABLE; "
        "cleanup_eligible=false"
    )
    return 0 if report["scan_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
