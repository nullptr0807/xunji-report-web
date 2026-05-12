"""Use `hermes -z` (one-shot LLM call) to enrich the report with:
- A viral hero hook (1 sentence + 1 subtitle) for the top of the page
- One-line "sharp commentary" per chart
- An improvement-oriented closing analysis

Output JSON is written to <job_dir>/llm_commentary.json. If the LLM call
fails (timeout, no model, etc.) the report degrades gracefully — the
hero hook simply isn't shown.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

PROMPT = """你是一位毒舌但精准的健身教练 / 数据评论员。下面是某用户的训练分析报告数据，请生成一份用于"社交媒体引爆"的点评。

风格要求：
- 中文口语，第一人称对话感（"你"）
- 准确（不要编造数据里没有的事实）
- 有趣，可以毒辣，但不羞辱
- 不要 AI 味（不要"首先/其次/总之"、不要"加油！"煽情、不要 emoji 满天飞）
- 不要列表式、不要排比

只输出一个 JSON 对象，不要包裹 markdown 代码块：

{
  "hero_hook": {
    "headline": "一句最抓眼球的总结，不超过 22 字。可以是一句反讽、一个金句、一个数字+感叹",
    "subline": "一句话补充，30 字内，描述这份报告最值得分享的点"
  },
  "chart_takes": {
    "volume": "训练容量趋势的一句话辣评，20-35 字",
    "pr": "主项 e1RM 累积曲线的一句话辣评，20-35 字（如果没有 PR 数据就说没有）",
    "calendar": "每日训练强度的一句话辣评，20-35 字",
    "weekday": "周内分布的一句话辣评，20-35 字",
    "top_exercises": "Top 20 动作的一句话辣评，20-35 字"
  },
  "improvement_plan": [
    "三到五条针对性的、能落地的下一步建议，每条 30-60 字。基于真实数据指出薄弱环节并给具体动作。"
  ]
}

数据如下：
"""


def generate_commentary(report_data: dict, out_path: Path, timeout: int = 90) -> dict | None:
    """Call hermes -z to generate commentary. Returns parsed JSON or None."""
    # Trim report_data: drop raw series arrays (too long), keep summary & insights
    compact = {
        "summary": report_data.get("summary", {}),
        "weekday_counts": report_data.get("weekday_counts"),
        "weekday_labels": report_data.get("weekday_labels"),
        "monthly": report_data.get("monthly"),
        "top_exercises": report_data.get("top_exercises", [])[:15],
        "pr_keys": list(report_data.get("pr_progression", {}).keys()),
        "insights": report_data.get("insights", []),
    }
    prompt = PROMPT + json.dumps(compact, ensure_ascii=False, indent=2)

    # Locate hermes binary (systemd PATH may not include ~/.local/bin)
    import os, shutil as _sh
    hermes_bin = (
        os.environ.get("HERMES_BIN")
        or _sh.which("hermes")
        or "/home/gexin/.local/bin/hermes"
    )

    try:
        result = subprocess.run(
            [hermes_bin, "-z", prompt, "-t", "", "--ignore-rules"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None

    raw = (result.stdout or "").strip()
    if not raw:
        return None

    # Extract JSON object (may have leading prose or code fences)
    raw_clean = raw
    if "```" in raw_clean:
        # take inside the first ```...``` block
        parts = raw_clean.split("```")
        for p in parts[1::2]:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                raw_clean = p
                break
    # Find first { ... last }
    start = raw_clean.find("{")
    end = raw_clean.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        parsed = json.loads(raw_clean[start:end+1])
    except json.JSONDecodeError:
        return None

    out_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
    return parsed


if __name__ == "__main__":
    import sys
    data_path = Path(sys.argv[1])
    out = data_path.parent / "llm_commentary.json"
    data = json.loads(data_path.read_text())
    r = generate_commentary(data, out)
    print(json.dumps(r, ensure_ascii=False, indent=2) if r else "FAILED")
