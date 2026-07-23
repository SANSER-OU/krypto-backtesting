"""
Käivita: python main.py

Laeb BTC/USDT ajaloolised hinnaandmed Binance API-st (või lokaalsest
cache'ist), arvutab "osta languses, müü tõusus" strateegia signaalid ja
testib seda kolmel erineval reaalsel turuperioodil — nii praeguse
baasstrateegiaga kui ka kolme kumulatiivse parandusega (config.SCENARIOS):

  0. Baasjoon (praegune)
  1. + Stop-loss
  2. + Trendifilter (MA200)
  3. + Trailing exit
  4. + Rohkem positsioone tõusutrendis (max 8, ikka trendifiltriga kaitstud)
  5. Uuringu tulemus (soovituslik) — vt research.py ja RESEARCH.md

Iga samm lisab eelmisele ÜHE muudatuse, et oleks selge, mis täpselt
tulemust mõjutas.
"""

from __future__ import annotations

import pandas as pd

import config
import strategy
from backtest_engine import run_backtest
from data_fetch import load_data
from metrics import compute_buy_and_hold, compute_metrics
from report import plot_equity_curve, print_period_report, print_scenario_comparison

WARNINGS_BANNER = """
HOIATUSED (loe enne tulemuste tõlgendamist — vt README.md täpsemalt):

  1. OVERFITTING: kui hakkad X/Y/Z parameetreid muutma, kuni tulemused
     nende 3 perioodi peal heaks lähevad, siis see EI TÕESTA, et strateegia
     tulevikus töötab — see näitab ainult, et see sobib minevikuga.
  2. TASUD: iga tehing maksab ~0.1% (ost + müük = ~0.2% ringiga). Sagedaste
     tehingute korral võib see reaalselt suure osa kasumist ära süüa.
  3. TÄITMISE LIHTSUSTUS: simulatsioon eeldab, et saad osta/müüa täpselt
     küünla sulgemishinnaga — reaalsuses (libisemine, hinnavahemik) oleks
     tulemus veidi halvem.
  4. 3 PERIOODI ON ÕPPIMISE MIINIMUM, MITTE LÕPLIK TÕESTUS.
"""


def _build_period_df(full_df: pd.DataFrame, period: config.MarketPeriod, strategy_cfg) -> pd.DataFrame:
    warmup_start = pd.Timestamp(period.start, tz="UTC") - pd.Timedelta(days=config.WARMUP_DAYS)
    period_end = pd.Timestamp(period.end, tz="UTC")
    period_start = pd.Timestamp(period.start, tz="UTC")

    slice_df = full_df[(full_df["open_time"] >= warmup_start) & (full_df["open_time"] <= period_end)]
    signals_df = strategy.add_signals(
        slice_df,
        strategy_cfg.lookback_periods,
        strategy_cfg.drop_pct,
        strategy_cfg.trend_filter_ma,
        strategy_cfg.trend_filter_fast_ma,
    )
    return signals_df[signals_df["open_time"] >= period_start].reset_index(drop=True)


def main() -> None:
    print(f"Laen andmeid: {config.DATA.symbol}, {config.DATA.interval}, "
          f"{config.DATA.fetch_start} .. {config.DATA.fetch_end} ...")
    full_df = load_data(
        symbol=config.DATA.symbol,
        interval=config.DATA.interval,
        start=config.DATA.fetch_start,
        end=config.DATA.fetch_end,
        cache_dir=config.DATA.cache_dir,
    )
    print(f"Laetud {len(full_df)} küünalt.")
    print(WARNINGS_BANNER)

    for period in config.MARKET_PERIODS:
        scenario_metrics = []
        baseline_result = None
        baseline_metrics = None
        benchmark = None

        for scenario in config.SCENARIOS:
            period_df = _build_period_df(full_df, period, scenario.strategy)
            if period_df.empty:
                continue

            result = run_backtest(period_df, scenario.strategy, scenario.backtest)
            metrics = compute_metrics(result, scenario.backtest.starting_capital)
            scenario_metrics.append((scenario.name, metrics))

            if benchmark is None:
                benchmark = compute_buy_and_hold(
                    period_df, config.BACKTEST.starting_capital, config.BACKTEST.fee_rate
                )
            if scenario is config.SCENARIOS[0]:
                baseline_result, baseline_metrics = result, metrics

        if not scenario_metrics:
            print(f"\n{period.name}: andmeid ei leitud.")
            continue

        # Baasjoone jaoks täielik raport (nagu varem).
        print_period_report(period.name, baseline_metrics, baseline_result, benchmark)
        plot_path = plot_equity_curve(period.name, baseline_result)
        if plot_path:
            print(f"  Equity-kõvera graafik salvestatud: {plot_path}")

        # Kõigi stsenaariumide kompaktne kõrvutus.
        print_scenario_comparison(period.name, scenario_metrics, benchmark)

    print(f"\n{'=' * 60}")
    print("Valmis. Loe README.md-st tulemuste tõlgendamise juhiseid.")


if __name__ == "__main__":
    main()
