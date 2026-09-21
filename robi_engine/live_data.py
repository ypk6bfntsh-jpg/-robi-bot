import requests
from .models import Candle

BASE='https://api.binance.com'

def get_klines(symbol, interval='15m', limit=200):
    r=requests.get(BASE+'/api/v3/klines',params={'symbol':symbol.upper(),'interval':interval,'limit':limit},timeout=15)
    r.raise_for_status()
    out=[]
    for x in r.json():
        out.append(Candle(float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5]),str(x[0])))
    return out

def get_ticker(symbol):
    r=requests.get(BASE+'/api/v3/ticker/24hr',params={'symbol':symbol.upper()},timeout=15); r.raise_for_status(); return r.json()

def get_recent_trades(symbol, limit=100):
    r=requests.get(BASE+'/api/v3/aggTrades',params={'symbol':symbol.upper(),'limit':limit},timeout=15); r.raise_for_status()
    rows=[]
    for x in r.json():
        # m=True means buyer is market maker; taker side is therefore sell in this representation.
        rows.append({'price':float(x['p']),'qty':float(x['q']),'buyer_maker':bool(x['m']),'side':'SELL' if x['m'] else 'BUY','time':x['T']})
    return rows
