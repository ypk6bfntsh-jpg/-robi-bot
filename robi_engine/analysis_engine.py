from .models import MarketSnapshot, Evidence
from .market_structure import trend, levels
from .patterns import detect
from .windows import detect_windows
from .indicators import sma,ema,rsi,stochastic,macd
from .volume import volume_snapshot
from .confluence import classify

def analyze(symbol, timeframe, candles):
    closes=[c.close for c in candles]; highs=[c.high for c in candles]; lows=[c.low for c in candles]
    vols=[c.volume for c in candles if c.volume is not None]
    t=trend(closes)
    snap=MarketSnapshot(symbol,timeframe,candles[-1].timestamp if candles else None,trend=t,candles=candles)
    snap.patterns=detect(candles,t)
    snap.windows=detect_windows(candles)
    sup,res=levels(candles)
    snap.support=sup; snap.resistance=res
    snap.indicators={
        "sma20":sma(closes,20),"sma50":sma(closes,50),
        "ema20":ema(closes,20),"rsi14":rsi(closes,14),
        "stochastic14":stochastic(highs,lows,closes,14),
        "macd":macd(closes)
    }
    snap.volume=volume_snapshot(vols) if vols else {}
    for p in snap.patterns:
        d="bullish" if p.direction=="bullish" or p.direction=="bullish_warning" else ("bearish" if p.direction=="bearish" or p.direction=="bearish_warning" else "neutral")
        snap.evidence.append(Evidence("candlestick",p.name,d,p.notes))
    for w in snap.windows:
        snap.evidence.append(Evidence("window",w["type"],w["direction"],str(w)))
    c=classify(snap.evidence)
    snap.state=c["state"]
    return snap
