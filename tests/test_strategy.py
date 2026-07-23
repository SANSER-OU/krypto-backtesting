"""
Kontrollib, et rolling-high / drop_pct / buy_signal arvutus on korrektne
ja EI kasuta kunagi tulevasi küünlaid (lookahead bias).
"""

import pandas as pd
import pytest

from strategy import add_signals

HIGHS = [100, 105, 102, 98, 101, 90, 95, 130, 125, 120]


def _make_df(highs: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=len(highs), freq="D", tz="UTC"),
        "high": highs,
        "close": highs,  # lihtsuse mõttes close == high selles testis
    })


def test_rolling_high_and_drop_pct_hand_calculated():
    df = add_signals(_make_df(HIGHS), lookback_periods=3, drop_pct=10.0)

    # Esimesed 2 rida: pole veel 3 täisküünalt, seega NaN ja buy_signal False.
    assert df.loc[0, "rolling_high"] != df.loc[0, "rolling_high"]  # NaN
    assert df.loc[0, "buy_signal"] == False
    assert df.loc[1, "buy_signal"] == False

    # Käsitsi arvutatud oodatud väärtused (vt kommentaari plaanis).
    assert df.loc[2, "rolling_high"] == 105
    assert df.loc[5, "rolling_high"] == 101
    assert df.loc[5, "drop_pct"] == pytest.approx((101 - 90) / 101 * 100)

    # Ainult idx=5 peaks ületama 10% languse läve.
    expected_buy = [False, False, False, False, False, True, False, False, False, False]
    assert list(df["buy_signal"]) == expected_buy


def test_golden_cross_filter_is_stricter_than_simple_ma_filter():
    """golden-cross (trend_filter_fast_ma) nõuab fast_MA > slow_MA, mitte
    lihtsalt close > slow_MA — see peab olema rangem tingimus."""
    closes = [100, 100, 100, 100, 20, 100]
    df = pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC"),
        "high": closes,
        "close": closes,
    })

    # drop_pct=-100 ja lookback_periods=1 -> buy_signal (enne trendifiltrit)
    # on alati True (rolling_high == praegune hind, drop_pct == 0 >= -100).
    simple = add_signals(df, lookback_periods=1, drop_pct=-100.0, trend_filter_ma=4)
    golden = add_signals(df, lookback_periods=1, drop_pct=-100.0, trend_filter_ma=4, trend_filter_fast_ma=2)

    # idx5: close=100, MA4=mean(100,100,20,100)=80 -> lihtne filter (100>80) läbib.
    assert simple.loc[5, "buy_signal"] == True
    # Sama koht, aga MA2=mean(20,100)=60 < MA4=80 -> golden cross EI kinnita trendi.
    assert golden.loc[5, "buy_signal"] == False


def test_no_lookahead_bias():
    """Kui muudame TULEVIKU küünla väärtust, ei tohi see mõjutada varasemaid signaale."""
    df_original = add_signals(_make_df(HIGHS), lookback_periods=3, drop_pct=10.0)

    modified_highs = HIGHS.copy()
    modified_highs[9] = 100_000  # dramaatiline muutus viimasel real
    df_modified = add_signals(_make_df(modified_highs), lookback_periods=3, drop_pct=10.0)

    # Kõik read PEALE muudetud rea peavad olema identsed.
    for col in ["rolling_high", "drop_pct", "buy_signal"]:
        pd.testing.assert_series_equal(
            df_original.loc[:8, col], df_modified.loc[:8, col], check_names=False
        )
