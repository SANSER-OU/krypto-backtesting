"""
Backtest'i tulemuste kokkuvõtlikud mõõdikud.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest_engine import BacktestResult


@dataclass
class Metrics:
    starting_capital: float
    final_capital: float
    total_return_pct: float
    total_return_usd: float
    num_trades: int
    win_rate_pct: float
    total_fees_usd: float
    max_drawdown_pct: float
    profit_factor: float
    gross_profit_usd: float
    gross_loss_usd: float


@dataclass
class BenchmarkResult:
    """'Osta ja hoia' võrdlusalus — see, mida passiivne indeksinvestor
    (nt BlackRock/Vanguard indeksifondi stiilis) teeks: osta perioodi
    alguses, ära tee ühtegi tehingut, müü perioodi lõpus."""
    final_capital: float
    total_return_pct: float
    total_return_usd: float


def max_drawdown(equity_curve: pd.DataFrame) -> float:
    """Suurim langus jooksvast tipust (running peak) protsendina, positiivse arvuna."""
    if equity_curve.empty:
        return 0.0
    running_peak = equity_curve["equity"].cummax()
    drawdown = (equity_curve["equity"] - running_peak) / running_peak
    return abs(drawdown.min()) * 100


def compute_metrics(result: BacktestResult, starting_capital: float) -> Metrics:
    final_capital = result.final_cash
    total_return_usd = final_capital - starting_capital
    total_return_pct = (total_return_usd / starting_capital) * 100

    num_trades = len(result.trades)
    winning_trades = sum(1 for t in result.trades if t.pnl > 0)
    win_rate_pct = (winning_trades / num_trades * 100) if num_trades else 0.0

    total_fees_usd = sum(t.entry_fee + t.exit_fee for t in result.trades)

    gross_profit_usd = sum(t.pnl for t in result.trades if t.pnl > 0)
    gross_loss_usd = abs(sum(t.pnl for t in result.trades if t.pnl < 0))
    if gross_loss_usd > 0:
        profit_factor = gross_profit_usd / gross_loss_usd
    else:
        # Pole ühtegi kaotavat tehingut — kasumitegur on defineerimata ("lõpmatu").
        profit_factor = float("inf") if gross_profit_usd > 0 else 0.0

    return Metrics(
        starting_capital=starting_capital,
        final_capital=final_capital,
        total_return_pct=total_return_pct,
        total_return_usd=total_return_usd,
        num_trades=num_trades,
        win_rate_pct=win_rate_pct,
        total_fees_usd=total_fees_usd,
        max_drawdown_pct=max_drawdown(result.equity_curve),
        profit_factor=profit_factor,
        gross_profit_usd=gross_profit_usd,
        gross_loss_usd=gross_loss_usd,
    )


def compute_buy_and_hold(df: pd.DataFrame, starting_capital: float, fee_rate: float) -> BenchmarkResult:
    """Simuleerib: osta kogu kapitaliga perioodi esimesel küünlal, hoia, müü viimasel."""
    entry_price = df.iloc[0]["close"]
    exit_price = df.iloc[-1]["close"]

    entry_fee = starting_capital * fee_rate
    qty = (starting_capital - entry_fee) / entry_price

    gross_proceeds = qty * exit_price
    exit_fee = gross_proceeds * fee_rate
    final_capital = gross_proceeds - exit_fee

    total_return_usd = final_capital - starting_capital
    total_return_pct = total_return_usd / starting_capital * 100

    return BenchmarkResult(
        final_capital=final_capital,
        total_return_pct=total_return_pct,
        total_return_usd=total_return_usd,
    )
