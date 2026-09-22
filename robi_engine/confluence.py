"""ROBI Confluence Engine v03.

Robust compatibility layer for ROBI analysis snapshots.
- Accepts dict/list variants from older analysis modules.
- No real orders.
- No buy/sell command.
"""

def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _items(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _unique(items):
    return list(dict.fromkeys(str(x) for x in items if x is not None))


def _indicator_value(indicators, key):
    indicators = _mapping(indicators)
    value = indicators.get(key)
    if isinstance(value, (list, tuple)):
        return value[-1] if value else None
    return value


def _macd_line(indicators):
    macd = _indicator_value(indicators, "macd")
    if isinstance(macd, dict):
        return _num(macd.get("line"))
    if isinstance(macd, (list, tuple)):
        if not macd:
            return None
        # Support [line, signal, histogram] and [{"line": ...}, ...]
        first = macd[-1]
        if isinstance(first, dict):
            return _num(first.get("line"))
        return _num(first)
    return _num(macd)


def build_confluence(snapshot):
    """Build transparent agreement/conflict information from ROBI evidence."""
    if not isinstance(snapshot, dict):
        return {
            "state": "WAIT",
            "trend": "unknown",
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "warning_count": 1,
            "agreement": "بيانات التحليل غير صالحة أو غير مكتملة.",
            "supporting": [],
            "conflicts": [],
            "warnings": ["صيغة snapshot غير متوقعة."],
        }

    explanation = _mapping(snapshot.get("explainability"))

    bullish = _items(explanation.get("bullish"))
    bearish = _items(explanation.get("bearish"))
    neutral = _items(explanation.get("neutral"))
    # Confluence warnings are independent from Explainability warnings.
    # Explainability already renders its own warnings, so copying them here
    # creates duplicate lines.
    warnings = []

    conflicts = []
    supporting = []

    trend = str(snapshot.get("trend") or "unknown").lower()
    state = str(snapshot.get("state") or "WAIT").upper()

    if trend == "up" and bearish:
        conflicts.append("الاتجاه العام صاعد، لكن توجد أدلة هابطة.")
    if trend == "down" and bullish:
        conflicts.append("الاتجاه العام هابط، لكن توجد أدلة صاعدة.")

    indicators = snapshot.get("indicators")
    rsi = _num(_indicator_value(indicators, "rsi14"))
    stoch = _num(_indicator_value(indicators, "stochastic14"))
    macd_line = _macd_line(indicators)

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

    ticker = _mapping(snapshot.get("ticker"))
    price = _num(ticker.get("lastPrice"))

    if price is not None and price > 0:
        resistances = [_num(x) for x in _items(snapshot.get("resistance"))]
        supports = [_num(x) for x in _items(snapshot.get("support"))]

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

    volume = _mapping(snapshot.get("volume"))
    current_volume = _num(volume.get("current"))
    relative = _num(volume.get("relative"))
    if current_volume is None or current_volume <= 0 or relative is None or relative <= 0:
        warnings.append("بيانات الحجم غير متاحة أو غير صالحة لهذه اللقطة.")
    elif relative < 0.5:
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
        agreement = "يوجد توافق جزئي مع تعارضات واضحة؛ يجب قراءة الأدلة كحزمة واحدة."
    elif bullish and not bearish:
        agreement = "الأدلة الصاعدة متوافقة نسبيًا، مع بقاء التحذيرات منفصلة."
    elif bearish and not bullish:
        agreement = "الأدلة الهابطة متوافقة نسبيًا، مع بقاء التحذيرات منفصلة."
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


# Compatibility API used by deployed/older ROBI app versions.
classify = build_confluence
