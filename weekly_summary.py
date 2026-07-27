"""
Käivita: python weekly_summary.py

Prindib nädalase kokkuvõtte paper trading tulemustest (viimase 7 päeva
equity_history põhjal) — mõeldud kutsumiseks kord nädalas (launchd) koos
macOS teatega, aga töötab ka lihtsalt käsitsi käivitatuna ülevaate saamiseks.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from paper_trade import SCENARIO, load_state


def main() -> None:
    if not os.path.exists("paper_state.json"):
        print("Paper trading pole veel käivitunud.")
        return

    _, meta = load_state()
    if not meta.equity_history:
        print("Olek on olemas, aga ühtegi küünalt pole veel töödeldud.")
        return

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    week_rows = [
        row for row in meta.equity_history
        if datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc) >= week_ago
    ]

    last = meta.equity_history[-1]
    starting_capital = SCENARIO.backtest.starting_capital

    if len(week_rows) >= 2:
        week_start_equity = week_rows[0]["equity"]
    elif week_rows:
        week_start_equity = starting_capital
    else:
        week_start_equity = last["equity"]
    week_return_pct = (last["equity"] - week_start_equity) / week_start_equity * 100

    trades_this_week = sum(1 for row in week_rows if row["action"] != "—")

    print(f"Nädala tootlus:        {week_return_pct:+.2f}%")
    print(f"Tehinguid sel nädalal: {trades_this_week}")
    print(f"Portfell:              ${last['equity']:,.2f}")
    print(f"Kogutootlus algusest:  {last['return_pct']:+.2f}%")
    print(f"Osta-ja-hoia võrdlus:  ${last['bh_value']:,.2f}")

    summary_line = (
        f"Nädala ülevaade: portfell ${last['equity']:,.0f} "
        f"(nädalas {week_return_pct:+.1f}%), kokku {last['return_pct']:+.1f}% algusest. "
        f"Osta-hoia: ${last['bh_value']:,.0f}."
    )
    print(f"\nNOTIFICATION_TEXT: {summary_line}")


if __name__ == "__main__":
    main()
