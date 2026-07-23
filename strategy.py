"""
Strateegia signaalide arvutus: "osta languses, müü tõusus".

Ostusignaal tekib, kui hetke sulgemishind on langenud vähemalt X% viimase
Y küünla kõrgeimast hinnast (rolling high). Müügiotsus tehakse
backtest_engine.py-s iga avatud positsiooni enda ostuhinna suhtes, mitte
siin — see fail arvutab ainult "kas praegu on hea hetk osta" signaali.

Tähtis: rolling-akna arvutus kasutab min_periods=Y, mistõttu esimesed
(Y-1) rida ei saa üldse signaali (pole veel piisavalt ajalugu) —
see väldib valesid signaale poolikute akende pealt ja ei kasuta kunagi
tulevasi küünlaid (pole "lookahead bias'e").
"""

import pandas as pd


def add_signals(
    df: pd.DataFrame,
    lookback_periods: int,
    drop_pct: float,
    trend_filter_ma: int | None = None,
    trend_filter_fast_ma: int | None = None,
) -> pd.DataFrame:
    df = df.copy()
    df["rolling_high"] = df["high"].rolling(window=lookback_periods, min_periods=lookback_periods).max()
    df["drop_pct"] = (df["rolling_high"] - df["close"]) / df["rolling_high"] * 100
    df["buy_signal"] = df["drop_pct"] >= drop_pct

    if trend_filter_ma is not None:
        # Trendifilter: osta ainult siis, kui hind on üleval pool oma pikaajalist
        # libisevat keskmist — st väldi languse ostmist SEES pikaajalises languses.
        # (min_periods=trend_filter_ma tähendab, et enne täisajaloo olemasolu
        # signaali ei teki — samuti lookahead-vaba, kasutab ainult minevikku.)
        df["trend_ma"] = df["close"].rolling(window=trend_filter_ma, min_periods=trend_filter_ma).mean()

        if trend_filter_fast_ma is not None:
            # "Golden cross" variant: nõua, et lühem MA oleks pikemast kõrgemal,
            # mitte lihtsalt hind > pikk MA — tugevam kinnitatud trendisignaal.
            df["trend_ma_fast"] = df["close"].rolling(
                window=trend_filter_fast_ma, min_periods=trend_filter_fast_ma
            ).mean()
            df["buy_signal"] = df["buy_signal"] & (df["trend_ma_fast"] > df["trend_ma"])
        else:
            df["buy_signal"] = df["buy_signal"] & (df["close"] > df["trend_ma"])

    return df
