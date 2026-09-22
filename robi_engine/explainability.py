"""ROBI Explainability layer.

Builds a transparent, rule-based explanation from the indicators and context
already calculated by the analysis engine. It does not place orders or create
trading instructions.
"""


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_explainability(snapshot):
    indicators = snapshot.get("indicators") or {}
    trend = str(snapshot.get("trend") or "unknown").lower()
    state = str(snapshot.get("state") or "WAIT")
    price = _num((snapshot.get("ticker") or {}).get("lastPrice"))
    if price is None:
        candles = snapshot.get("candles") or []
        if candles:
            last = candles[-1]
            price = _num(last.get("close") if isinstance(last, dict) else getattr(last, "close", None))

    sma20 = _num(indicators.get("sma20"))
    sma50 = _num(indicators.get("sma50"))
    ema20 = _num(indicators.get("ema20"))
    rsi = _num(indicators.get("rsi14"))
    stoch = _num(indicators.get("stochastic14"))
    macd = indicators.get("macd") or {}
    macd_line = _num(macd.get("line") if isinstance(macd, dict) else None)

    bullish, bearish, warnings, neutral = [], [], [], []

    # Trend / moving-average structure.
    if trend == "up":
        bullish.append("الاتجاه العام صاعد")
    elif trend == "down":
        bearish.append("الاتجاه العام هابط")
    else:
        neutral.append("الاتجاه غير محسوم")

    if price is not None and sma20 is not None:
        (bullish if price > sma20 else bearish).append(
            "السعر فوق SMA20" if price > sma20 else "السعر تحت SMA20"
        )
    if price is not None and ema20 is not None:
        (bullish if price > ema20 else bearish).append(
            "السعر فوق EMA20" if price > ema20 else "السعر تحت EMA20"
        )
    if sma20 is not None and sma50 is not None:
        (bullish if sma20 > sma50 else bearish).append(
            "SMA20 أعلى من SMA50" if sma20 > sma50 else "SMA20 أدنى من SMA50"
        )

    # Momentum indicators: extremes are warnings, not automatic signals.
    if rsi is not None:
        if rsi >= 70:
            warnings.append(f"RSI مرتفع ({rsi:.2f})")
        elif rsi <= 30:
            warnings.append(f"RSI منخفض ({rsi:.2f}) وقد يشير إلى ضغط بيعي/احتمال ارتداد")
        elif rsi > 50:
            bullish.append(f"RSI فوق 50 ({rsi:.2f})")
        elif rsi < 50:
            bearish.append(f"RSI تحت 50 ({rsi:.2f})")
        else:
            neutral.append("RSI قريب من 50")

    if stoch is not None:
        if stoch >= 80:
            warnings.append(f"Stochastic مرتفع ({stoch:.2f})")
        elif stoch <= 20:
            warnings.append(f"Stochastic منخفض ({stoch:.2f}) وقد يعكس ضغطًا بيعيًا")
        elif stoch > 50:
            bullish.append(f"Stochastic فوق 50 ({stoch:.2f})")
        elif stoch < 50:
            bearish.append(f"Stochastic تحت 50 ({stoch:.2f})")

    if macd_line is not None:
        if macd_line > 0:
            bullish.append(f"MACD موجب ({macd_line:.6g})")
        elif macd_line < 0:
            bearish.append(f"MACD سالب ({macd_line:.6g})")
        else:
            neutral.append("MACD قريب من الصفر")

    # Existing candle/window evidence.
    for p in snapshot.get("patterns") or []:
        p = p if isinstance(p, dict) else {}
        name = p.get("name", "نمط شموعي")
        direction = str(p.get("direction", "")).lower()
        if "bullish" in direction:
            bullish.append(f"نمط شموعي صاعد: {name}")
        elif "bearish" in direction:
            bearish.append(f"نمط شموعي هابط: {name}")
        else:
            neutral.append(f"نمط شموعي محايد: {name}")

    for w in snapshot.get("windows") or []:
        direction = str(w.get("direction", "")).lower()
        role = str(w.get("role", "")).lower()
        name = w.get("type", "window")
        if direction == "bullish":
            bullish.append(f"Window صاعد ({role or name})")
        elif direction == "bearish":
            bearish.append(f"Window هابط ({role or name})")

    # Volume context.
    volume = snapshot.get("volume") or {}
    spike = bool(volume.get("spike"))
    relative = _num(volume.get("relative"))
    if spike:
        if trend == "up":
            bullish.append("ارتفاع واضح في الحجم مع اتجاه صاعد")
        elif trend == "down":
            bearish.append("ارتفاع واضح في الحجم مع اتجاه هابط")
        else:
            neutral.append("ارتفاع واضح في الحجم مع اتجاه غير محسوم")
    elif relative is not None and relative < 0.5:
        warnings.append(f"الحجم الحالي منخفض نسبيًا ({relative:.2f})")

    # Trade-flow context when available.
    flow = snapshot.get("trade_flow_summary") or {}
    buy_share = _num(flow.get("buy_share"))
    sell_share = _num(flow.get("sell_share"))
    if buy_share is not None and sell_share is not None and (buy_share + sell_share) > 0:
        if buy_share > sell_share:
            bullish.append(f"تدفق الصفقات يميل للشراء ({buy_share * 100:.1f}%)")
        elif sell_share > buy_share:
            bearish.append(f"تدفق الصفقات يميل للبيع ({sell_share * 100:.1f}%)")

    # Support/resistance context.
    supports = [_num(x) for x in (snapshot.get("support") or [])]
    resistances = [_num(x) for x in (snapshot.get("resistance") or [])]
    supports = [x for x in supports if x is not None]
    resistances = [x for x in resistances if x is not None]
    if price is not None and supports:
        nearest_support = max((x for x in supports if x <= price), default=None)
        if nearest_support is not None and price > 0 and (price - nearest_support) / price < 0.03:
            warnings.append("السعر قريب من الدعم")
    if price is not None and resistances:
        nearest_resistance = min((x for x in resistances if x >= price), default=None)
        if nearest_resistance is not None and price > 0 and (nearest_resistance - price) / price < 0.03:
            warnings.append("السعر قريب من المقاومة")

    # Data-quality warnings.
    zero_indicators = [k for k in ("sma20", "sma50", "ema20") if indicators.get(k) in (0, 0.0)]
    if zero_indicators:
        warnings.append("بعض المتوسطات ظهرت بصفر؛ يجب التحقق من كفاية/جودة البيانات التاريخية")

    # Deduplicate while preserving order.
    def uniq(items):
        return list(dict.fromkeys(items))

    bullish, bearish, warnings, neutral = map(uniq, (bullish, bearish, warnings, neutral))

    if state == "CONFLICT":
        summary = "أدلة صاعدة وهابطة موجودة معًا؛ الحالة تحتاج سياقًا إضافيًا ولا تعتمد على عامل واحد."
    elif state == "BULLISH_EVIDENCE":
        summary = "الأدلة الصاعدة الحالية أكثر اتساقًا مع حالة ROBI، مع إبقاء التحذيرات منفصلة."
    elif state == "BEARISH_EVIDENCE":
        summary = "الأدلة الهابطة الحالية أكثر اتساقًا مع حالة ROBI، مع إبقاء التحذيرات منفصلة."
    else:
        summary = "الأدلة الحالية لا تعطي اتجاهًا فنيًا واضحًا بما يكفي."

    return {
        "state": state,
        "bullish": bullish,
        "bearish": bearish,
        "warnings": warnings,
        "neutral": neutral,
        "counts": {
            "bullish": len(bullish),
            "bearish": len(bearish),
            "warnings": len(warnings),
            "neutral": len(neutral),
        },
        "summary": summary,
    }
