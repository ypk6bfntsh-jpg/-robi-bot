def sma(values, n):
    if n<=0 or len(values)<n:return None
    return sum(values[-n:])/n

def ema(values,n):
    if n<=0 or len(values)<n:return None
    k=2/(n+1); e=sum(values[:n])/n
    for x in values[n:]: e=x*k+e*(1-k)
    return e

def rsi(closes,n=14):
    if len(closes)<=n:return None
    gains=[]; losses=[]
    for a,b in zip(closes[-n-1:-1],closes[-n:]):
        d=b-a; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains)/n; al=sum(losses)/n
    if al==0:return 100.0
    return 100-(100/(1+ag/al))

def stochastic(highs,lows,closes,n=14):
    if len(closes)<n:return None
    hi=max(highs[-n:]); lo=min(lows[-n:])
    if hi==lo:return 50.0
    return (closes[-1]-lo)/(hi-lo)*100

def macd(closes,fast=12,slow=26,signal=9):
    if len(closes)<slow+signal:return None
    fastv=ema(closes,fast); slowv=ema(closes,slow)
    line=fastv-slowv
    # A full signal series is preferable; this is a compact snapshot.
    return {"line":line,"fast_period":fast,"slow_period":slow,"signal_period":signal}
