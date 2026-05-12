"""Bulk fetch all dates in a range, fast (per-date rate limit + retry).

Uses fetch_with_retry so 30s global throttles are absorbed automatically.
Sleeps 1.5s between dates by default (different dates aren't blocked).
"""
from __future__ import annotations
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .client import XunjiClient
from .parse import parse_response

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PARSED_DIR = ROOT / "data" / "parsed"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--gap", type=float, default=1.5,
                    help="seconds between requests (default 1.5)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)

    client = XunjiClient()
    total = len(days)
    n_fetched = n_cached = n_with_data = 0
    t0 = time.time()
    for i, day in enumerate(days):
        ds = day.isoformat()
        raw_path = RAW_DIR / f"{ds}.json"
        if raw_path.exists() and not args.force:
            n_cached += 1
            data = json.loads(raw_path.read_text())
        else:
            try:
                data = client.fetch_with_retry(ds, max_retries=8)
            except Exception as e:
                print(f"[{i+1}/{total}] {ds} ERR: {e}", flush=True)
                time.sleep(args.gap)
                continue
            raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            parsed = parse_response(data)
            (PARSED_DIR / f"{ds}.json").write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2)
            )
            n_fetched += 1
            time.sleep(args.gap)

        n = len(data.get("res", []) or [])
        if n:
            n_with_data += 1
        if (i + 1) % 30 == 0 or i == total - 1:
            elapsed = time.time() - t0
            print(f"[{i+1}/{total}] {ds}  fetched={n_fetched} cached={n_cached} "
                  f"non-empty={n_with_data}  elapsed={elapsed:.0f}s", flush=True)

    print(f"DONE: total={total} fetched={n_fetched} cached={n_cached} "
          f"non-empty={n_with_data}")


if __name__ == "__main__":
    main()
