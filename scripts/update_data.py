#!/usr/bin/env python3
"""Fetch 5-year daily index history + live quotes from Yahoo Finance and
regenerate index.html. No AI involved — pure data fetch + template fill.
Meant to run on a schedule via .github/workflows/update.yml.
"""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "scripts" / "template.html"
OUTPUT_PATH = ROOT / "index.html"

USER_AGENT = "Mozilla/5.0 (compatible; global-markets-chart-bot/1.0)"

# symbol -> Yahoo Finance ticker. 科创50 has no history under its own index
# ticker (000688.SS) on Yahoo, so we track it via 588000.SS, the flagship
# "华夏上证科创板50ETF" — the standard, highly-liquid tracker for that index.
GROUPS = [
    {
        "key": "china",
        "title": "中国",
        "series": [
            {"symbol": "000001.SS", "name": "上证综指"},
            {"symbol": "399001.SZ", "name": "深证成指"},
            {"symbol": "588000.SS", "name": "科创50(ETF代理)"},
        ],
    },
    {
        "key": "us",
        "title": "美国",
        "series": [
            {"symbol": "^IXIC", "name": "纳斯达克综合指数"},
            {"symbol": "^DJI", "name": "道琼斯工业指数"},
        ],
    },
    {
        "key": "taiwan",
        "title": "台湾",
        "series": [{"symbol": "^TWII", "name": "台湾加权指数"}],
    },
    {
        "key": "japan",
        "title": "日本",
        "series": [{"symbol": "^N225", "name": "日经225"}],
    },
    {
        "key": "korea",
        "title": "韩国",
        "series": [{"symbol": "^KS11", "name": "KOSPI综合指数"}],
    },
]


def fetch_json(url: str) -> dict:
    result = subprocess.run(
        ["curl", "-sL", "-A", USER_AGENT, "--max-time", "30", url],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def fetch_history(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5y&interval=1d"
    data = fetch_json(url)
    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    by_date = {}
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        by_date[date] = close
    return by_date


def fetch_live(symbol: str) -> tuple[float, float]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    data = fetch_json(url)
    meta = data["chart"]["result"][0]["meta"]
    price = meta["regularMarketPrice"]
    prev_close = meta["chartPreviousClose"]
    delta_pct = (price - prev_close) / prev_close * 100
    return price, delta_pct


def merge_series(histories: list) -> list:
    """Union + forward-fill N {date: price} dicts into aligned [date, p1, p2, ...] rows."""
    all_dates = sorted(set().union(*[h.keys() for h in histories]))
    last_vals = [None] * len(histories)
    merged = []
    for d in all_dates:
        for i, h in enumerate(histories):
            if d in h:
                last_vals[i] = h[d]
        if all(v is not None for v in last_vals):
            merged.append([d, *last_vals])
    return merged


def build_group_payload(group: dict) -> dict:
    symbols = [s["symbol"] for s in group["series"]]
    histories = [fetch_history(sym) for sym in symbols]
    merged = merge_series(histories)
    base = merged[0][1:]

    series_out = []
    for i, s in enumerate(group["series"]):
        pct_series = [[row[0], round((row[1 + i] / base[i] - 1) * 100, 3)] for row in merged]
        price, delta = fetch_live(s["symbol"])
        series_out.append({
            "name": s["name"],
            "data": pct_series,
            "latest": round(price, 2),
            "deltaPct": round(delta, 2),
        })

    return {
        "title": group["title"],
        "dateRange": f"{merged[0][0]} 至 {merged[-1][0]}",
        "series": series_out,
    }


def main():
    payload = [build_group_payload(g) for g in GROUPS]

    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = (
        template
        .replace("__GROUPS_JSON__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        .replace("__AS_OF__", as_of)
        .replace("__UPDATED_AT__", updated_at)
    )
    OUTPUT_PATH.write_text(html, encoding="utf-8")

    summary = ", ".join(
        f"{g['title']}:" + "/".join(f"{s['name']}{s['deltaPct']:+.2f}%" for s in g["series"])
        for g in payload
    )
    print(f"Wrote {OUTPUT_PATH} — {summary}")


if __name__ == "__main__":
    main()
