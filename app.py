import os
import json
import time
import sqlite3
import threading
import traceback
from typing import Any

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

# ============================================================
# ROBI BOT — Integrated Research / Paper Trading App
# ============================================================
# Source knowledge:
# - Japanese candlestick concepts from the supplied Steve Nison book.
# - Engineering modules live in ./robi_engine.
#
# This app:
# - reads market data through the existing ROBI engine
# - analyzes candles, trend, S/R, windows, indicators, volume
# - reads recent trade flow
# - fetches/stores news
# - links news to the requested symbol by simple keyword mapping
# - records analysis snapshots in SQLite
# - supports Telegram commands and periodic monitoring
#
# IMPORTANT:
# - No real order endpoint exists in this file.
# - No buy/sell order is submitted.
# - Binance account/private trading access is NOT used.
# - Experimental scores/thresholds are not presented as Nison rules.
# ============================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PUBLIC_URL = (
    os.getenv("PUBLIC_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or "https://robi-bot-1.onrender.com"
).rstrip("/")

DB_PATH = os.getenv("ROBI_DB_PATH", "robi.db")
MONITOR_INTERVAL = int(os.getenv("ROBI_MONITOR_INTERVAL", "300"))
DEFAULT_SYMBOLS = [
    x.strip().upper()
    for x in os.getenv(
        "ROBI_MONITOR_SYMBOLS",
        "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,AAPL,TSLA,NVDA,MSFT",
    ).split(",")
    if x.strip()
]

REAL_TRADING_ENABLED = False
START_BALANCE = 40.0

app = FastAPI(title="ROBI Trading Bot")
paused = False
monitoring = False
monitor_thread = None
paper_balance = START_BALANCE
paper_trades: list[dict[str, Any]] = []
last_monitor_state: dict[str, str] = {}

# The existing engine is the source of the analysis implementation.
try:
    from robi_engine.integrated import (
        analyze_live,
        save_analysis,
        trade_flow_summary,
    )
    from robi_engine.news_engine import fetch_news, latest_news, init_db
    try:
        from robi_engine.live_data import (
            get_klines,
            get_ticker,
            market_kind,
            market_provider_status,
        )
    except Exception:
        def market_provider_status():
            return {
                "configured": "unknown",
                "routing": {
                    "crypto": "kraken_public",
                    "us_equity": "yahoo_finance_yfinance",
                },
                "real_trading": False,
                "private_api": False,
            }
        def market_kind(symbol):
            return "unknown"
        def get_klines(*args, **kwargs):
            raise RuntimeError("Market data adapter unavailable")
        def get_ticker(*args, **kwargs):
            raise RuntimeError("Market data adapter unavailable")
    ENGINE_READY = True
    ENGINE_IMPORT_ERROR = ""
except Exception as exc:
    ENGINE_READY = False
    ENGINE_IMPORT_ERROR = repr(exc)
    _ENGINE_IMPORT_FAILURE = str(exc)

    def init_db():
        return None

    def fetch_news(limit=20):
        raise RuntimeError(f"ROBI news engine unavailable: {_ENGINE_IMPORT_FAILURE}")

    def latest_news(limit=10):
        return []

    def market_provider_status():
        return {
            "configured": "unavailable",
            "routing": {
                "crypto": "kraken_public",
                "us_equity": "yahoo_finance_yfinance",
            },
            "real_trading": False,
            "private_api": False,
        }

    def market_kind(symbol):
        return "unknown"

    def get_klines(*args, **kwargs):
        raise RuntimeError("ROBI market-data adapter is unavailable")

    def get_ticker(*args, **kwargs):
        raise RuntimeError("ROBI market-data adapter is unavailable")

# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

