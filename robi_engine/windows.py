from .models import Signal

def rising_window(prev, cur):
    # Window requires no shadow overlap: current low above prior high.
    if cur.low > prev.high:
        return {"type":"rising_window","bottom":prev.high,"top":cur.low,
                "direction":"bullish","role":"support"}
def falling_window(prev, cur):
    if cur.high < prev.low:
        return {"type":"falling_window","bottom":cur.high,"top":prev.low,
                "direction":"bearish","role":"resistance"}
def detect_windows(candles):
    out=[]
    for p,c in zip(candles,candles[1:]):
        x=rising_window(p,c) or falling_window(p,c)
        if x: out.append(x)
    return out
