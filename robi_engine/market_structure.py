def trend(closes, lookback=20):
    if len(closes)<3:return "unknown"
    a=closes[-min(lookback,len(closes)):]
    if a[-1]>a[0]:return "up"
    if a[-1]<a[0]:return "down"
    return "sideways"

def levels(candles, window=20):
    if not candles:return [],[]
    c=candles[-window:]
    return [min(x.low for x in c)],[max(x.high for x in c)]

def change_of_polarity(price, old_level, direction):
    if direction=="up": return price>old_level
    if direction=="down": return price<old_level
    return False
