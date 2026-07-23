"""
Käivita: python research.py

Süstemaatiline, järkjärguline (staged) otsing kõige robustsema
parameetrite/mehhanismide kombinatsiooni leidmiseks.

MIKS JÄRKJÄRGULINE, MITTE TÄIS-GRID?
Meil on kokku ~7 häälestatavat "nuppu" (drop_pct, lookback_periods, rise_pct,
stop_loss_pct, trend_filter_ma, trailing_stop_pct, max_concurrent_positions,
+ Stage C mehhanismid). Kõigi kombinatsioonide läbiproovimine korraga
(täis-grid) kasvaks miljonitesse jooksudesse — ajaliselt mõttetu ja
sisuliselt EI OLE VAJALIK, kuna paljud parameetrid mõjutavad tulemust
suuresti sõltumatult. Selle asemel lahendame etapiviisiliselt:
riskijuhtimise nupud enne (Stage A), siis signaali nupud (Stage B) kinnitatud
riskiseadete peal, siis uued mehhanismid (Stage C) võitja peal, siis
lõplik valideerimine puutumata perioodil (Stage D). See on oluliselt
kiirem ja ka LIHTSAM MÕISTA — iga etapp vastab ühele küsimusele korraga.

VALIKUREEGEL (kehtib igas etapis ühtemoodi — turvalisus enne kasumit):
  1. HALVIM kolme tuntud perioodi tootlusest (peamine kriteerium)
  2. KESKMINE tootlus kolme perioodi peale (teisene kriteerium)
  3. KESKMINE kasumitegur (viimane, lahtiharutav kriteerium)
Me EI VALI kunagi puhtalt parima juhu või ainult keskmise järgi — see
oleks täpselt see overfitting-lõks, millest kogu selle projekti käigus
korduvalt räägitud on.

PUUTUMATA PERIOOD (2024-2025): kasutatakse AINULT üks kord, kõige lõpus
(Stage D), lõpliku valiku ausaks kontrolliks. Seda EI VAADATA kordagi
Stage A-C otsuste tegemisel.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pandas as pd

import config
import strategy
from backtest_engine import run_backtest
from config import BacktestConfig, MarketPeriod, StrategyConfig
from data_fetch import load_data
from metrics import compute_metrics

random.seed(42)  # korratavuse jaoks


def build_period_df(full_df: pd.DataFrame, period: MarketPeriod, strategy_cfg: StrategyConfig) -> pd.DataFrame:
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


def evaluate(
    full_df: pd.DataFrame,
    periods: list[MarketPeriod],
    strategy_cfg: StrategyConfig,
    backtest_cfg: BacktestConfig,
) -> dict:
    """Käivitab backtest'i kõigi antud perioodide peale ja tagastab
    valikureegli jaoks vajalikud koondnäitajad."""
    returns = []
    profit_factors = []
    per_period = {}

    for period in periods:
        period_df = build_period_df(full_df, period, strategy_cfg)
        if period_df.empty:
            returns.append(0.0)
            profit_factors.append(0.0)
            per_period[period.name] = None
            continue
        result = run_backtest(period_df, strategy_cfg, backtest_cfg)
        m = compute_metrics(result, backtest_cfg.starting_capital)
        returns.append(m.total_return_pct)
        pf = m.profit_factor if m.profit_factor != float("inf") else 50.0  # lae lõpmatuse jaoks võrdluses
        profit_factors.append(pf)
        per_period[period.name] = m

    worst_return = min(returns)
    mean_return = sum(returns) / len(returns)
    mean_pf = sum(profit_factors) / len(profit_factors)

    return {
        "worst_return": worst_return,
        "mean_return": mean_return,
        "mean_pf": mean_pf,
        "returns": returns,
        "per_period": per_period,
    }


def selection_key(evaluation: dict) -> tuple[float, float, float]:
    """Valikureegel: (halvim tootlus, keskmine tootlus, keskmine PF) —
    Python võrdleb tuple'eid elementhaaval, seega see rakendab automaatselt
    prioriteetsuse järjekorra (esimene võrdub alles siis vaadatakse teist jne)."""
    return (evaluation["worst_return"], evaluation["mean_return"], evaluation["mean_pf"])


def best_of(candidates: list[tuple[str, StrategyConfig, BacktestConfig, dict]]) -> tuple[str, StrategyConfig, BacktestConfig, dict]:
    return max(candidates, key=lambda c: selection_key(c[3]))


def print_stage_header(title: str) -> None:
    print(f"\n{'#' * 78}\n# {title}\n{'#' * 78}")


def print_row(label: str, evaluation: dict) -> None:
    r = evaluation["returns"]
    print(
        f"  {label:<70} halvim={evaluation['worst_return']:>8.2f}%  "
        f"keskm={evaluation['mean_return']:>8.2f}%  PF_keskm={evaluation['mean_pf']:>6.2f}  "
        f"[{r[0]:>7.2f}% / {r[1]:>7.2f}% / {r[2]:>7.2f}%]"
    )


def main() -> None:
    print("Laen andmeid (2020-01-01 .. 2026-01-01, sisaldab puutumata perioodi 2024-2025)...")
    full_df = load_data(
        symbol=config.DATA.symbol,
        interval=config.DATA.interval,
        start=config.DATA.fetch_start,
        end=config.DATA.fetch_end,
        cache_dir=config.DATA.cache_dir,
    )
    print(f"Laetud {len(full_df)} küünalt.\n")

    periods = config.MARKET_PERIODS
    base_strategy = StrategyConfig(drop_pct=10.0, lookback_periods=14, rise_pct=8.0)
    base_backtest = BacktestConfig(starting_capital=10_000.0, fee_rate=0.001)

    run_count = 0

    # ------------------------------------------------------------------
    # STAGE A: riskijuhtimise nupud
    # ------------------------------------------------------------------
    print_stage_header("STAGE A: riskijuhtimise nupud (trend_filter_ma, stop_loss_pct, "
                        "trailing_stop_pct, max_concurrent_positions)")

    trend_filter_options = [None, 100, 150, 200]
    stop_loss_options = [None, 10.0, 15.0, 20.0]
    trailing_options = [None, 10.0, 15.0, 20.0]
    max_positions_options = [3, 5, 8]

    stage_a_candidates = []
    for tf in trend_filter_options:
        for sl in stop_loss_options:
            for tr in trailing_options:
                for mp in max_positions_options:
                    strat = replace(base_strategy, trend_filter_ma=tf, stop_loss_pct=sl, trailing_stop_pct=tr)
                    bt = replace(base_backtest, max_concurrent_positions=mp)
                    ev = evaluate(full_df, periods, strat, bt)
                    run_count += 1
                    label = f"MA{tf} SL{sl} TRAIL{tr} POS{mp}"
                    stage_a_candidates.append((label, strat, bt, ev))

    print(f"Testitud {len(stage_a_candidates)} riskikonfiguratsiooni.")
    stage_a_winner_label, stage_a_strategy, stage_a_backtest, stage_a_eval = best_of(stage_a_candidates)
    print("\nVõitja:")
    print_row(stage_a_winner_label, stage_a_eval)

    # Top 5 kuvamiseks
    top5 = sorted(stage_a_candidates, key=lambda c: selection_key(c[3]), reverse=True)[:5]
    print("\nTop 5:")
    for label, _, _, ev in top5:
        print_row(label, ev)

    # ------------------------------------------------------------------
    # STAGE B: signaali nupud (fikseeritud Stage A riskiseaded)
    # ------------------------------------------------------------------
    print_stage_header("STAGE B: signaali nupud (drop_pct, lookback_periods, rise_pct) "
                        "Stage A võitja riskiseadete peal")

    drop_pct_options = [7.0, 10.0, 13.0, 16.0]
    lookback_options = [7, 14, 21, 30]
    rise_pct_options = [5.0, 8.0, 12.0, 16.0]

    stage_b_candidates = []
    for dp in drop_pct_options:
        for lb in lookback_options:
            for rp in rise_pct_options:
                strat = replace(stage_a_strategy, drop_pct=dp, lookback_periods=lb, rise_pct=rp)
                ev = evaluate(full_df, periods, strat, stage_a_backtest)
                run_count += 1
                label = f"DROP{dp} LOOKBACK{lb} RISE{rp}"
                stage_b_candidates.append((label, strat, stage_a_backtest, ev))

    print(f"Testitud {len(stage_b_candidates)} signaalikonfiguratsiooni.")
    stage_b_winner_label, stage_b_strategy, stage_b_backtest, stage_b_eval = best_of(stage_b_candidates)
    print("\nVõitja:")
    print_row(stage_b_winner_label, stage_b_eval)

    top5b = sorted(stage_b_candidates, key=lambda c: selection_key(c[3]), reverse=True)[:5]
    print("\nTop 5:")
    for label, _, _, ev in top5b:
        print_row(label, ev)

    # ------------------------------------------------------------------
    # STAGE C: uued mehhanismid, igaüks eraldi testitud Stage B võitja peal
    # ------------------------------------------------------------------
    print_stage_header("STAGE C: uued mehhanismid (igaüks eraldi Stage B võitja peal)")

    baseline_eval = stage_b_eval
    print("Stage B võitja (baasjoon Stage C jaoks):")
    print_row("BASELINE (Stage B võitja)", baseline_eval)

    kept_mechanisms: dict[str, dict] = {}

    # C1: jahtumisperiood pärast stop-lossi
    print("\n--- C1: jahtumisperiood pärast stop-lossi ---")
    c1_candidates = []
    for n in [3, 7, 14]:
        strat = replace(stage_b_strategy, cooldown_after_stop_loss=n)
        ev = evaluate(full_df, periods, strat, stage_b_backtest)
        run_count += 1
        label = f"COOLDOWN{n}"
        c1_candidates.append((label, strat, stage_b_backtest, ev))
        print_row(label, ev)
    c1_label, c1_strategy, c1_backtest, c1_eval = best_of(c1_candidates)
    if selection_key(c1_eval) > selection_key(baseline_eval):
        print(f"-> C1 ALLES ({c1_label}): parandab baasjoont.")
        kept_mechanisms["cooldown_after_stop_loss"] = c1_strategy.cooldown_after_stop_loss
    else:
        print("-> C1 TAGASI LÜKATUD: ei paranda baasjoont.")

    # C2: osaline kasumivõtt (scale-out) — vajab trailing_stop_pct olemasolu
    print("\n--- C2: osaline kasumivõtt (scale-out 50%) ---")
    if stage_b_strategy.trailing_stop_pct is None:
        # Kui Stage B võitjal polnud trailingut, lisa testimiseks üks mõistlik väärtus.
        c2_base = replace(stage_b_strategy, trailing_stop_pct=10.0)
        print("  (Stage B võitjal polnud trailing_stop_pct'i — lisan katseks 10% testimise ajaks.)")
    else:
        c2_base = stage_b_strategy
    strat_c2 = replace(c2_base, scale_out_fraction=0.5)
    ev_c2 = evaluate(full_df, periods, strat_c2, stage_b_backtest)
    run_count += 1
    print_row("SCALE_OUT_0.5", ev_c2)
    if selection_key(ev_c2) > selection_key(baseline_eval):
        print("-> C2 ALLES: parandab baasjoont.")
        kept_mechanisms["scale_out_fraction"] = 0.5
        kept_mechanisms["_scale_out_needed_trailing"] = c2_base.trailing_stop_pct
    else:
        print("-> C2 TAGASI LÜKATUD: ei paranda baasjoont.")

    # C3: ajapõhine sundsulgemine
    print("\n--- C3: ajapõhine sundsulgemine (max_holding_periods) ---")
    c3_candidates = []
    for n in [30, 60, 90]:
        strat = replace(stage_b_strategy, max_holding_periods=n)
        ev = evaluate(full_df, periods, strat, stage_b_backtest)
        run_count += 1
        label = f"MAXHOLD{n}"
        c3_candidates.append((label, strat, stage_b_backtest, ev))
        print_row(label, ev)
    c3_label, c3_strategy, c3_backtest, c3_eval = best_of(c3_candidates)
    if selection_key(c3_eval) > selection_key(baseline_eval):
        print(f"-> C3 ALLES ({c3_label}): parandab baasjoont.")
        kept_mechanisms["max_holding_periods"] = c3_strategy.max_holding_periods
    else:
        print("-> C3 TAGASI LÜKATUD: ei paranda baasjoont.")

    # C4: MA50/MA200 golden-cross trendifilter (asendab lihtsa hind>MA filtri, kui see oli seatud)
    print("\n--- C4: golden-cross trendifilter (MA50 > MA200) ---")
    if stage_b_strategy.trend_filter_ma is not None:
        strat_c4 = replace(stage_b_strategy, trend_filter_fast_ma=50)
        ev_c4 = evaluate(full_df, periods, strat_c4, stage_b_backtest)
        run_count += 1
        print_row("GOLDEN_CROSS_MA50", ev_c4)
        if selection_key(ev_c4) > selection_key(baseline_eval):
            print("-> C4 ALLES: parandab baasjoont.")
            kept_mechanisms["trend_filter_fast_ma"] = 50
        else:
            print("-> C4 TAGASI LÜKATUD: ei paranda baasjoont.")
    else:
        print("  (Stage B võitjal polnud trend_filter_ma seatud — golden-cross pole rakendatav, jäetakse vahele.)")

    # ------------------------------------------------------------------
    # Kombineeri ALLESJÄÄNUD mehhanismid ühte lõplikku kandidaati
    # ------------------------------------------------------------------
    print_stage_header("Kombineeritud lõplik kandidaat (allesjäänud C-mehhanismid koos)")

    final_strategy = stage_b_strategy
    if "_scale_out_needed_trailing" in kept_mechanisms:
        final_strategy = replace(final_strategy, trailing_stop_pct=kept_mechanisms["_scale_out_needed_trailing"])
    if "cooldown_after_stop_loss" in kept_mechanisms:
        final_strategy = replace(final_strategy, cooldown_after_stop_loss=kept_mechanisms["cooldown_after_stop_loss"])
    if "scale_out_fraction" in kept_mechanisms:
        final_strategy = replace(final_strategy, scale_out_fraction=kept_mechanisms["scale_out_fraction"])
    if "max_holding_periods" in kept_mechanisms:
        final_strategy = replace(final_strategy, max_holding_periods=kept_mechanisms["max_holding_periods"])
    if "trend_filter_fast_ma" in kept_mechanisms:
        final_strategy = replace(final_strategy, trend_filter_fast_ma=kept_mechanisms["trend_filter_fast_ma"])

    final_eval_combined = evaluate(full_df, periods, final_strategy, stage_b_backtest)
    run_count += 1
    print_row("KOMBINEERITUD", final_eval_combined)

    if selection_key(final_eval_combined) >= selection_key(baseline_eval):
        print("-> Kombinatsioon on vähemalt sama hea kui Stage B võitja üksi — kasutame kombinatsiooni.")
        final_strategy_chosen = final_strategy
        final_eval = final_eval_combined
    else:
        print("-> Kombinatsioon KOOS on halvem kui üksikud mehhanismid eraldi (vastuolud kombineerudes) "
              "— kasutame selle asemel ainult Stage B võitjat.")
        final_strategy_chosen = stage_b_strategy
        final_eval = baseline_eval

    final_backtest_chosen = stage_b_backtest

    # ------------------------------------------------------------------
    # STAGE D: väike lokaalne täpsustus + PUUTUMATA valideerimine (ÜKS KORD)
    # ------------------------------------------------------------------
    print_stage_header("STAGE D: lokaalne täpsustus + puutumata (holdout) valideerimine")

    refine_candidates = [("ALGNE", final_strategy_chosen, final_backtest_chosen,
                           evaluate(full_df, periods, final_strategy_chosen, final_backtest_chosen))]
    run_count += 1

    for delta_drop in [-2.0, 0.0, 2.0]:
        for delta_rise in [-2.0, 0.0, 2.0]:
            if delta_drop == 0.0 and delta_rise == 0.0:
                continue
            strat = replace(
                final_strategy_chosen,
                drop_pct=max(1.0, final_strategy_chosen.drop_pct + delta_drop),
                rise_pct=max(1.0, final_strategy_chosen.rise_pct + delta_rise),
            )
            ev = evaluate(full_df, periods, strat, final_backtest_chosen)
            run_count += 1
            label = f"REFINE drop{delta_drop:+.0f} rise{delta_rise:+.0f}"
            refine_candidates.append((label, strat, final_backtest_chosen, ev))

    print(f"Lokaalne täpsustus: testitud {len(refine_candidates)} varianti ümber lõpliku kandidaadi.")
    refine_label, refine_strategy, refine_backtest, refine_eval = best_of(refine_candidates)
    print("Parim lokaalse täpsustuse variant:")
    print_row(refine_label, refine_eval)

    if selection_key(refine_eval) > selection_key(final_eval):
        print("-> Lokaalne täpsustus parandas tulemust, kasutame seda lõpliku konfiguratsioonina.")
        final_strategy_chosen = refine_strategy
        final_eval = refine_eval
    else:
        print("-> Lokaalne täpsustus ei parandanud midagi, jääme eelmise valiku juurde.")

    print(f"\nKOKKU testitud kombinatsioone kõigis etappides: {run_count}")

    print("\nLÕPLIK VALITUD KONFIGURATSIOON (enne holdout't):")
    print(f"  {final_strategy_chosen}")
    print(f"  {final_backtest_chosen}")
    print("\nTulemused KOLMEL TUNTUD perioodil (need, mille põhjal valiti):")
    for period, m in final_eval["per_period"].items():
        if m is None:
            print(f"  {period}: (andmeid ei olnud)")
        else:
            pf_str = "inf" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
            print(f"  {period}: tootlus={m.total_return_pct:+.2f}%  PF={pf_str}  "
                  f"tehinguid={m.num_trades}  max_dd={m.max_drawdown_pct:.2f}%")

    print("\n" + "=" * 78)
    print("PUUTUMATA PERIOOD (2024-2025) — EI OLE KASUTATUD ÜHESKI EELNEVAS VALIKUS")
    print("=" * 78)
    holdout_df = build_period_df(full_df, config.HOLDOUT_PERIOD, final_strategy_chosen)
    if holdout_df.empty:
        print("Andmeid puutumata perioodi jaoks ei leitud.")
    else:
        holdout_result = run_backtest(holdout_df, final_strategy_chosen, final_backtest_chosen)
        holdout_metrics = compute_metrics(holdout_result, final_backtest_chosen.starting_capital)
        pf_str = "inf" if holdout_metrics.profit_factor == float("inf") else f"{holdout_metrics.profit_factor:.2f}"
        print(f"  Tootlus:      {holdout_metrics.total_return_pct:+.2f}%  (${holdout_metrics.total_return_usd:+,.2f})")
        print(f"  Tehinguid:    {holdout_metrics.num_trades}")
        print(f"  PF:           {pf_str}")
        print(f"  Max drawdown: {holdout_metrics.max_drawdown_pct:.2f}%")

        known_mean = final_eval["mean_return"]
        gap = known_mean - holdout_metrics.total_return_pct
        print(f"\n  Tuntud perioodide keskmine tootlus: {known_mean:+.2f}%")
        print(f"  Puutumata perioodi tootlus:         {holdout_metrics.total_return_pct:+.2f}%")
        print(f"  Vahe (üleöialtamise/overfitting risk):  {gap:+.2f} protsendipunkti")

    print("\nValmis. Vt RESEARCH.md täieliku analüüsi ja soovituste jaoks.")


if __name__ == "__main__":
    main()
