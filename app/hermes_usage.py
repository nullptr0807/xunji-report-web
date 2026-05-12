"""Attribute real token usage from a `hermes -z` subprocess call.

Hermes writes per-session token accounting into ~/.hermes/state.db
(sessions table: input_tokens, output_tokens, cache_read_tokens,
reasoning_tokens, estimated_cost_usd). We embed a UUID sentinel in the
prompt, then after the subprocess returns we look up the unique CLI
session whose first user message contains that sentinel and read its
usage columns. This is robust against concurrent jobs because the
sentinel uniquely identifies the session we created.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

STATE_DB = Path(os.path.expanduser("~/.hermes/state.db"))


def make_sentinel() -> str:
    """Generate a sentinel token to embed in the prompt."""
    return f"XJUSAGE-{uuid.uuid4().hex[:16]}"


def lookup_usage(sentinel: str) -> dict | None:
    """Find the hermes CLI session whose user message contained `sentinel`.

    Returns dict with input_tokens, output_tokens, cache_read_tokens,
    reasoning_tokens, estimated_cost_usd, model — or None if not found
    (state.db unreadable, session not yet flushed, hermes schema changed).
    """
    if not STATE_DB.exists():
        return None
    try:
        # uri=ro so we never lock hermes
        conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=2.0)
        row = conn.execute(
            """
            SELECT s.input_tokens, s.output_tokens, s.cache_read_tokens,
                   s.reasoning_tokens, s.estimated_cost_usd, s.model
            FROM sessions s
            WHERE s.source='cli'
              AND s.id IN (
                  SELECT session_id FROM messages
                  WHERE role='user' AND content LIKE ?
                  LIMIT 1
              )
            ORDER BY s.started_at DESC
            LIMIT 1
            """,
            (f"%{sentinel}%",),
        ).fetchone()
        conn.close()
    except sqlite3.DatabaseError:
        return None
    if not row:
        return None
    return {
        "input_tokens": row[0] or 0,
        "output_tokens": row[1] or 0,
        "cache_read_tokens": row[2] or 0,
        "reasoning_tokens": row[3] or 0,
        "estimated_cost_usd": row[4] or 0.0,
        "model": row[5],
    }
