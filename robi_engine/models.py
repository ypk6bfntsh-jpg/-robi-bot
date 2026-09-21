from dataclasses import dataclass, field, asdict
from typing import Optional, Any

@dataclass(frozen=True)
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    timestamp: Optional[str] = None

    @property
    def body(self): return abs(self.close-self.open)
    @property
    def range(self): return self.high-self.low
    @property
    def upper_shadow(self): return self.high-max(self.open,self.close)
    @property
    def lower_shadow(self): return min(self.open,self.close)-self.low
    @property
    def bullish(self): return self.close > self.open
    @property
    def bearish(self): return self.close < self.open

@dataclass
class Signal:
    name: str
    direction: str
    category: str
    confirmed: bool = False
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Evidence:
    source: str
    name: str
    direction: str
    details: str = ""

@dataclass
class MarketSnapshot:
    symbol: str
    timeframe: str
    timestamp: Optional[str]
    trend: str = "unknown"
    candles: list[Candle] = field(default_factory=list)
    patterns: list[Signal] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    support: list[float] = field(default_factory=list)
    resistance: list[float] = field(default_factory=list)
    windows: list[dict] = field(default_factory=list)
    indicators: dict = field(default_factory=dict)
    volume: dict = field(default_factory=dict)
    measured_moves: list[dict] = field(default_factory=list)
    news: list[dict] = field(default_factory=list)
    conflicts: list[Evidence] = field(default_factory=list)
    state: str = "WAIT"

    def to_dict(self):
        return asdict(self)
