"""Delete cache/raw files and job dirs older than 7 days."""
from __future__ import annotations
import os
import shutil
import time
from pathlib import Path

from app import storage

RETENTION_DAYS = 7


def cleanup(verbose: bool = False) -> dict:
    cutoff = time.time() - RETENTION_DAYS * 86400
    stats = {"cache_files_removed": 0, "job_dirs_removed": 0}

    # Per-user cache
    cache_root = storage.DATA_DIR / "cache"
    if cache_root.exists():
        for user_dir in cache_root.iterdir():
            if not user_dir.is_dir():
                continue
            for f in user_dir.iterdir():
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    stats["cache_files_removed"] += 1
            # remove empty user cache dir
            try:
                if not any(user_dir.iterdir()):
                    user_dir.rmdir()
            except Exception:
                pass

    # Job dirs (entire job: raw + parsed + report + snapshot)
    if storage.JOBS_DIR.exists():
        for d in storage.JOBS_DIR.iterdir():
            if not d.is_dir():
                continue
            try:
                age = time.time() - d.stat().st_mtime
                if age > RETENTION_DAYS * 86400:
                    shutil.rmtree(d)
                    stats["job_dirs_removed"] += 1
            except Exception:
                pass

    if verbose:
        print(stats)
    return stats


if __name__ == "__main__":
    cleanup(verbose=True)