def ensure_db():
    """Create the tables used by the existing ROBI news/analysis engine."""
    try:
        init_db()
    except Exception as exc:
        print("DB init warning:", exc)

    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            symbol TEXT,
            timeframe TEXT,
            state TEXT,
            trend TEXT,
            price REAL,
            summary TEXT
        )
        """
    )
    con.commit()
    con.close()


# ------------------------------------------------------------
# Telegram
# ------------------------------------------------------------

def telegram(method: str, payload: dict | None = None):
    if not TOKEN:
        return None
    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        json=payload or {},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def send_message(chat_id: int, text: str):
    # Telegram messages have a practical size limit.
    if len(text) <= 3900:
        return telegram("sendMessage", {"chat_id": chat_id, "text": text})

    parts = [text[i:i + 3900] for i in range(0, len(text), 3900)]
    result = None
    for part in parts:
        result = telegram("sendMessage", {"chat_id": chat_id, "text": part})
    return result


# ------------------------------------------------------------
# Formatting helpers
# ------------------------------------------------------------

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money(value):
    value = safe_float(value)
    if abs(value) >= 1:
        return f"{value:,.2f}"
    if value:
        return f"{value:,.8f}"
    return "0"


def compact(value, digits=2):
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)


def pattern_names(snapshot):
    return [
        p.get("name", "?") if isinstance(p, dict) else str(p)
        for p in snapshot.get("patterns", [])
    ]


def latest_candle(snapshot):
    candles = snapshot.get("candles") or []
    return candles[-1] if candles else {}


def snapshot_text(snapshot, symbol, timeframe):
    ticker = snapshot.get("ticker") or {}
    price = safe_float(ticker.get("lastPrice"))
    change = safe_float(ticker.get("priceChangePercent"))
    volume_24 = safe_float(ticker.get("quoteVolume"))

    indicators = snapshot.get("indicators") or {}
    patterns = pattern_names(snapshot)
    windows = snapshot.get("windows") or []
    support = snapshot.get("support") or []
    resistance = snapshot.get("resistance") or []
    volume = snapshot.get("volume") or {}
    flow = snapshot.get("trade_flow") or []
    flow_sum = trade_flow_summary(flow) if flow else {}

    lines = [
        f"📊 ROBI ANALYSIS — {symbol.upper()} — {timeframe}",
        "",
        f"💵 السعر: {money(price)}",
        f"📈 24h: {change:+.2f}%",
        f"📦 حجم 24h: ${volume_24:,.0f}",
        f"🧭 الاتجاه: {snapshot.get('trend', 'unknown')}",
        f"🧠 الحالة: {snapshot.get('state', 'WAIT')}",
        "",
        "🕯️ الشموع:",
        ("• " + ", ".join(patterns)) if patterns else "• لا يوجد نمط مسجل على آخر شمعة",
        "",
        "📍 الدعم:",
        "• " + ", ".join(money(x) for x in support[:5]) if support else "• —",
        "📍 المقاومة:",
        "• " + ", ".join(money(x) for x in resistance[:5]) if resistance else "• —",
        "",
        "📐 المؤشرات:",
        f"• SMA20: {compact(indicators.get('sma20'))}",
        f"• SMA50: {compact(indicators.get('sma50'))}",
        f"• EMA20: {compact(indicators.get('ema20'))}",
        f"• RSI14: {compact(indicators.get('rsi14'))}",
        f"• Stochastic14: {compact(indicators.get('stochastic14'))}",
        f"• MACD: {compact(indicators.get('macd'))}",
        "",
        "🪟 Windows:",
        "• " + (", ".join(str(w) for w in windows[:3]) if windows else "لا يوجد"),
        "",
        "📊 Volume:",
        f"• {json.dumps(volume, ensure_ascii=False)}",
        "",
        "🔄 Trade Flow:",
        (
            f"• BUY: ${safe_float(flow_sum.get('buy_notional')):,.2f}\n"
            f"• SELL: ${safe_float(flow_sum.get('sell_notional')):,.2f}\n"
            f"• BUY share: {safe_float(flow_sum.get('buy_share')) * 100:.1f}%\n"
            f"• SELL share: {safe_float(flow_sum.get('sell_share')) * 100:.1f}%"
        ) if flow_sum else "• لا توجد بيانات تدفق",
        "",
        "📰 الأخبار المرتبطة:",
        f"• {len(snapshot.get('news', []))} خبر/أخبار مخزنة",
        "",
        "🔐 الوضع: قراءة وتحليل + Paper Trading فقط",
        "🚫 التداول الحقيقي: معطّل",
    ]

    return "\n".join(lines)


# ------------------------------------------------------------
# Public market-data status / routing
# ------------------------------------------------------------

def market_status():
    """Return an explicit, human-readable public-data routing status."""
    try:
        status = dict(market_provider_status() or {})
    except Exception as exc:
        status = {"configured": "error", "routing": {}, "error": str(exc)}

    routing = status.get("routing") or {}
    status.setdefault("configured", "auto")
    status["routing"] = {
        "crypto": routing.get("crypto", "kraken_public"),
        "us_equity": routing.get("us_equity", "yahoo_finance_yfinance"),
    }
    status["real_trading"] = False
    status["private_api"] = False
    return status


def market_provider_text():
    status = market_status()
    configured = str(status.get("configured", "auto")).upper()
    crypto = str(status["routing"]["crypto"])
    equities = str(status["routing"]["us_equity"])
    return (
        f"AUTO ({configured}) — Crypto: Kraken Public API; "
        f"US equities: Yahoo Finance/yfinance "
        f"[routes: {crypto}, {equities}]"
    )


def public_market_test(symbol="BTCUSDT", timeframe="15m", limit=20):
    """Actually contact the configured public market-data adapter."""
    symbol = symbol.upper().strip()
    candles = get_klines(symbol, timeframe, limit)
    ticker = get_ticker(symbol)
    return {
        "ok": bool(candles and ticker),
        "symbol": symbol,
        "timeframe": timeframe,
        "market_kind": market_kind(symbol),
        "provider": ticker.get("provider", "unknown") if isinstance(ticker, dict) else "unknown",
        "candles_received": len(candles),
        "last_price": safe_float(ticker.get("lastPrice")) if isinstance(ticker, dict) else None,
        "price_change_percent": safe_float(ticker.get("priceChangePercent")) if isinstance(ticker, dict) else None,
    }


# ------------------------------------------------------------
# News linkage
# ------------------------------------------------------------

ASSET_KEYWORDS = {
    "BTC": ["bitcoin", "btc", "crypto", "cryptocurrency"],
    "ETH": ["ethereum", "ether", "eth"],
    "BNB": ["bnb", "binance coin", "binance"],
    "SOL": ["solana", "sol"],
    "XRP": ["xrp", "ripple"],
    "AAPL": ["apple", "aapl"],
    "TSLA": ["tesla", "tsla"],
    "NVDA": ["nvidia", "nvda"],
    "MSFT": ["microsoft", "msft"],
    "AMZN": ["amazon", "amzn"],
    "META": ["meta", "facebook"],
    "GOOGL": ["alphabet", "google", "googl"],
    "AMD": ["amd", "advanced micro devices"],
    "AVGO": ["broadcom", "avgo"],
    "PLTR": ["palantir", "pltr"],
}


def symbol_assets(symbol: str):
    s = symbol.upper().replace("/", "")
    return [asset for asset in ASSET_KEYWORDS if s.startswith(asset)]


def news_for_symbol(symbol: str, limit=10):
    try:
        rows = latest_news(limit=50)
    except Exception:
        rows = []

    assets = symbol_assets(symbol)
    out = []

    for item in rows:
        title = (item.get("title") or "").lower()
        matched = any(
            keyword in title
            for asset in assets
            for keyword in ASSET_KEYWORDS.get(asset, [])
        )
        # General crypto/market news is also retained as context.
        if matched or not assets:
            copy = dict(item)
            copy["affected_assets"] = assets
            out.append(copy)
        if len(out) >= limit:
            break

    return out


def news_text(symbol=None, limit=10):
    if symbol:
        rows = news_for_symbol(symbol, limit)
        title = f"📰 ROBI NEWS — {symbol.upper()}"
    else:
        rows = latest_news(limit)
        title = "📰 ROBI NEWS — Global Market Feed"

    if not rows:
        return title + "\n\nلا توجد أخبار مخزنة حاليًا."

    lines = [title, ""]
    for i, item in enumerate(rows, 1):
        lines.append(
            f"{i}) {item.get('title', 'بدون عنوان')}\n"
            f"المصدر: {item.get('source', '—')}\n"
            f"الوقت: {item.get('published', '—')}\n"
            f"{item.get('url', '')}"
        )
    return "\n\n".join(lines)


# ------------------------------------------------------------
# Analysis
# ------------------------------------------------------------

def run_analysis(symbol: str, timeframe: str = "15m", limit: int = 200):
    if not ENGINE_READY:
        raise RuntimeError(
            "ROBI Engine import failed: " + ENGINE_IMPORT_ERROR
        )

    snapshot = analyze_live(symbol.upper(), timeframe, limit)
    snapshot["news"] = news_for_symbol(symbol, 10)
    ensure_db()

    try:
        save_analysis(snapshot)
    except Exception as exc:
        print("Analysis save warning:", exc)

    return snapshot


def record_monitor_event(snapshot):
    ticker = snapshot.get("ticker") or {}
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        INSERT INTO monitor_events(ts,symbol,timeframe,state,trend,price,summary)
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            time.time(),
            snapshot.get("symbol", ""),
            snapshot.get("timeframe", ""),
            snapshot.get("state", ""),
            snapshot.get("trend", ""),
            safe_float(ticker.get("lastPrice")),
            ", ".join(pattern_names(snapshot)),
        ),
    )
    con.commit()
    con.close()


# ------------------------------------------------------------
# Periodic market monitor
# ------------------------------------------------------------

def monitor_loop():
    global monitoring

    while monitoring:
        for symbol in DEFAULT_SYMBOLS:
            if not monitoring:
                break

            try:
                snapshot = run_analysis(symbol, "15m", 200)
                state = snapshot.get("state", "WAIT")
                trend = snapshot.get("trend", "unknown")
                patterns = ",".join(pattern_names(snapshot))

                signature = f"{state}|{trend}|{patterns}"
                previous = last_monitor_state.get(symbol)

                record_monitor_event(snapshot)
                last_monitor_state[symbol] = signature

                # Only notify on a change, to avoid Telegram spam.
                if previous is not None and previous != signature and TOKEN:
                    # chat_id is configured through ROBI_MONITOR_CHAT_ID.
                    chat_id = os.getenv("ROBI_MONITOR_CHAT_ID", "").strip()
                    if chat_id:
                        send_message(
                            int(chat_id),
                            snapshot_text(snapshot, symbol, "15m")
                            + "\n\n🔔 تغيرت حالة المراقبة.",
                        )

            except Exception as exc:
                print(f"Monitor error {symbol}: {exc}")

        time.sleep(max(MONITOR_INTERVAL, 60))


def start_monitor():
    global monitoring, monitor_thread

    if monitoring:
        return False

    monitoring = True
    monitor_thread = threading.Thread(
        target=monitor_loop,
        name="robi-market-monitor",
        daemon=True,
    )
    monitor_thread.start()
    return True


def stop_monitor():
    global monitoring
    monitoring = False


# ------------------------------------------------------------
# Telegram command handler
# ------------------------------------------------------------

def handle_message(message: dict):
    global paused

    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return

    command = text.split()[0].lower()

    try:
        if command == "/start":
            send_message(
                chat_id,
                "🤖 ROBI Trading Bot\n\n"
                "🧠 Candlestick + Technical Analysis\n"
                "📰 News + Market Monitoring\n"
                "🔄 Trade Flow\n"
                "🗃️ SQLite logging\n\n"
                "🔐 Read/Research + Paper Trading فقط\n"
                "🚫 التداول الحقيقي: غير مفعّل\n\n"
                "الأوامر:\n"
                "/analyze BTCUSDT 15m\n"
                "/analyze AAPL 1h\n"
                "/analyze TSLA 15m\n"
                "/news\n"
                "/news BTCUSDT\n"
                "/flow BTCUSDT\n"
                "/monitor\n"
                "/stopmonitor\n"
                "/status\n"
                "/pause\n"
                "/resume\n"
                "/help",
            )

        elif command == "/help":
            send_message(
                chat_id,
                "/analyze SYMBOL [TIMEFRAME] - تحليل السوق (AAPL / TSLA / BTCUSDT...)\n"
                "/news [SYMBOL] - آخر الأخبار\n"
                "/flow SYMBOL - تدفق الصفقات\n"
                "/monitor - تشغيل المراقبة\n"
                "/stopmonitor - إيقاف المراقبة\n"
                "/status - حالة ROBI\n"
                "/pause - إيقاف Paper Trading\n"
                "/resume - تشغيل Paper Trading\n"
                "/help\n\n"
                "المحرك لا يعتبر الشمعة وحدها أمر شراء/بيع.\n"
                "يستخدم السياق والتأكيد والتوافق والتعارض.",
            )

        elif command == "/status":
            engine_status = "READY" if ENGINE_READY else "ERROR"
            send_message(
                chat_id,
                "🤖 ROBI STATUS\n\n"
                f"Engine: {engine_status}\n"
                f"Monitoring: {'ON' if monitoring else 'OFF'}\n"
                f"Paper Trading: {'PAUSED' if paused else 'RUNNING'}\n"
                f"Paper Balance: ${paper_balance:.2f}\n"
                f"Paper Trades: {len(paper_trades)}\n"
                "Real Trading: DISABLED\n"
                f"PUBLIC_URL: {PUBLIC_URL}",
            )

        elif command == "/pause":
            paused = True
            send_message(chat_id, "⏸ تم إيقاف Paper Trading.")

        elif command == "/resume":
            paused = False
            send_message(chat_id, "▶️ تم تشغيل Paper Trading.")

        elif command == "/monitor":
            if start_monitor():
                send_message(
                    chat_id,
                    "🟢 ROBI بدأ مراقبة السوق.\n"
                    f"الأزواج: {', '.join(DEFAULT_SYMBOLS)}\n"
                    f"الفاصل: {MONITOR_INTERVAL} ثانية\n"
                    "🔔 التنبيه عند تغيّر حالة التحليل.",
                )
            else:
                send_message(chat_id, "ℹ️ المراقبة تعمل أصلًا.")

        elif command == "/stopmonitor":
            stop_monitor()
            send_message(chat_id, "⏹ تم إيقاف مراقبة السوق.")

        elif command == "/news":
            parts = text.split()
            symbol = parts[1] if len(parts) > 1 else None

            try:
                fetch_news(20)
            except Exception as exc:
                print("News fetch warning:", exc)

            send_message(chat_id, news_text(symbol, 10))

        elif command == "/flow":
            parts = text.split()
            symbol = parts[1].upper() if len(parts) > 1 else "BTCUSDT"

            # Reuse the integrated engine so flow and analysis share
            # the same market-data path.
            snapshot = run_analysis(symbol, "15m", 200)
            rows = snapshot.get("trade_flow") or []
            summary = trade_flow_summary(rows)

            send_message(
                chat_id,
                f"🔄 TRADE FLOW — {symbol}\n\n"
                f"BUY notional: ${summary['buy_notional']:,.2f}\n"
                f"SELL notional: ${summary['sell_notional']:,.2f}\n"
                f"BUY share: {summary['buy_share'] * 100:.1f}%\n"
                f"SELL share: {summary['sell_share'] * 100:.1f}%\n"
                f"Trades sampled: {summary['trades']}\n\n"
                "📌 هذا وصف لتدفق الصفقات، وليس أمر شراء/بيع.",
            )

        elif command == "/analyze":
            parts = text.split()
            symbol = parts[1].upper() if len(parts) > 1 else "BTCUSDT"
            timeframe = parts[2] if len(parts) > 2 else "15m"

            snapshot = run_analysis(symbol, timeframe, 200)
            send_message(chat_id, snapshot_text(snapshot, symbol, timeframe))

        else:
            send_message(
                chat_id,
                "ما فهمت الأمر. استخدم /help.",
            )

    except requests.HTTPError as exc:
        detail = ""
        if exc.response is not None:
            try:
                detail = exc.response.text[:500]
            except Exception:
                detail = f"HTTP {exc.response.status_code}"

        send_message(
            chat_id,
            "🔴 تعذر جلب بيانات السوق من مزود البيانات الحالي.\n\n"
            f"{detail}\n\n"
            "ROBI ما زال شغال، لكن مصدر بيانات السوق يحتاج مصدرًا "
            "متاحًا من السيرفر.",
        )
        print("HTTP error:", traceback.format_exc())

    except Exception as exc:
        print("Command error:", traceback.format_exc())
        send_message(
            chat_id,
            "⚠️ ROBI واجه خطأ أثناء تنفيذ الأمر.\n"
            f"التفاصيل: {str(exc)[:700]}",
        )


# ------------------------------------------------------------
# HTTP endpoints
# ------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home():
    status = market_status()
    return f"""
    <h2>🤖 ROBI Trading Bot</h2>
    <p>Integrated research / paper-trading service is running.</p>
    <p>Engine: {"READY" if ENGINE_READY else "ERROR"}</p>
    <p>Monitoring: {"ON" if monitoring else "OFF"}</p>
    <p>Real trading: <b>DISABLED</b></p>
    <p>Market analysis: candles, patterns, windows, indicators,
       support/resistance, volume, trade flow and news.</p>
    <p><b>Public market data: EXTERNAL ONLY</b></p>
    <p>Crypto source: <b>Kraken Public API</b></p>
    <p>US equities source: <b>Yahoo Finance / yfinance</b></p>
    <p>Configured mode: <b>{str(status.get("configured", "auto")).upper()}</b></p>
    <p>Private exchange API: <b>DISABLED</b></p>
    <p><a href="/health">Health</a> &nbsp; | &nbsp; <a href="/market-test?symbol=BTCUSDT&timeframe=15m">Test BTCUSDT data</a></p>
    """


@app.get("/health")
def health():
    return {
        "ok": True,
        "engine_ready": ENGINE_READY,
        "engine_import_error": ENGINE_IMPORT_ERROR if not ENGINE_READY else "",
        "telegram_token_configured": bool(TOKEN),
        "public_url": PUBLIC_URL,
        "webhook_url": f"{PUBLIC_URL}/telegram/webhook",
        "monitoring": monitoring,
        "real_trading_enabled": False,
        "paper_trading": True,
        "database": DB_PATH,
        "market_data": market_status(),
        "market_data_policy": "external_public_only",
        "crypto_provider": "Kraken Public API",
        "us_equity_provider": "Yahoo Finance / yfinance",
        "private_exchange_api": False,
    }


@app.get("/market-test")
def market_test(symbol: str = "BTCUSDT", timeframe: str = "15m", limit: int = 20):
    try:
        return public_market_test(symbol, timeframe, max(1, min(limit, 200)))
    except Exception as exc:
        return {
            "ok": False,
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "market_kind": market_kind(symbol),
            "error": str(exc),
            "market_data_policy": "external_public_only",
            "crypto_provider": "Kraken Public API",
            "us_equity_provider": "Yahoo Finance / yfinance",
            "private_exchange_api": False,
        }


@app.get("/analyze")
def analyze_http(symbol: str = "BTCUSDT", timeframe: str = "15m"):
    snapshot = run_analysis(symbol.upper(), timeframe, 200)
    return snapshot


@app.get("/news")
def news_http(symbol: str | None = None, limit: int = 10):
    try:
        fetch_news(max(1, min(limit, 50)))
    except Exception:
        pass
    if symbol:
        return {"symbol": symbol.upper(), "news": news_for_symbol(symbol, limit)}
    return {"news": latest_news(limit)}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    update = await request.json()
    message = update.get("message")

    if message:
        threading.Thread(
            target=handle_message,
            args=(message,),
            daemon=True,
        ).start()

    return {"ok": True}


def configure_webhook():
    if not TOKEN:
        print("WARNING: TELEGRAM_BOT_TOKEN is not configured.")
        return

    webhook_url = f"{PUBLIC_URL}/telegram/webhook"

    try:
        result = telegram("setWebhook", {"url": webhook_url})
        print("Telegram webhook configured:", result)
    except Exception as exc:
        print("WARNING: Could not configure Telegram webhook:", exc)


@app.on_event("startup")
def startup():
    ensure_db()
    threading.Thread(target=configure_webhook, daemon=True).start()
