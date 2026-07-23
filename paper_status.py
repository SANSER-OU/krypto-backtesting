"""
Käivita: python paper_status.py

Prindib praeguse paper trading seisu (viimase TÖÖDELDUD päeva kohta,
ilma uut päeva alla laadimata/töötlemata) — kasutajale igal ajal
käsitsi kontrollimiseks. Uue päeva töötlemiseks kasuta paper_trade.py.
"""

from __future__ import annotations

import os

from paper_trade import SCENARIO, load_state


def main() -> None:
    if not os.path.exists("paper_state.json"):
        print("Paper trading pole veel käivitatud — käivita esmalt: python paper_trade.py")
        return

    portfolio, meta = load_state()

    if not meta.equity_history:
        print("Olek on olemas, aga ühtegi küünalt pole veel töödeldud.")
        return

    last = meta.equity_history[-1]
    starting_capital = SCENARIO.backtest.starting_capital

    print(f"Paper trading algas: {meta.started_at.strftime('%Y-%m-%d') if meta.started_at else '—'}")
    print(f"Viimati töödeldud: {last['date']}")
    print()
    print(f"Portfelli väärtus:     ${last['equity']:,.2f}  ({last['return_pct']:+.2f}% algusest)")
    print(f"Osta-ja-hoia võrdlus:  ${last['bh_value']:,.2f}")
    print(f"Sularaha:              ${portfolio.cash:,.2f}")
    print(f"Kokku tehinguid:       {len(portfolio.trades)}")
    print()

    if portfolio.open_positions:
        print(f"Avatud positsioone: {len(portfolio.open_positions)}")
        for pos in portfolio.open_positions:
            print(
                f"  - avatud {pos.entry_time.strftime('%Y-%m-%d')} @ ${pos.entry_price:,.2f}, "
                f"maht ${pos.size_usd:,.2f}, tipp ${pos.peak_price:,.2f}, "
                f"{'relvastatud' if pos.armed else 'ootel'}"
            )
    else:
        print("Avatud positsioone pole hetkel.")

    print(f"\nStarting capital: ${starting_capital:,.2f} — vt paper_trading_log.md täieliku ajaloo jaoks.")


if __name__ == "__main__":
    main()
