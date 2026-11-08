import pytest

from tradebot.config import Settings
from tradebot.data import Candle


def make_candles(closes, start_ts=1_700_000_000_000, step_ms=3_600_000, spread=0.002):
    """Candles whose open is the previous close; high/low a small spread around the bar."""
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(Candle(start_ts + i * step_ms, o, max(o, c) * (1 + spread), min(o, c) * (1 - spread), c, 1.0))
        prev = c
    return out


@pytest.fixture
def settings(tmp_path):
    return Settings(data_source="synthetic", db_path=str(tmp_path / "t.sqlite3"), symbols=["BTC/USD"],
                    poll_seconds=1)
