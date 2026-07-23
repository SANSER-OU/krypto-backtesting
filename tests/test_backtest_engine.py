"""
Kontrollib backtest-mootori tasude mahaarvamist ja max drawdown arvutust
käsitsi arvutatava stsenaariumiga.
"""

import pandas as pd
import pytest

from backtest_engine import run_backtest
from config import BacktestConfig, StrategyConfig
from metrics import max_drawdown


def _make_df(closes: list[float], buy_signals: list[bool]) -> pd.DataFrame:
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC"),
        "close": closes,
        "high": closes,
        "buy_signal": buy_signals,
    })


def test_fee_deduction_and_take_profit_and_period_end_close():
    # 1% tasu, et arvud oleksid käsitsi kontrollitavad.
    strategy_cfg = StrategyConfig(drop_pct=0, lookback_periods=1, rise_pct=10.0, stop_loss_pct=None)
    backtest_cfg = BacktestConfig(starting_capital=1000.0, max_concurrent_positions=1, fee_rate=0.01)

    # Küünlad: osta 100-ga, hoia, müü 112-ga (>=10% tõus), siis osta uuesti
    # 90-ga ja periood lõppeb kohe (positsioon suletakse sunniviisiliselt
    # sama hinnaga, mis oli ostuhind -> peaks andma väikese kahjumi tasude võrra).
    df = _make_df(
        closes=[100, 105, 112, 90],
        buy_signals=[True, False, False, True],
    )

    result = run_backtest(df, strategy_cfg, backtest_cfg)

    assert len(result.trades) == 2

    trade1 = result.trades[0]
    assert trade1.exit_reason == "take_profit"
    assert trade1.entry_price == 100
    assert trade1.exit_price == 112
    assert trade1.entry_fee == pytest.approx(10.0)
    assert trade1.exit_fee == pytest.approx(9.9 * 112 * 0.01)
    assert trade1.pnl == pytest.approx(97.712, abs=1e-3)

    trade2 = result.trades[1]
    assert trade2.exit_reason == "period_end"
    assert trade2.entry_price == 90
    assert trade2.exit_price == 90  # periood lõppes samal hinnal, mis ost

    # Mõlemal juhul kaotasime raha ainult tasude tõttu (ost ja müük sama hinnaga).
    assert trade2.pnl < 0

    expected_final_cash = 1077.812
    assert result.final_cash == pytest.approx(expected_final_cash, abs=1e-2)

    total_fees = sum(t.entry_fee + t.exit_fee for t in result.trades)
    assert total_fees == pytest.approx(40.988, abs=1e-2)


def test_max_drawdown_hand_calculated():
    equity_curve = pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=6, freq="D"),
        "equity": [1000, 1200, 900, 950, 1300, 800],
    })

    # Running peak: 1000,1200,1200,1200,1300,1300
    # Suurim langus: (800-1300)/1300 = -38.46%
    result = max_drawdown(equity_curve)
    assert result == pytest.approx(38.4615, abs=1e-3)


def test_cooldown_after_stop_loss_blocks_reentry():
    strategy_cfg = StrategyConfig(
        drop_pct=0, lookback_periods=1, rise_pct=1000.0,
        stop_loss_pct=10.0, cooldown_after_stop_loss=3,
    )
    backtest_cfg = BacktestConfig(starting_capital=1000.0, max_concurrent_positions=2, fee_rate=0.0)

    # idx0: ost 100-ga. idx1: hind langeb 85-ni (>=10% langus 100-st) -> stop-loss,
    # käivitab 3-küünlase jahtumisperioodi. idx2 ja idx3 ostusignaalid PEAVAD
    # olema blokeeritud. idx4-l on jahtumine läbi -> ost lubatud.
    df = _make_df(
        closes=[100, 85, 85, 85, 85],
        buy_signals=[True, False, True, True, True],
    )

    result = run_backtest(df, strategy_cfg, backtest_cfg)

    assert len(result.trades) == 2
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].exit_time == df.iloc[1]["open_time"]

    # Teine tehing sai avaneda alles idx4 juures (idx2/idx3 olid jahtumises).
    assert result.trades[1].entry_time == df.iloc[4]["open_time"]
    assert result.trades[1].exit_reason == "period_end"


