"""FastAPI app for xunji-report-web.

Mounted at /xunji/ via nginx reverse proxy.
"""
from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field

from app import storage
from app.pipeline import run_pipeline, JobCancelled

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
JOBS_DIR = ROOT / "data" / "jobs"

app = FastAPI(title="xunji-report-web", root_path="/xunji")
_executor = ThreadPoolExecutor(max_workers=2)


class GenerateReq(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=200)
    start: str
    end: str


@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB_DIR / "index.html").read_text()


@app.post("/api/generate")
def generate(req: GenerateReq):
    for s in (req.start, req.end):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            raise HTTPException(400, f"Invalid date: {s}")
    try:
        d_start = date.fromisoformat(req.start)
        d_end = date.fromisoformat(req.end)
    except ValueError:
        raise HTTPException(400, "Invalid date format")
    if d_end < d_start:
        raise HTTPException(400, "end < start")
    if (d_end - d_start).days > 365 * 6:
        raise HTTPException(400, "range too large (>6 years)")

    # Per-key daily quota (3 reports / 24h)
    allowed, used, limit = storage.check_quota(req.api_key)
    if not allowed:
        raise HTTPException(
            429,
            f"超过每日配额：同一 API Key 24 小时内最多 {limit} 次报告生成，"
            f"今日已使用 {used} 次。请明天再来。",
        )

    # Pre-create job so we can return job_id instantly, run pipeline in thread
    job_id, _ = storage.create_job(req.api_key, req.start, req.end)
    _executor.submit(_safe_run, req.api_key, req.start, req.end, job_id)
    return {"job_id": job_id, "quota_used": used + 1, "quota_limit": limit}


def _safe_run(api_key: str, start: str, end: str, job_id: str):
    try:
        run_pipeline(api_key, start, end, job_id=job_id)
    except JobCancelled:
        # User-cancelled: mark as cancelled + refund quota
        from datetime import datetime
        storage.update_job(
            job_id,
            status="cancelled",
            quota_refunded=1,
            finished_at=datetime.utcnow().isoformat(),
        )
    except Exception as e:
        import traceback
        storage.update_job(job_id, status="failed", error=str(e)[:500])
        traceback.print_exc()


@app.post("/api/job/{job_id}/cancel")
def cancel_job(job_id: str):
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    status = job.get("status") or ""
    if status == "done":
        raise HTTPException(409, "report already finished — cannot cancel")
    if status.startswith("cancelled") or job.get("cancel_requested"):
        return {"ok": True, "already": True}
    # Set flag; pipeline thread detects it at the next checkpoint and exits
    # cleanly. _safe_run will mark status='cancelled' + quota_refunded=1.
    storage.update_job(job_id, cancel_requested=1)
    return {"ok": True, "quota_refunded": True}


@app.get("/api/job/{job_id}")
def job_status(job_id: str):
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    job_dir = JOBS_DIR / job_id
    return {**job, "report_ready": (job_dir / "report.html").exists()}


@app.get("/report/{job_id}/", response_class=HTMLResponse)
@app.get("/report/{job_id}", response_class=HTMLResponse)
def report_index(job_id: str):
    f = JOBS_DIR / job_id / "report.html"
    if not f.exists():
        raise HTTPException(404, "report not ready")
    return f.read_text()


@app.get("/report/{job_id}/{filename}")
def report_asset(job_id: str, filename: str):
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")

    # On-demand snapshot generation
    if filename == "snapshot.jpg":
        snap = JOBS_DIR / job_id / "snapshot.jpg"
        if not snap.exists():
            try:
                from app.snapshot import snapshot_report
                # Render via localhost (avoid TLS overhead)
                report_url = f"http://127.0.0.1:8610/report/{job_id}/"
                snapshot_report(report_url, snap)
            except Exception as e:
                raise HTTPException(500, f"snapshot failed: {e}")
        return FileResponse(snap, media_type="image/jpeg",
                            headers={"Content-Disposition": f'attachment; filename="xunji-report-{job_id}.jpg"'})

    f = JOBS_DIR / job_id / filename
    if not f.exists() or not f.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(f)


@app.get("/health")
def health():
    return {"ok": True}
