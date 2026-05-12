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
        created_at TEXT NOT NULL,
        finished_at TEXT,
        error TEXT,
        FOREIGN KEY(key_hash) REFERENCES users(key_hash)
    );
    """)
    conn.commit()
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


def count_jobs_today(key_hash_value: str) -> int:
    """Count jobs created in the last 24h for this key."""
    from datetime import timedelta
    init_db()
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE key_hash=? AND created_at>=?",
        (key_hash_value, cutoff),
    )
    n = cur.fetchone()[0]
    conn.close()
    return n


def check_quota(api_key: str) -> tuple[bool, int, int]:
    """Return (allowed, used_today, limit)."""
    kh = key_hash(api_key)
    used = count_jobs_today(kh)
    return used < DAILY_LIMIT_PER_KEY, used, DAILY_LIMIT_PER_KEY
