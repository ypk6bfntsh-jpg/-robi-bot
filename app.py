import os, threading, time
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="ROBI Trading Bot")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PUBLIC_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
balance = 40.0
paused = False
trades = []

def tg(method, payload=None):
    if not TOKEN: return None
    try:
        return requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=payload or {}, timeout=15).json()
    except Exception:
        return None

def send(chat_id, text):
    tg("sendMessage", {"chat_id": chat_id, "text": text})

def handle_message(message):
    global paused
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip().lower()
    if not chat_id: return
    if text == "/start":
        send(chat_id, "🤖 أهلاً بك في ROBI Trading Bot\n\n💰 الرصيد التجريبي: $40.00\n📊 الوضع: Paper Trading فقط\n🟢 الحالة: Online\n\n/status - الحالة والرصيد\n/scan - فحص تجريبي للسوق\n/pause - إيقاف المحاكاة\n/resume - تشغيل المحاكاة\n/help - الأوامر")
    elif text == "/status":
        send(chat_id, f"🤖 ROBI STATUS\n\n💰 Balance: ${balance:.2f}\n📈 Trades: {len(trades)}\n🟢 Mode: {'PAUSED' if paused else 'RUNNING'}\n🧪 Paper Trading فقط")
    elif text == "/pause":
        paused = True; send(chat_id, "⏸ تم إيقاف المحاكاة.")
    elif text == "/resume":
        paused = False; send(chat_id, "▶️ تم تشغيل المحاكاة.")
    elif text == "/scan":
        send(chat_id, "⏸ البوت متوقف. استخدم /resume أولاً." if paused else "🔎 SCAN RESULT\n\n🧪 هذه محاكاة تعليمية فقط.\nلا توجد صفقات حقيقية أو أموال حقيقية.")
    elif text == "/help":
        send(chat_id, "/start\n/status\n/scan\n/pause\n/resume\n/help")

@app.get("/", response_class=HTMLResponse)
def home():
    return f"<h1>🤖 ROBI BOT</h1><p>Balance: ${balance:.2f}</p><p>Mode: {'PAUSED' if paused else 'RUNNING'}</p><p>Telegram: {'Connected' if TOKEN else 'Token missing'}</p><p>Paper Trading only.</p>"

@app.get("/health")
def health():
    return {"ok": True, "telegram_token_configured": bool(TOKEN)}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    update = await request.json()
    message = update.get("message")
    if message:
        threading.Thread(target=handle_message, args=(message,), daemon=True).start()
    return {"ok": True}

def configure_webhook():
    if TOKEN and PUBLIC_URL:
        time.sleep(2)
        tg("setWebhook", {"url": PUBLIC_URL + "/telegram/webhook"})

@app.on_event("startup")
def startup():
    threading.Thread(target=configure_webhook, daemon=True).start()
