"""
Backtest'i simulatsioonimootor.

See on event-loop simulatsioon (mitte puhtalt "vektoriseeritud" pandas
arvutus), kuna pyramiding — mitu samaaegset avatud positsiooni, igaühel
oma ostuhind ja oma müügi-eesmärk — vajab olekut, mida on lihtsam
küünal-küünla-haaval jälgida kui ühe suure tabeliarvutusega väljendada.

Kapitali jaotus: algkapital jagatakse `max_concurrent_positions` võrdseks
"pesaks" (slot_size). Uus ostusignaal avab positsiooni ainult siis, kui
vaba pesa on olemas — see piirab riski, sest muidu võiks langevas turus
kogu kapital "kinni jääda" enne, kui ükski positsioon jõuab müügihinnani.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from config import BacktestConfig, StrategyConfig


@dataclass
class Position:
    entry_time: pd.Timestamp
    entry_price: float
    size_usd: float
    qty: float
    peak_price: float = 0.0   # kõrgeim hind, mis positsiooni avamisest saati nähtud
    armed: bool = False       # trailing-exit puhul: kas rise_pct sihtmärk on juba korra saavutatud
    entry_index: int = 0      # küünla järjekorranumber ostuhetkel (max_holding_periods jaoks)
    scaled_out: bool = False  # kas osaline kasumivõtt (scale-out) on juba tehtud

    def __post_init__(self) -> None:
        if self.peak_price == 0.0:
            self.peak_price = self.entry_price


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: float
    size_usd: float
    entry_fee: float
    exit_fee: float
    pnl: float
    exit_reason: str


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.DataFrame = None
    final_cash: float = 0.0


@dataclass
class PortfolioState:
    """Kogu kauplemisoleku, mida `step()` iga küünla kohta uuendab.

    Sama klass ja sama `step()` funktsioon on kasutusel nii backtestingus
    (`run_backtest`, kõik küünlad korraga) kui paper trading'us
    (`paper_trade.py`, üks uus küünal päevas, olek püsib kettal) — see
    tagab, et mõlemad kasutavad TÄPSELT sama otsustusloogikat, mitte kahte
    lahknevat re-implementatsiooni.
    """
    cash: float
    running_peak_equity: float
    open_positions: list[Position] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    cooldown_remaining: int = 0


def _close_position(
    position: Position,
    exit_time: pd.Timestamp,
    exit_price: float,
    fee_rate: float,
    exit_reason: str,
) -> tuple[Trade, float]:
    """Sulgeb positsiooni ja tagastab (Trade, laekunud raha pärast tasu)."""
    gross_proceeds = position.qty * exit_price
    exit_fee = gross_proceeds * fee_rate
    net_proceeds = gross_proceeds - exit_fee

    entry_fee = position.size_usd * fee_rate
    pnl = net_proceeds - position.size_usd

    trade = Trade(
        entry_time=position.entry_time,
        exit_time=exit_time,
        entry_price=position.entry_price,
        exit_price=exit_price,
        qty=position.qty,
        size_usd=position.size_usd,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        pnl=pnl,
        exit_reason=exit_reason,
    )
    return trade, net_proceeds


def _scale_out_position(
    position: Position,
    exit_time: pd.Timestamp,
    exit_price: float,
    fee_rate: float,
    fraction: float,
) -> tuple[Trade, float]:
    """Müüb ära ainult `fraction` osa positsioonist (nt 0.5 = pool) ja
    vähendab ülejäänud positsiooni qty/size_usd vastavalt — positsioon jääb
    avatuks, ainult väiksemas mahus, ja jätkab trailing-stop loogikaga."""
    sold_qty = position.qty * fraction
    sold_size_usd = position.size_usd * fraction

    gross_proceeds = sold_qty * exit_price
    exit_fee = gross_proceeds * fee_rate
    net_proceeds = gross_proceeds - exit_fee

    entry_fee = sold_size_usd * fee_rate
    pnl = net_proceeds - sold_size_usd

    trade = Trade(
        entry_time=position.entry_time,
        exit_time=exit_time,
        entry_price=position.entry_price,
        exit_price=exit_price,
        qty=sold_qty,
        size_usd=sold_size_usd,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        pnl=pnl,
        exit_reason="scale_out",
    )

    position.qty -= sold_qty
    position.size_usd -= sold_size_usd
    position.scaled_out = True

    return trade, net_proceeds


def step(
    state: PortfolioState,
    current_time: pd.Timestamp,
    current_close: float,
    buy_signal: bool,
    t_idx: int,
    strategy_cfg: StrategyConfig,
    backtest_cfg: BacktestConfig,
) -> None:
    """Töötleb ÜHE küünla otsustusloogika ja muudab `state`-t kohapeal:
    positsioonide sulgemine (stop-loss / trailing-stop / scale-out / aja
    sundsulgemine), portfelli-katkestaja, ostusignaali kontroll ja
    jahtumisperiood. `t_idx` on monotoonselt kasvav küünla-loendur (kasutusel
    `max_holding_periods` jaoks) — backtestis rea indeks, paper trading'us
    püsiv loendur olekus.

    See on ainus koht, kus otsustatakse, millal osta/müüa — nii
    `run_backtest` kui `paper_trade.py` kutsuvad ainult seda funktsiooni,
    mitte oma versiooni loogikast.
    """
    slot_size = backtest_cfg.slot_size
    fee_rate = backtest_cfg.fee_rate

    # 1) Kontrolli iga avatud positsiooni müügi-/stop-loss/scale-out/aja tingimust.
    still_open: list[Position] = []
    stop_loss_triggered_this_candle = False
    for pos in state.open_positions:
        pos.peak_price = max(pos.peak_price, current_close)

        take_profit_price = pos.entry_price * (1 + strategy_cfg.rise_pct / 100)
        stop_loss_price = None
        if strategy_cfg.stop_loss_pct is not None:
            stop_loss_price = pos.entry_price * (1 - strategy_cfg.stop_loss_pct / 100)

        exit_reason = None

        # Stop-loss on kõva riskipiir — kontrolli seda esimesena, sõltumata
        # trailing/fikseeritud müügiloogikast.
        if stop_loss_price is not None and current_close <= stop_loss_price:
            exit_reason = "stop_loss"
        elif strategy_cfg.trailing_stop_pct is not None:
            # Trailing-exit: "relvastu" positsioon, kui rise_pct on korra
            # saavutatud, seejärel müü alles siis, kui hind langeb
            # trailing_stop_pct võrra oma seniselt tipult (peak_price) —
            # see laseb tugeval tõusul kaua kasvada, mitte ei müü kohe Z%-l.
            if not pos.armed and current_close >= take_profit_price:
                pos.armed = True
                # Osaline kasumivõtt: müü kohe relvastumisel ära osa
                # positsioonist, ülejäänu jätkab trailing-stop'iga.
                if strategy_cfg.scale_out_fraction is not None and not pos.scaled_out:
                    scale_trade, scale_proceeds = _scale_out_position(
                        pos, current_time, current_close, fee_rate, strategy_cfg.scale_out_fraction
                    )
                    state.cash += scale_proceeds
                    state.trades.append(scale_trade)
            if pos.armed:
                trailing_stop_price = pos.peak_price * (1 - strategy_cfg.trailing_stop_pct / 100)
                if current_close <= trailing_stop_price:
                    exit_reason = "trailing_stop"
        else:
            # Algne lihtne loogika: müü kohe, kui rise_pct on saavutatud.
            if current_close >= take_profit_price:
                exit_reason = "take_profit"

        # Ajapõhine sundsulgemine: ainult siis, kui miski muu juba ei sulgenud.
        if (
            exit_reason is None
            and strategy_cfg.max_holding_periods is not None
            and (t_idx - pos.entry_index) >= strategy_cfg.max_holding_periods
        ):
            exit_reason = "time_exit"

        if exit_reason is not None:
            trade, proceeds = _close_position(pos, current_time, current_close, fee_rate, exit_reason)
            state.cash += proceeds
            state.trades.append(trade)
            if exit_reason == "stop_loss":
                stop_loss_triggered_this_candle = True
        else:
            still_open.append(pos)
    state.open_positions = still_open

    if stop_loss_triggered_this_candle and strategy_cfg.cooldown_after_stop_loss is not None:
        state.cooldown_remaining = strategy_cfg.cooldown_after_stop_loss

    # 1b) Portfelli-tasandi katkestaja: kui kogu portfell on juba tipust
    # rohkem langenud kui lubatud, ei avata uusi positsioone — kasutab
    # ainult juba teadaolevat (praeguse küünla) seisu, mitte tulevikku.
    pre_buy_equity = state.cash + sum(pos.qty * current_close for pos in state.open_positions)
    state.running_peak_equity = max(state.running_peak_equity, pre_buy_equity)
    circuit_breaker_tripped = False
    if backtest_cfg.max_portfolio_drawdown_pct is not None:
        current_drawdown_pct = (state.running_peak_equity - pre_buy_equity) / state.running_peak_equity * 100
        circuit_breaker_tripped = current_drawdown_pct >= backtest_cfg.max_portfolio_drawdown_pct

    # 2) Kontrolli ostusignaali (ainult kui rolling-high juba arvutatud, st mitte NaN).
    if (
        buy_signal
        and not circuit_breaker_tripped
        and state.cooldown_remaining <= 0
        and len(state.open_positions) < backtest_cfg.max_concurrent_positions
        and state.cash >= slot_size
    ):
        entry_fee = slot_size * fee_rate
        qty = (slot_size - entry_fee) / current_close
        state.cash -= slot_size
        state.open_positions.append(
            Position(
                entry_time=current_time, entry_price=current_close, size_usd=slot_size, qty=qty,
                entry_index=t_idx,
            )
        )

    if state.cooldown_remaining > 0:
        state.cooldown_remaining -= 1


def run_backtest(
    df: pd.DataFrame,
    strategy_cfg: StrategyConfig,
    backtest_cfg: BacktestConfig,
) -> BacktestResult:
    """
    df peab sisaldama veerge: open_time, close, buy_signal (vt strategy.add_signals).
    Simuleerib kauplemist rida-rea haaval (kutsudes `step()`-i) ja tagastab
    kõik kauplused + equity-kõvera.
    """
    state = PortfolioState(cash=backtest_cfg.starting_capital, running_peak_equity=backtest_cfg.starting_capital)
    equity_rows = []

    for t_idx, row in enumerate(df.itertuples(index=False)):
        current_time = row.open_time
        current_close = row.close
        buy_signal = bool(getattr(row, "buy_signal", False))

        step(state, current_time, current_close, buy_signal, t_idx, strategy_cfg, backtest_cfg)

        # Equity = sularaha + kõigi avatud positsioonide praegune turuväärtus.
        positions_value = sum(pos.qty * current_close for pos in state.open_positions)
        equity_rows.append({"time": current_time, "equity": state.cash + positions_value})

    # Perioodi lõpus sulgeme kõik veel avatud positsioonid viimase teadaoleva
    # hinnaga, et tulemus oleks lõplik ja võrreldav (mitte "õhus rippuv" kasum/kahjum).
    if state.open_positions:
        last_time = df.iloc[-1]["open_time"]
        last_close = df.iloc[-1]["close"]
        for pos in state.open_positions:
            trade, proceeds = _close_position(pos, last_time, last_close, backtest_cfg.fee_rate, "period_end")
            state.cash += proceeds
            state.trades.append(trade)

    equity_curve = pd.DataFrame(equity_rows)
    if not equity_curve.empty:
        equity_curve.loc[equity_curve.index[-1], "equity"] = state.cash

    return BacktestResult(trades=state.trades, equity_curve=equity_curve, final_cash=state.cash)
