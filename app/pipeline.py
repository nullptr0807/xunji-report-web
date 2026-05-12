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


class JobCancelled(Exception):
    """Raised when the user cancels a running job."""


def _check_cancelled(job_id: str):
    j = storage.get_job(job_id)
    if j and j.get("cancel_requested"):
        raise JobCancelled()


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
        _check_cancelled(job_id)
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

    _check_cancelled(job_id)
    storage.update_job(job_id, status="analyzing")
    try:
        summary = analyze(parsed_dir, job_dir)
    except Exception as e:
        storage.update_job(job_id, status="failed", error=f"analyze: {e}",
                           finished_at=datetime.utcnow().isoformat())
        raise

    # Optional LLM commentary (best-effort, never fails the pipeline)
    storage.update_job(job_id, status="commenting")
    report_data = json.loads((job_dir / "report_data.json").read_text())
    summary_ = report_data.get("summary") or {}
    # Use time-based ratio (set-based wildly biases toward strength because
    # a 60-min run contributes 0 sets while 4 sets of bench press = 4 sets).
    strength_time_ratio = summary_.get("strength_time_ratio")
    if strength_time_ratio is None:
        strength_time_ratio = summary_.get("strength_ratio", 1.0)
    # Threshold: if <60% of training TIME is on weighted strength work,
    # the strength template will be a poor fit — hand off to dynamic LLM.
    use_dynamic = strength_time_ratio < 0.60

    if use_dynamic:
        try:
            from app.commentary_dynamic import generate_dynamic_commentary
            # Load parsed records (raw-ish data the LLM gets to see)
            records = []
            for p in sorted(parsed_dir.glob("*.json")):
                try:
                    records.extend(json.loads(p.read_text()))
                except Exception:
                    pass
            c = generate_dynamic_commentary(
                report_data, records, job_dir / "dynamic_sections.json", timeout=180,
            )
            if not c:
                # Dynamic failed — fall back to strength template anyway
                use_dynamic = False
                (job_dir / "dynamic_skipped.log").write_text(
                    "LLM returned no parseable JSON, falling back to strength template"
                )
        except Exception as e:
            import traceback
            use_dynamic = False
            (job_dir / "dynamic_skipped.log").write_text(
                f"dynamic commentary failed: {e}\n\n{traceback.format_exc()}"
            )

    if not use_dynamic:
        try:
            from app.commentary import generate_commentary
            c = generate_commentary(report_data, job_dir / "llm_commentary.json", timeout=120)
            if not c:
                (job_dir / "commentary_skipped.log").write_text("LLM returned no parseable JSON")
        except Exception as e:
            import traceback
            (job_dir / "commentary_skipped.log").write_text(
                f"commentary failed: {e}\n\n{traceback.format_exc()}"
            )

    _render_html(job_dir, summary, use_dynamic=use_dynamic)

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


def _render_html(job_dir: Path, summary: dict, use_dynamic: bool = False):
    """Copy the appropriate report template into job dir."""
    tmpl_name = "report_template_dynamic.html" if use_dynamic else "report_template.html"
    template = Path(__file__).resolve().parent.parent / "web" / tmpl_name
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
