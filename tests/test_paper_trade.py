"""
Kontrollib paper trading oleku (de)serialiseerimist ja kõige tähtsamat
invarianti: `step()` kaudu antud üks samm annab TÄPSELT sama tulemuse, mis
vastava ühe-rea `run_backtest()` väljakutse — see ongi backtest/live
paarsuse otsene tõend.
"""

import pandas as pd
import pytest

import paper_trade
from backtest_engine import PortfolioState, Trade, run_backtest, step
from config import BacktestConfig, StrategyConfig


def test_position_dict_round_trip():
    from backtest_engine import Position

    pos = Position(
        entry_time=pd.Timestamp("2024-03-01", tz="UTC"),
        entry_price=50_000.0,
        size_usd=2000.0,
        qty=0.04,
        peak_price=51_000.0,
        armed=True,
        entry_index=3,
        scaled_out=True,
    )
    restored = paper_trade._position_from_dict(paper_trade._position_to_dict(pos))
    assert restored == pos


def test_trade_dict_round_trip():
    trade = Trade(
        entry_time=pd.Timestamp("2024-03-01", tz="UTC"),
        exit_time=pd.Timestamp("2024-03-05", tz="UTC"),
        entry_price=50_000.0,
        exit_price=54_000.0,
        qty=0.04,
        size_usd=2000.0,
        entry_fee=2.0,
        exit_fee=2.16,
        pnl=155.84,
        exit_reason="take_profit",
    )
    restored = paper_trade._trade_from_dict(paper_trade._trade_to_dict(trade))
    assert restored == trade


def test_load_save_state_round_trip(tmp_path, monkeypatch):
    from backtest_engine import Position

    state_path = tmp_path / "paper_state.json"
    monkeypatch.setattr(paper_trade, "STATE_PATH", str(state_path))

    portfolio = PortfolioState(cash=8000.0, running_peak_equity=10_000.0, cooldown_remaining=2)
    portfolio.open_positions.append(
        Position(entry_time=pd.Timestamp("2024-01-01", tz="UTC"), entry_price=40_000.0, size_usd=2000.0, qty=0.05)
    )
    meta = paper_trade.PaperMeta(
        t_idx=5,
        last_processed_open_time=pd.Timestamp("2024-01-05", tz="UTC"),
        started_at=pd.Timestamp("2024-01-01", tz="UTC"),
        bh_qty=0.2,
        bh_entry_price=40_000.0,
        equity_history=[{"date": "2024-01-05", "price": 41000, "equity": 10100, "bh_value": 10050, "return_pct": 1.0}],
    )

    paper_trade.save_state(portfolio, meta)
    restored_portfolio, restored_meta = paper_trade.load_state()

    assert restored_portfolio.cash == portfolio.cash
    assert restored_portfolio.cooldown_remaining == portfolio.cooldown_remaining
    assert restored_portfolio.open_positions == portfolio.open_positions
    assert restored_meta.t_idx == meta.t_idx
    assert restored_meta.last_processed_open_time == meta.last_processed_open_time
    assert restored_meta.bh_qty == meta.bh_qty
    assert restored_meta.equity_history == meta.equity_history


def test_step_matches_run_backtest_on_same_data():
    """Backtest/live paarsus: kutsudes step()-i käsitsi rida-realt samas
    järjekorras nagu run_backtest() seda teeb, peab lõpptulemus (cash,
    kauplused) olema identne run_backtest()-i väljundiga sama df peale."""
    strategy_cfg = StrategyConfig(drop_pct=5.0, lookback_periods=2, rise_pct=8.0, trailing_stop_pct=10.0)
    backtest_cfg = BacktestConfig(starting_capital=1000.0, max_concurrent_positions=2, fee_rate=0.001)

    df = pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC"),
        "close": [100, 95, 90, 105, 120, 100],
        "buy_signal": [False, False, True, False, False, True],
    })

    expected = run_backtest(df, strategy_cfg, backtest_cfg)

    # Käsitsi, "paper trading stiilis" — üks step() kutse rea kohta.
    state = PortfolioState(cash=backtest_cfg.starting_capital, running_peak_equity=backtest_cfg.starting_capital)
    for t_idx, row in enumerate(df.itertuples(index=False)):
        step(state, row.open_time, row.close, bool(row.buy_signal), t_idx, strategy_cfg, backtest_cfg)

    # run_backtest sunnib perioodi lõpus veel avatud positsioonid kinni —
    # tee sama, et lõpptulemused oleks võrreldavad.
    from backtest_engine import _close_position
    last_time = df.iloc[-1]["open_time"]
    last_close = df.iloc[-1]["close"]
    for pos in state.open_positions:
        trade, proceeds = _close_position(pos, last_time, last_close, backtest_cfg.fee_rate, "period_end")
        state.cash += proceeds
        state.trades.append(trade)

    assert state.cash == pytest.approx(expected.final_cash)
    assert len(state.trades) == len(expected.trades)
    for a, b in zip(state.trades, expected.trades):
        assert a.pnl == pytest.approx(b.pnl)
        assert a.exit_reason == b.exit_reason
