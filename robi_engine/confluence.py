"""ROBI Confluence Engine v01.

Combines already-calculated ROBI evidence into a transparent
agreement/conflict view.

This layer does NOT place orders and does NOT create buy/sell commands.
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

    trend = str(snapshot.get("trend") or "unknown").lower()
    state = str(snapshot.get("state") or "WAIT").upper()

    # --------------------------------------------------------
    # Cross-check trend against existing evidence
    # --------------------------------------------------------

    if trend == "up" and bearish:
        conflicts.append(
            "الاتجاه العام صاعد، لكن توجد أدلة هابطة."
        )

    if trend == "down" and bullish:
        conflicts.append(
            "الاتجاه العام هابط، لكن توجد أدلة صاعدة."
        )

    # --------------------------------------------------------
    # Momentum cross-check
    # --------------------------------------------------------

    indicators = snapshot.get("indicators") or {}

    rsi = _num(indicators.get("rsi14"))
    stoch = _num(indicators.get("stochastic14"))

    macd = indicators.get("macd") or {}

    macd_line = _num(
        macd.get("line")
        if isinstance(macd, dict)
        else None
    )

    if trend == "up" and rsi is not None and rsi < 50:
        conflicts.append(
            f"الاتجاه صاعد، لكن RSI تحت 50 ({rsi:.2f})."
        )

    if trend == "down" and rsi is not None and rsi > 50:
        conflicts.append(
            f"الاتجاه هابط، لكن RSI فوق 50 ({rsi:.2f})."
        )

    if trend == "up" and macd_line is not None and macd_line < 0:
        conflicts.append(
            f"الاتجاه صاعد، لكن MACD سالب ({macd_line:.6g})."
        )

    if trend == "down" and macd_line is not None and macd_line > 0:
        conflicts.append(
            f"الاتجاه هابط، لكن MACD موجب ({macd_line:.6g})."
        )

    # --------------------------------------------------------
    # Stochastic context
    # --------------------------------------------------------

    if stoch is not None:

        if stoch >= 80:
            warnings.append(
                f"Stochastic مرتفع ({stoch:.2f})"
            )

        elif stoch <= 20:
            warnings.append(
                f"Stochastic منخفض ({stoch:.2f})"
            )

    # --------------------------------------------------------
    # Support / Resistance context
    # --------------------------------------------------------

    ticker = snapshot.get("ticker") or {}

    price = _num(
        ticker.get("lastPrice")
    )

    if price is not None and price > 0:

        resistances = [
            _num(x)
            for x in (snapshot.get("resistance") or [])
        ]

        supports = [
            _num(x)
            for x in (snapshot.get("support") or [])
        ]

        resistances = [
            x for x in resistances
            if x is not None and x >= price
        ]

        supports = [
            x for x in supports
            if x is not None and x <= price
        ]

        if resistances:

            nearest_resistance = min(resistances)

            if (
                nearest_resistance - price
            ) / price <= 0.03:

                warnings.append(
                    "السعر قريب نسبيًا من المقاومة."
                )

        if supports:

            nearest_support = max(supports)

            if (
                price - nearest_support
            ) / price <= 0.03:

                warnings.append(
                    "السعر قريب نسبيًا من الدعم."
                )

    # --------------------------------------------------------
    # Volume context
    # --------------------------------------------------------

    volume = snapshot.get("volume") or {}

    relative = _num(
        volume.get("relative")
    )

    if relative is not None and relative < 0.5:

        warnings.append(
            f"الحجم منخفض نسبيًا ({relative:.2f})."
        )

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    bullish = _unique(bullish)
    bearish = _unique(bearish)
    neutral = _unique(neutral)
    warnings = _unique(warnings)
    conflicts = _unique(conflicts)

    # --------------------------------------------------------
    # Evidence supporting the current broad direction
    # --------------------------------------------------------

    if trend == "up":

        supporting = bullish[:8]

    elif trend == "down":

        supporting = bearish[:8]

    else:

        supporting = (
            bullish + bearish
        )[:8]

    # --------------------------------------------------------
    # Overall agreement description
    # --------------------------------------------------------

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

        agreement = (
            "الأدلة مختلطة أو غير كافية "
            "لتكوين توافق واضح."
        )

    # --------------------------------------------------------
    # Final Confluence object
    # --------------------------------------------------------

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
