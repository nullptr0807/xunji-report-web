"""Pipeline: api_key + date range → job dir with parsed data + report."""
from __future__ import annotations
import json
import time
from datetime import datetime, timedelta, date
from pathlib import Path

from core.client import XunjiClient
from core.parse import parse_response
from core.analyze import analyze
from app import storage


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def run_pipeline(api_key: str, start: str, end: str, gap: float = 1.3,
                 job_id: str | None = None) -> dict:
    """Full pipeline. If job_id provided, reuses that job; else creates one."""
    if job_id is None:
        job_id, job_dir = storage.create_job(api_key, start, end)
    else:
        job_dir = storage.JOBS_DIR / job_id
        (job_dir / "raw").mkdir(parents=True, exist_ok=True)
        (job_dir / "parsed").mkdir(parents=True, exist_ok=True)
    raw_dir = job_dir / "raw"
    parsed_dir = job_dir / "parsed"

    storage.update_job(job_id, status="fetching")
    client = XunjiClient(api_key=api_key)

    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()
    days = list(_daterange(start_d, end_d))

    # Per-user cache: data/cache/<key_hash>/<YYYY-MM-DD>.json
    kh = storage.key_hash(api_key)
    cache_dir = storage.DATA_DIR / "cache" / kh
    cache_dir.mkdir(parents=True, exist_ok=True)

    # ===== Pre-scan: how many days are already cached =====
    pre_cached = [d for d in days if (cache_dir / f"{d.isoformat()}.json").exists()]
    to_fetch = [d for d in days if not (cache_dir / f"{d.isoformat()}.json").exists()]
    storage.update_job(
        job_id,
        status=f"planning total={len(days)} cached={len(pre_cached)} todo={len(to_fetch)}",
    )

    n_fetched = n_cached = n_with_data = 0
    errors = []
    total = len(days)
    for i, day in enumerate(days):
        ds = day.isoformat()
        cache_path = cache_dir / f"{ds}.json"
        from_cache = False
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text())
                from_cache = True
                n_cached += 1
            except Exception:
                from_cache = False
        if not from_cache:
            try:
                data = client.fetch_with_retry(ds, max_retries=8)
            except Exception as e:
                errors.append({"date": ds, "error": str(e)})
                time.sleep(gap)
                storage.update_job(
                    job_id,
                    status=f"fetching {i+1}/{total} cache:{n_cached} new:{n_fetched} todo={len(to_fetch)}",
                )
                continue
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            n_fetched += 1
            time.sleep(gap)

        # mirror into job dir + parse
        (raw_dir / f"{ds}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
        parsed = parse_response(data)
        (parsed_dir / f"{ds}.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
        if data.get("res"):
            n_with_data += 1
        storage.update_job(
            job_id,
            status=f"fetching {i+1}/{total} cache:{n_cached} new:{n_fetched} todo={len(to_fetch)}",
        )

    storage.update_job(job_id, status="analyzing")
    try:
        summary = analyze(parsed_dir, job_dir)
    except Exception as e:
        storage.update_job(job_id, status="failed", error=f"analyze: {e}",
                           finished_at=datetime.utcnow().isoformat())
        raise

    # Optional LLM commentary (best-effort, never fails the pipeline)
    storage.update_job(job_id, status="commenting")
    try:
        from app.commentary import generate_commentary
        report_data = json.loads((job_dir / "report_data.json").read_text())
        c = generate_commentary(report_data, job_dir / "llm_commentary.json", timeout=120)
        if not c:
            (job_dir / "commentary_skipped.log").write_text("LLM returned no parseable JSON")
    except Exception as e:
        import traceback
        (job_dir / "commentary_skipped.log").write_text(
            f"commentary failed: {e}\n\n{traceback.format_exc()}"
        )

    _render_html(job_dir, summary)

    storage.update_job(job_id, status="done", finished_at=datetime.utcnow().isoformat())
    return {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "days_fetched": n_fetched,
        "days_cached": n_cached,
        "days_with_data": n_with_data,
        "errors": errors,
        "summary": summary,
    }


def _render_html(job_dir: Path, summary: dict):
    """Copy the report template into job dir. JS will fetch report_data.json."""
    template = Path(__file__).resolve().parent.parent / "web" / "report_template.html"
    (job_dir / "report.html").write_text(template.read_text())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--gap", type=float, default=1.3)
    args = ap.parse_args()
    result = run_pipeline(args.key, args.start, args.end, args.gap)
    print(json.dumps({k: v for k, v in result.items() if k != "summary"}, ensure_ascii=False, indent=2))
    print(f"\n→ Report: {result['job_dir']}/report.html")
