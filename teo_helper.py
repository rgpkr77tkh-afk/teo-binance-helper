#!/usr/bin/env python3
"""
Teo Binance Helper — PAPER/SIGNAL ONLY.

Purpose:
- use public Binance USD-M Futures market data
- never use API keys
- never place real orders
- scan liquid USDT perpetual altcoins
- shortlist 5 candidates
- check CLOSED H1/M15/M5 structure
- apply pullback/confirmation, Remaining Fuel, RR and anti-chase
- save a human-readable report in reports/
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = "https://fapi.binance.com"
EXCLUDED = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"}

MIN_QUOTE_VOLUME = 10_000_000
BREADTH_TARGET = 50
SHORTLIST_COUNT = 5

TARGET_MOVE = 0.009
MAX_CHASE = 0.0025
TZ = timezone(timedelta(hours=5))


def api(path: str, params: dict | None = None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "teo-binance-helper/1.0"},
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"Binance request failed {path}: {last_error}")


def num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def closed_candles(symbol: str, interval: str, limit: int):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        raw = api("/fapi/v1/klines", params)
        source = "fapi"
    except Exception as primary_error:
        # Official Binance derivatives docs state the DAPI kline endpoint
        # accepts both CM and UM symbols after the CM migration.
        try:
            time.sleep(0.4)
            raw = api(
                "/dapi/v1/klines",
                params,
                base=KLINE_FALLBACK_BASE,
            )
            source = "dapi_fallback"
        except Exception as fallback_error:
            raise RuntimeError(
                f"fapi klines failed: {primary_error}; "
                f"dapi fallback failed: {fallback_error}"
            )
    now_ms = int(time.time() * 1000)

    out = []
    for x in raw:
        if int(x[6]) < now_ms:
            out.append(
                {
                    "open_time": int(x[0]),
                    "o": num(x[1]),
                    "h": num(x[2]),
                    "l": num(x[3]),
                    "c": num(x[4]),
                    "v": num(x[5]),
                    "source": source,
                }
            )
    return out


def ema(values, period):
    if not values:
        return 0.0

    alpha = 2 / (period + 1)
    e = values[0]
    for value in values[1:]:
        e = alpha * value + (1 - alpha) * e
    return e


def trend(candles):
    if len(candles) < 24:
        return "MIXED"

    closes = [x["c"] for x in candles]
    e9 = ema(closes[-30:], 9)
    e21 = ema(closes[-40:], 21)
    momentum = closes[-1] - closes[-4]

    if e9 > e21 and momentum > 0:
        return "UP"
    if e9 < e21 and momentum < 0:
        return "DOWN"
    return "MIXED"


def analyze(symbol: str):
    h1 = closed_candles(symbol, "1h", 50)
    m15 = closed_candles(symbol, "15m", 60)
    m5 = closed_candles(symbol, "5m", 80)

    if min(len(h1), len(m15), len(m5)) < 24:
        return {
            "symbol": symbol,
            "status": "REJECT",
            "reason": "not enough CLOSED candles",
        }

    h1_trend = trend(h1)
    m15_trend = trend(m15)

    if h1_trend == "UP" and m15_trend == "UP":
        side = "LONG"
    elif h1_trend == "DOWN" and m15_trend == "DOWN":
        side = "SHORT"
    else:
        return {
            "symbol": symbol,
            "status": "REJECT",
            "reason": f"H1/M15 conflict {h1_trend}/{m15_trend}",
        }

    closes = [x["c"] for x in m5]
    last = m5[-1]
    prev = m5[-2]

    e9_now = ema(closes[-30:], 9)
    e9_prev = ema(closes[-31:-1], 9)
    recent = m5[-6:-1]

    if side == "LONG":
        pullback = min(x["l"] for x in recent) <= e9_prev
        confirm = (
            last["c"] > last["o"]
            and last["c"] > prev["c"]
            and last["c"] > e9_now
        )
    else:
        pullback = max(x["h"] for x in recent) >= e9_prev
        confirm = (
            last["c"] < last["o"]
            and last["c"] < prev["c"]
            and last["c"] < e9_now
        )

    if not pullback:
        return {
            "symbol": symbol,
            "status": "REJECT",
            "side": side,
            "reason": "no normal M5 pullback/retest",
        }

    if not confirm:
        return {
            "symbol": symbol,
            "status": "REJECT",
            "side": side,
            "reason": "waiting for CLOSED M5 confirmation",
        }

    recent_m15 = m15[-13:-1]
    trigger = last["c"]

    if side == "LONG":
        nearest_level = max(x["h"] for x in recent_m15)
        fuel = (nearest_level - trigger) / trigger
        sl = min(x["l"] for x in m5[-6:]) * (1 - 0.0005)
        risk = (trigger - sl) / trigger
        tp = trigger * (1 + TARGET_MOVE)
    else:
        nearest_level = min(x["l"] for x in recent_m15)
        fuel = (trigger - nearest_level) / trigger
        sl = max(x["h"] for x in m5[-6:]) * (1 + 0.0005)
        risk = (sl - trigger) / trigger
        tp = trigger * (1 - TARGET_MOVE)

    if fuel > 0 and fuel < TARGET_MOVE * 0.8:
        return {
            "symbol": symbol,
            "status": "REJECT",
            "side": side,
            "reason": f"Remaining Fuel only {fuel * 100:.2f}% before nearby level",
        }

    rr = TARGET_MOVE / risk if risk > 0 else 0
    if rr < 1.5:
        return {
            "symbol": symbol,
            "status": "REJECT",
            "side": side,
            "reason": f"structural RR {rr:.2f} < 1.5",
        }

    current = num(
        api("/fapi/v1/ticker/price", {"symbol": symbol}).get("price")
    )
    chase = abs(current - trigger) / trigger

    if chase > MAX_CHASE:
        return {
            "symbol": symbol,
            "status": "REJECT",
            "side": side,
            "reason": f"anti-chase: current price moved {chase * 100:.2f}% from trigger",
        }

    return {
        "symbol": symbol,
        "status": "PASS",
        "side": side,
        "class": "PROFITABLE_TREND",
        "entry": current,
        "sl": sl,
        "tp": tp,
        "margin_usdt": 5.0,
        "leverage": 20,
        "reason": (
            "H1/M15 aligned + M5 pullback/closed confirmation "
            "+ Remaining Fuel/RR/anti-chase passed"
        ),
    }


def main():
    exchange = api("/fapi/v1/exchangeInfo")
    tickers = api("/fapi/v1/ticker/24hr")

    eligible = {
        s["symbol"]
        for s in exchange["symbols"]
        if s.get("status") == "TRADING"
        and s.get("contractType") == "PERPETUAL"
        and s.get("quoteAsset") == "USDT"
        and s.get("symbol") not in EXCLUDED
    }

    rows = []
    for ticker in tickers:
        symbol = ticker.get("symbol")
        if symbol not in eligible:
            continue

        quote = num(ticker.get("quoteVolume"))
        if quote < MIN_QUOTE_VOLUME:
            continue

        change = abs(num(ticker.get("priceChangePercent")))
        high = num(ticker.get("highPrice"))
        low = num(ticker.get("lowPrice"))
        last = num(ticker.get("lastPrice"))
        day_range = ((high - low) / last * 100) if last > 0 else 0

        score = (
            math.log10(max(quote, 1))
            + min(change, 12)
            + 0.35 * min(day_range, 18)
            - max(0, change - 12) * 2
        )

        rows.append(
            {
                "symbol": symbol,
                "quote": quote,
                "change": change,
                "range": day_range,
                "score": score,
            }
        )

    by_liquidity = sorted(rows, key=lambda x: x["quote"], reverse=True)
    breadth = by_liquidity[: min(max(BREADTH_TARGET, 100), len(by_liquidity))]
    scanned = min(BREADTH_TARGET, len(breadth))

    shortlist = sorted(
        breadth,
        key=lambda x: x["score"],
        reverse=True,
    )[:SHORTLIST_COUNT]

    results = []
    for candidate in shortlist:
        try:
            results.append(analyze(candidate["symbol"]))
        except Exception as exc:
            results.append(
                {
                    "symbol": candidate["symbol"],
                    "status": "REJECT",
                    "reason": f"data error: {exc}",
                }
            )

    valid_second_checks = [
        r for r in results
        if not str(r.get("reason", "")).startswith("data error:")
    ]
    raw_signals = [r for r in results if r["status"] == "PASS"]

    if scanned < 50 or len(valid_second_checks) < 3:
        status = "SCAN_INCOMPLETE"
        signals = []
    elif raw_signals:
        status = "SIGNAL_FOUND"
        signals = raw_signals
    else:
        status = "NO_VALID_ENTRY"

    now = datetime.now(TZ).isoformat(timespec="seconds")

    report = {
        "timestamp_qostanay": now,
        "mode": "PAPER_SIGNAL_ONLY",
        "status": status,
        "eligible_liquid_count": len(rows),
        "scanned_symbol_count": scanned,
        "shortlist": [x["symbol"] for x in shortlist],
        "valid_second_check_count": len(valid_second_checks),
        "results": results,
        "signals": signals,
    }

    Path("reports").mkdir(exist_ok=True)
    Path("reports/latest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        "# Teo Binance Helper — latest scan",
        "",
        f"- Time Asia/Qostanay: **{now}**",
        "- Mode: **PAPER / SIGNAL ONLY**",
        f"- Status: **{status}**",
        f"- Liquid eligible symbols: **{len(rows)}**",
        f"- Breadth checked: **{scanned}**",
        f"- Shortlist: **{', '.join(report['shortlist'])}**",
        "",
        "## Decisions",
        "",
    ]

    for result in results:
        extra = ""
        if result["status"] == "PASS":
            extra = (
                f" — {result['side']}"
                f" | Entry {result['entry']:.8g}"
                f" | SL {result['sl']:.8g}"
                f" | TP {result['tp']:.8g}"
                f" | {result['class']}"
            )
        lines.append(
            f"- **{result['symbol']} — {result['status']}**"
            f"{extra}: {result['reason']}"
        )

    lines.extend(
        [
            "",
            "_No Binance API keys. No real orders. Public Futures data only._",
            "",
        ]
    )

    Path("reports/latest.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
