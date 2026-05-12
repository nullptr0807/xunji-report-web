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
- 准确（不要编造数据里没有的事实，数字必须对得上）
- **要毒辣、要狠、要一针见血**：直接戳破短板、指出自欺欺人的地方、敢说"你这就是在划水"
- **有趣**：可以用反讽、类比、网络梗（适度）、生活化比喻（"像股票回撤"、"打卡机"、"摆烂"）
- 不要 AI 味：不要"首先/其次/总之"、不要"加油！"煽情、不要 emoji、不要排比句、不要"建议你…"这种端着的口吻
- 不要列表式（除了 improvement_plan）
- **严格 JSON**：字符串值内部禁止使用英文直引号 `"`，需要引用短语时一律用中文「」或单引号 `'`，否则 JSON 解析会失败

只输出一个 JSON 对象，不要包裹 markdown 代码块：

{
  "hero_hook": {
    "headline": "一句最抓眼球的总结，不超过 22 字。反讽 / 金句 / 数字+反问，要让人想转发",
    "subline": "一句话补充，30 字内，揭穿这份数据最尴尬或最值得吹的点"
  },
  "overall_take": "**总体点评，200-250 字，最重要的一段**。要求：(1) 准确——数字必须对得上数据，不能编造；(2) 毒辣有趣——敢戳短板、用反讽和类比、像私教骂学生那样直接；(3) 三件套都要覆盖：先说『做得好的』（具体数字 + 表扬）、再说『做得不好的』（具体数字 + 开喷）、最后说『可改进的方向』（落地建议）。三部分不要用列表或'首先其次'切割，揉成自然口语段落，读起来像教练一边看你数据一边骂一边给方向。",
  "chart_takes": {
    "volume": "训练容量趋势的点评，**2-3 句，60-100 字**。先说数据事实，再开喷或开夸，要有具体的数字或对比，不要泛泛而谈。",
    "pr": "主项 e1RM 累积曲线的点评，**2-3 句，60-100 字**。如果没有 PR 数据就直接说没救。有数据就指出谁在涨、谁在原地踏步。",
    "calendar": "每日训练强度的点评，**2-3 句，60-100 字**。看节奏、看断档、看连续性，要狠。",
    "weekday": "周内分布的点评，**2-3 句，60-100 字**。揭穿生活习惯，比如打工人 / 摸鱼 / 周末党。",
    "top_exercises": "Top 20 动作的点评，**2-3 句，60-100 字**。看动作偏好暴露的虚荣 / 偷懒 / 失衡，比如练胳膊不练腿、练镜子肌肉。"
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
    # Debug: persist raw output next to out_path for postmortem
    try:
        (out_path.parent / "llm_raw.txt").write_text(
            f"RC={result.returncode}\nSTDERR:\n{result.stderr or ''}\n\nSTDOUT:\n{raw}"
        )
    except Exception:
        pass
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
        # Salvage: LLM sometimes embeds straight " quotes inside string values,
        # e.g. "样本仅 2 天却敢标"每周 7 次"——..." -> breaks JSON. Any " whose
        # next non-space char is not one of , ] } : (i.e. not a real string
        # terminator) is treated as a stray inner quote and backslash-escaped.
        candidate = raw_clean[start:end+1]

        def _escape_stray_quotes(s: str) -> str:
            out = []
            i = 0
            in_str = False
            while i < len(s):
                c = s[i]
                if c == '\\' and in_str and i + 1 < len(s):
                    out.append(c); out.append(s[i+1]); i += 2; continue
                if c == '"':
                    if not in_str:
                        in_str = True
                        out.append(c)
                    else:
                        # Look ahead past whitespace
                        k = i + 1
                        while k < len(s) and s[k] in ' \t\r\n':
                            k += 1
                        nxt = s[k] if k < len(s) else ''
                        if nxt in ',]}:' or nxt == '':
                            in_str = False
                            out.append(c)
                        else:
                            # Stray inner quote — escape it
                            out.append('\\"')
                    i += 1
                else:
                    out.append(c); i += 1
            return ''.join(out)

        try:
            parsed = json.loads(_escape_stray_quotes(candidate))
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
