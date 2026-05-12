"""训记 API 客户端。"""
from __future__ import annotations
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://trains.xunjiapp.cn"
ENDPOINT = "/api_trains_for_llm"


class XunjiError(Exception):
    pass


class RateLimited(XunjiError):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"too frequent, retry after {retry_after}s")


class XunjiClient:
    def __init__(self, api_key: str | None = None, timeout: int = 30):
        self.api_key = api_key or os.environ.get("XUNJI_API_KEY")
        if not self.api_key:
            raise XunjiError("XUNJI_API_KEY not set (env or .env)")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        })

    def fetch(self, datestr: str) -> dict:
        """抓取某天的训练数据。datestr: YYYY-MM-DD。"""
        body = {"datestr": datestr, "apikey": self.api_key}
        r = self.session.post(
            BASE_URL + ENDPOINT,
            json=body,
            params={"apikey": self.api_key},
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        res = data.get("res")
        # success: res is a list (records). errors come back as a string.
        if isinstance(res, list):
            return data
        msg = str(res or "")
        if "too frequent" in msg:
            import re
            m = re.search(r"(\d+)s", msg)
            raise RateLimited(int(m.group(1)) if m else 90)
        raise XunjiError(msg or "unknown error")

    def upsert(self, rows: list[str]) -> dict:
        """写入 / 更新训练记录。

        rows: 训练行字符串列表，全部必须同一日期，单次最多 12 条，每行 ≤1500 字符。
        含 ``id:...`` 的行会按 localId 更新已有记录；不含 id 的会新建。
        """
        if not rows:
            raise XunjiError("rows must be non-empty")
        if len(rows) > 12:
            raise XunjiError(f"max 12 rows per call, got {len(rows)}")
        for i, r in enumerate(rows):
            if len(r) > 1500:
                raise XunjiError(f"row {i} exceeds 1500 chars ({len(r)})")

        body = {"res": rows, "apikey": self.api_key}
        r = self.session.post(
            BASE_URL + "/api_upsert_trains_for_llm",
            json=body,
            params={"apikey": self.api_key},
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        res = data.get("res")
        if isinstance(res, list):
            return data
        msg = str(res or "")
        if "too frequent" in msg:
            import re
            m = re.search(r"(\d+)s", msg)
            raise RateLimited(int(m.group(1)) if m else 90)
        raise XunjiError(msg or "unknown error")

    def fetch_with_retry(self, datestr: str, max_retries: int = 3) -> dict:
        """碰到限流自动等待重试。"""
        for attempt in range(max_retries):
            try:
                return self.fetch(datestr)
            except RateLimited as e:
                wait = e.retry_after + 2
                print(f"  [rate-limited] sleeping {wait}s...")
                time.sleep(wait)
        raise XunjiError(f"still rate-limited after {max_retries} retries")
