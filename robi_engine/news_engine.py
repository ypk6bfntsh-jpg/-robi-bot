import sqlite3
import hashlib
import html
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import requests


DB_PATH = "robi_news.db"
RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# كلمات تصنيف بسيطة وشفافة. لا تعتمد على كلمة واحدة وحدها متى أمكن.
POSITIVE_TERMS = {
    "beats estimates": 3, "beat estimates": 3, "record revenue": 3,
    "record profit": 3, "strong earnings": 2, "strong results": 2,
    "raises outlook": 3, "raised outlook": 3, "raises guidance": 3,
    "raised guidance": 3, "upgrade": 2, "upgraded": 2,
    "buyback": 2, "dividend": 1, "growth": 1, "surge": 2,
    "rises": 1, "rising": 1, "gains": 1, "gain": 1,
    "partnership": 1, "contract": 1, "demand": 1,
}

NEGATIVE_TERMS = {
    "misses estimates": 3, "missed estimates": 3, "weak earnings": 2,
    "weak results": 2, "lowers outlook": 3, "lowered outlook": 3,
    "lowers guidance": 3, "lowered guidance": 3, "downgrade": 2,
    "downgraded": 2, "lawsuit": 2, "investigation": 2,
    "probe": 2, "recall": 2, "cut jobs": 2, "layoffs": 2,
    "falls": 1, "falling": 1, "drops": 1, "drop": 1,
    "decline": 1, "declines": 1, "warning": 1,
}

# كلمات لا نصنفها سلبية بمفردها لأنها قد تظهر في خبر إيجابي أو محايد.
AR_TERM_LABELS = {
    "rises": "ارتفاع السهم",
    "rising": "ارتفاع",
    "gains": "مكاسب",
    "gain": "مكسب",
    "growth": "نمو",
    "demand": "طلب قوي",
    "adoption": "زيادة التبني",
    "partnership": "شراكة",
    "contract": "عقد",
    "upgrade": "ترقية التقييم",
    "upgraded": "ترقية التقييم",
    "dividend": "توزيعات أرباح",
    "buyback": "إعادة شراء الأسهم",
    "record revenue": "إيرادات قياسية",
    "record profit": "أرباح قياسية",
    "strong earnings": "نتائج مالية قوية",
    "strong results": "نتائج قوية",
    "beats estimates": "تجاوز التوقعات",
    "beat estimates": "تجاوز التوقعات",
    "raises outlook": "رفع التوقعات",
    "raised outlook": "رفع التوقعات",
    "raises guidance": "رفع التوجيهات",
    "raised guidance": "رفع التوجيهات",
    "falls": "انخفاض السهم",
    "falling": "انخفاض",
    "drops": "تراجع السهم",
    "drop": "تراجع",
    "decline": "تراجع",
    "declines": "تراجع",
    "warning": "تحذير",
    "downgrade": "خفض التقييم",
    "downgraded": "خفض التقييم",
    "lawsuit": "دعوى قضائية",
    "investigation": "تحقيق",
    "probe": "تحقيق",
    "recall": "استدعاء منتج",
    "cut jobs": "خفض الوظائف",
    "layoffs": "تسريح موظفين",
}

IGNORE_ALONE = {
    "fear", "fears", "fearing", "concern", "concerns", "concerned",
    "risk", "risks", "ai", "artificial intelligence",
}


def _parse_published(value):
    """تحويل وقت الخبر إلى وقت UTC. يدعم RFC822 وISO8601."""
    if not value:
        return None
    value = str(value).strip()
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def _is_fresh(item, max_age_hours=24):
    """هل الخبر حديث بما يكفي للتحليل الحالي؟"""
    dt = _parse_published(item.get("published"))
    if dt is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    return 0 <= age_seconds <= max_age_hours * 3600

