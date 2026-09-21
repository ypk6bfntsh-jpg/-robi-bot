import os
import time
import hmac
import hashlib
import threading
import requests
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PUBLIC_URL = os.getenv(
    "PUBLIC_URL",
    "https://robi-bot-0iea.onrender.com",
).rstrip("/")

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
BINANCE_BASE_URL = "https://api.binance.com"

app = FastAPI(title="ROBI Trading Bot")

START_BALANCE = 40.0
balance = START_BALANCE
paused = False
trades = []


def telegram(method: str, payload: dict | None = None):
    if not TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    response = requests.post(url, json=payload or {}, timeout=15)
    response.raise_for_status()
    return response.json()


def send_message(chat_id: int, text: str):
    return telegram("sendMessage", {"chat_id": chat_id, "text": text})


def binance_public_get(path: str, params: dict | None = None):
    response = requests.get(
        f"{BINANCE_BASE_URL}{path}",
        params=params or {},
        timeout=15,
    )
  print("BINANCE PUBLIC DEBUG:", response.status_code, response.text[:1000])
    response.raise_for_status()
    return response.json()


def binance_signed_get(path: str, params: dict | None = None):
    """Read-only signed request. No trading/order endpoint is used."""
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("Binance API credentials are not configured.")

    query = dict(params or {})
    query["timestamp"] = int(time.time() * 1000)
    query["recvWindow"] = 5000

    query_string = urlencode(query)
    signature = hmac.new(
        BINANCE_API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    query["signature"] = signature

    response = requests.get(
        f"{BINANCE_BASE_URL}{path}",
        params=query,
        headers={"X-MBX-APIKEY": BINANCE_API_KEY},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_binance_account():
    # GET /api/v3/account is a signed USER_DATA endpoint.
    return binance_signed_get(
        "/api/v3/account",
        {"omitZeroBalances": "true"},
    )


def get_binance_ticker(symbol: str):
    symbol = symbol.upper().replace("/", "")
    return binance_public_get(
        "/api/v3/ticker/24hr",
        {"symbol": symbol},
    )


def format_balances(account: dict):
    balances = account.get("balances") or []
    if not balances:
        return "لا توجد أرصدة غير صفرية ظاهرة."

    lines = []
    for item in balances[:20]:
        asset = item.get("asset", "?")
        free = item.get("free", "0")
        locked = item.get("locked", "0")
        lines.append(f"• {asset}: متاح {free} | محجوز {locked}")
    return "\n".join(lines)


def money(value):
    if value >= 1:
        return f"${value:,.2f}"
    if value > 0:
        return f"${value:.8f}"
    return "$0"


def handle_message(message: dict):
    global balance, paused

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id:
        return

    command = text.lower()

    if command == "/start":
        send_message(
            chat_id,
            "🤖 ROBI Trading Bot\n\n"
            "🔐 Binance: قراءة فقط\n"
            "🚫 التداول الحقيقي: غير مفعّل\n"
            f"💰 الرصيد الورقي: ${balance:.2f}\n\n"
            "الأوامر:\n"
            "/status - الحالة + رصيد Binance\n"
            "/binance - اختبار اتصال Binance وعرض الأرصدة\n"
            "/ticker BTCUSDT - سعر 24h\n"
            "/scan - فحص السوق العام\n"
            "/pause - إيقاف Paper Trading\n"
            "/resume - تشغيل Paper Trading\n"
            "/help - المساعدة",
        )

    elif command == "/status" or command == "/binance":
        if not BINANCE_API_KEY or not BINANCE_API_SECRET:
            send_message(
                chat_id,
                "⚠️ مفاتيح Binance غير موجودة في إعدادات الخادم."
            )
            return

        try:
            account = get_binance_account()
            balances_text = format_balances(account)
            send_message(
                chat_id,
                "🟢 Binance متصل — قراءة فقط\n\n"
                f"📌 نوع الحساب: {account.get('accountType', 'غير معروف')}\n"
                "💰 الأرصدة غير الصفرية:\n"
                f"{balances_text}\n\n"
                f"🤖 Paper Trading: {'متوقف' if paused else 'يعمل'}\n"
                f"💵 الرصيد الورقي: ${balance:.2f}\n"
                "🚫 لا توجد أوامر شراء/بيع في هذا الإصدار.",
            )
        except requests.HTTPError as exc:
            detail = ""
            if exc.response is not None:
                try:
                    data = exc.response.json()
                    detail = f"\nBinance: {data.get('msg', data)}"
                except Exception:
                    detail = f"\nHTTP {exc.response.status_code}"
            send_message(
                chat_id,
                "🔴 تعذر الاتصال بحساب Binance." + detail
            )
        except Exception as exc:
            print("Binance account error:", exc)
            send_message(
                chat_id,
                "🔴 تعذر اختبار اتصال Binance. راجع إعدادات المفاتيح."
            )

    elif command.startswith("/ticker"):
        parts = text.split()
        symbol = parts[1] if len(parts) > 1 else "BTCUSDT"

        try:
            ticker = get_binance_ticker(symbol)
            price = float(ticker.get("lastPrice", 0))
            change = float(ticker.get("priceChangePercent", 0))
            volume = float(ticker.get("quoteVolume", 0))

            send_message(
                chat_id,
                f"📈 Binance — {symbol.upper()}\n\n"
                f"السعر: {price:,.8f}\n"
                f"24h: {change:+.2f}%\n"
                f"حجم 24h: ${volume:,.0f}\n\n"
                "🔐 قراءة بيانات فقط — لا يوجد تداول.",
            )
        except Exception:
            send_message(
                chat_id,
                f"⚠️ تعذر جلب بيانات {symbol.upper()}."
            )

    elif command == "/pause":
        paused = True
        send_message(chat_id, "⏸ تم إيقاف Paper Trading.")

    elif command == "/resume":
        paused = False
        send_message(chat_id, "▶️ تم تشغيل Paper Trading.")

    elif command == "/scan":
        try:
            symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
            rows = []

            for symbol in symbols:
                ticker = get_binance_ticker(symbol)
                rows.append(
                    (
                        symbol,
                        float(ticker.get("lastPrice", 0)),
                        float(ticker.get("priceChangePercent", 0)),
                        float(ticker.get("quoteVolume", 0)),
                    )
                )

            rows.sort(key=lambda x: abs(x[2]), reverse=True)

            lines = ["🔎 SCAN — Binance\n"]
            for i, (symbol, price, change, volume) in enumerate(rows, 1):
                lines.append(
                    f"{i}) {symbol}\n"
                    f"السعر: {price:,.8f}\n"
                    f"24h: {change:+.2f}%\n"
                    f"الحجم: ${volume:,.0f}\n"
                )

            lines.append(
                "🔐 بيانات سوق عامة فقط.\n"
                "🚫 لم يتم تنفيذ أي شراء أو بيع."
            )
            send_message(chat_id, "\n".join(lines))
        except Exception as exc:
            print("Scan error:", exc)
            send_message(
                chat_id,
                "⚠️ تعذر جلب بيانات Binance الآن. حاول مرة أخرى."
            )

    elif command == "/help":
        send_message(
            chat_id,
            "/start\n"
            "/status — حالة البوت وحساب Binance\n"
            "/binance — اختبار الاتصال وعرض الأرصدة\n"
            "/ticker BTCUSDT — بيانات زوج محدد\n"
            "/scan — فحص مجموعة من أزواج Binance\n"
            "/pause\n"
            "/resume\n"
            "/help\n\n"
            "🔐 مفاتيح Binance تستخدم للقراءة فقط في هذا الإصدار.\n"
            "🚫 لا يوجد كود لإنشاء أو تعديل أو إلغاء أوامر تداول.",
        )


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <h2>ROBI Trading Bot</h2>
    <p>Telegram webhook service is running.</p>
    <p>Binance mode: Read-only.</p>
    <p>Real trading: Disabled.</p>
    """


@app.get("/health")
def health():
    return {
        "ok": True,
        "telegram_token_configured": bool(TOKEN),
        "binance_api_key_configured": bool(BINANCE_API_KEY),
        "binance_api_secret_configured": bool(BINANCE_API_SECRET),
        "real_trading_enabled": False,
        "webhook_url": f"{PUBLIC_URL}/telegram/webhook",
    }


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
    threading.Thread(target=configure_webhook, daemon=True).start()
