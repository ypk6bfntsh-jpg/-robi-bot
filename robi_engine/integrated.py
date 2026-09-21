import json, sqlite3, time
from .analysis_engine import analyze
from .live_data import get_klines, get_ticker, get_recent_trades
from .news_engine import fetch_news, latest_news, init_db


def analyze_live(symbol, timeframe='15m', limit=200):
    init_db(); candles=get_klines(symbol,timeframe,limit); snap=analyze(symbol,timeframe,candles)
    ticker=get_ticker(symbol); news=latest_news(10)
    snap.news=news
    snap_dict=snap.to_dict(); snap_dict['ticker']=ticker
    snap_dict['trade_flow']=get_recent_trades(symbol,100)
    return snap_dict

def save_analysis(snapshot):
    con=sqlite3.connect('robi.db')
    con.execute('INSERT INTO analysis_events(ts,symbol,timeframe,state,trend,patterns,evidence,news_count,price,expected,outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
      (time.time(),snapshot['symbol'],snapshot['timeframe'],snapshot['state'],snapshot['trend'],json.dumps(snapshot['patterns'],ensure_ascii=False),json.dumps(snapshot['evidence'],ensure_ascii=False),len(snapshot.get('news',[])),float(snapshot['ticker'].get('lastPrice',0)),snapshot['state'],''))
    con.commit(); con.close()

def trade_flow_summary(rows):
    buy=sum(x['qty']*x['price'] for x in rows if x['side']=='BUY'); sell=sum(x['qty']*x['price'] for x in rows if x['side']=='SELL')
    total=buy+sell
    return {'buy_notional':buy,'sell_notional':sell,'buy_share':buy/total if total else 0,'sell_share':sell/total if total else 0,'trades':len(rows)}
