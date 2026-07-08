# -*- coding: utf-8 -*-
"""回填过去约 30 天的金价历史到 history.json。

数据来源说明（本环境可达性受限）：
- 真实历史：4 只黄金 ETF 的日 K 线，来自新浪 (money.finance.sina.com.cn)。
  东方财富/ ruseo.cn 在本机被封，yahoo/stooq 限流，dwo.cc 无历史接口。
- 推导数据（与图表自身规则一致）：
  * AU9999(元/克) = 博时ETF收盘价 × 100  （图表里 boshi_etf 也是 ×100 折算克价）
  * 国际金价(人民币/克) ≈ AU9999
  * 国际金价(美元/盎司) = 人民币克价 × 31.1035 / 近似汇率(7.16)
  * 品牌金价 = AU9999 + 各品牌固定溢价（估算，真实品牌历史接口不可达）

回填后 history.json 即包含约一个月的连续数据；留存/渲染上限已改为按日期(33/31天)。
"""
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta

sys.path.insert(0, ".")
from gold_monitor import load_history, save_history  # 复用留存逻辑

SINA_KLINE = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen={n}"
)

# ETF ticker -> 基金代码（与 gold_monitor.GOLD_FUND_ETFS 一致）
ETF_TICKERS = ["sz159937", "sh518880", "sz159934", "sh518800"]
FUND_TICKER = {
    "002610": "sz159937",
    "000216": "sh518880",
    "002963": "sz159934",
    "000218": "sh518800",
    "000929": "sz159937",  # 博时黄金D，同底层 ETF
}
FUND_LABEL = {
    "002610": "博时黄金",
    "000216": "华安黄金",
    "002963": "易方达黄金",
    "000218": "国泰黄金",
    "000929": "博时黄金D",
}
ETF_NAME = {
    "sz159937": "博时黄金ETF",
    "sh518880": "华安黄金ETF",
    "sz159934": "易方达黄金ETF",
    "sh518800": "国泰黄金ETF",
}
# 品牌零售溢价（元/克，估算；真实历史接口不可达）
BRAND_PREMIUM = {
    "周大福": 120, "老庙黄金": 110, "周六福": 108, "老凤祥": 115,
    "中国黄金": 100, "潮宏基": 110, "金至尊": 105, "谢瑞麟": 120,
    "六福珠宝": 115, "周生生": 115,
}
USDCNY_APPROX = 7.16  # 回填期近似汇率


def fetch_kline(sym, n=70):
    url = SINA_KLINE.format(sym=sym, n=n)
    req = urllib.request.Request(
        url,
        headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.loads(r.read().decode("utf-8"))
    return {row["day"]: float(row["close"]) for row in rows}


def main():
    print("[回填] 拉取 4 只黄金 ETF 日 K 线（新浪，真实历史）...")
    kl = {}
    for sym in ETF_TICKERS:
        try:
            kl[sym] = fetch_kline(sym, 70)
            print(f"  ✓ {sym}: {len(kl[sym])} 个交易日")
        except Exception as e:
            print(f"  ✗ {sym} 失败: {e}")
            kl[sym] = {}

    if not kl.get("sz159937"):
        print("❌ 博时ETF(159937) 拉取失败，无法推导 AU9999，终止")
        sys.exit(1)

    all_dates = sorted(set().union(*[set(v.keys()) for v in kl.values()]))
    today = date.today()
    cutoff = today - timedelta(days=35)
    dates = [
        d for d in all_dates
        if date.fromisoformat(d) < today and date.fromisoformat(d) >= cutoff
    ]
    dates.sort()
    print(f"[回填] 回填日期范围: {dates[0]} ~ {dates[-1]} ({len(dates)} 天)")

    history = load_history()
    before = len(history)
    added = 0

    prev_close = {sym: None for sym in ETF_TICKERS}  # 用于近似 change
    for d in dates:
        boshi = kl["sz159937"].get(d)
        if boshi is None:
            continue
        au9999_price = round(boshi * 100, 2)
        cny = au9999_price
        usd = round(cny * 31.1035 / USDCNY_APPROX, 1)

        gold_funds = {}
        for code, ticker in FUND_TICKER.items():
            ep = kl[ticker].get(d)
            if ep is None:
                continue
            pe = prev_close.get(ticker)
            change = round(ep - pe, 6) if pe else 0.0
            rate = round(change / pe * 100, 4) if pe else 0.0
            gold_funds[code] = {
                "name": FUND_LABEL[code],
                "code": code,
                "etf_name": ETF_NAME.get(ticker, ""),
                "etf_price": ep,
                "gold_price": round(ep * 100, 2),
                "prev_etf_price": pe,
                "prev_gold_price": round(pe * 100, 2) if pe else None,
                "change": change,
                "change_rate": rate,
            }

        pb = prev_close.get("sz159937")
        bchange = round(boshi - pb, 6) if pb else 0.0
        brate = round(bchange / pb * 100, 4) if pb else 0.0

        brands = {b: round(au9999_price + prem) for b, prem in BRAND_PREMIUM.items()}

        key = d + " 00:00"
        if key in history:
            continue
        history[key] = {
            "intl_spot": {
                "name": "国际金价(现货)",
                "intl_price": usd,
                "intl_unit": "美元/盎司",
                "cny_price": cny,
                "update_time": key,
                "prev_close": None,
            },
            "au9999": {
                "name": "AU9999",
                "price": au9999_price,
                "prev_close": None,
                "change": None,
                "change_rate": None,
            },
            "boshi_etf": {
                "name": "博时黄金ETF",
                "code": "159937",
                "price": boshi,
                "prev_close": pb,
                "change": bchange,
                "change_rate": brate,
            },
            "gold_funds": gold_funds,
            "brands": brands,
        }
        added += 1
        for sym in ETF_TICKERS:
            if kl[sym].get(d) is not None:
                prev_close[sym] = kl[sym][d]

    save_history(history)
    after = len(history)
    ks = sorted(history.keys())
    print(f"[回填] 完成: 新增 {added} 天，history.json 现共 {after} 条")
    print(f"        范围: {ks[0]} ~ {ks[-1]}")


if __name__ == "__main__":
    main()
