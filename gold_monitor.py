#!/usr/bin/env python3
"""
金价监控脚本（每小时版）
- 国内金价: AU9999 (浙商/工银积存金代理) + 博时黄金ETF
- 支付宝黄金基金: 通过底层ETF实时行情换算克价（现价）
- 门面金价: 周大福、老庙、周六福 等品牌零售价
- 交易日 9:00-15:00 每小时微信推送，晚上/周末不推送
- 数据来源: 东方财富 + dwo.cc + ruseo.cn

用法:
  python gold_monitor.py           # 交易时段运行监控
  python gold_monitor.py --force   # 强制推送
  python gold_monitor.py --test    # 测试推送
"""

import json
import os
import sys
import time as _time
from datetime import datetime, time, timezone, timedelta
from pathlib import Path

# 修复 Windows 控制台 GBK 编码问题
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

import requests

# ─── 路径 ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
HISTORY_PATH = SCRIPT_DIR / "history.json"

# 统一使用北京时间（UTC+8，无夏令时）。服务端(GitHub Actions)与本地(WorkBuddy)
# 都用它生成 ts_key，避免两边时区不一致导致 history.json 时间戳错乱/顺序颠倒。
BEIJING_TZ = timezone(timedelta(hours=8))

# ─── API ──────────────────────────────────────────────
API_EASTMONEY = "https://push2.eastmoney.com/api/qt/stock/get"
API_BRAND_GOLD = "https://api.ruseo.cn/api/goldprice"
API_BRAND_BACKUP = "https://openapi.dwo.cc/api/jinjia"

# ─── 推送 ─────────────────────────────────────────────
WXPUSHER_API = "https://wxpusher.zjiecode.com/api/send/message/"
PUSHPLUS_API = "http://www.pushplus.plus/send"
SERVERCHAN_API = "https://sc3.ft07.com/send"

# ─── 交易日历 ─────────────────────────────────────────
TRADING_DAY_START = time(9, 0)
TRADING_DAY_END = time(15, 0)


