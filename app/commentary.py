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

PROMPT = """你是一位有经验、有判断力的健身教练 + 数据分析师。下面是某用户的训练分析数据，请生成一份**对他真正有价值**的点评。

风格要求：
- 中文口语，第一人称对话感（"你"）
- **准确**：所有数字必须能在数据里查到，不要编造
- **有价值**：把笔墨花在用户最需要知道的地方——他做对了什么、状态趋势如何、下一步该往哪走。**不要为了犀利而犀利，不要鸡蛋里挑骨头**。
- 可以有点幽默和直率，但**先把分析做扎实**，再考虑表达风格。批评要批评在刀刃上（真正影响进步/健康的问题），不要纠结无关紧要的小事。
- 不要 AI 味：不要"首先/其次"、不要排比、不要"加油！"煽情、不要 emoji、不要"建议你…"端着的口吻
- 不要列表式（除了 improvement_plan）
- **严格 JSON**：字符串值内部禁止英文直引号 `"`，要引用就用中文「」或单引号 `'`

只输出一个 JSON 对象，不要包裹 markdown 代码块：

{
  "hero_hook": {
    "headline": "一句最抓眼球的总结，不超过 22 字。反讽 / 金句 / 数字+反问，要让人想转发",
    "subline": "一句话补充，30 字内，揭穿这份数据最尴尬或最值得吹的点"
  },
  "overall_take": "**总体点评，200-250 字，最重要的一段**。结构：先说做得好的（具体数字+真诚的肯定），然后说有什么趋势值得注意（向上/向下/瓶颈），最后给一两条最有价值的改进方向。三部分揉成自然口语段落，像教练一边看数据一边和你聊天，**重点是有用、有洞察**，而不是为了喷而喷。",
  "chart_takes": {
    "volume": "训练容量趋势的点评，**2-3 句，60-100 字**。讲事实+讲意义：是稳定、上升、还是出现明显下滑？背后可能的原因（减量周/工作忙/兴趣转移）。有问题就直说，没问题就坦然承认。",
    "pr": "主项 e1RM 累积曲线的点评，**2-3 句，60-100 字**。哪些主项在涨、哪些卡了多久。如果没有 PR 数据就解释为什么——可能是热身/新手期/刚开始记录。",
    "calendar": "每日训练强度的点评，**2-3 句，60-100 字**。节奏感、规律性、有没有明显断档及其影响。",
    "weekday": "周内分布的点评，**2-3 句，60-100 字**。看出他的生活节奏（工作日型/周末型/平均型），是否合理。",
    "top_exercises": "Top 20 动作的点评，**2-3 句，60-100 字**。看动作选择反映的训练偏好和平衡（推拉比、上下肢比、主项辅项比），指出真正影响进步的失衡，无关紧要的偏好不必过度解读。"
  },
  "improvement_plan": [
    "三到五条针对性的、能落地的下一步建议，每条 30-60 字。基于真实数据指出**最值得改的 1-2 个点**，给具体动作和数字。建议要可执行、不要空话。"
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
    # Stash token-budget info for stats aggregation
    parsed["_meta"] = {
        "prompt_chars": len(prompt),
        "response_chars": len(raw),
    }
    return parsed


if __name__ == "__main__":
    import sys
    data_path = Path(sys.argv[1])
    out = data_path.parent / "llm_commentary.json"
    data = json.loads(data_path.read_text())
    r = generate_commentary(data, out)
    print(json.dumps(r, ensure_ascii=False, indent=2) if r else "FAILED")
