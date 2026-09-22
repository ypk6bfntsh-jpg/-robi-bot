"""ROBI News Engine v01.

Public RSS/Google News ingestion with SQLite storage and transparent,
rule-based news classification. No trading orders or recommendations.
"""
import os
import re
import sqlite3
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

DB_PATH = os.getenv("ROBI_DB_PATH", "robi.db")
NEWS_TIMEOUT = int(os.getenv("ROBI_NEWS_TIMEOUT", "15"))
NEWS_MAX_AGE_HOURS = int(os.getenv("ROBI_NEWS_MAX_AGE_HOURS", "72"))

ASSET_TERMS = {
    "BTC": ["bitcoin", "btc"], "ETH": ["ethereum", "ether", "eth"],
    "SOL": ["solana", "sol"], "XRP": ["xrp", "ripple"],
    "BNB": ["bnb", "binance"], "AAPL": ["apple", "aapl"],
    "TSLA": ["tesla", "tsla"], "NVDA": ["nvidia", "nvda"],
    "MSFT": ["microsoft", "msft"], "AMZN": ["amazon", "amzn"],
    "META": ["meta", "facebook"], "GOOGL": ["google", "alphabet", "googl"],
    "AMD": ["amd", "advanced micro devices"], "INTC": ["intel", "intc"],
    "MU": ["micron", "mu"], "PLTR": ["palantir", "pltr"],
}

POSITIVE = {
    "beats", "beat", "surges", "surge", "rises", "rise", "gains", "gain",
    "growth", "record", "upgrade", "upgraded", "approval", "approved",
    "strong", "profit", "profits", "revenue growth", "bullish", "partnership",
    "contract", "launch", "expands", "expansion", "positive", "outperform",
}
NEGATIVE = {
    "falls", "fall", "drops", "drop", "loss", "losses", "downgrade", "downgraded",
    "warning", "lawsuit", "investigation", "probe", "recall", "cuts", "cut",
    "weak", "decline", "declines", "miss", "misses", "negative", "fraud",
    "layoffs", "delay", "delays", "bearish", "fine", "ban", "shutdown",
}


def _db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS news(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        source TEXT,
        url TEXT UNIQUE,
        published TEXT,
        fetched_at REAL,
        summary TEXT,
        assets TEXT,
        sentiment TEXT,
        impact TEXT
    )""")
    # Backward compatibility with older ROBI news tables.
    cols = {r[1] for r in con.execute("PRAGMA table_info(news)")}
    for name, typ in [("summary", "TEXT"), ("assets", "TEXT"), ("sentiment", "TEXT"), ("impact", "TEXT")]:
        if name not in cols:
            con.execute(f"ALTER TABLE news ADD COLUMN {name} {typ}")
    con.commit()
    return con


def init_db():
    con = _db()
    con.close()


def _asset_matches(text):
    low = text.lower()
    found = []
    for asset, terms in ASSET_TERMS.items():
        if any(re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", low) for term in terms):
            found.append(asset)
    return found


def _classify(title, summary=""):
    text = f"{title} {summary}".lower()
    pos = sum(1 for x in POSITIVE if x in text)
    neg = sum(1 for x in NEGATIVE if x in text)
    if pos > neg:
        sentiment = "positive"
    elif neg > pos:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    strength = "high" if abs(pos - neg) >= 2 else ("medium" if abs(pos - neg) == 1 else "low")
    return sentiment, strength


def _parse_rss(xml_bytes):
    root = ET.fromstring(xml_bytes)
    rows = []
    for item in root.findall(".//item"):
        def txt(tag):
            node = item.find(tag)
            return (node.text or "").strip() if node is not None else ""
        title = txt("title")
        link = txt("link")
        desc = re.sub(r"<[^>]+>", " ", txt("description"))
        pub = txt("pubDate") or txt("published")
        source = txt("source") or "Google News RSS"
        if title and link:
            rows.append({"title": title, "url": link, "summary": desc, "published": pub, "source": source})
    return rows


def _feed_url(query):
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _queries(symbol=None):
    if symbol:
        s = symbol.upper().replace("/", "")
        assets = [s]
        for asset, terms in ASSET_TERMS.items():
            if s.startswith(asset):
                assets = terms[:2]
                break
        return [" OR ".join(f'"{x}"' for x in assets)]
    return [
        "stock market OR S&P 500 OR Nasdaq",
        "bitcoin OR ethereum OR crypto market",
        "Federal Reserve OR interest rates markets",
    ]


def fetch_news(limit=20, symbol=None):
    init_db()
    collected = []
    for query in _queries(symbol):
        try:
            r = requests.get(_feed_url(query), timeout=NEWS_TIMEOUT, headers={"User-Agent": "ROBI-NewsEngine/1.0"})
            r.raise_for_status()
            collected.extend(_parse_rss(r.content))
        except Exception as exc:
            print("News feed warning:", query, exc)

    seen = set()
    con = _db()
    now = time.time()
    for item in collected:
        url = item["url"]
        if url in seen:
            continue
        seen.add(url)
        assets = _asset_matches(item["title"] + " " + item.get("summary", ""))
        sentiment, impact = _classify(item["title"], item.get("summary", ""))
        con.execute("""INSERT INTO news(title,source,url,published,fetched_at,summary,assets,sentiment,impact)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET
            title=excluded.title, source=excluded.source, published=excluded.published,
            summary=excluded.summary, assets=excluded.assets, sentiment=excluded.sentiment, impact=excluded.impact""",
            (item["title"], item["source"], url, item.get("published", ""), now,
             item.get("summary", ""), ",".join(assets), sentiment, impact))
    con.commit()
    con.close()
    return latest_news(limit, symbol=symbol)


def latest_news(limit=10, symbol=None):
    init_db()
    con = _db()
    cutoff = time.time() - NEWS_MAX_AGE_HOURS * 3600
    if symbol:
        assets = [symbol.upper().replace("/", "")]
        for asset in ASSET_TERMS:
            if assets[0].startswith(asset):
                assets.append(asset)
        clauses = " OR ".join("(',' || assets || ',') LIKE ?" for _ in assets)
        params = [cutoff] + [f"%,{a},%" for a in assets]
        rows = con.execute(f"SELECT title,source,url,published,summary,assets,sentiment,impact FROM news WHERE fetched_at>=? AND ({clauses}) ORDER BY fetched_at DESC LIMIT ?", params + [limit]).fetchall()
    else:
        rows = con.execute("SELECT title,source,url,published,summary,assets,sentiment,impact FROM news WHERE fetched_at>=? ORDER BY fetched_at DESC LIMIT ?", (cutoff, limit)).fetchall()
    con.close()
    keys = ["title","source","url","published","summary","assets","sentiment","impact"]
    return [dict(zip(keys, row)) for row in rows]


def analyze_news(news):
    news = news or []
    positive = sum(1 for x in news if x.get("sentiment") == "positive")
    negative = sum(1 for x in news if x.get("sentiment") == "negative")
    neutral = sum(1 for x in news if x.get("sentiment") == "neutral")
    if positive > negative:
        direction = "positive"
    elif negative > positive:
        direction = "negative"
    else:
        direction = "mixed" if news else "none"
    return {"count": len(news), "positive": positive, "negative": negative, "neutral": neutral, "direction": direction,
            "summary": "لا توجد أخبار مرتبطة." if not news else f"الأخبار المرتبطة: {positive} إيجابية، {negative} سلبية، {neutral} محايدة. التصنيف آلي بالكلمات المفتاحية."}
