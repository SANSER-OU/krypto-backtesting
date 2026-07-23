"""
Käivita: python paper_trade.py

Paper trading — Stsenaarium 5 (uuringu soovitus) jooksutamine päris BTC/USDT
turul, päris ajas, FIKTIIVSE rahaga. Ei tee kunagi päris tehinguid.

Mõeldud käivitamiseks üks kord päevas (nt ajastatud pilve-rutiiniga, pärast
Binance'i päevaküünla sulgemist kell 00:00 UTC). Idempotentne: kui samal
päeval juba pole uut suletud küünalt töödelda, ei tee midagi teist korda.

Kasutab TÄPSELT sama otsustusloogikat (`backtest_engine.step()`) mis
backtesting — see on kavakohane, mitte juhus: paper trading ja backtest
EI TOHI kunagi lahku minna sama koodi kasutamises, muidu kaob mõte, milleks
backtest üldse tehti.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

import pandas as pd

import config
import data_fetch
import strategy
from backtest_engine import Position, PortfolioState, Trade, step

STATE_PATH = "paper_state.json"
LOG_PATH = "paper_trading_log.md"
SCENARIO = config.SCENARIOS[5]

# Sama puhver, mis backtestingus (200-päevase trendifiltri + lookback'i
# jaoks), et signaalid oleks värske andme peal kohe algusest korrektsed.
FETCH_LOOKBACK_DAYS = config.WARMUP_DAYS


@dataclass
class PaperMeta:
    t_idx: int = 0
    last_processed_open_time: pd.Timestamp | None = None
    started_at: pd.Timestamp | None = None
    bh_qty: float | None = None       # osta-ja-hoia varju-jälgija kogus (BTC)
    bh_entry_price: float | None = None
    equity_history: list[dict] = field(default_factory=list)


def _position_to_dict(pos: Position) -> dict:
    d = asdict(pos)
    d["entry_time"] = pos.entry_time.isoformat()
    return d


def _position_from_dict(d: dict) -> Position:
    d = dict(d)
    d["entry_time"] = pd.Timestamp(d["entry_time"])
    return Position(**d)


def _trade_to_dict(t: Trade) -> dict:
    d = asdict(t)
    d["entry_time"] = t.entry_time.isoformat()
    d["exit_time"] = t.exit_time.isoformat()
    return d


def _trade_from_dict(d: dict) -> Trade:
    d = dict(d)
    d["entry_time"] = pd.Timestamp(d["entry_time"])
    d["exit_time"] = pd.Timestamp(d["exit_time"])
    return Trade(**d)


def load_state() -> tuple[PortfolioState, PaperMeta]:
    starting_capital = SCENARIO.backtest.starting_capital

    if not os.path.exists(STATE_PATH):
        portfolio = PortfolioState(cash=starting_capital, running_peak_equity=starting_capital)
        return portfolio, PaperMeta()

    with open(STATE_PATH) as f:
        raw = json.load(f)

    portfolio = PortfolioState(
        cash=raw["cash"],
        running_peak_equity=raw["running_peak_equity"],
        open_positions=[_position_from_dict(p) for p in raw["open_positions"]],
        trades=[_trade_from_dict(t) for t in raw["trades"]],
        cooldown_remaining=raw["cooldown_remaining"],
    )
    meta = PaperMeta(
        t_idx=raw["t_idx"],
        last_processed_open_time=(
            pd.Timestamp(raw["last_processed_open_time"]) if raw["last_processed_open_time"] else None
        ),
        started_at=pd.Timestamp(raw["started_at"]) if raw["started_at"] else None,
        bh_qty=raw["bh_qty"],
        bh_entry_price=raw["bh_entry_price"],
        equity_history=raw["equity_history"],
    )
    return portfolio, meta


def save_state(portfolio: PortfolioState, meta: PaperMeta) -> None:
    raw = {
        "cash": portfolio.cash,
        "running_peak_equity": portfolio.running_peak_equity,
        "cooldown_remaining": portfolio.cooldown_remaining,
        "open_positions": [_position_to_dict(p) for p in portfolio.open_positions],
        "trades": [_trade_to_dict(t) for t in portfolio.trades],
        "t_idx": meta.t_idx,
        "last_processed_open_time": (
            meta.last_processed_open_time.isoformat() if meta.last_processed_open_time is not None else None
        ),
        "started_at": meta.started_at.isoformat() if meta.started_at is not None else None,
        "bh_qty": meta.bh_qty,
        "bh_entry_price": meta.bh_entry_price,
        "equity_history": meta.equity_history,
    }
    with open(STATE_PATH, "w") as f:
        json.dump(raw, f, indent=2)


def fetch_recent_closed_candles() -> pd.DataFrame:
    """Tõmbab värskelt (ilma cache'ita — aken nihkub iga päev) viimased
    FETCH_LOOKBACK_DAYS päeva ja jätab alles ainult TÄIELIKULT SULETUD
    küünlad (close_time juba minevikus) — väldib pooliku, alles kujuneva
    tänase küünla peal kauplemist."""
    now_utc = pd.Timestamp.now(tz="UTC")
    start_str = (now_utc - pd.Timedelta(days=FETCH_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end_str = (now_utc + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    raw_df = data_fetch.fetch_klines(SCENARIO_SYMBOL, SCENARIO_INTERVAL, start_str, end_str)
    return raw_df[raw_df["close_time"] < now_utc].reset_index(drop=True)


SCENARIO_SYMBOL = config.DATA.symbol
SCENARIO_INTERVAL = config.DATA.interval


def _describe_trades(trades: list[Trade]) -> str:
    if not trades:
        return "—"
    parts = []
    for t in trades:
        sign = "+" if t.pnl >= 0 else ""
        if t.exit_reason is None:
            continue
        parts.append(f"{t.exit_reason}: {sign}${t.pnl:,.2f}")
    return "; ".join(parts) if parts else "—"


def _append_log(rows: list[dict]) -> None:
    is_new_file = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a") as f:
        if is_new_file:
            f.write("# Paper trading logi — Stsenaarium 5 (uuringu soovitus)\n\n")
            f.write(
                f"Algus: {rows[0]['date']}, algkapital "
                f"${SCENARIO.backtest.starting_capital:,.0f}. Fiktiivne raha, "
                "päris turg — vt README.md.\n\n"
            )
            f.write("| Kuupäev | BTC hind | Tegevus | Portfell | Osta-hoia | Tootlus |\n")
            f.write("|---|---|---|---|---|---|\n")
        for row in rows:
            f.write(
                f"| {row['date']} | ${row['price']:,.2f} | {row['action']} "
                f"| ${row['equity']:,.2f} | ${row['bh_value']:,.2f} | "
                f"{row['return_pct']:+.2f}% |\n"
            )


def main() -> None:
    portfolio, meta = load_state()
    is_first_run = meta.started_at is None

    df = fetch_recent_closed_candles()
    signals_df = strategy.add_signals(
        df,
        SCENARIO.strategy.lookback_periods,
        SCENARIO.strategy.drop_pct,
        SCENARIO.strategy.trend_filter_ma,
        SCENARIO.strategy.trend_filter_fast_ma,
    )

    if is_first_run:
        # Esimesel käivitusel ei kaubelda tagasiulatuvalt — kogu ajalugu on
        # ainult indikaatori soojendus. Töödeldakse ainult kõige VIIMANE
        # (kõige värskem suletud) küünal, ehk paper trading algab "täna".
        new_rows = signals_df.tail(1)
        meta.started_at = pd.Timestamp.now(tz="UTC")
    else:
        new_rows = signals_df[signals_df["open_time"] > meta.last_processed_open_time]

    if new_rows.empty:
        print("Uusi suletud küünlaid pole töötlemiseks — tänane päev juba käsitletud, midagi ei tehtud.")
        return

    log_rows = []
    for row in new_rows.itertuples(index=False):
        buy_signal = bool(getattr(row, "buy_signal", False))
        trades_before = len(portfolio.trades)

        step(portfolio, row.open_time, row.close, buy_signal, meta.t_idx, SCENARIO.strategy, SCENARIO.backtest)

        new_trades = portfolio.trades[trades_before:]
        meta.t_idx += 1
        meta.last_processed_open_time = row.open_time

        if meta.bh_qty is None:
            # Osta-ja-hoia varju-jälgija: virtuaalne ühekordne ost paper
            # trading'u alguses, sama loogika mis metrics.compute_buy_and_hold.
            fee = SCENARIO.backtest.starting_capital * SCENARIO.backtest.fee_rate
            meta.bh_qty = (SCENARIO.backtest.starting_capital - fee) / row.close
            meta.bh_entry_price = row.close

        positions_value = sum(p.qty * row.close for p in portfolio.open_positions)
        equity = portfolio.cash + positions_value
        bh_value = meta.bh_qty * row.close
        return_pct = (equity - SCENARIO.backtest.starting_capital) / SCENARIO.backtest.starting_capital * 100

        log_row = {
            "date": row.open_time.strftime("%Y-%m-%d"),
            "price": row.close,
            "action": _describe_trades(new_trades),
            "equity": equity,
            "bh_value": bh_value,
            "return_pct": return_pct,
        }
        log_rows.append(log_row)
        meta.equity_history.append(log_row)

    save_state(portfolio, meta)
    _append_log(log_rows)

    last = log_rows[-1]
    print(f"Töödeldud {len(log_rows)} uus(t) küünal(t). Viimane: {last['date']}, BTC ${last['price']:,.2f}")
    print(f"Tegevus: {last['action']}")
    print(f"Portfell: ${last['equity']:,.2f} ({last['return_pct']:+.2f}% algusest)")
    print(f"Osta-ja-hoia võrdlus: ${last['bh_value']:,.2f}")
    print(f"Avatud positsioone: {len(portfolio.open_positions)}")


if __name__ == "__main__":
    main()
