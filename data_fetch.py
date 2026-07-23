"""
Ajalooliste hinnaandmete allalaadimine Binance avalikust API-st.

Binance API-st saab avalikke turuandmeid (OHLCV küünlaid) ilma kontota ja
ilma API-võtmeta — see on nn "market data" endpoint, mitte kauplemise
endpoint. OHLCV tähendab: Open (avamishind), High (kõrgeim hind),
Low (madalaim hind), Close (sulgemishind), Volume (kaubeldud kogus)
ühe küünla (nt ühe päeva) kohta.

Binance tagastab ühe päringuga maksimaalselt 1000 küünalt, seega mitme
aasta andmete jaoks tuleb päringuid korrata ("pagination") ja tulemused
kokku liita.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
MAX_CANDLES_PER_REQUEST = 1000

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "num_trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _cache_path(cache_dir: str, symbol: str, interval: str, start: str, end: str) -> str:
    filename = f"{symbol}_{interval}_{start}_{end}.csv"
    return os.path.join(cache_dir, filename)


def fetch_klines(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """Laeb OHLCV küünlad Binance API-st ajavahemikus [start, end] (UTC kuupäevad)."""
    start_ms = _to_ms(start)
    end_ms = _to_ms(end)

    all_rows: list[list] = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": MAX_CANDLES_PER_REQUEST,
        }
        response = requests.get(BINANCE_KLINES_URL, params=params, timeout=30)
        response.raise_for_status()
        rows = response.json()

        if not rows:
            break

        all_rows.extend(rows)

        last_open_time = rows[-1][0]
        if last_open_time <= cursor:
            break
        cursor = last_open_time + 1

        if len(rows) < MAX_CANDLES_PER_REQUEST:
            break

        time.sleep(0.2)  # viisakas paus, et mitte Binance rate-limitit tabada

    df = pd.DataFrame(all_rows, columns=COLUMNS)

    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

    df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
    df = df.drop_duplicates(subset="open_time").reset_index(drop=True)
    return df


def load_data(symbol: str, interval: str, start: str, end: str, cache_dir: str) -> pd.DataFrame:
    """Tagastab OHLCV andmed — lokaalsest cache'ist, kui olemas, muidu Binance API-st."""
    os.makedirs(cache_dir, exist_ok=True)
    path = _cache_path(cache_dir, symbol, interval, start, end)

    if os.path.exists(path):
        df = pd.read_csv(path, parse_dates=["open_time", "close_time"])
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
        return df

    df = fetch_klines(symbol, interval, start, end)
    df.to_csv(path, index=False)
    return df
