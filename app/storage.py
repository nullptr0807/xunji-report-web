"""Storage: KEYs (Fernet-encrypted SQLite) + job filesystem layout.

- data/keys.db   SQLite: users + jobs tables
- data/jobs/<job_id>/{raw/, parsed/, report.html, report.md, *.png, *.csv, meta.json}
"""
from __future__ import annotations
import os
import json
import hashlib
import sqlite3
import secrets
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
JOBS_DIR = DATA_DIR / "jobs"
DB_PATH = DATA_DIR / "keys.db"

DATA_DIR.mkdir(exist_ok=True)
JOBS_DIR.mkdir(exist_ok=True)
try:
    os.chmod(DATA_DIR, 0o700)
except Exception:
    pass


def _get_master_key() -> bytes:
    k = os.environ.get("MASTER_KEY")
    if not k:
        raise RuntimeError(
            "MASTER_KEY not set. Generate with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return k.encode()


def _fernet() -> Fernet:
    return Fernet(_get_master_key())


def key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        key_hash TEXT PRIMARY KEY,
        key_encrypted BLOB NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        job_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        key_hash TEXT NOT NULL,
        date_start TEXT,
        date_end TEXT,
        status TEXT NOT NULL,
        error TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT,
        quota_refunded INTEGER DEFAULT 0,
        cancel_requested INTEGER DEFAULT 0,
        days_in_range INTEGER,
        strength_minutes REAL,
        cardio_minutes REAL,
        prompt_chars INTEGER,
        response_chars INTEGER,
        duration_seconds REAL,
        FOREIGN KEY(key_hash) REFERENCES users(key_hash)
    );
    CREATE TABLE IF NOT EXISTS visitors (
        ip_hash TEXT PRIMARY KEY,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        hit_count INTEGER NOT NULL DEFAULT 1
    );
    """)
    conn.commit()
    # Migration: add columns if missing on old DBs
    for col in (
        "quota_refunded INTEGER DEFAULT 0",
        "cancel_requested INTEGER DEFAULT 0",
        "days_in_range INTEGER",
        "strength_minutes REAL",
        "cardio_minutes REAL",
        "prompt_chars INTEGER",
        "response_chars INTEGER",
        "duration_seconds REAL",
    ):
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.close()
    try:
        os.chmod(DB_PATH, 0o600)
    except Exception:
        pass


def upsert_user(api_key: str) -> str:
    """Encrypt+store key. Returns key_hash."""
    init_db()
    kh = key_hash(api_key)
    enc = _fernet().encrypt(api_key.encode())
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT key_hash FROM users WHERE key_hash=?", (kh,))
    if cur.fetchone():
        cur.execute("UPDATE users SET last_seen=?, job_count=job_count+1 WHERE key_hash=?", (now, kh))
    else:
        cur.execute(
            "INSERT INTO users(key_hash,key_encrypted,first_seen,last_seen,job_count) VALUES(?,?,?,?,1)",
            (kh, enc, now, now),
        )
    conn.commit()
    conn.close()
    return kh


def get_key_by_hash(kh: str) -> str | None:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT key_encrypted FROM users WHERE key_hash=?", (kh,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return _fernet().decrypt(row[0]).decode()


def create_job(api_key: str, date_start: str | None, date_end: str | None) -> tuple[str, Path]:
    """Create job, register in DB, return (job_id, job_dir)."""
    kh = upsert_user(api_key)
    job_id = secrets.token_urlsafe(16)
    job_dir = JOBS_DIR / job_id
    (job_dir / "raw").mkdir(parents=True)
    (job_dir / "parsed").mkdir(parents=True)
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO jobs(job_id,key_hash,date_start,date_end,status,created_at) VALUES(?,?,?,?,?,?)",
        (job_id, kh, date_start, date_end, "pending", now),
    )
    conn.commit()
    conn.close()
    meta = {
        "job_id": job_id,
        "key_hash": kh,
        "date_start": date_start,
        "date_end": date_end,
        "created_at": now,
        "status": "pending",
    }
    (job_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return job_id, job_dir


def update_job(job_id: str, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [job_id]
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"UPDATE jobs SET {sets} WHERE job_id=?", vals)
    conn.commit()
    conn.close()
    # mirror status into meta.json
    job_dir = JOBS_DIR / job_id
    meta_path = job_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            meta.update(fields)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        except Exception:
            pass


def get_job(job_id: str) -> dict | None:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ===== Rate limiting =====
DAILY_LIMIT_PER_KEY = 3

# Whitelist: key_hash values that bypass the daily quota.
# Configure via env WHITELIST_KEY_HASHES="hash1,hash2" (comma-separated key_hash() values).
# Use scripts/whitelist_hash.py to compute a hash from a raw API key.
_WHITELIST = {
    h.strip() for h in os.environ.get("WHITELIST_KEY_HASHES", "").split(",") if h.strip()
}


def count_jobs_today(key_hash_value: str) -> int:
    """Count jobs created in the last 24h for this key."""
    from datetime import timedelta
    init_db()
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE key_hash=? AND created_at>=? AND COALESCE(quota_refunded,0)=0",
        (key_hash_value, cutoff),
    )
    n = cur.fetchone()[0]
    conn.close()
    return n


def check_quota(api_key: str) -> tuple[bool, int, int]:
    """Return (allowed, used_today, limit). Whitelisted keys always allowed."""
    kh = key_hash(api_key)
    if kh in _WHITELIST:
        return True, 0, -1  # -1 sentinel = unlimited
    used = count_jobs_today(kh)
    return used < DAILY_LIMIT_PER_KEY, used, DAILY_LIMIT_PER_KEY



# ===== Visitor tracking & global stats =====
def _ip_hash(ip: str) -> str:
    return hashlib.sha256((ip or "unknown").encode()).hexdigest()[:16]


def track_visitor(ip: str):
    """Record a unique visitor (hashed IP). Counts hits on existing rows."""
    init_db()
    ih = _ip_hash(ip)
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO visitors(ip_hash,first_seen,last_seen,hit_count) VALUES(?,?,?,1)",
            (ih, now, now),
        )
    except sqlite3.IntegrityError:
        conn.execute(
            "UPDATE visitors SET last_seen=?, hit_count=hit_count+1 WHERE ip_hash=?",
            (now, ih),
        )
    conn.commit()
    conn.close()


def get_global_stats() -> dict:
    """Aggregate stats for the public footer."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    n_visitors = c.execute("SELECT COUNT(*) FROM visitors").fetchone()[0]
    n_keys = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    n_reports_done = c.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]

    avg_days = c.execute(
        "SELECT AVG(days_in_range) FROM jobs WHERE status='done' AND days_in_range IS NOT NULL"
    ).fetchone()[0]

    # Per-key avg jobs (engagement proxy — not training freq, which would need
    # per-job session counts we don't store separately).
    avg_jobs_per_key = (n_reports_done / n_keys) if n_keys else 0

    sm = c.execute(
        "SELECT COALESCE(SUM(strength_minutes),0), COALESCE(SUM(cardio_minutes),0) FROM jobs WHERE status='done'"
    ).fetchone()
    strength_total, cardio_total = sm
    total_min = (strength_total or 0) + (cardio_total or 0)
    aerobic_ratio = (cardio_total / total_min) if total_min else None

    pc = c.execute(
        "SELECT COALESCE(SUM(prompt_chars),0), COALESCE(SUM(response_chars),0), "
        "COUNT(*) FILTER (WHERE prompt_chars IS NOT NULL) FROM jobs WHERE status='done'"
    ).fetchone()
    prompt_chars_total, response_chars_total, n_with_tokens = pc
    total_chars = (prompt_chars_total or 0) + (response_chars_total or 0)
    # Token estimate: CJK-heavy text ~ chars/1.8. Use /2 conservatively.
    est_tokens_total = int(total_chars / 2) if total_chars else 0
    est_tokens_per_report = int(est_tokens_total / n_with_tokens) if n_with_tokens else 0

    avg_duration_s = c.execute(
        "SELECT AVG(duration_seconds) FROM jobs WHERE status='done' AND duration_seconds IS NOT NULL"
    ).fetchone()[0]

    conn.close()

    return {
        "visitors": n_visitors,
        "unique_keys": n_keys,
        "reports_generated": n_reports_done,
        "avg_days_per_report": round(avg_days, 1) if avg_days else 0,
        "avg_jobs_per_key": round(avg_jobs_per_key, 2),
        "aerobic_ratio": round(aerobic_ratio, 3) if aerobic_ratio is not None else None,
        "anaerobic_ratio": round(1 - aerobic_ratio, 3) if aerobic_ratio is not None else None,
        "est_tokens_total": est_tokens_total,
        "est_tokens_per_report": est_tokens_per_report,
        "avg_duration_seconds": round(avg_duration_s, 1) if avg_duration_s else 0,
    }
