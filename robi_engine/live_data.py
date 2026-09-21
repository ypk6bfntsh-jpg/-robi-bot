"""ROBI multi-market public market-data adapter.

Markets:
- Crypto: Kraken public REST market data.
- US equities: Yahoo Finance via yfinance.

No private keys and no order endpoints are used.
"""
import os
import time
from typing import Any

import requests

from .models import Candle

KRAKEN_BASE = "https://api.kraken.com"
MARKET_PROVIDER = os.getenv("ROBI_MARKET_PROVIDER", "auto").strip().lower()

_SESSION = requests.Session()
_ASSET_PAIRS_CACHE: dict[str, Any] | None = None
_ASSET_PAIRS_CACHE_TS = 0.0
_ASSET_PAIRS_CACHE_TTL = 3600.0

TIMEFRAME_MAP = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}

US_SYMBOLS = {
    "AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "META", "GOOGL", "GOOG",
    "AMD", "AVGO", "PLTR", "NFLX", "INTC", "QCOM", "ORCL", "CRM",
    "COST", "JPM", "V", "MA", "WMT", "DIS", "BA", "SPY", "QQQ",
}


def _get(url: str, params: dict | None = None, timeout: int = 15):
    response = _SESSION.get(url, params=params or {}, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError("; ".join(map(str, data["error"])))
    return data


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("-", "").replace("_", "").strip()


CRYPTO_QUOTES = ("USDT", "USDC", "USD", "EUR", "GBP")
FIAT_BASES = {
    "USD", "USDT", "USDC", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF",
}
STABLE_BASES = {
    "DAI", "TUSD", "USDE", "PYUSD", "FDUSD", "USDD", "EURC",
}


def is_crypto_symbol(symbol: str) -> bool:
    """Classify arbitrary Kraken spot symbols, not just a hard-coded coin list."""
    s = _normalize_symbol(symbol)
    for quote in CRYPTO_QUOTES:
        if s.endswith(quote):
            base = s[:-len(quote)]
            if not base or base in FIAT_BASES or base in STABLE_BASES:
                return False
            # Kraken may expose XBT while the scanner uses BTC.
            return True
    return False


def is_us_symbol(symbol: str) -> bool:
    s = _normalize_symbol(symbol)
    if is_crypto_symbol(s):
        return False
    return s.isalpha() and 1 <= len(s) <= 6


def market_kind(symbol: str) -> str:
    if is_crypto_symbol(symbol):
        return "crypto"
    if is_us_symbol(symbol):
        return "us_equity"
    return "unknown"


def _load_kraken_pairs() -> dict[str, dict]:
    global _ASSET_PAIRS_CACHE, _ASSET_PAIRS_CACHE_TS
    now = time.time()
    if _ASSET_PAIRS_CACHE and now - _ASSET_PAIRS_CACHE_TS < _ASSET_PAIRS_CACHE_TTL:
        return _ASSET_PAIRS_CACHE
    data = _get(f"{KRAKEN_BASE}/0/public/AssetPairs", timeout=15)
    _ASSET_PAIRS_CACHE = data.get("result") or {}
    _ASSET_PAIRS_CACHE_TS = now
    return _ASSET_PAIRS_CACHE


def _kraken_pair(symbol: str) -> str:
    wanted = _normalize_symbol(symbol)
    pairs = _load_kraken_pairs()
    wanted_norm = wanted.replace("XBT", "BTC")

    for key, row in pairs.items():
        values = set()
        for field in ("altname", "wsname", "symbol"):
            value = _normalize_symbol(str(row.get(field) or ""))
            if value:
                values.add(value)
        base = str(row.get("base") or "")
        quote = str(row.get("quote") or "")
        if base and quote:
            values.add(_normalize_symbol(base + quote))
        normalized = {x.replace("XBT", "BTC") for x in values}
        if wanted in values or wanted_norm in normalized:
            return str(row.get("altname") or key)

    common = {
        "BTCUSDT": "XBTUSDT", "BTCUSD": "XBTUSD",
        "ETHUSDT": "ETHUSDT", "ETHUSD": "ETHUSD",
        "SOLUSDT": "SOLUSDT", "SOLUSD": "SOLUSD",
        "XRPUSDT": "XRPUSDT", "XRPUSD": "XRPUSD",
    }
    if wanted in common:
        return common[wanted]
    raise ValueError(f"Kraken market pair not found for {symbol}")


def _kraken_ohlc(symbol: str, interval: str, limit: int):
    minutes = TIMEFRAME_MAP.get(interval.lower())
    if minutes is None:
        raise ValueError(f"Unsupported timeframe: {interval}")
    pair = _kraken_pair(symbol)
    data = _get(f"{KRAKEN_BASE}/0/public/OHLC", {"pair": pair, "interval": minutes})
    result = data.get("result") or {}
    rows = next((v for k, v in result.items() if k != "last"), [])
    rows = rows[-min(max(int(limit), 1), 720):]
    return [Candle(float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[6]), str(int(float(x[0])))) for x in rows]


