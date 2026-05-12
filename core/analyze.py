"""分析数据 → JSON。给前端 lightweight-charts 用。
不再生成 matplotlib PNG（HTML/JS 渲染图表）。"""
from __future__ import annotations
import json, glob
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime
import numpy as np
import pandas as pd


def _load_records(parsed_dir: Path) -> list[dict]:
    recs = []
    for f in sorted(glob.glob(str(parsed_dir / '*.json'))):
        for r in json.load(open(f)):
            r['date'] = Path(f).stem
            recs.append(r)
    return recs


def analyze(parsed_dir: Path, out_dir: Path) -> dict:
    """Compute summary + chart data, write report_data.json. Return summary dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = _load_records(parsed_dir)
    if not recs:
        raise ValueError("无数据：未找到任何已解析的训练记录")

    sess = []
    for r in recs:
        if not r.get('exercises'):
            continue
        sets_list = [s for e in r['exercises'] for s in e['sets']]
        vol = sum((s.get('weight_kg') or 0) * (s.get('reps') or 0) for s in sets_list)
        reps_total = sum((s.get('reps') or 0) for s in sets_list)
        rests = [s.get('rest_s') for s in sets_list if s.get('rest_s')]
        sess.append({
            'date': r['date'],
            'duration_min': (r.get('duration_ms') or 0) / 60000,
            'calorie': r.get('calorie'),
            'n_exercises': len(r['exercises']),
            'n_sets': len(sets_list),
            'n_reps': reps_total,
            'volume_kg': vol,
            'avg_rest_s': float(np.mean(rests)) if rests else None,
            'exercises': [e['name'] for e in r['exercises']],
        })
    if not sess:
        raise ValueError("有数据但没有可用的训练动作")

    df = pd.DataFrame(sess)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    set_rows = []
    ex_rows = []
    for r in recs:
        if not r.get('exercises'):
            continue
        for e in r['exercises']:
            ex_rows.append({'date': r['date'], 'name': e['name']})
            for s in e['sets']:
                set_rows.append({
                    'date': r['date'], 'exercise': e['name'],
                    'weight_kg': s.get('weight_kg'),
                    'reps': s.get('reps'),
                })
    exdf = pd.DataFrame(ex_rows); exdf['date'] = pd.to_datetime(exdf['date'])
    sdf = pd.DataFrame(set_rows); sdf['date'] = pd.to_datetime(sdf['date'])

    total_days = (df.date.max() - df.date.min()).days + 1
    summary = {
        'date_start': str(df.date.min().date()),
        'date_end': str(df.date.max().date()),
        'span_days': int(total_days),
        'training_days': int(len(df)),
        'frequency_pct': round(len(df) / total_days * 100, 1),
        'avg_per_week': round(len(df) / total_days * 7, 2),
        'total_minutes': int(df.duration_min.sum()),
        'total_hours': round(df.duration_min.sum() / 60, 1),
        'total_volume_kg': float(df.volume_kg.sum()),
        'total_sets': int(df.n_sets.sum()),
        'total_reps': int(df.n_reps.sum()),
    }

    # 周内分布
    wd_zh = ['周一','周二','周三','周四','周五','周六','周日']
    weekday_counts = [int((df.date.dt.weekday == i).sum()) for i in range(7)]

    # 月度训练次数
    monthly = df.groupby(df.date.dt.to_period('M').astype(str)).size()
    monthly_data = [{"month": m, "count": int(v)} for m, v in monthly.items()]

    # 容量时间线（lightweight-charts area series）
    df_for_chart = df.copy()
    df_for_chart['ts'] = df_for_chart.date.dt.strftime('%Y-%m-%d')
    volume_series = [
        {"time": r.ts, "value": round(float(r.volume_kg), 1)}
        for r in df_for_chart.itertuples()
    ]
    # 7日滑动均值（在训练日序列上）
    df_for_chart['vol_ma7'] = df_for_chart['volume_kg'].rolling(7, min_periods=1).mean()
    volume_ma_series = [
        {"time": r.ts, "value": round(float(r.vol_ma7), 1)}
        for r in df_for_chart.itertuples()
    ]
    duration_series = [
        {"time": r.ts, "value": round(float(r.duration_min), 1)}
        for r in df_for_chart.itertuples()
    ]

    # 最常做的动作 Top 20
    ex_count = exdf['name'].value_counts().head(20)
    top_exercises = [{"name": n, "count": int(c)} for n, c in ex_count.items()]

    # PR + 主项 e1RM 曲线（Epley: w * (1 + reps/30)）
    def pr_for(name_kw):
        sub = sdf[sdf['exercise'].str.contains(name_kw, na=False)]
        sub = sub[sub['weight_kg'].fillna(0) > 0]
        if sub.empty: return None
        idx = sub['weight_kg'].idxmax()
        row = sub.loc[idx]
        return {
            'kw': name_kw,
            'exercise': row['exercise'],
            'weight_kg': float(row['weight_kg']),
            'reps': int(row['reps'] or 0),
            'date': str(row['date'].date()),
        }

    prs = []
    for kw in ['卧推','深蹲','硬拉','划船','推举','弯举','下拉','引体','臀推','腿举','飞鸟']:
        pr = pr_for(kw)
        if pr: prs.append(pr)
    summary['prs'] = prs

    # 主项 e1RM 累积曲线
    pr_progression = {}
    for kw in ['卧推','深蹲','硬拉','划船','推举']:
        sub = sdf[sdf['exercise'].str.contains(kw, na=False) & (sdf['weight_kg'].fillna(0) > 0)]
        if sub.empty: continue
        sub = sub.copy()
        sub['e1rm'] = sub['weight_kg'] * (1 + sub['reps'].fillna(1) / 30)
        daily_max = sub.groupby(sub['date'].dt.strftime('%Y-%m-%d'))['e1rm'].max().cummax()
        if len(daily_max) < 2: continue
        pr_progression[kw] = [{"time": d, "value": round(float(v), 1)} for d, v in daily_max.items()]

    # 日历热力图数据
    all_dates = pd.date_range(df.date.min(), df.date.max())
    vol_by_date = df.set_index('date')['volume_kg'].to_dict()
    calendar = []
    max_vol = df['volume_kg'].max() or 1
    for d in all_dates:
        v = vol_by_date.get(d, 0)
        calendar.append({
            "date": d.strftime('%Y-%m-%d'),
            "weekday": int(d.weekday()),
            "volume": round(float(v), 1),
            "intensity": min(1.0, float(v) / max_vol) if v else 0,
        })

    # 连续性
    dates = sorted(df.date.dt.date.unique())
    cur = max_streak = 1
    for i in range(1, len(dates)):
        if (dates[i] - dates[i-1]).days == 1:
            cur += 1; max_streak = max(max_streak, cur)
        else:
            cur = 1
    gaps = [(dates[i] - dates[i-1]).days for i in range(1, len(dates))] if len(dates) > 1 else [0]
    summary['longest_streak'] = max_streak
    summary['longest_gap'] = int(max(gaps)) if gaps else 0
    summary['avg_gap_days'] = round(float(np.mean(gaps)), 1) if gaps else 0

    # 文字点评（简单规则）
    insights = []
    if summary['avg_per_week'] >= 4:
        insights.append(f"训练频率不错：平均每周 {summary['avg_per_week']} 次，属于稳定训练者区间。")
    elif summary['avg_per_week'] >= 2:
        insights.append(f"训练频率中等：平均每周 {summary['avg_per_week']} 次，可以考虑提到 3 次以上加速进步。")
    else:
        insights.append(f"训练频率偏低：平均每周 {summary['avg_per_week']} 次，规律性是力量训练最重要的变量。")

    if max_streak >= 5:
        insights.append(f"最长连续 {max_streak} 天训练，自律性表现强。")
    if summary['longest_gap'] > 14:
        insights.append(f"最长一次断练 {summary['longest_gap']} 天，断练通常会让进度回到 2-4 周前。")

    if len(monthly) >= 3:
        vol_trend = df.set_index('date')['volume_kg'].resample('ME').sum()
        if len(vol_trend) >= 3:
            recent = vol_trend.iloc[-1]
            prev = vol_trend.iloc[-2]
            if prev > 0:
                pct = (recent - prev) / prev * 100
                if pct > 10:
                    insights.append(f"近一个月总容量比上月增长 {pct:.0f}%，处于上升期。")
                elif pct < -10:
                    insights.append(f"近一个月总容量比上月下降 {abs(pct):.0f}%，可能是减量周或状态调整期。")

    if len(prs) >= 3:
        insights.append(f"已记录 {len(prs)} 个主项 PR，最近一个 PR 是 {max(prs, key=lambda x: x['date'])['exercise']}。")

    # ===== Training-type detection =====
    # set-based ratio (sets with weight / total sets) — biased toward strength
    # because cardio sessions have 0 sets
    n_sets_total = len(sdf)
    n_sets_weighted = int((sdf['weight_kg'].fillna(0) > 0).sum())
    strength_ratio = (n_sets_weighted / n_sets_total) if n_sets_total else 0.0

    # time-based detection — much more honest. For each session, classify
    # by whether it's primarily weighted sets or cardio activity.
    strength_minutes = 0.0
    cardio_minutes = 0.0
    cardio_exercises = []  # {name, date, distance_km, duration_s, avg_bpm, kcal}
    for r in recs:
        if not r.get('exercises'):
            continue
        rdate = (r.get('start_iso') or '')[:10]
        dur_min = (r.get('duration_ms') or 0) / 60000.0
        has_weighted = any(
            (s.get('weight_kg') or 0) > 0
            for e in r['exercises'] for s in e.get('sets', [])
        )
        has_cardio_ex = False
        for e in r['exercises']:
            is_cardio = (
                any(k in e for k in ('distance_km', 'duration_s', 'avg_bpm', 'kcal'))
                and not e.get('sets')
            )
            if is_cardio:
                has_cardio_ex = True
                cardio_exercises.append({
                    'name': e['name'],
                    'date': rdate,
                    'distance_km': e.get('distance_km'),
                    'duration_s': e.get('duration_s'),
                    'avg_bpm': e.get('avg_bpm'),
                    'kcal': e.get('kcal'),
                })
        # Attribute session duration
        if has_cardio_ex and not has_weighted:
            cardio_minutes += dur_min
        elif has_weighted and not has_cardio_ex:
            strength_minutes += dur_min
        else:
            # Mixed session — split evenly. (Could refine via per-exercise
            # duration_s when present, but rare and not worth complexity yet.)
            cardio_minutes += dur_min / 2
            strength_minutes += dur_min / 2

    total_train_min = strength_minutes + cardio_minutes
    strength_time_ratio = (strength_minutes / total_train_min) if total_train_min else 1.0

    total_distance_km = round(sum(c.get('distance_km') or 0 for c in cardio_exercises), 2)
    total_cardio_minutes = round(cardio_minutes, 1)
    n_cardio_sessions = len({c['date'] for c in cardio_exercises if c.get('date')})

    summary['strength_ratio'] = round(strength_ratio, 3)       # set-based (legacy)
    summary['strength_time_ratio'] = round(strength_time_ratio, 3)  # time-based (primary)
    summary['n_sets_weighted'] = n_sets_weighted
    summary['n_sets_total'] = n_sets_total
    summary['strength_minutes'] = round(strength_minutes, 1)
    summary['cardio_minutes'] = total_cardio_minutes
    summary['total_distance_km'] = total_distance_km
    summary['total_cardio_minutes'] = total_cardio_minutes  # back-compat alias
    summary['n_cardio_sessions'] = n_cardio_sessions

    report_data = {
        "summary": summary,
        "weekday_counts": weekday_counts,
        "weekday_labels": wd_zh,
        "monthly": monthly_data,
        "volume_series": volume_series,
        "volume_ma_series": volume_ma_series,
        "duration_series": duration_series,
        "top_exercises": top_exercises,
        "pr_progression": pr_progression,
        "calendar": calendar,
        "insights": insights,
        "cardio_exercises": cardio_exercises,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    (out_dir / 'report_data.json').write_text(json.dumps(report_data, ensure_ascii=False, indent=2))
    df.to_csv(out_dir / 'sessions.csv', index=False)
    sdf.to_csv(out_dir / 'sets.csv', index=False)
    return summary
