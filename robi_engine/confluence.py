"""ROBI Confluence Engine v02.

Combines already-calculated ROBI evidence into a transparent
agreement/conflict view.

This module is analysis-only:
- no real orders
- no buy/sell command
- no trading execution

Compatibility:
- build_confluence(snapshot) is the primary API.
- classify(snapshot) is kept as a compatibility alias for older app versions.
"""


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _unique(items):
    return list(dict.fromkeys(items))


def build_confluence(snapshot):
    """Build a structured agreement/conflict summary from ROBI evidence."""
    explanation = snapshot.get("explainability") or {}

    bullish = list(explanation.get("bullish") or [])
    bearish = list(explanation.get("bearish") or [])
    neutral = list(explanation.get("neutral") or [])
    warnings = list(explanation.get("warnings") or [])

    conflicts = []
    supporting = []

    trend = str(snapshot.get("trend") or "unknown").lower()
    state = str(snapshot.get("state") or "WAIT").upper()

    if trend == "up" and bearish:
        conflicts.append("الاتجاه العام صاعد، لكن توجد أدلة هابطة.")
    if trend == "down" and bullish:
        conflicts.append("الاتجاه العام هابط، لكن توجد أدلة صاعدة.")

    indicators = snapshot.get("indicators") or {}
    rsi = _num(indicators.get("rsi14"))
    stoch = _num(indicators.get("stochastic14"))

    macd = indicators.get("macd") or {}
    if isinstance(macd, dict):
        macd_line = _num(macd.get("line"))
    else:
        macd_line = _num(macd)

    if trend == "up" and rsi is not None and rsi < 50:
        conflicts.append(f"الاتجاه صاعد، لكن RSI تحت 50 ({rsi:.2f}).")
    if trend == "down" and rsi is not None and rsi > 50:
        conflicts.append(f"الاتجاه هابط، لكن RSI فوق 50 ({rsi:.2f}).")

    if trend == "up" and macd_line is not None and macd_line < 0:
        conflicts.append(f"الاتجاه صاعد، لكن MACD سالب ({macd_line:.6g}).")
    if trend == "down" and macd_line is not None and macd_line > 0:
        conflicts.append(f"الاتجاه هابط، لكن MACD موجب ({macd_line:.6g}).")

    if stoch is not None and stoch >= 80:
        warnings.append(f"Stochastic مرتفع ({stoch:.2f})")
    elif stoch is not None and stoch <= 20:
        warnings.append(f"Stochastic منخفض ({stoch:.2f})")

    ticker = snapshot.get("ticker") or {}
    price = _num(ticker.get("lastPrice"))

    if price is not None and price > 0:
        resistances = [_num(x) for x in (snapshot.get("resistance") or [])]
        supports = [_num(x) for x in (snapshot.get("support") or [])]

        resistances = [x for x in resistances if x is not None and x >= price]
        supports = [x for x in supports if x is not None and x <= price]

        if resistances:
            nearest = min(resistances)
            if (nearest - price) / price <= 0.03:
                warnings.append("السعر قريب نسبيًا من المقاومة.")

        if supports:
            nearest = max(supports)
            if (price - nearest) / price <= 0.03:
                warnings.append("السعر قريب نسبيًا من الدعم.")

    volume = snapshot.get("volume") or {}
    relative = _num(volume.get("relative"))

    if relative is not None and relative < 0.5:
        warnings.append(f"الحجم منخفض نسبيًا ({relative:.2f}).")

    bullish = _unique(bullish)
    bearish = _unique(bearish)
    neutral = _unique(neutral)
    warnings = _unique(warnings)
    conflicts = _unique(conflicts)

    if trend == "up":
        supporting = bullish[:8]
    elif trend == "down":
        supporting = bearish[:8]
    else:
        supporting = (bullish + bearish)[:8]

    if conflicts:
        agreement = (
            "يوجد توافق جزئي مع تعارضات واضحة؛ "
            "يجب قراءة الأدلة كحزمة واحدة."
        )
    elif bullish and not bearish:
        agreement = (
            "الأدلة الصاعدة متوافقة نسبيًا، "
            "مع بقاء التحذيرات منفصلة."
        )
    elif bearish and not bullish:
        agreement = (
            "الأدلة الهابطة متوافقة نسبيًا، "
            "مع بقاء التحذيرات منفصلة."
        )
    else:
        agreement = "الأدلة مختلطة أو غير كافية لتكوين توافق واضح."

    return {
        "state": state,
        "trend": trend,
        "bullish_count": len(bullish),
        "bearish_count": len(bearish),
        "neutral_count": len(neutral),
        "warning_count": len(warnings),
        "agreement": agreement,
        "supporting": supporting,
        "conflicts": conflicts,
        "warnings": warnings,
    }


# Compatibility alias required by the currently deployed ROBI app.
classify = build_confluence
