from datetime import datetime, timezone

_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
}


def _to_timestamp(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        # Kraken timestamps are seconds; very large values are milliseconds.
        value = float(value)
        if value > 10_000_000_000:
            value /= 1000.0
        return value

    text = str(value).strip()
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        pass

    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _completed_indexes(timestamps, timeframe, now=None):
    if not timestamps or not timeframe:
        return list(range(len(timestamps)))

    seconds = _TIMEFRAME_SECONDS.get(str(timeframe).lower())
    if not seconds:
        return list(range(len(timestamps)))

    now_ts = _to_timestamp(now) if now is not None else datetime.now(timezone.utc).timestamp()
    completed = []

    for i, ts in enumerate(timestamps):
        start = _to_timestamp(ts)
        if start is None:
            continue
        if start + seconds <= now_ts:
            completed.append(i)

    return completed


def relative_volume(volumes, n=20, timestamps=None, timeframe=None, now=None):
    if not volumes:
        return None

    if timestamps is not None and timeframe is not None:
        indexes = _completed_indexes(timestamps, timeframe, now=now)
        values = [volumes[i] for i in indexes if i < len(volumes) and volumes[i] is not None]
    else:
        values = [v for v in volumes if v is not None]

    if len(values) < n + 1:
        return None

    # The newest completed candle is the one being evaluated.
    current = float(values[-1])
    history = [float(v) for v in values[-n-1:-1]]
    baseline = sum(history) / len(history)

    return None if baseline <= 0 else current / baseline


def volume_snapshot(volumes, n=20, timestamps=None, timeframe=None, now=None):
    if not volumes:
        return {
            "current": None,
            "relative": None,
            "spike": False,
            "source": "none",
            "completed_candles": 0,
        }

    if timestamps is not None and timeframe is not None:
        indexes = _completed_indexes(timestamps, timeframe, now=now)
        values = [volumes[i] for i in indexes if i < len(volumes) and volumes[i] is not None]
        source = "completed_candles"
    else:
        values = [v for v in volumes if v is not None]
        source = "raw_candles"

    if not values:
        return {
            "current": None,
            "relative": None,
            "spike": False,
            "source": source,
            "completed_candles": 0,
        }

    current = float(values[-1])
    rv = relative_volume(
        values,
        n=n,
        timestamps=None,
        timeframe=None,
        now=now,
    )

    return {
        "current": current,
        "relative": rv,
        "spike": bool(rv is not None and rv >= 2.0),
        "source": source,
        "completed_candles": len(values),
    }
