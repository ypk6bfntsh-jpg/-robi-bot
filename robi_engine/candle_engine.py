from .models import Candle

def candle_from_dict(row):
    return Candle(float(row["open"]),float(row["high"]),float(row["low"]),float(row["close"]),
                  None if row.get("volume") is None else float(row["volume"]),row.get("timestamp"))

def anatomy(c):
    return {"body":c.body,"range":c.range,"upper_shadow":c.upper_shadow,"lower_shadow":c.lower_shadow,
            "bullish":c.bullish,"bearish":c.bearish,
            "body_ratio": c.body/c.range if c.range else 0}

def is_doji(c, tolerance=0.10):
    # Engineering tolerance only; not attributed to Nison.
    return c.range > 0 and c.body/c.range <= tolerance

def is_spinning_top(c, max_body_ratio=0.35):
    return c.range > 0 and c.body/c.range <= max_body_ratio and not is_doji(c, 0.10)
