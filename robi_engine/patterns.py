from .models import Signal
from .candle_engine import is_doji

def _body(c): return max(c.body, c.range*0.001)

def hammer(c):
    if c.range<=0:return None
    b=_body(c)
    if c.lower_shadow>=2*b and c.upper_shadow<=b and max(c.open,c.close)>=c.low+.60*c.range:
        return Signal("Hammer","bullish","reversal",False,"Hammer-like structure; decline context and confirmation required.")
def hanging_man(c, prior_trend):
    s=hammer(c)
    if s and prior_trend in {"up","advance","bullish"}:
        return Signal("Hanging Man","bearish_warning","reversal",False,"Hammer-like structure after an advance.")
def shooting_star(c):
    if c.range<=0:return None
    b=_body(c)
    if c.upper_shadow>=2*b and c.lower_shadow<=b and min(c.open,c.close)<=c.low+.40*c.range:
        return Signal("Shooting Star","bearish","reversal",False,"Top-warning structure; advance context and confirmation required.")
def inverted_hammer(c):
    if c.range<=0:return None
    b=_body(c)
    if c.upper_shadow>=2*b and c.lower_shadow<=b and min(c.open,c.close)<=c.low+.40*c.range:
        return Signal("Inverted Hammer","bullish_warning","reversal",False,"Bottom-warning structure; confirmation required.")
def doji(c):
    if is_doji(c): return Signal("Doji","neutral","indecision",False,"Warning/transition clue; context and confirmation matter.")
def bullish_engulfing(p,c):
    if p.bearish and c.bullish and c.open<=p.close and c.close>=p.open:
        return Signal("Bullish Engulfing","bullish","reversal",False,"Bullish engulfing; decline context and confirmation required.")
def bearish_engulfing(p,c):
    if p.bullish and c.bearish and c.open>=p.close and c.close<=p.open:
        return Signal("Bearish Engulfing","bearish","reversal",False,"Bearish engulfing; advance context and confirmation required.")
def harami(p,c):
    if p.body>0 and c.body<p.body and min(p.open,p.close)<=min(c.open,c.close) and max(p.open,p.close)>=max(c.open,c.close):
        return Signal("Harami","neutral_warning","reversal","", "Small real body within prior large body.")
def harami_cross(p,c):
    if is_doji(c) and p.body>0 and min(p.open,p.close)<=c.close<=max(p.open,p.close):
        return Signal("Harami Cross","neutral_warning","reversal",False,"Harami with Doji; confirmation required.")
def piercing(p,c):
    midpoint=(p.open+p.close)/2
    if p.bearish and c.bullish and c.open<p.low and c.close>midpoint and c.close<p.open:
        return Signal("Piercing Pattern","bullish","reversal",False,"Piercing structure; resistance/context matter.")
def dark_cloud(p,c):
    midpoint=(p.open+p.close)/2
    if p.bullish and c.bearish and c.open>p.high and c.close<midpoint and c.close>p.open:
        return Signal("Dark Cloud Cover","bearish","reversal",False,"Dark Cloud structure; resistance/context matter.")
def tweezers_top(p,c):
    if abs(p.high-c.high) <= max(p.range,c.range)*0.02:
        return Signal("Tweezers Top","bearish_warning","reversal",False,"Repeated high area; minor signal unless reinforced.")
def tweezers_bottom(p,c):
    if abs(p.low-c.low) <= max(p.range,c.range)*0.02:
        return Signal("Tweezers Bottom","bullish_warning","reversal",False,"Repeated low area; minor signal unless reinforced.")

def detect(candles, prior_trend="unknown"):
    if not candles:return []
    c=candles[-1]; out=[]
    for s in [hammer(c),hanging_man(c,prior_trend),shooting_star(c),inverted_hammer(c),doji(c)]:
        if s: out.append(s)
    if len(candles)>=2:
        p=candles[-2]
        for s in [bullish_engulfing(p,c),bearish_engulfing(p,c),harami(p,c),harami_cross(p,c),
                  piercing(p,c),dark_cloud(p,c),tweezers_top(p,c),tweezers_bottom(p,c)]:
            if s: out.append(s)
    return out
