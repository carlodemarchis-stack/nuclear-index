"""Build the AGWAS Nuclear Index from Yahoo Finance daily closes.

    python3 tools/build.py            -> data/index.json

Two indices over the same constituents, both in US dollars, base 100 on base_date:
  ew  equal weight, rebalanced daily (mean of the day's USD returns)
  cw  market-cap weight (shares held constant x USD price, weights from the previous close)

The calendar is the union of every constituent's trading dates (exchange-local dates).
A market that is shut on a date carries its last close forward, so it adds a 0% return
that day. A stock counts from its first close on or after base_date (or its `since`).
"""
import datetime as dt
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF = json.loads((ROOT / "constituents.json").read_text())
UA = {"User-Agent": "Mozilla/5.0"}
FX = {"GBp": ("GBPUSD=X", 0.01), "GBP": ("GBPUSD=X", 1), "CAD": ("CADUSD=X", 1),
      "EUR": ("EURUSD=X", 1), "KRW": ("KRWUSD=X", 1), "AUD": ("AUDUSD=X", 1)}


def chart(symbol, start):
    p1 = int(dt.datetime.combine(start, dt.time()).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={int(time.time())}&interval=1d")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                res = json.load(r)["chart"]["result"][0]
            break
        except Exception as e:  # Yahoo throttles bursts; back off and retry
            if attempt == 3:
                raise SystemExit(f"{symbol}: {e}")
            time.sleep(3 * (attempt + 1))
    meta = res["meta"]
    off = meta.get("gmtoffset", 0)

    def day(t):
        return dt.datetime.utcfromtimestamp(t + off).date().isoformat()

    closes = {}
    for t, c in zip(res.get("timestamp", []), res["indicators"]["quote"][0]["close"]):
        if c is not None:
            closes[day(t)] = c
    # Yahoo sometimes leaves the latest daily bar empty (Korea does it every day) while
    # the quote header already holds that session's close.
    ts = res.get("timestamp", [])
    if ts and day(ts[-1]) not in closes and meta.get("regularMarketTime") \
            and day(meta["regularMarketTime"]) == day(ts[-1]):
        closes[day(ts[-1])] = meta["regularMarketPrice"]
    return res["meta"]["currency"], closes


def ffill(series, dates):
    """Value on or before each date (None before the first one)."""
    keys = sorted(series)
    out, j, last = [], 0, None
    for d in dates:
        while j < len(keys) and keys[j] <= d:
            last = series[keys[j]]
            j += 1
        out.append(last)
    return out


def pct(a, b):
    return None if a in (None, 0) or b is None else round((b / a - 1) * 100, 2)


def main():
    base = CONF["base_date"]
    start = dt.date.fromisoformat(base) - dt.timedelta(days=12)

    raw = {}
    for c in CONF["constituents"]:
        raw[c["yahoo"]] = chart(c["yahoo"], start)
        time.sleep(0.4)
    fx = {}
    for cur in {cur for cur, _ in raw.values()} - {"USD"}:
        fx[cur] = chart(FX[cur][0], start)[1]
        time.sleep(0.4)

    dates = sorted({d for _, cl in raw.values() for d in cl if d >= base})
    if not dates or dates[0] != base:
        raise SystemExit(f"no trading on base date {base}")
    # A row that only the Korean/Australian session has reached yet would show a half-day.
    # The Action runs after the US close, so every market has its row by then.

    stocks = []
    for c in CONF["constituents"]:
        cur, closes = raw[c["yahoo"]]
        since = max(base, c.get("since", base))
        first = min((d for d in closes if d >= since), default=None)
        local = ffill(closes, dates)
        if cur == "USD":
            rate = [1.0] * len(dates)
        else:
            rate = [None if r is None else r * FX[cur][1] for r in ffill(fx[cur], dates)]
        usd = [None if (first is None or d < first or p is None or r is None) else p * r
               for d, p, r in zip(dates, local, rate)]
        stocks.append({"c": c, "cur": cur, "closes": closes, "local": local, "usd": usd,
                       "first": first})

    ew, cw = [100.0], [100.0]
    for t in range(1, len(dates)):
        rets, caps = [], []
        for s in stocks:
            a, b = s["usd"][t - 1], s["usd"][t]
            if a and b:
                rets.append(b / a - 1)
                caps.append(a * s["c"]["shares"])
        ew.append(ew[-1] * (1 + sum(rets) / len(rets)) if rets else ew[-1])
        cw.append(cw[-1] * (sum(k * (1 + r) for k, r in zip(caps, rets)) / sum(caps))
                  if caps else cw[-1])
        # Gate: a one-day jump this size is a data error (split, bad tick), not a market.
        for name, s in (("ew", ew), ("cw", cw)):
            if abs(s[-1] / s[-2] - 1) > 0.2:
                raise SystemExit(f"{name} moved {s[-1] / s[-2] - 1:+.1%} on {dates[t]}: check data")

    last = len(dates) - 1
    as_of = dates[last]
    stale = [s["c"]["ticker"] for s in stocks
             if max(s["closes"]) < (dt.date.fromisoformat(as_of) - dt.timedelta(days=6)).isoformat()]
    if stale:
        raise SystemExit(f"no recent close for {stale}")

    def ago(days):
        """Index of the last date on or before as_of minus `days`."""
        cut = (dt.date.fromisoformat(as_of) - dt.timedelta(days=days)).isoformat()
        return max(i for i, d in enumerate(dates) if d <= cut) if dates[0] <= cut else 0

    i1m, iytd = ago(30), max([i for i, d in enumerate(dates) if d <= f"{as_of[:4]}-01-01"] or [0])
    total_cap = sum(s["usd"][last] * s["c"]["shares"] for s in stocks if s["usd"][last])

    out_stocks = []
    for s in stocks:
        u, c = s["usd"], s["c"]
        j0 = next(i for i, v in enumerate(u) if v)
        cap = u[last] * c["shares"]
        last_local_date = max(s["closes"])
        out_stocks.append({
            "ticker": c["ticker"], "yahoo": c["yahoo"], "name": c["name"],
            "country": c["country"], "industry": c["industry"], "currency": s["cur"],
            "source": c["source"], "note": c.get("note"),
            "price": round(s["closes"][last_local_date], 4), "price_date": last_local_date,
            "since": dates[j0],
            "cap_usd": round(cap), "weight_cw": round(cap / total_cap * 100, 2),
            "chg_1d": pct(u[last - 1], u[last]),
            "chg_1m": pct(u[max(i1m, j0)], u[last]),
            "chg_ytd": pct(u[max(iytd, j0)], u[last]),
            "chg_all": pct(u[j0], u[last]),
            "series": [None if v is None else round(v / u[j0] * 100, 2) for v in u],
        })

    def summary(s):
        return {"level": round(s[last], 2), "chg_1d": pct(s[last - 1], s[last]),
                "chg_1m": pct(s[i1m], s[last]), "chg_ytd": pct(s[iytd], s[last]),
                "chg_all": pct(s[0], s[last]), "high": round(max(s), 2),
                "high_date": dates[s.index(max(s))], "low": round(min(s), 2),
                "low_date": dates[s.index(min(s))]}

    data = {
        "name": CONF["name"], "base_date": base, "as_of": as_of,
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "list_source": CONF["list_source"], "list_snapshot": CONF["list_snapshot"],
        "shares_note": CONF["shares_note"],
        "dates": dates,
        "ew": [round(v, 2) for v in ew], "cw": [round(v, 2) for v in cw],
        "summary": {"ew": summary(ew), "cw": summary(cw)},
        "constituents": out_stocks,
    }
    (ROOT / "data" / "index.json").write_text(json.dumps(data, separators=(",", ":")))
    print(f"{as_of}: EW {ew[-1]:.2f}  CW {cw[-1]:.2f}  ({len(dates)} days, {len(stocks)} stocks)")


if __name__ == "__main__":
    sys.exit(main())
