#!/bin/bash
# launchd käivitab selle iga päev. Jookseb paper_trade.py, saadab macOS
# teate AINULT kui reaalselt toimus tehing, ja teeb valikulise git
# commit+push varukoopiaks (olek püsib niikuinii kohalikus paper_state.json-is).
set -euo pipefail
cd "$(dirname "$0")"

source venv/bin/activate
OUTPUT=$(python paper_trade.py 2>&1)
echo "$OUTPUT"

ACTION_LINE=$(echo "$OUTPUT" | grep "^Tegevus:" || true)
if [ -n "$ACTION_LINE" ] && [ "$ACTION_LINE" != "Tegevus: —" ]; then
    PORTFOLIO_LINE=$(echo "$OUTPUT" | grep "^Portfell:" || true)
    osascript -e "display notification \"$ACTION_LINE $PORTFOLIO_LINE\" with title \"Paper trading\"" || true
fi

if ! git diff --quiet -- paper_state.json paper_trading_log.md 2>/dev/null; then
    git add paper_state.json paper_trading_log.md
    git commit -m "Paper trading: $(date -u +%Y-%m-%d)" >/dev/null
    git push || echo "Git push ebaõnnestus (olek on kohalikult siiski salvestatud, pole kriitiline)."
fi