def _kraken_ticker(symbol: str):
    pair = _kraken_pair(symbol)
    result = (_get(f"{KRAKEN_BASE}/0/public/Ticker", {"pair": pair}).get("result") or {})
    if not result:
        raise RuntimeError(f"No Kraken ticker for {symbol}")
    row = next(iter(result.values()))
    last = float(row["c"][0]); opening = float(row["o"])
    volume = float(row["v"][1]); quote_volume = volume * last
    change = ((last - opening) / opening * 100.0) if opening else 0.0
    return {
        "symbol": _normalize_symbol(symbol), "lastPrice": last,
        "priceChangePercent": change, "quoteVolume": quote_volume,
        "volume": volume, "openPrice": opening,
        "highPrice": float(row["h"][1]), "lowPrice": float(row["l"][1]),
        "provider": "kraken",
    }


def _kraken_trades(symbol: str, limit: int):
    pair = _kraken_pair(symbol)
    result = (_get(f"{KRAKEN_BASE}/0/public/Trades", {"pair": pair}).get("result") or {})
    rows = next((v for k, v in result.items() if k != "last"), [])
    rows = rows[-min(max(int(limit), 1), 1000):]
    return [{"price": float(x[0]), "qty": float(x[1]), "side": "BUY" if str(x[3]).lower() == "b" else "SELL", "buyer_maker": None, "time": float(x[2]) * 1000} for x in rows]


def _yf_interval(timeframe: str) -> str:
    return {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "1d": "1d", "1w": "1wk"}.get(timeframe.lower(), "15m")


def _us_ohlc(symbol: str, interval: str, limit: int):
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("US market provider requires yfinance") from exc

    tf = interval.lower()
    if tf == "4h":
        base_interval = "1h"
    else:
        base_interval = _yf_interval(tf)

    # Yahoo/yfinance limits intraday history; 5d is enough for live analysis.
    period = "5d" if base_interval not in {"1d", "1wk"} else ("2y" if base_interval == "1d" else "5y")
    df = yf.download(symbol.upper(), period=period, interval=base_interval, auto_adjust=False, progress=False, threads=False, prepost=False)
    if df is None or df.empty:
        raise RuntimeError(f"No US market data returned for {symbol}")
    if getattr(df.columns, "nlevels", 1) > 1:
        df = df.xs(symbol.upper(), axis=1, level=1, drop_level=True) if symbol.upper() in df.columns.get_level_values(-1) else df.droplevel(1, axis=1)

    df = df.dropna(subset=["Open", "High", "Low", "Close"]).tail(max(int(limit), 1))

    if tf == "4h":
        # Resample the 1h bars locally; Yahoo does not expose a native 4h interval.
        df = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
        df = df.tail(max(int(limit), 1))

    candles = []
    for idx, row in df.iterrows():
        ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
        candles.append(Candle(float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), float(row.get("Volume", 0) or 0), ts))
    return candles


def _us_ticker(symbol: str):
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("US market provider requires yfinance") from exc

    t = yf.Ticker(symbol.upper())
    hist = t.history(period="5d", interval="1d", auto_adjust=False, actions=False)
    if hist is None or hist.empty:
        raise RuntimeError(f"No US ticker data for {symbol}")
    last = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
    day_open = float(hist["Open"].iloc[-1]); day_high = float(hist["High"].iloc[-1]); day_low = float(hist["Low"].iloc[-1])
    volume = float(hist["Volume"].iloc[-1] or 0)
    change = ((last - prev) / prev * 100.0) if prev else 0.0
    return {"symbol": symbol.upper(), "lastPrice": last, "priceChangePercent": change, "quoteVolume": volume * last, "volume": volume, "openPrice": day_open, "highPrice": day_high, "lowPrice": day_low, "provider": "yahoo_finance"}


def _us_trades(symbol: str, limit: int):
    # yfinance does not provide a consolidated recent trade tape comparable to Kraken trades.
    return []


def get_klines(symbol, interval="15m", limit=200):
    kind = market_kind(symbol)
    if kind == "crypto":
        return _kraken_ohlc(symbol, interval, limit)
    if kind == "us_equity":
        return _us_ohlc(symbol, interval, limit)
    raise ValueError(f"Unsupported market symbol: {symbol}")


def get_ticker(symbol):
    kind = market_kind(symbol)
    if kind == "crypto":
        return _kraken_ticker(symbol)
    if kind == "us_equity":
        return _us_ticker(symbol)
    raise ValueError(f"Unsupported market symbol: {symbol}")


def get_recent_trades(symbol, limit=100):
    kind = market_kind(symbol)
    if kind == "crypto":
        return _kraken_trades(symbol, limit)
    if kind == "us_equity":
        return _us_trades(symbol, limit)
    raise ValueError(f"Unsupported market symbol: {symbol}")


def market_provider_status():
    return {
        "configured": MARKET_PROVIDER,
        "routing": {"crypto": "kraken_public", "us_equity": "yahoo_finance_yfinance"},
        "real_trading": False,
        "private_api": False,
        "us_trade_tape": "not_available_in_current_adapter",
    }
