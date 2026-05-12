"""解析 res 数组里的训练记录文本。

实际格式 (单条记录, 逗号分隔):
  260507,
  id:1778154285558,
  train_time:1778154290609-1778158610355,
  calorie:441,
  1.引体向上（辅助）, 1组,0kg,10次,time:120s, 2组,0kg,10次,time:120s, ...
  2.杠铃划船, 1组,65kg,8次,time:120s, ...

字段:
  - 头部 6 位数字 = 日期短码 (YYMMDD)
  - id:xxx = localId (不是训练记录主键)
  - train_time:start-end = 起止时间戳 (毫秒)
  - calorie:N = 卡路里
  - N.动作名 后面跟若干 "M组,Wkg,R次,time:Ts" 组成的 set
"""
from __future__ import annotations
import re
from datetime import datetime
from typing import Any


_EXERCISE_HEAD = re.compile(r"^\d+\.\D")  # "1.引体向上" not "17.5kg"
_SET = re.compile(r"^\d+组$")            # "1组"
_KG = re.compile(r"^([\d.]+)kg$")
_REPS = re.compile(r"^(\d+)次$")
_TIME = re.compile(r"^time:(\d+)s$")


def parse_record(text: str) -> dict[str, Any]:
    """把单条训练记录文本解析成结构化 dict。"""
    rec: dict[str, Any] = {"raw": text}
    tokens = [t.strip() for t in text.split(",") if t.strip()]

    exercises: list[dict] = []
    current_ex: dict | None = None
    current_set: dict | None = None

    for tok in tokens:
        # 元数据
        if re.fullmatch(r"\d{6}", tok):
            rec["date_code"] = tok
            continue
        if tok.startswith("id:"):
            rec["local_id"] = tok[3:]
            continue
        if tok.startswith("train_time:"):
            m = re.match(r"train_time:(\d+)-(\d+)", tok)
            if m:
                start_ms, end_ms = int(m.group(1)), int(m.group(2))
                rec["start_ms"] = start_ms
                rec["end_ms"] = end_ms
                rec["duration_ms"] = end_ms - start_ms
                rec["start_iso"] = datetime.fromtimestamp(start_ms / 1000).isoformat()
                rec["end_iso"] = datetime.fromtimestamp(end_ms / 1000).isoformat()
            continue
        if tok.startswith("calorie:"):
            v = tok.split(":", 1)[1].strip()
            if v:
                try:
                    rec["calorie"] = int(float(v))
                except ValueError:
                    rec["calorie_raw"] = v
            continue

        # 新动作 "1.引体向上"
        if _EXERCISE_HEAD.match(tok):
            current_ex = {"name": re.sub(r"^\d+\.", "", tok), "sets": []}
            exercises.append(current_ex)
            current_set = None
            continue

        # 组开始
        if _SET.match(tok):
            current_set = {"set": int(tok[:-1])}
            if current_ex is not None:
                current_ex["sets"].append(current_set)
            continue

        if current_set is None:
            continue

        if m := _KG.match(tok):
            current_set["weight_kg"] = float(m.group(1))
        elif m := _REPS.match(tok):
            current_set["reps"] = int(m.group(1))
        elif m := _TIME.match(tok):
            current_set["rest_s"] = int(m.group(1))

    if exercises:
        rec["exercises"] = exercises
        rec["total_sets"] = sum(len(e["sets"]) for e in exercises)
        rec["total_volume_kg"] = sum(
            (s.get("weight_kg") or 0) * (s.get("reps") or 0)
            for e in exercises for s in e["sets"]
        )

    return rec


def parse_response(data: dict) -> list[dict]:
    """解析整个 API 响应的 res 数组。"""
    res = data.get("res", [])
    if not isinstance(res, list):
        return []
    return [parse_record(item) if isinstance(item, str) else item for item in res]
