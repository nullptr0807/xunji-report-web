"""Dynamic-report commentary: hand the LLM raw + parsed + summary data and let
it design 3-8 sections of analysis. Used when strength_ratio is too low for
the canonical strength template.

Output JSON shape (written to <job_dir>/dynamic_sections.json):

{
  "hero_hook": {"headline": "...", "subline": "..."},
  "overall_take": "200-300 字综合点评",
  "sections": [
    {"title": "...", "kind": "chart_line"|"chart_bar"|"kv_grid"|"prose",
     "data": {...}, "take": "...one-paragraph commentary..."}
  ]
}

Section data shapes:
  chart_line / chart_bar: {"x": ["label", ...], "y": [num, ...],
                            "y_label": "kg"|"km"|"分钟", "unit": "..."}
  kv_grid:                {"items": [{"k": "...", "v": "..."}, ...]}
  prose:                  {"text": "...one paragraph..."}
"""
from __future__ import annotations
import json
import os
import shutil as _sh
import subprocess
from pathlib import Path

PROMPT = """你是一位有经验、有判断力的健身教练 + 数据分析师。下面是某用户的训练原始数据 + 已经初步分析过的统计数据。这个用户的训练**不以传统力量训练（卧推/深蹲/硬拉）为主**，所以不能套用模板，要根据他实际练的东西自由设计**一份对他真正有价值**的报告。

# 你的任务

输出一份完全自定义的报告 JSON，包含 3-8 个分析 section。每个 section 自己选最合适的展示形式。

# 风格要求

- 中文口语，第一人称对话感（"你"）
- **数据准确性第一**：所有数字必须能在我给你的数据里查到，**绝对不能编造**任何重量/距离/次数/心率。如果数据没有就直接说没有，不要瞎掰。
- **诚实承认数据局限**：训记 App 通过苹果健康同步过来的有氧数据通常只有「时长 + 可能有心率」，**没有 km、配速、心率分布**。如果用户主练有氧但数据这么粗，**要诚实告诉他**——"你的有氧训练我能看到的只有时长和总热量，没有配速和心率曲线，所以这部分能给的洞察有限"。不要拿一句话当饭吃强行编 6 个 section。**宁可少做 section 也不要假装看到了不存在的数据**。
- **有价值优先于有趣**：把笔墨花在用户最该知道的地方——他做对了什么、状态趋势如何、下一步该往哪走。不要为了犀利而犀利、**不要鸡蛋里挑骨头**、不要为了凑字数而强行批评无关紧要的小事。
- 可以幽默、直率、一针见血，但**先把分析做扎实再考虑表达**。批评要批在刀刃上——真正影响进步/健康/可持续性的问题，比如训练失衡、心率漂移、伤病信号、明显的低效模式。无关大局的偏好不必过度解读。
- **特别警告：不要贬低用户的训练选择**。如果用户主练有氧、力量只占小部分，那是他的选择，不要居高临下地评判"力量训练水平"，更不要因为他只做了几组卧推就开喷。重点放在他**实际练的东西**上。
- 不要 AI 味：不要"首先/其次"、不要"加油！"、不要 emoji、不要排比、不要"建议你…"端着的口吻
- 严格 JSON：字符串值内禁止英文直引号 `"`，要引用就用中文「」或单引号

# 输出格式

只输出一个 JSON 对象，不要包裹 markdown：

{
  "hero_hook": {
    "headline": "一句最抓眼球的总结，不超过 22 字。反讽/金句/数字+反问，让人想转发。",
    "subline": "一句话补充，30 字内。"
  },
  "overall_take": "200-250 字的整体点评。结构：先说做得好的（具体数字+真诚的肯定），再说有什么趋势值得注意（向上/向下/瓶颈/伤病信号），最后给一两条最有价值的改进方向。揉成自然口语段落，**重点是有用、有洞察**，而不是为了喷而喷。",
  "sections": [
    {
      "title": "section 标题，6-12 字",
      "kind": "chart_line",
      "data": {
        "x": ["4-12", "4-15", "4-19", ...],
        "y": [5.2, 6.0, 5.5, ...],
        "y_label": "km"
      },
      "take": "针对这个 section 的点评，2-4 句，60-120 字。**扎实+有价值**：先讲数据事实，再讲含义和下一步。无关紧要的小问题不必揪着不放。"
    },
    ...
  ]
}

# 可用的 section kind

- **chart_line**：折线图。data = {x:[str], y:[number], y_label:str}。适合时间序列（每日里程、配速、心率…）。
- **chart_bar**：柱状图。data = {x:[str], y:[number], y_label:str}。适合分类比较（动作 Top 10、周内分布、月度对比…）。
- **kv_grid**：键值对网格。data = {items:[{k:str, v:str}, ...]}。适合一组关键指标（总里程/总时长/平均心率/最快配速/PB）。
- **prose**：纯文字段落。data = {text: str}。适合无法图表化的洞察。

# 设计原则

- **不要硬套力量模板**。如果用户主要在跑步/做有氧，section 应该围绕**实际有数据的维度**组织（时长、频率、心率均值、热量、动作多样性…），而不是 e1RM 和深蹲。
- **从用户实际练的动作里挑**。看 cardio_exercises、top_exercises、session_samples 里的动作名，识别他到底在练什么（跑步？划船机？瑜伽？椭圆机？苹果健康同步过来的「健身训练」？）。
- 数字要**精确**，能从我给的数据里**直接查到**。允许做简单计算（平均值、增长率），但禁止凭感觉编。
- chart 的 x、y 数组长度必须一致。x 用日期短格式 `M-D` 或类别名，y 是数字。
- **3-6 个 section 是甜蜜点**，太多读不完。如果数据本身很稀（比如全是苹果健康的时长记录，没有 km/配速/心率分布），那就老老实实做 2-3 个 section + 一个 "数据局限" 的 prose section 解释为什么不能给更多分析，**不要硬撑**。

# 数据如下

"""


