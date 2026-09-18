import os
import threading
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PUBLIC_URL = os.getenv(
    "PUBLIC_URL",
    "https://robi-bot-0iea.onrender.com",
).rstrip("/")

app = FastAPI(title="ROBI Trading Bot")

balance = 40.0
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


def handle_message(message: dict):
    global balance, paused
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip().lower()

    if not chat_id:
        return

    if text == "/start":
        send_message(
            chat_id,
            "🤖 ROBI Trading Bot\n\n"
            "وضع التشغيل: Paper Trading فقط\n"
            "الرصيد التجريبي: $40.00\n\n"
            "الأوامر:\n"
            "/status - الحالة والرصيد\n"
            "/scan - محاكاة فحص\n"
            "/pause - إيقاف المحاكاة\n"
            "/resume - تشغيل المحاكاة\n"
            "/help - المساعدة",
        )

    elif text == "/status":
        pnl = balance - 40.0
        send_message(
            chat_id,
            f"📊 الحالة: {'PAUSED' if paused else 'RUNNING'}\n"
            f"💰 الرصيد التجريبي: ${balance:.2f}\n"
            f"📈 P&L: ${pnl:+.2f}\n"
            f"🔢 العمليات: {len(trades)}",
        )

    elif text == "/pause":
        paused = True
        send_message(chat_id, "⏸ تم إيقاف المحاكاة.")

    elif text == "/resume":
        paused = False
        send_message(chat_id, "▶️ تم تشغيل المحاكاة.")

    elif text == "/scan":
        if paused:
            send_message(chat_id, "⏸ البوت متوقف. استخدم /resume أولًا.")
            return

        # Educational paper-trading simulation only.
        import random

        score = random.randint(40, 98)
        change = random.uniform(-12, 25)

        if score >= 70 and change > 0:
            size = balance * 0.05
            trade_pnl = size * random.uniform(-0.20, 0.45)

            balance += trade_pnl
            trades.append(
                {
                    "score": score,
                    "change": round(change, 2),
                    "pnl": round(trade_pnl, 2),
                }
            )

            send_message(
                chat_id,
                f"🔎 SCAN\n"
                f"Signal: {score}\n"
                f"Change: {change:+.2f}%\n"
                f"🧪 Paper trade P&L: ${trade_pnl:+.2f}\n"
                f"💰 Balance: ${balance:.2f}",
            )
        else:
            send_message(
                chat_id,
                f"🔎 SCAN\nSignal: {score}\n"
                f"Change: {change:+.2f}%\n"
                "⏭ SKIP - لم تتجاوز الإشارة الفلاتر.",
            )

    elif text == "/help":
        send_message(
            chat_id,
            "/start\n/status\n/scan\n/pause\n/resume\n/help\n\n"
            "هذا الإصدار تجريبي ولا ينفذ أي تداول حقيقي.",
        )


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <h2>ROBI Trading Bot</h2>
    <p>Telegram webhook service is running.</p>
    <p>Mode: Paper Trading only.</p>
    """


@app.get("/health")
def health():
    return {
        "ok": True,
        "telegram_token_configured": bool(TOKEN),
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