def load_config():
    if not CONFIG_PATH.exists():
        print(f"[ERROR] 配置文件不存在: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_history():
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(history):
    """保留最近约 33 天数据（覆盖一个月视图 + 余量；支持 10 分钟密集采集）

    注意：history.json 必须按时间戳 key 升序保存——服务端(GitHub Actions)与本地
    (WorkBuddy) 两边都往这里写数据，任意一侧落盘前都已按 key 排序，合并/变基后才不会乱序。
    """
    from datetime import datetime, timedelta
    now = datetime.now(BEIJING_TZ)
    cutoff = now - timedelta(days=33)
    trimmed = {}
    for k, v in history.items():
        try:
            kt = datetime.strptime(k, "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING_TZ)
        except Exception:
            trimmed[k] = v
            continue
        if kt >= cutoff:
            trimmed[k] = v
    trimmed = dict(sorted(trimmed.items()))  # 始终按时间先后排序
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)
    # 同时保存最新一条快照，供图表页加载时刷新
    save_latest_snapshot(history)


LATEST_PATH = SCRIPT_DIR / "latest.json"


def save_latest_snapshot(history):
    """保存最新一条数据到 latest.json，供静态图表页加载时刷新"""
    if not history:
        return
    latest_key = sorted(history.keys())[-1]
    latest_data = {latest_key: history[latest_key]}
    try:
        with open(LATEST_PATH, "w", encoding="utf-8") as f:
            json.dump(latest_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [latest.json] 保存失败: {e}")


SILENT_START = time(21, 0)
SILENT_END = time(8, 30)
SILENT_THRESHOLD = 10  # 静默时段大幅波动阈值（元）

def is_trading_time(now=None):
    """判断当前是否在交易时段（周一至周五 9:00-15:00）"""
    if now is None:
        now = datetime.now()
    if now.weekday() >= 5:  # 周六/周日
        return False
    t = now.time()
    return TRADING_DAY_START <= t <= TRADING_DAY_END


def is_silent_hours(now=None):
    """判断是否在静默时段（每日 21:00-次日 08:30）"""
    if now is None:
        now = datetime.now()
    t = now.time()
    return t >= SILENT_START or t <= SILENT_END


# ═══════════════════════════════════════════════════════
#  数据获取
# ═══════════════════════════════════════════════════════

def _em_fetch(secid, fields="f43,f169,f170,f60"):
    """通用东方财富行情获取（带重试）"""
    for attempt in range(3):
        try:
            r = requests.get(
                API_EASTMONEY,
                params={"secid": secid, "fields": fields},
                headers={"Referer": "https://quote.eastmoney.com"},
                timeout=10,
            )
            d = r.json()
            if d.get("rc") != 0 or d.get("data") is None:
                return None
            return d["data"]
        except Exception as e:
            if attempt < 2:
                _time.sleep(0.5)
                continue
            print(f"  [ERR] 东方财富 {secid}: {e}")
            return None


def fetch_au9999():
    """获取 AU9999 现货价格 —— 优先用银行金条价（ruseo），备用国际金价"""
    # 主源: ruseo.cn 银行金条价（最接近 AU9999）
    try:
        r = requests.get(API_BRAND_GOLD, timeout=15)
        data = r.json()
        if data.get("code") == 0:
            bars = data["data"].get("bank_gold_bar_price", [])
            if bars:
                prices = [float(b["price"]) for b in bars if b.get("price")]
                if prices:
                    avg = sum(prices) / len(prices)
                    return {
                        "name": "AU9999",
                        "price": round(avg, 2),
                        "prev_close": None,
                        "change": None,
                        "change_rate": None,
                    }
    except Exception:
        pass

    # 备用: 东方财富
    data = _em_fetch("118.AU9999", "f43,f60,f169,f170,f57,f58")
    if data:
        price = float(data.get("f43", 0)) / 100
        prev_close = float(data.get("f60", 0)) / 100
        change = float(data.get("f169", 0)) / 100
        change_rate = float(data.get("f170", 0)) / 100
        return {
            "name": "AU9999",
            "price": price,
            "prev_close": prev_close,
            "change": change,
            "change_rate": change_rate,
        }
    return None


def fetch_boshi_etf():
    """获取博时黄金ETF (159937) 实时行情 —— 新浪 + 东方财富备用"""
    # 主源: 新浪
    try:
        r = requests.get(
            "https://hq.sinajs.cn/list=sz159937",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10,
        )
        parts = r.text.split('"')
        if len(parts) >= 2:
            fields = parts[1].split(",")
            if len(fields) >= 5:
                price = float(fields[3])
                prev_close = float(fields[2])
                return {
                    "name": "博时黄金ETF",
                    "code": "159937",
                    "price": price,
                    "prev_close": prev_close,
                    "change": price - prev_close,
                    "change_rate": (price - prev_close) / prev_close * 100 if prev_close else 0,
                }
    except Exception:
        pass

    # 备用: 东方财富
    data = _em_fetch("0.159937", "f43,f60,f169,f170,f57,f58")
    if data:
        price = float(data.get("f43", 0)) / 1000
        prev_close = float(data.get("f60", 0)) / 1000
        change = float(data.get("f169", 0)) / 1000
        change_rate = float(data.get("f170", 0)) / 100
        return {
            "name": "博时黄金ETF",
            "code": "159937",
            "price": price,
            "prev_close": prev_close,
            "change": change,
            "change_rate": change_rate,
        }
    return None


# 黄金基金 → 底层ETF新浪行情代码
GOLD_FUND_ETFS = {
    "002610": {"ticker": "sz159937", "label": "博时黄金", "etf_name": "博时黄金ETF"},
    "000216": {"ticker": "sh518880", "label": "华安黄金", "etf_name": "华安黄金ETF"},
    "002963": {"ticker": "sz159934", "label": "易方达黄金", "etf_name": "易方达黄金ETF"},
    "000218": {"ticker": "sh518800", "label": "国泰黄金", "etf_name": "国泰黄金ETF"},
    "000929": {"ticker": "sz159937", "label": "博时黄金D", "etf_name": "博时黄金ETF"},
}

def fetch_gold_funds():
    """通过新浪ETF实时行情获取黄金基金折合克价（现价）"""
    tickers = ",".join(info["ticker"] for info in GOLD_FUND_ETFS.values())
    try:
        r = requests.get(
            f"https://hq.sinajs.cn/list={tickers}",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=15,
        )
        lines = r.text.strip().split("\n")
        raw = {}
        for line in lines:
            if not line.strip():
                continue
            parts = line.split('"')
            ticker = parts[0].split("_")[-1].rstrip("=")
            fields = parts[1].split(",")
            if len(fields) < 5:
                continue
            raw[ticker] = {
                "name": fields[0],
                "open": float(fields[1]),
                "prev_close": float(fields[2]),
                "price": float(fields[3]),           # 现价
                "high": float(fields[4]),
                "low": float(fields[5]),
            }

        results = {}
        for code, info in GOLD_FUND_ETFS.items():
            ticker = info["ticker"]
            if ticker not in raw:
                continue
            d = raw[ticker]
            etf_price = d["price"]
            prev_close = d["prev_close"]
            change = etf_price - prev_close
            change_rate = (change / prev_close * 100) if prev_close else 0

            # 每份ETF ≈ 0.01克黄金 → 折合克价 = ETF单价 × 100
            gold_price = round(etf_price * 100, 2)
            prev_gold = round(prev_close * 100, 2)

            results[code] = {
                "name": info["label"],
                "code": code,
                "etf_name": info["etf_name"],
                "etf_price": etf_price,
                "gold_price": gold_price,      # ★ 折合克价 — 现价
                "prev_etf_price": prev_close,
                "prev_gold_price": prev_gold,
                "change": change,
                "change_rate": change_rate,
            }
        return results if results else None
    except Exception as e:
        print(f"  [ERR] 黄金基金: {e}")
        return None


def fetch_intl_spot():
    """获取国际现货金价（美元/盎司 + 人民币/克换算）
    主源：东方财富 XAU（伦敦金/美元）
    辅源：dwo.cc 用于人民币/克换算，以及美元价备用
    """
    result = {
        "name": "国际黄金现货",
        "intl_price": 0.0,
        "intl_unit": "美元/盎司",
        "cny_price": 0.0,
        "update_time": "",
        "prev_close": None,
    }

    # 1. 先获取东方财富 XAU（更准确的美元/盎司）
    try:
        from datetime import datetime as _dt
        em_fields = "f43,f44,f45,f46,f47,f48,f57,f58,f60,f107,f170"
        em_url = f"https://push2.eastmoney.com/api/qt/stock/get?secid=122.XAU&fields={em_fields}"
        r = requests.get(em_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        em_data = r.json()
        em = em_data.get("data", {})
        if em.get("f43") is not None:
            result["intl_price"] = round(float(em.get("f43", 0)) / 100, 2)
            result["prev_close"] = round(float(em.get("f60", 0)) / 100, 2) if em.get("f60") else None
            result["update_time"] = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(f"  [WARN] 东方财富XAU: {e}")

    # 2. 从 dwo.cc 获取人民币/克换算价，以及备用美元价
    try:
        r = requests.get(API_BRAND_BACKUP, timeout=15)
        data = r.json()
        if data.get("code") == 200:
            futures = data["data"].get("futures", [])
            for f in futures:
                if "黄金" in f.get("name", ""):
                    cny_price = float(f.get("convert_price", 0))
                    if cny_price > 0:
                        result["cny_price"] = cny_price
                    # 如果东方财富没有拿到，才用 dwo.cc 的美元价
                    if result["intl_price"] <= 0:
                        result["intl_price"] = float(f.get("trade_price", 0))
                    result["update_time"] = f.get("update_time", result["update_time"])
                    break
    except Exception as e:
        print(f"  [WARN] dwo.cc国际金价: {e}")

    if result["intl_price"] > 0 and result["cny_price"] > 0:
        return result
    return None


def fetch_brand_gold():
    """获取品牌金店金价"""
    # 主源: ruseo.cn
    try:
        r = requests.get(API_BRAND_GOLD, timeout=15)
        data = r.json()
        if data.get("code") == 0:
            items = data["data"].get("precious_metal_price", [])
            result = {}
            for b in items:
                brand = b.get("brand", "")
                gp = b.get("gold_price", "-")
                if gp != "-":
                    result[brand] = float(gp)
            if result:
                return result
    except Exception as e:
        print(f"  [WARN] ruseo: {e}")

    # 备用: dwo.cc
    try:
        r = requests.get(API_BRAND_BACKUP, timeout=15)
        data = r.json()
        if data.get("code") == 200:
            shops = data["data"].get("shops", [])
            result = {}
            for s in shops:
                name = s.get("name", "")
                price = s.get("retail_price")
                if price and price != "暂无":
                    result[name] = float(price)
            if result:
                return result
    except Exception as e:
        print(f"  [ERR] dwo: {e}")

    return None


# ═══════════════════════════════════════════════════════
#  通知
# ═══════════════════════════════════════════════════════

def send_notification(config, title, content):
    cfg = config.get("notification", {})
    ntype = cfg.get("type", "wxpusher")

    if ntype == "wxpusher":
        app_token = cfg.get("wxpusher_app_token", "")
        uids = cfg.get("wxpusher_uids", [])
        if not app_token or not uids:
            print("[ERROR] wxpusher_app_token 或 wxpusher_uids 未配置")
            return False
        content_type = cfg.get("wxpusher_content_type", 2)  # 2=HTML
        try:
            r = requests.post(
                WXPUSHER_API,
                json={
                    "appToken": app_token,
                    "content": content,
                    "contentType": content_type,
                    "uids": uids,
                    "summary": title,
                },
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            result = r.json()
            if result.get("code") == 1000:
                print("[OK] WxPusher 推送成功")
                return True
            print(f"[ERROR] WxPusher: {result}")
            return False
        except Exception as e:
            print(f"[ERROR] WxPusher异常: {e}")
            return False

    elif ntype == "pushplus":
        token = cfg.get("pushplus_token", "")
        if not token:
            print("[ERROR] pushplus_token 未配置")
            return False
        try:
            r = requests.post(
                PUSHPLUS_API,
                json={"token": token, "title": title, "content": content, "template": "html"},
                timeout=15,
            )
            result = r.json()
            if result.get("code") == 200:
                print("[OK] PushPlus 推送成功")
                return True
            print(f"[ERROR] PushPlus: {result}")
            return False
        except Exception as e:
            print(f"[ERROR] PushPlus异常: {e}")
            return False

    elif ntype == "serverchan":
        send_key = cfg.get("serverchan_key", "")
        if not send_key:
            print("[ERROR] serverchan_key 未配置")
            return False
        try:
            r = requests.post(
                f"{SERVERCHAN_API}/{send_key}",
                data={"title": title, "desp": content},
                timeout=15,
            )
            result = r.json()
            if result.get("code") == 0:
                print("[OK] Server酱 推送成功")
                return True
            print(f"[ERROR] Server酱: {result}")
            return False
        except Exception as e:
            print(f"[ERROR] Server酱异常: {e}")
            return False

    print(f"[ERROR] 未知通知类型: {ntype}")
    return False


# ═══════════════════════════════════════════════════════
#  格式化 & 通知构建
# ═══════════════════════════════════════════════════════

def _arrow(val, unit=""):
    """涨跌箭头"""
    if val is None:
        return "—"
    if val > 0:
        return f"📈 +{val:.2f}{unit}"
    if val < 0:
        return f"📉 {val:.2f}{unit}"
    return f"➡️ 0.00{unit}"


def _color_span(val, fmt=".2f"):
    """带颜色的涨跌 span"""
    if val is None or val == 0:
        return f'<span style="color:#666">{val:{fmt}}' if val else '<span style="color:#666">0.00'
    color = "#d32f2f" if val > 0 else "#388e3c"
    sign = "+" if val > 0 else ""
    return f'<span style="color:{color};font-weight:bold">{sign}{val:{fmt}}</span>'


def _product_row(name, price, prev_price=None, unit="元/克", is_nav=False):
    """构建产品行"""
    now_str = f"{price:.4f}" if is_nav else f"{price:.2f}"
    diff = None
    if prev_price is not None:
        diff = price - prev_price
    diff_str = _arrow(diff, f" {unit}") if diff is not None else "—"
    return (
        f"<tr>"
        f"<td><b>{name}</b></td>"
        f"<td style='font-weight:bold'>{now_str} {unit}</td>"
        f"<td>{diff_str}</td>"
        f"</tr>"
    )


def build_notification(au9999, boshi_etf, gold_funds, intl_spot, brand_prices,
                       prev_au, prev_etf, prev_funds, prev_intl, prev_brands,
                       selected_brands, is_test=False):
    """构建 HTML 通知 — 现代简约风格"""
    now = datetime.now()
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    prefix = "[测试] " if is_test else ""

    def _trend(val, fmt=".2f", unit=""):
        """涨跌标签"""
        if val is None:
            return '<span style="color:#999">—</span>'
        if val > 0:
            return f'<span style="color:#d32f2f">↑ {val:+{fmt}}{unit}</span>'
        if val < 0:
            return f'<span style="color:#388e3c">↓ {val:{fmt}}{unit}</span>'
        return f'<span style="color:#999">→ 0.00{unit}</span>'

    def _item_row(label, price, prev, fmt=".2f", unit="元/克"):
        """单行数据项"""
        diff = price - prev if prev is not None else None
        trend_html = _trend(diff, fmt, unit) if diff is not None else f'<span style="color:#ccc">·</span>'
        price_str = f"{price:{fmt}}" if isinstance(price, float) else str(price)
        return (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:8px 0;border-bottom:1px solid #f0ede6">'
            f'<span style="color:#5a4e3c;font-size:14px">{label}</span>'
            f'<span style="font-weight:600;color:#2d2416;font-size:14px;font-variant-numeric:tabular-nums">'
            f'{price_str}{unit}</span>'
            f'<span style="font-size:12px;min-width:60px;text-align:right">{trend_html}</span>'
            f'</div>'
        )

    lines = []

    # ── 外层容器 ──
    lines.append(
        '<div style="max-width:420px;margin:0 auto;'
        'background:linear-gradient(180deg,#fdfbf7 0%,#f7f3ea 100%);'
        'border-radius:16px;overflow:hidden;'
        'box-shadow:0 2px 16px rgba(0,0,0,.06);'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'PingFang SC\',sans-serif">'
    )

    # ── 头部 ──
    lines.append(
        f'<div style="padding:16px 16px 12px;border-bottom:1px solid #f0ede6">'
    )
    lines.append(
        f'<div style="font-size:15px;font-weight:500;color:#8b7355">'
        f'金价播报</div>'
    )
    lines.append(
        f'<div style="font-size:12px;margin-top:4px;color:#c4b99a">'
        f'{now.strftime("%m/%d")} {weekday_cn[now.weekday()]} · {now.hour:02d}:00'
        f'</div>'
    )
    lines.append('</div>')  # end header

    # ── 内容区 ──
    lines.append('<div style="padding:12px 16px">')

    # ═══ 国际金价 ═══
    if intl_spot:
        lines.append(
            '<div style="background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:10px;'
            'box-shadow:0 1px 4px rgba(0,0,0,.04)">'
        )
        lines.append(
            '<div style="font-size:13px;color:#b8860b;font-weight:600;margin-bottom:10px">'
            '🌍 国际金价</div>'
        )
        intl_price = intl_spot["intl_price"]
        cny_price = intl_spot["cny_price"]
        prev_cny = prev_intl.get("cny_price") if prev_intl else None
        lines.append(_item_row("伦敦金现", intl_price, None, ".0f", " 美元/盎司"))
        lines[-4] = lines[-4].replace('border-bottom:1px solid #f0ede6', 'border-bottom:none')
        lines.append(_item_row("折合人民币", cny_price, prev_cny))
        if intl_spot.get("update_time"):
            lines.append(
                f'<div style="font-size:11px;color:#bbb;margin-top:6px;text-align:right">'
                f'{intl_spot["update_time"]}</div>'
            )
        lines.append('</div>')

    # ═══ 投资金 ═══
    lines.append(
        '<div style="background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:10px;'
        'box-shadow:0 1px 4px rgba(0,0,0,.04)">'
    )
    lines.append(
        '<div style="font-size:13px;color:#b8860b;font-weight:600;margin-bottom:10px">'
        '📊 积存金 · ETF</div>'
    )
    if au9999:
        prev = prev_au.get("price") if prev_au else None
        lines.append(_item_row("AU9999 现货", au9999["price"], prev))
        lines.append(
            '<div style="font-size:11px;color:#c4b99a;padding:2px 0 6px">'
            '  浙商/工银积存金参考价</div>'
        )
    if boshi_etf:
        prev = prev_etf.get("price") if prev_etf else None
        etf_gold_price = boshi_etf["price"] * 100
        lines.append(_item_row("博时黄金ETF", etf_gold_price, prev * 100 if prev else None))
        lines.append(
            f'<div style="font-size:11px;color:#c4b99a;padding:2px 0 6px">'
            f'  ETF 现价 {boshi_etf["price"]:.4f} 元/份 · 折合 ≈{etf_gold_price:.0f} 元/克</div>'
        )
    if not au9999 and not boshi_etf:
        lines.append('<div style="color:#999;font-size:13px;padding:8px 0">数据获取中...</div>')
    lines.append('</div>')

    # ═══ 支付宝黄金基金 ═══
    if gold_funds:
        lines.append(
            '<div style="background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:10px;'
            'box-shadow:0 1px 4px rgba(0,0,0,.04)">'
        )
        lines.append(
            '<div style="font-size:13px;color:#b8860b;font-weight:600;margin-bottom:10px">'
            '📱 黄金基金</div>'
        )
        lines.append(
            '<div style="font-size:11px;color:#c4b99a;padding:0 0 8px">'
            '  折合克价 = 底层ETF现价 × 100（每份≈0.01克）</div>'
        )

        # 按折合克价排序
        fund_list = []
        for code, f in gold_funds.items():
            prev = prev_funds.get(code, {}).get("gold_price") if prev_funds else None
            fund_list.append((code, f, prev))
        fund_list.sort(key=lambda x: x[1]["gold_price"], reverse=True)

        for i, (code, f, prev_gold) in enumerate(fund_list):
            border = '' if i == len(fund_list) - 1 else 'border-bottom:1px solid #f0ede6;'
            diff = f["gold_price"] - prev_gold if prev_gold else None
            trend_html = _trend(diff, ".2f", "") if diff is not None else f'<span style="color:#ccc">·</span>'
            lines.append(
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:8px 0;{border}">'
                f'<span style="color:#5a4e3c;font-size:14px">{f["name"]}</span>'
                f'<span style="font-weight:600;color:#2d2416;font-size:14px">'
                f'{f["gold_price"]:.2f} 元/克</span>'
                f'<span style="font-size:12px;min-width:50px;text-align:right">{trend_html}</span>'
                f'</div>'
            )
        lines.append('</div>')

    # ═══ 门面金价 ═══
    lines.append(
        '<div style="background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:10px;'
        'box-shadow:0 1px 4px rgba(0,0,0,.04)">'
    )
    lines.append(
        '<div style="font-size:13px;color:#b8860b;font-weight:600;margin-bottom:10px">'
        '🏪 品牌金店</div>'
    )
    if brand_prices:
        for i, b in enumerate(selected_brands):
            if b in brand_prices:
                tp = brand_prices[b]
                yp = prev_brands.get(b) if prev_brands else None
                diff = tp - yp if yp else None
                trend_html = _trend(diff, ".0f", "") if diff is not None else f'<span style="color:#ccc">·</span>'
                kwargs = {}
                if i == len([x for x in selected_brands if x in brand_prices]) - 1:
                    kwargs = {}
                border = '' if i == len(selected_brands) - 1 else 'border-bottom:1px solid #f0ede6;'
                lines.append(
                    f'<div style="display:flex;justify-content:space-between;align-items:center;'
                    f'padding:8px 0;{border}">'
                    f'<span style="color:#5a4e3c;font-size:14px">{b}</span>'
                    f'<span style="font-weight:600;color:#2d2416;font-size:14px">'
                    f'{tp:.0f} 元/克</span>'
                    f'<span style="font-size:12px;min-width:40px;text-align:right">{trend_html}</span>'
                    f'</div>'
                )
    else:
        lines.append('<div style="color:#999;font-size:13px;padding:8px 0">获取失败</div>')
    lines.append('</div>')

    lines.append('</div>')  # end content

    # ── K线图链接 ──
    chart_url = os.environ.get("CHART_URL", "")
    if not chart_url:
        # 尝试自动推断 GitHub Pages URL
        try:
            import subprocess
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=str(SCRIPT_DIR), capture_output=True, text=True, timeout=5
            )
            remote = result.stdout.strip()
            if "github.com" in remote:
                if remote.startswith("git@"):
                    repo = remote.split("github.com:")[1].replace(".git", "")
                else:
                    repo = remote.split("github.com/")[1].replace(".git", "")
                parts = repo.split("/")
                if len(parts) == 2:
                    chart_url = f"https://{parts[0]}.github.io/{parts[1]}/"
        except Exception:
            pass

    if chart_url:
        lines.append(
            '<div style="padding:8px 16px 0;text-align:center">'
            f'<a href="{chart_url}" style="display:inline-block;padding:8px 20px;'
            f'background:linear-gradient(135deg,#d4af37,#b8942e);color:#fff;'
            f'border-radius:20px;font-size:13px;text-decoration:none;font-weight:500;'
            f'box-shadow:0 2px 8px rgba(212,175,55,0.3)">'
            f'📈 查看一周走势图</a>'
            '</div>'
        )

    # ── 底部 ──
    lines.append(
        '<div style="padding:10px 16px 14px;text-align:center;font-size:11px;color:#c4b99a">'
        f'数据来源 东方财富 · dwo.cc · ruseo.cn'
        f'  ·  下一报 {_next_hour(now)}'
        '</div>'
    )

    lines.append('</div>')  # end outer
    return "\n".join(lines)


def _next_hour(now):
    """下一报时点"""
    h = now.hour + 1
    if h > 15:
        return "明日 9:00"
    if h == 12:
        return "13:00"
    return f"{h:02d}:00"


# ═══════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════

def generate_chart_html(output_path=None):
    """从 history.json 生成交互式 K 线图 HTML。
    
    返回生成的 HTML 文件路径。
    """
    import json as _json
    from datetime import datetime as _dt
    
    history = load_history()
    if not history:
        print("  [图表] 无历史数据，跳过生成")
        return None
    
    # 取最近 31 天数据（按日期窗口，而非固定条数）→ 展示完整一个月
    from datetime import datetime, timedelta
    now = datetime.now()
    cutoff = now - timedelta(days=31)

    def _in_window(k):
        try:
            return datetime.strptime(k, "%Y-%m-%d %H:%M") >= cutoff
        except Exception:
            return True

    all_keys = sorted(history.keys())
    recent_keys = [k for k in all_keys if _in_window(k)]
    if not recent_keys:
        recent_keys = all_keys[-50:]
    recent_data = {k: history[k] for k in recent_keys}
    
    # 读取模板
    template_path = SCRIPT_DIR / "chart_template.html"
    if not template_path.exists():
        print(f"  [图表] 模板文件不存在: {template_path}")
        return None
    
    template = template_path.read_text(encoding="utf-8")
    
    # 注入数据
    data_json = _json.dumps(recent_data, ensure_ascii=False, indent=2)
    gen_time = _dt.now().strftime("%Y-%m-%d %H:%M")
    
    html = template.replace("__DATA_PLACEHOLDER__", data_json)
    html = html.replace("__GEN_TIME__", gen_time)
    
    # 写入输出
    if output_path is None:
        output_path = SCRIPT_DIR / "chart_output.html"
    else:
        output_path = Path(output_path)
    
    output_path.write_text(html, encoding="utf-8")
    print(f"  [图表] 已生成: {output_path}")
    return str(output_path)


def deploy_chart_to_gh_pages(html_path):
    """将 K 线图 HTML 部署到 GitHub Pages (gh-pages 分支)。
    
    通过写入文件到本地，然后推送到 gh-pages 分支实现。
    返回公开访问 URL。
    """
    import subprocess
    import os
    from datetime import datetime as _dt
    
    html_file = Path(html_path)
    if not html_file.exists():
        print(f"  [部署] 文件不存在: {html_path}")
        return None

    # 防御：生成文件可能位于仓库内且曾被 gh-pages 跟踪，
    # 后续的 `git checkout gh-pages` 会把它覆盖成陈旧版本，
    # 导致部署出去的永远是旧图表。先复制到仓库外的临时文件，
    # 分支切换后再用它覆盖 index.html。
    import tempfile as _tempfile
    import shutil as _shutil
    _tmpf = _tempfile.NamedTemporaryFile(delete=False, suffix=".html", prefix="chart_deploy_")
    _tmpf.close()
    _shutil.copy(html_file, _tmpf.name)
    html_file = Path(_tmpf.name)
    _html_tmp = str(_tmpf.name)

    repo_dir = str(SCRIPT_DIR)
    
    # 获取 GitHub 仓库信息
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10
        )
        remote_url = result.stdout.strip()
        # 从 remote URL 提取 owner/repo
        # 支持 https://github.com/owner/repo.git 和 git@github.com:owner/repo.git
        if "github.com" in remote_url:
            if remote_url.startswith("git@"):
                repo_part = remote_url.split("github.com:")[1].replace(".git", "")
            else:
                repo_part = remote_url.split("github.com/")[1].replace(".git", "")
        else:
            print(f"  [部署] 无法解析仓库: {remote_url}")
            return None
    except Exception as e:
        print(f"  [部署] 获取仓库信息失败: {e}")
        return None
    
    # 保存当前分支
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10
        )
        current_branch = result.stdout.strip()
    except Exception:
        current_branch = "main"
    
    # 切换到 gh-pages 分支（如果存在），否则创建
    try:
        # 先尝试切换
        subprocess.run(
            ["git", "checkout", "gh-pages"],
            cwd=repo_dir, capture_output=True, text=True, timeout=15
        )
    except Exception:
        # 创建孤儿分支
        subprocess.run(
            ["git", "checkout", "--orphan", "gh-pages"],
            cwd=repo_dir, capture_output=True, text=True, timeout=15
        )
        # 清空工作区
        import glob as _glob
        for f in _glob.glob(os.path.join(repo_dir, "*")):
            if os.path.basename(f) not in [".git", ".github", ".workbuddy"]:
                try:
                    if os.path.isfile(f):
                        os.remove(f)
                except Exception:
                    pass
    
    # 复制 HTML 文件到 index.html
    import shutil
    target = Path(repo_dir) / "index.html"
    shutil.copy(html_file, target)
    # 清理临时文件
    try:
        os.unlink(_html_tmp)
    except Exception:
        pass
    
    # 复制辅助资源文件（已存在于 gh-pages 时 src==dst，跳过以免 SameFileError）
    for res in ["chart.umd.min.js", "latest.json"]:
        src = Path(repo_dir) / res
        dst = Path(repo_dir) / res
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copy(src, dst)
    
    # 提交
    subprocess.run(
        ["git", "add", "index.html", "chart.umd.min.js", "latest.json"],
        cwd=repo_dir, capture_output=True, text=True, timeout=10
    )
    
    now_str = _dt.now().strftime("%Y-%m-%d %H:%M")
    result = subprocess.run(
        ["git", "commit", "-m", f"Update chart {now_str}"],
        cwd=repo_dir, capture_output=True, text=True, timeout=10
    )
    
    if "nothing to commit" in result.stdout + result.stderr:
        print("  [部署] 内容无变化，跳过提交")
    else:
        # 强制推送 gh-pages
        try:
            subprocess.run(
                ["git", "push", "origin", "gh-pages", "--force"],
                cwd=repo_dir, capture_output=True, text=True, timeout=30
            )
            print("  [部署] 已推送到 gh-pages")
        except Exception as e:
            print(f"  [部署] 推送失败: {e}")
    
    # 切回原分支
    try:
        subprocess.run(
            ["git", "checkout", current_branch],
            cwd=repo_dir, capture_output=True, text=True, timeout=10
        )
    except Exception:
        pass
    
    # 构建 URL
    url = f"https://{repo_part.split('/')[0]}.github.io/{repo_part.split('/')[1]}/"
    print(f"  [部署] 访问地址: {url}")
    return url


def find_previous_key(history, current_key):
    """在当前 key 之前找最近一条历史记录 key（兼容旧调用）"""
    return find_previous_day_last_key(history, current_key)


def find_previous_day_last_key(history, current_key):
    """找前一天最后一次数据（昨日收盘价），用于涨跌对比基准。

    规则：
      1. 提取 current_key 的日期部分（YYYY-MM-DD）
      2. 在该日期之前，找最近一个日期的最后一条记录
      3. 跳过价格异常的脏数据（≤0 或偏离合理范围太远）
    """
    all_keys = sorted(history.keys())
    # 当前日期
    cur_date = current_key[:10] if len(current_key) >= 10 else current_key.split(" ")[0]

    prev_day_keys = []
    for k in all_keys:
        d = k[:10] if len(k) >= 10 else k.split(" ")[0]
        if d < cur_date:
            prev_day_keys.append(k)

    if not prev_day_keys:
        return None

    # 取前一天最后一条
    target_date = prev_day_keys[-1][:10] if len(prev_day_keys[-1]) >= 10 else prev_day_keys[-1].split(" ")[0]
    day_keys = [k for k in prev_day_keys if k.startswith(target_date)]
    if not day_keys:
        day_keys = [prev_day_keys[-1]]  # fallback: 该日最后一条

    # 从后往前找第一条有效的（跳过零/负值）
    for k in reversed(day_keys):
        d = history.get(k, {})
        bf = d.get("boshi_etf", {})
        if bf and isinstance(bf.get("price"), (int, float)) and bf["price"] > 0.1:
            return k

    # fallback: 该日最后一条（即使可疑也比没有好）
    return day_keys[-1]


def main():
    force = "--force" in sys.argv
    is_test = "--test" in sys.argv
    save_only = "--save-only" in sys.argv

    now = datetime.now(BEIJING_TZ)
    # save-only 模式使用精确到分钟的时间戳（如 2026-07-01 19:10）
    # 非 save-only 模式使用整点时间戳（保持原有逻辑）
    if save_only:
        ts_key = now.strftime("%Y-%m-%d %H:%M")
    else:
        ts_key = now.strftime("%Y-%m-%d %H:00")

    print(f"\n{'='*55}")
    print(f"  🪙 金价播报 — {now.strftime('%Y-%m-%d %H:%M')}")
    if save_only:
        print(f"  [仅保存数据模式]")
    elif is_test:
        print(f"  [测试模式]")
    elif not is_trading_time(now):
        if not is_silent_hours(now):
            print(f"  ⏸️  非交易时段且非静默时段，跳过")
            print(f"{'='*55}\n")
            return
        print(f"  🌙 静默时段，仅大幅波动时推送")
    print(f"{'='*55}\n")

    config = load_config()
    selected_brands = config.get(
        "selected_brands", ["周大福", "老庙黄金", "周六福"]
    )

    # 加载历史
    history = load_history()
    prev_key = find_previous_key(history, ts_key)
    prev_data = history.get(prev_key, {}) if prev_key else {}
    prev_au = prev_data.get("au9999")
    prev_etf = prev_data.get("boshi_etf")
    prev_funds = prev_data.get("gold_funds") or {}
    prev_intl = prev_data.get("intl_spot") or {}
    prev_brands = prev_data.get("brands")

    # ── 获取数据 ──
    print("[1/4] 国际现货金价...")
    intl_spot = fetch_intl_spot()
    if intl_spot:
        print(f"      ✓ {intl_spot['intl_price']:.2f} 美元/盎司  |  换算 {intl_spot['cny_price']:.2f} 元/克")

    print("[2/4] AU9999 (积存金参考价)...")
    au9999 = fetch_au9999()
    if au9999:
        prev_str = f"  |  昨收 {au9999['prev_close']:.2f}" if au9999.get("prev_close") else ""
        change_str = f"  |  日内 {_arrow(au9999['change'])}" if au9999.get("change") is not None else ""
        print(f"      ✓ {au9999['price']:.2f} 元/克{change_str}{prev_str}")

    _time.sleep(0.3)  # 东方财富限流间隔
    print("[3/4] 黄金基金...")
    boshi_etf = fetch_boshi_etf()
    if boshi_etf:
        print(f"      ✓ 博时ETF  {boshi_etf['price']:.4f} 元/份  |  {_arrow(boshi_etf['change'])}")
    gold_funds = fetch_gold_funds()
    if gold_funds:
        for code, f in gold_funds.items():
            print(f"      ✓ {f['name']}({code})  克价 {f['gold_price']:.2f} 元/克  (ETF {f['etf_price']:.4f} 元/份)")

    print("[4/4] 品牌金店门面价...")
    brand_prices = fetch_brand_gold()
    if brand_prices:
        print(f"      ✓ {len(brand_prices)} 个品牌")
        for b in selected_brands:
            if b in brand_prices:
                print(f"        {b}: {brand_prices[b]:.0f} 元/克")

    if not au9999 and not brand_prices:
        print("\n❌ 所有数据源获取失败，退出")
        return

    # ── 保存历史 ──
    history[ts_key] = {
        "intl_spot": intl_spot,
        "au9999": au9999,
        "boshi_etf": boshi_etf,
        "gold_funds": gold_funds,
        "brands": brand_prices,
    }
    save_history(history)
    print(f"  [数据] 已保存 {ts_key}")

    # ── --save-only 模式：仅保存，不推送 ──
    if save_only:
        print(f"\n{'='*55}")
        print(f"  ✅ 仅保存模式完成")
        print(f"{'='*55}\n")
        return

    # ── 判断推送 ──
    should_push = False
    reason = ""
    in_silent = is_silent_hours(now)

    if is_test:
        should_push = True
        reason = "测试"
    elif force and not in_silent:
        # 交易时段强制推送
        should_push = True
        reason = "强制推送"
    else:
        # 其余情况（含 force+静默、非force交易时段、非force静默）都走变化判断
        threshold = config.get("threshold", 0.05)
        changes = []
        big_changes = []  # ≥10元的大幅波动

        if intl_spot and prev_intl:
            diff = abs(intl_spot["cny_price"] - prev_intl.get("cny_price", 0))
            if diff >= threshold:
                changes.append(f"国际金价 {diff:+.2f}")
            if diff >= SILENT_THRESHOLD:
                big_changes.append(f"国际金价 波动 {diff:+.1f}元")

        if au9999 and prev_au:
            p = au9999["price"]
            pp = prev_au.get("price", 0) if prev_au.get("price") else p
            diff = abs(p - pp)
            if diff >= threshold:
                changes.append(f"AU9999 {diff:+.2f}")
            if diff >= SILENT_THRESHOLD:
                big_changes.append(f"AU9999 波动 {diff:+.1f}元")

        if boshi_etf and prev_etf:
            diff_etf = abs(boshi_etf["price"] - prev_etf.get("price", 0))
            if diff_etf >= 0.001:
                changes.append(f"博时ETF {diff_etf:+.4f}")
            diff_gold = abs(boshi_etf["price"] * 100 - prev_etf.get("price", 0) * 100)
            if diff_gold >= SILENT_THRESHOLD:
                big_changes.append(f"博时黄金ETF 波动 {diff_gold:+.1f}元")

        if gold_funds and prev_funds:
            for code, f in gold_funds.items():
                p = prev_funds.get(code, {}).get("gold_price")
                if p is not None:
                    diff = abs(f["gold_price"] - p)
                    if diff >= 0.05:
                        changes.append(f"{f['name']} 克价 {f['gold_price']-p:+.2f}")
                    if diff >= SILENT_THRESHOLD:
                        big_changes.append(f"{f['name']} 波动 {diff:+.1f}元")

        if brand_prices and prev_brands:
            for b, tp in brand_prices.items():
                pp = prev_brands.get(b)
                if pp is not None:
                    diff = abs(tp - pp)
                    if diff >= SILENT_THRESHOLD:
                        big_changes.append(f"{b} 波动 {diff:+.1f}元")

        if not prev_data:
            # 首次运行：静默时段不推送
            if in_silent:
                reason = "静默时段首次运行，跳过"
            else:
                should_push = True
                reason = "首次运行"
        elif in_silent:
            # 静默时段：只在大幅波动时推送
            if big_changes:
                should_push = True
                reason = f"静默时段大幅波动: {', '.join(big_changes)}"
            else:
                reason = "静默时段无大幅波动，跳过"
        else:
            # 正常时段：有变化就推送
            if changes:
                should_push = True
                reason = f"变化: {', '.join(changes)}"
            else:
                reason = "价格无变化"

    if in_silent and not is_test:
        print(f"  [静默时段 {SILENT_START.strftime('%H:%M')}-{SILENT_END.strftime('%H:%M')}]")

    print(f"\n[推送] {reason}")

    # ── 生成并部署 K 线图 ──
    chart_url = ""
    try:
        chart_path = generate_chart_html()
        if chart_path:
            # 部署到 GitHub Pages
            chart_url = deploy_chart_to_gh_pages(chart_path) or ""
    except Exception as e:
        print(f"  [图表] 生成/部署失败: {e}")

    if should_push:
        title = "金价"

        # 注入 chart_url 到环境变量供 build_notification 使用
        if chart_url:
            os.environ["CHART_URL"] = chart_url

        content = build_notification(
            au9999, boshi_etf, gold_funds, intl_spot, brand_prices,
            prev_au, prev_etf, prev_funds, prev_intl, prev_brands,
            selected_brands, is_test=is_test,
        )
        send_notification(config, title, content)
    else:
        print("  → 不推送")

    print(f"\n{'='*55}")
    print(f"  ✅ 完成")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
