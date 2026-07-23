"""
Tulemuste inimloetav väljund.
"""

from __future__ import annotations

import os

from backtest_engine import BacktestResult
from metrics import BenchmarkResult, Metrics


def print_period_report(
    period_name: str,
    metrics: Metrics,
    result: BacktestResult,
    benchmark: BenchmarkResult | None = None,
) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {period_name}")
    print(f"{'=' * 60}")
    print(f"  Algkapital:         ${metrics.starting_capital:,.2f}")
    print(f"  Lõppkapital:        ${metrics.final_capital:,.2f}")
    sign = "+" if metrics.total_return_usd >= 0 else ""
    print(f"  Kogutootlus:        {sign}${metrics.total_return_usd:,.2f}  ({sign}{metrics.total_return_pct:.2f}%)")
    print(f"  Tehingute arv:      {metrics.num_trades}")
    print(f"  Võiduprotsent:      {metrics.win_rate_pct:.1f}%")
    print(f"  Kokku tasusid:      ${metrics.total_fees_usd:,.2f}")
    print(f"  Max drawdown:       -{metrics.max_drawdown_pct:.2f}%")

    pf_display = "∞ (kaotavaid tehinguid polnud)" if metrics.profit_factor == float("inf") else f"{metrics.profit_factor:.2f}"
    print(f"  Kasumitegur (PF):   {pf_display}")
    print(f"    (kogukasum ${metrics.gross_profit_usd:,.2f} / kogukahjum ${metrics.gross_loss_usd:,.2f})")

    if metrics.num_trades > 0:
        avg_fee_impact = metrics.total_fees_usd / metrics.starting_capital * 100
        print(f"\n  Selgitus: tasud moodustasid kokku {avg_fee_impact:.2f}% algkapitalist.")
        if metrics.total_return_usd > 0 and metrics.total_fees_usd > metrics.total_return_usd:
            print("  HOIATUS: kauplemistasud olid suuremad kui toorkasum enne tasusid —")
            print("  ilma tasudeta oleks tulemus näinud parem välja, aga reaalsuses kasum kadus tasudesse.")
    else:
        print("\n  Selgitus: sel perioodil ei tekkinud ühtegi ostusignaali antud parameetritega.")

    if benchmark is not None:
        bsign = "+" if benchmark.total_return_usd >= 0 else ""
        print(f"\n  --- Võrdlus: 'osta ja hoia' (passiivne, nt BlackRock/Vanguard indeksifondi stiil) ---")
        print(f"  Osta-ja-hoia tootlus: {bsign}${benchmark.total_return_usd:,.2f}  ({bsign}{benchmark.total_return_pct:.2f}%)")
        diff = metrics.total_return_pct - benchmark.total_return_pct
        if diff > 0:
            print(f"  -> Aktiivne strateegia ÜLETAS osta-ja-hoia tulemust {diff:.2f} protsendipunkti võrra.")
        elif diff < 0:
            print(f"  -> Aktiivne strateegia JÄI osta-ja-hoia tulemusele ALLA {abs(diff):.2f} protsendipunkti võrra.")
        else:
            print("  -> Tulemused olid võrdsed.")


def print_scenario_comparison(
    period_name: str,
    scenario_metrics: list[tuple[str, Metrics]],
    benchmark: BenchmarkResult,
) -> None:
    """Kompaktne kõrvutus: kuidas iga kumulatiivne parandus mõjutas tulemust."""
    print(f"\n{'=' * 78}")
    print(f"  {period_name} — stsenaariumide võrdlus")
    print(f"{'=' * 78}")
    header = f"  {'Stsenaarium':<32}{'Tootlus %':>12}{'PF':>8}{'Tehinguid':>11}{'Max DD %':>11}"
    print(header)
    print(f"  {'-' * 74}")

    for name, m in scenario_metrics:
        pf_str = "∞" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
        print(
            f"  {name:<32}{m.total_return_pct:>+11.2f}%{pf_str:>8}"
            f"{m.num_trades:>11}{m.max_drawdown_pct:>10.2f}%"
        )

    print(f"  {'-' * 74}")
    print(f"  {'Osta-ja-hoia (võrdlus)':<32}{benchmark.total_return_pct:>+11.2f}%{'—':>8}{'0':>11}{'—':>11}")


def plot_equity_curve(period_name: str, result: BacktestResult, output_dir: str = "data") -> str | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if result.equity_curve.empty:
        return None

    os.makedirs(output_dir, exist_ok=True)
    safe_name = period_name.replace(" ", "_").replace("(", "").replace(")", "")
    path = os.path.join(output_dir, f"equity_{safe_name}.png")

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(result.equity_curve["time"], result.equity_curve["equity"])
    ax.set_title(f"Equity-kõver — {period_name}")
    ax.set_xlabel("Aeg")
    ax.set_ylabel("Portfelli väärtus ($)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
