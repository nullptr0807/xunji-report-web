"""抓取训记数据，落盘到 data/raw + data/parsed。"""
from __future__ import annotations
import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .client import XunjiClient, RateLimited
from .parse import parse_response

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PARSED_DIR = ROOT / "data" / "parsed"


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def fetch_one(client: XunjiClient, datestr: str, force: bool = False) -> dict:
    raw_path = RAW_DIR / f"{datestr}.json"
    if raw_path.exists() and not force:
        print(f"  [cached] {datestr}")
        return json.loads(raw_path.read_text())

    print(f"  [fetch]  {datestr}")
    data = client.fetch_with_retry(datestr)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    parsed = parse_response(data)
    (PARSED_DIR / f"{datestr}.json").write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2)
    )
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="single date YYYY-MM-DD")
    ap.add_argument("--start", help="range start YYYY-MM-DD")
    ap.add_argument("--end", help="range end YYYY-MM-DD (inclusive)")
    ap.add_argument("--force", action="store_true", help="re-fetch cached days")
    ap.add_argument("--sleep", type=int, default=92,
                    help="sleep seconds between days (rate limit is 90s)")
    args = ap.parse_args()

    client = XunjiClient()

    if args.date:
        fetch_one(client, args.date, force=args.force)
        return

    if not (args.start and args.end):
        ap.error("provide --date OR --start/--end")

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    days = list(daterange(start, end))
    print(f"Fetching {len(days)} days from {start} to {end}")

    for i, d in enumerate(days):
        ds = d.isoformat()
        raw_path = RAW_DIR / f"{ds}.json"
        cached = raw_path.exists() and not args.force
        fetch_one(client, ds, force=args.force)
        if i < len(days) - 1 and not cached:
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