def generate_dynamic_commentary(
    report_data: dict,
    raw_records: list,
    out_path: Path,
    timeout: int = 180,
) -> dict | None:
    """Call hermes -z, get a dynamic sections JSON. Returns parsed dict or None."""
    # Build a compact data packet: summary + chart series + top exercises
    # + cardio_exercises + a sample of raw records (to capture exercise names
    # and any patterns python missed).
    summary = report_data.get("summary", {})
    cardio = report_data.get("cardio_exercises", [])
    top = report_data.get("top_exercises", [])

    # Sample up to 60 records (most recent first) — names + duration + exercise list
    sampled = []
    for r in raw_records[-60:]:
        if not r.get("exercises"):
            continue
        sampled.append({
            "date": (r.get("start_iso") or "")[:10],
            "title": r.get("raw", "").split(",")[1] if r.get("raw") else "",
            "duration_min": round((r.get("duration_ms") or 0) / 60000, 1),
            "exercises": [
                {
                    "name": e["name"],
                    "n_sets": len(e.get("sets", [])),
                    "distance_km": e.get("distance_km"),
                    "duration_s": e.get("duration_s"),
                    "avg_bpm": e.get("avg_bpm"),
                    "kcal": e.get("kcal"),
                    "max_weight_kg": max(
                        (s.get("weight_kg") or 0 for s in e.get("sets", [])),
                        default=0,
                    ) or None,
                    "max_reps": max(
                        (s.get("reps") or 0 for s in e.get("sets", [])),
                        default=0,
                    ) or None,
                }
                for e in r["exercises"]
            ],
        })

    packet = {
        "summary": summary,
        "monthly": report_data.get("monthly"),
        "weekday_counts": report_data.get("weekday_counts"),
        "weekday_labels": report_data.get("weekday_labels"),
        "volume_series": report_data.get("volume_series"),
        "duration_series": report_data.get("duration_series"),
        "top_exercises": top[:25],
        "cardio_exercises": cardio,
        "session_samples": sampled,
        "insights_python": report_data.get("insights", []),
    }
    prompt = PROMPT + json.dumps(packet, ensure_ascii=False, indent=2)

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
    try:
        (out_path.parent / "dynamic_raw.txt").write_text(
            f"RC={result.returncode}\nSTDERR:\n{result.stderr or ''}\n\nSTDOUT:\n{raw}"
        )
    except Exception:
        pass
    if not raw:
        return None

    # Extract JSON object
    raw_clean = raw
    if "```" in raw_clean:
        parts = raw_clean.split("```")
        for p in parts[1::2]:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                raw_clean = p
                break
    start = raw_clean.find("{")
    end = raw_clean.rfind("}")
    if start == -1 or end == -1:
        return None

    candidate = raw_clean[start:end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Salvage: escape stray inner quotes (same trick as commentary.py)
        def _escape_stray(s: str) -> str:
            out = []
            i = 0
            in_str = False
            while i < len(s):
                c = s[i]
                if c == "\\" and in_str and i + 1 < len(s):
                    out.append(c); out.append(s[i + 1]); i += 2; continue
                if c == '"':
                    if not in_str:
                        in_str = True
                        out.append(c)
                    else:
                        k = i + 1
                        while k < len(s) and s[k] in " \t\r\n":
                            k += 1
                        nxt = s[k] if k < len(s) else ""
                        if nxt in ",]}:" or nxt == "":
                            in_str = False
                            out.append(c)
                        else:
                            out.append('\\"')
                    i += 1
                else:
                    out.append(c); i += 1
            return "".join(out)

        try:
            parsed = json.loads(_escape_stray(candidate))
        except json.JSONDecodeError:
            return None

    # Sanity: must have sections
    if not isinstance(parsed.get("sections"), list) or not parsed["sections"]:
        return None

    out_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
    return parsed


if __name__ == "__main__":
    import sys
    rd_path = Path(sys.argv[1])
    parsed_dir = rd_path.parent / "parsed"
    report_data = json.loads(rd_path.read_text())
    records = []
    for p in sorted(parsed_dir.glob("*.json")):
        records.extend(json.loads(p.read_text()))
    out = rd_path.parent / "dynamic_sections.json"
    r = generate_dynamic_commentary(report_data, records, out)
    print(json.dumps(r, ensure_ascii=False, indent=2) if r else "FAILED")