def fresh_news(rows, max_age_hours=24, limit=10):
    """إرجاع الأخبار الحديثة فقط، مرتبة من الأحدث للأقدم."""
    fresh = [row for row in (rows or []) if _is_fresh(row, max_age_hours)]
    fresh.sort(
        key=lambda row: _parse_published(row.get("published")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return fresh[:limit]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT UNIQUE,
            published TEXT,
            source TEXT,
            description TEXT,
            query TEXT,
            sentiment TEXT,
            confidence REAL,
            sentiment_ar TEXT,
            confidence_ar TEXT,
            reason_ar TEXT,
            created_at TEXT
        )
    """)
    # دعم قواعد البيانات القديمة بدون حذف البيانات.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(news)").fetchall()}
    additions = {
        "confidence": "REAL",
        "sentiment_ar": "TEXT",
        "confidence_ar": "TEXT",
        "reason_ar": "TEXT",
        "impact_ar": "TEXT",
        "created_at": "TEXT",
        "query": "TEXT",
    }
    for col, typ in additions.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE news ADD COLUMN {col} {typ}")
    conn.commit()
    conn.close()

def _clean(value):
    if value is None:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", " ", str(value))).strip()

def _classify(title, description=""):
    """
    تصنيف سياقي مبسط:
    - لا يعتمد على كلمة واحدة فقط.
    - يجمع الإشارات الإيجابية والسلبية.
    - يعطي درجة ثقة.
    - يحدد الأثر المحتمل على الأصل.
    """
    title_text = _clean(title)
    desc_text = _clean(description)
    text_all = f"{title_text} {desc_text}".lower()
    title_low = title_text.lower()

    pos_score = 0
    neg_score = 0
    pos_hits = []
    neg_hits = []

    for term, weight in POSITIVE_TERMS.items():
        if term in text_all:
            # العنوان أهم من الوصف، لذلك نعطيه وزنًا أعلى قليلًا.
            w = weight + (1 if term in title_low else 0)
            pos_score += w
            pos_hits.append(term)

    for term, weight in NEGATIVE_TERMS.items():
        if term in text_all:
            w = weight + (1 if term in title_low else 0)
            neg_score += w
            neg_hits.append(term)

    # عبارات تتطلب سياقًا ولا تُعتبر سلبية/إيجابية بمفردها.
    context_positive = [
        "bottleneck", "demand", "adoption", "next generation",
        "ai infrastructure", "physical ai", "data center",
    ]
    context_negative = [
        "fears", "fearing", "concerns", "concerned", "risk",
    ]

    # "bottleneck" مثلًا لا يعني تلقائيًا أن السهم سلبي.
    # إذا ظهر مع طلب/بنية تحتية/تبنٍ، نتركه محايدًا ما لم توجد إشارات أخرى.
    for term in context_positive:
        if term in text_all and term in title_low:
            if "demand" in text_all or "adoption" in text_all or "infrastructure" in text_all:
                pos_score += 1
                pos_hits.append("سياق داعم للنمو")

    for term in context_negative:
        if term in text_all:
            # لا نضيف سلبية إلا إذا ارتبطت بخسارة/هبوط/تحذير فعلي.
            if any(x in text_all for x in [
                "loss", "losses", "cut", "lower", "downgrade",
                "miss", "decline", "falls", "drop"
            ]):
                neg_score += 1
                neg_hits.append("مخاوف مرتبطة بمؤشر سلبي")

    if pos_score == 0 and neg_score == 0:
        return (
            "neutral", 0.55, "⚪ محايد", "متوسطة",
            "غير واضح",
            "لم تظهر إشارة كافية على اتجاه الخبر، لذلك تم تصنيفه محايدًا."
        )

    diff = pos_score - neg_score
    total = pos_score + neg_score

    if diff > 0:
        confidence = min(0.96, 0.62 + min(diff, 7) * 0.05)
        if pos_score >= 5 and diff >= 3:
            confidence = min(0.96, confidence + 0.04)
        reason = "توجد إشارات داعمة في الخبر"
        if pos_hits:
            reason += " مثل: " + "، ".join(_arabic_terms(pos_hits[:3]))
        if neg_hits:
            reason += " مع وجود بعض الإشارات المقابلة"
        impact = "داعم للسهم"
        return (
            "positive", confidence, "🟢 إيجابي",
            _confidence_ar(confidence), impact, reason + "."
        )

    if diff < 0:
        confidence = min(0.96, 0.62 + min(abs(diff), 7) * 0.05)
        if neg_score >= 5 and abs(diff) >= 3:
            confidence = min(0.96, confidence + 0.04)
        reason = "توجد إشارات سلبية في الخبر"
        if neg_hits:
            reason += " مثل: " + "، ".join(_arabic_terms(neg_hits[:3]))
        if pos_hits:
            reason += " مع وجود بعض الإشارات المقابلة"
        impact = "ضاغط على السهم"
        return (
            "negative", confidence, "🔴 سلبي",
            _confidence_ar(confidence), impact, reason + "."
        )

    return (
        "neutral", 0.60, "⚪ محايد", "متوسطة",
        "غير واضح",
        "الإشارات الإيجابية والسلبية متقاربة، لذلك لا يوجد اتجاه واضح."
    )


def _arabic_terms(terms):
    translated = []
    for term in terms:
        translated.append(AR_TERM_LABELS.get(str(term).lower(), "إشارة مرتبطة بالخبر"))
    # إزالة التكرار مع الحفاظ على الترتيب
    return list(dict.fromkeys(translated))

def _confidence_ar(value):
    value = float(value or 0)
    if value >= 0.80:
        return "مرتفعة"
    if value >= 0.65:
        return "متوسطة"
    return "منخفضة"

def _parse_rss(xml_text, query):
    root = ET.fromstring(xml_text)
    rows = []
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title"))
        link = _clean(item.findtext("link"))
        pub = _clean(item.findtext("pubDate"))
        desc = _clean(item.findtext("description"))
        source_el = item.find("source")
        source = _clean(source_el.text if source_el is not None else "")
        if not title or not link:
            continue
        sentiment, confidence, sentiment_ar, confidence_ar, impact_ar, reason_ar = _classify(title, desc)
        rows.append({
            "title": title,
            "url": link,
            "published": pub,
            "source": source or "Google News",
            "description": desc,
            "query": query,
            "sentiment": sentiment,
            "confidence": confidence,
            "sentiment_ar": sentiment_ar,
            "confidence_ar": confidence_ar,
            "reason_ar": reason_ar,
        })
    return rows

def _save(rows):
    if not rows:
        return 0
    init_db()
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    for row in rows:
        try:
            conn.execute("""
                INSERT INTO news
                (title,url,published,source,description,query,sentiment,confidence,
                 sentiment_ar,confidence_ar,reason_ar,impact_ar,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                  title=excluded.title,
                  published=excluded.published,
                  source=excluded.source,
                  description=excluded.description,
                  query=excluded.query,
                  sentiment=excluded.sentiment,
                  confidence=excluded.confidence,
                  sentiment_ar=excluded.sentiment_ar,
                  confidence_ar=excluded.confidence_ar,
                  reason_ar=excluded.reason_ar,
                  impact_ar=excluded.impact_ar
            """, (
                row["title"], row["url"], row["published"], row["source"],
                row["description"], row["query"], row["sentiment"],
                row["confidence"], row["sentiment_ar"],
                row["confidence_ar"], row["reason_ar"], row.get("impact_ar", "غير واضح"), now
            ))
            saved += 1
        except sqlite3.Error as exc:
            print("News DB save warning:", exc)
            continue
    conn.commit()
    conn.close()
    return saved

def fetch_news(limit=20, query="NVIDIA OR NVDA", symbol=None):
    """جلب أخبار حديثة من Google News RSS وتخزينها."""
    init_db()
    try:
        if symbol:
            query = symbol
        url = RSS_URL.format(query=quote_plus(query))
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "ROBI-News-Engine/3.0"}
        )
        response.raise_for_status()
        rows = _parse_rss(response.text, query)
        _save(rows[:limit])
        return rows[:limit]
    except Exception:
        return []

def latest_news(limit=10, query=None, max_age_hours=None):
    """قراءة الأخبار المخزنة. لا تعتمد على إعادة الجلب."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if query:
        rows = conn.execute("""
            SELECT * FROM news
            WHERE lower(query) LIKE ?
               OR lower(title) LIKE ?
            ORDER BY id DESC LIMIT ?
        """, (f"%{query.lower()}%", f"%{query.lower()}%", int(limit))).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM news ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    if max_age_hours is not None:
        result = fresh_news(result, max_age_hours=max_age_hours, limit=limit)
    return result

def analyze_news(rows):
    """تلخيص اتجاه الأخبار مع دعم البيانات القديمة والجديدة."""
    rows = rows or []
    if not rows:
        return {
            "direction": "none",
            "direction_ar": "لا توجد أخبار",
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "confidence": 0.0,
            "impact_ar": "غير واضح",
        }

    positive = 0
    negative = 0
    neutral = 0
    confidences = []

    for r in rows:
        sentiment = str(r.get("sentiment") or "").strip().lower()
        sentiment_ar = str(r.get("sentiment_ar") or "").strip()

        # دعم السجلات القديمة التي قد لا تحتوي sentiment.
        if sentiment not in {"positive", "negative", "neutral"}:
            if "إيجابي" in sentiment_ar:
                sentiment = "positive"
            elif "سلبي" in sentiment_ar:
                sentiment = "negative"
            elif "محايد" in sentiment_ar:
                sentiment = "neutral"
            else:
                title = str(r.get("title") or "").lower()
                if any(x in title for x in ("rises", "growth", "beats", "upgrade", "dividend", "gains")):
                    sentiment = "positive"
                elif any(x in title for x in ("falls", "drops", "downgrade", "misses", "lawsuit")):
                    sentiment = "negative"
                else:
                    sentiment = "neutral"

        if sentiment == "positive":
            positive += 1
        elif sentiment == "negative":
            negative += 1
        else:
            neutral += 1

        try:
            confidences.append(float(r.get("confidence") or 0))
        except (TypeError, ValueError):
            pass

    total = positive + negative + neutral

    if positive > negative:
        direction = "positive"
        direction_ar = "إيجابي"
        impact_ar = "داعم للسهم"
    elif negative > positive:
        direction = "negative"
        direction_ar = "سلبي"
        impact_ar = "ضاغط على السهم"
    elif positive == negative and positive > 0:
        direction = "mixed"
        direction_ar = "مختلط"
        impact_ar = "متضارب"
    else:
        direction = "none"
        direction_ar = "محايد"
        impact_ar = "غير واضح"

    confidence = round(sum(confidences) / len(confidences), 2) if confidences else (
        round(max(positive, negative) / total, 2) if total else 0.0
    )

    return {
        "direction": direction,
        "direction_ar": direction_ar,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "confidence": confidence,
        "impact_ar": impact_ar,
    }


def build_news_impact(rows):
    """يبني ملخصًا عربيًا للأخبار لاستخدامه في التحليل والتوافق."""
    rows = rows or []
    positive = sum(1 for r in rows if r.get("sentiment") == "positive")
    negative = sum(1 for r in rows if r.get("sentiment") == "negative")
    neutral = sum(1 for r in rows if r.get("sentiment") == "neutral")

    if positive > negative:
        direction = "positive"
        direction_ar = "إيجابي"
        impact_ar = "داعم للسهم"
    elif negative > positive:
        direction = "negative"
        direction_ar = "سلبي"
        impact_ar = "ضاغط على السهم"
    elif positive == negative and positive > 0:
        direction = "mixed"
        direction_ar = "مختلط"
        impact_ar = "متضارب"
    else:
        direction = "none"
        direction_ar = "محايد"
        impact_ar = "غير واضح"

    confidences = [float(r.get("confidence") or 0) for r in rows]
    confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

    return {
        "direction": direction,
        "direction_ar": direction_ar,
        "impact_ar": impact_ar,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "confidence": confidence,
    }


def news_stats():
    """إحصاءات بسيطة تفصل بين السجل التاريخي والأخبار الحديثة."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM news ORDER BY id DESC").fetchall()
    conn.close()

    all_rows = [dict(r) for r in rows]
    fresh = fresh_news(all_rows, 24, limit=10000)
    return {
        "total_stored": len(all_rows),
        "fresh_24h": len(fresh),
        "old": max(0, len(all_rows) - len(fresh)),
    }


def search_news(query, limit=10, max_age_hours=None):
    """جلب أخبار تخص أصلًا محددًا، ثم إرجاع المخزن منها."""
    rows = fetch_news(limit=limit, query=query)
    if rows:
        return rows
    return latest_news(limit=limit, query=query, max_age_hours=max_age_hours)

init_db()
