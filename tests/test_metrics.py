"""
Kontrollib kasumiteguri (profit factor) arvutust: kogukasum / kogukahjum.
"""

import pandas as pd
import pytest

from backtest_engine import BacktestResult, Trade
from metrics import compute_metrics


def _trade(pnl: float) -> Trade:
    return Trade(
        entry_time=pd.Timestamp("2024-01-01", tz="UTC"),
        exit_time=pd.Timestamp("2024-01-02", tz="UTC"),
        entry_price=100.0,
        exit_price=100.0,
        qty=1.0,
        size_usd=100.0,
        entry_fee=0.0,
        exit_fee=0.0,
        pnl=pnl,
        exit_reason="take_profit",
    )


def test_profit_factor_mixed_trades():
    # Kogukasum: 100+50=150, kogukahjum: |-40|+|-10|=50 -> PF = 150/50 = 3.0
    trades = [_trade(100), _trade(-40), _trade(50), _trade(-10)]
    result = BacktestResult(trades=trades, equity_curve=pd.DataFrame({"time": [], "equity": []}), final_cash=1100)

    metrics = compute_metrics(result, starting_capital=1000)

    assert metrics.gross_profit_usd == pytest.approx(150)
    assert metrics.gross_loss_usd == pytest.approx(50)
    assert metrics.profit_factor == pytest.approx(3.0)


def test_profit_factor_no_losses_is_infinite():
    trades = [_trade(100), _trade(50)]
    result = BacktestResult(trades=trades, equity_curve=pd.DataFrame({"time": [], "equity": []}), final_cash=1150)

    metrics = compute_metrics(result, starting_capital=1000)

    assert metrics.profit_factor == float("inf")


def test_profit_factor_no_trades_is_zero():
    result = BacktestResult(trades=[], equity_curve=pd.DataFrame({"time": [], "equity": []}), final_cash=1000)

    metrics = compute_metrics(result, starting_capital=1000)

    assert metrics.profit_factor == 0.0