def test_scale_out_sells_half_and_trailing_manages_remainder():
    strategy_cfg = StrategyConfig(
        drop_pct=0, lookback_periods=1, rise_pct=10.0,
        trailing_stop_pct=20.0, scale_out_fraction=0.5,
    )
    backtest_cfg = BacktestConfig(starting_capital=1000.0, max_concurrent_positions=1, fee_rate=0.0)

    # idx0: ost 100-ga. idx1: hind 112 (>=10% tõus) -> relvastub JA müüb kohe
    # poole maha (scale-out). idx2: hind 150 (uus tipp). idx3: hind langeb
    # 100-ni -> trailing-stop käivitub (150 * 0.8 = 120 > 100), müüb ülejäänud poole.
    df = _make_df(
        closes=[100, 112, 150, 100],
        buy_signals=[True, False, False, False],
    )

    result = run_backtest(df, strategy_cfg, backtest_cfg)

    assert len(result.trades) == 2

    scale_out_trade = result.trades[0]
    assert scale_out_trade.exit_reason == "scale_out"
    assert scale_out_trade.qty == pytest.approx(5.0)
    assert scale_out_trade.size_usd == pytest.approx(500.0)
    assert scale_out_trade.pnl == pytest.approx(60.0)  # (5*112) - 500

    remainder_trade = result.trades[1]
    assert remainder_trade.exit_reason == "trailing_stop"
    assert remainder_trade.qty == pytest.approx(5.0)
    assert remainder_trade.pnl == pytest.approx(0.0)  # (5*100) - 500

    assert result.final_cash == pytest.approx(1060.0)


def test_max_holding_periods_forces_time_exit():
    strategy_cfg = StrategyConfig(
        drop_pct=0, lookback_periods=1, rise_pct=1000.0,  # take-profit ei saa iial vallanduda
        max_holding_periods=2,
    )
    backtest_cfg = BacktestConfig(starting_capital=1000.0, max_concurrent_positions=1, fee_rate=0.0)

    # Hind ei muutu kunagi (100 kogu aeg) — ainus võimalik sulgemispõhjus on aeg.
    df = _make_df(
        closes=[100, 100, 100, 100, 100],
        buy_signals=[True, False, False, False, False],
    )

    result = run_backtest(df, strategy_cfg, backtest_cfg)

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "time_exit"
    # Avati idx0 (entry_index=0), max_holding_periods=2 -> suletakse esimesel
    # küünlal, kus (t_idx - entry_index) >= 2, st idx2 juures.
    assert result.trades[0].exit_time == df.iloc[2]["open_time"]
    assert result.trades[0].pnl == pytest.approx(0.0)


def test_no_open_positions_beyond_max_concurrent():
    strategy_cfg = StrategyConfig(drop_pct=0, lookback_periods=1, rise_pct=1000.0, stop_loss_pct=None)
    backtest_cfg = BacktestConfig(starting_capital=1000.0, max_concurrent_positions=2, fee_rate=0.0)

    # Ostusignaal iga küünla peal, aga max 2 positsiooni tohib korraga lahti olla.
    df = _make_df(
        closes=[100, 100, 100, 100],
        buy_signals=[True, True, True, True],
    )

    result = run_backtest(df, strategy_cfg, backtest_cfg)

    # rise_pct=1000% tähendab, et ükski positsioon ei jõua kunagi müügihinnani
    # enne perioodi lõppu, seega kõik "trades" tulevad period_end sulgemisest.
    assert len(result.trades) == 2
    assert all(t.exit_reason == "period_end" for t in result.trades)
