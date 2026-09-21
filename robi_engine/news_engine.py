import os, time, sqlite3, hashlib, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests

DB_PATH = os.getenv('ROBI_DB_PATH', 'robi.db')
NEWS_RSS = os.getenv('NEWS_RSS_URL', 'https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+binance&hl=en-US&gl=US&ceid=US:en')

def init_db():
    con=sqlite3.connect(DB_PATH)
    con.execute('''CREATE TABLE IF NOT EXISTS news_events(
      id TEXT PRIMARY KEY, title TEXT, source TEXT, url TEXT, published TEXT,
      query TEXT, fetched_at REAL, assets TEXT, reaction TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS analysis_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, symbol TEXT, timeframe TEXT,
      state TEXT, trend TEXT, patterns TEXT, evidence TEXT, news_count INTEGER,
      price REAL, expected TEXT, outcome TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS trade_flow(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, symbol TEXT, price REAL,
      qty REAL, buyer_maker INTEGER, side TEXT)''')
    con.commit(); con.close()

def fetch_news(limit=20):
    r=requests.get(NEWS_RSS,timeout=15,headers={'User-Agent':'ROBI/1.0'})
    r.raise_for_status()
    root=ET.fromstring(r.content)
    rows=[]
    for item in root.findall('.//item')[:limit]:
        title=(item.findtext('title') or '').strip()
        link=(item.findtext('link') or '').strip()
        pub=(item.findtext('pubDate') or '').strip()
        source=(item.findtext('source') or '').strip()
        if not title: continue
        nid=hashlib.sha256((title+'|'+link).encode()).hexdigest()
        rows.append({'id':nid,'title':title,'source':source,'url':link,'published':pub})
    con=sqlite3.connect(DB_PATH)
    for x in rows:
        con.execute('INSERT OR IGNORE INTO news_events VALUES(?,?,?,?,?,?,?,?,?)',
                    (x['id'],x['title'],x['source'],x['url'],x['published'],'crypto',time.time(),'',''))
    con.commit(); con.close()
    return rows

def latest_news(limit=10):
    con=sqlite3.connect(DB_PATH)
    cur=con.execute('SELECT title,source,url,published FROM news_events ORDER BY fetched_at DESC LIMIT ?', (limit,))
    rows=cur.fetchall(); con.close()
    return [{'title':r[0],'source':r[1],'url':r[2],'published':r[3]} for r in rows]
