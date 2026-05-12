# xunji-report-web

为训记 (Xunji, 训记 App) 用户提供一键生成训练数据分析报告的 Web 服务。

> 在线体验：粘贴 API Key 即可生成报告
> 数据来源：训记 (https://trains.xunjiapp.cn) `/api_trains_for_llm` 公开 LLM 接口

## ✨ 特性

- **零安装**：浏览器粘贴 Key → 几十秒拿到长图报告
- **数据可视化**：lightweight-charts 实时曲线 + SVG 热力图
- **响应式**：移动端 / 桌面端自适应
- **数据去重缓存**：同一个 Key 的同一天数据只下载一次
- **下载长图 JPG**：playwright 截全页，适合分享
- **加密落盘**：API Key 用 Fernet 对称加密后存入 SQLite

## 📊 报告包含

- 训练容量趋势 + 7 次滑动均值
- 主项 e1RM (Epley 公式) 累积曲线
- 每日训练强度热力图（≤60 天：横向圆点条；>60 天：GitHub 风日历）
- 周内训练分布
- Top 20 常做动作排行
- 主项历史最佳 (PR) 列表
- 自动文字点评（基于规则）

## 🏗️ 架构

```
浏览器 ──► nginx (HTTPS, /xunji/) ──► uvicorn (127.0.0.1:8610)
                                         │
                                         ├── FastAPI
                                         ├── 后台线程池 (ThreadPoolExecutor)
                                         ├── SQLite (Fernet 加密 KEY)
                                         ├── 训记 API client
                                         └── playwright (headless chromium → JPG)
```

## 🚀 本地运行

```bash
git clone https://github.com/<your>/xunji-report-web.git
cd xunji-report-web

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 生成主密钥
python -c "from cryptography.fernet import Fernet; print('MASTER_KEY='+Fernet.generate_key().decode())" > .env
chmod 600 .env

# 启动
uvicorn app.main:app --host 127.0.0.1 --port 8610
```

## 🔧 CLI 用法

```bash
python -m app.pipeline --key xjllm_XXX --start 2025-01-01 --end 2025-12-31
# 输出到 data/jobs/<job_id>/report.html
```

## 🔒 安全说明

- API Key 通过 HTTPS 传输，服务端用 **Fernet** 加密落盘，`MASTER_KEY` 不进 git
- 训练数据 / 报告保留 7 天，到期自动清理（cron 在 03:00 跑 `app/cleanup.py`）
- 报告链接为 22 字符 URL-safe 随机串（128-bit 熵），无登录但需知道链接才能访问
- **每日配额**：同一 API Key 24h 最多 3 次报告（避免 LLM 成本爆炸）
- **白名单**：在 `.env` 设 `WHITELIST_KEY_HASHES=<hash1>,<hash2>` 即可免限额。
  用 `python scripts/whitelist_hash.py xjllm_xxx` 计算 hash（仅存 hash，不存原 key）
- 用户可随时在训记 App 端吊销 Key

## 📁 项目结构

```
xunji-report-web/
├── app/
│   ├── main.py          # FastAPI app
│   ├── pipeline.py      # key + date range → report
│   ├── storage.py       # SQLite + Fernet
│   └── snapshot.py      # headless chromium → JPG
├── core/
│   ├── client.py        # 训记 API client (per skill)
│   ├── parse.py         # row parser
│   └── analyze.py       # data analysis
├── web/
│   ├── index.html       # landing page
│   └── report_template.html
└── data/                # gitignored
    ├── keys.db          # encrypted KEY store
    ├── cache/           # per-user raw API cache
    └── jobs/            # per-job output
```

## 📝 训记 API 备注

详见 [xunji-training-api skill](https://github.com/nullptr0807/xunji-data) — 训记官方 LLM 接口的踩坑总结。

## License

MIT
