#!/bin/bash
# launchd käivitab selle kord nädalas (esmaspäeviti). Saadab alati macOS
# teate nädala kokkuvõttega, sõltumata sellest, kas tehinguid toimus.
set -euo pipefail
cd "$(dirname "$0")"

source venv/bin/activate
OUTPUT=$(python weekly_summary.py 2>&1)
echo "$OUTPUT"

NOTIFICATION_TEXT=$(echo "$OUTPUT" | grep "^NOTIFICATION_TEXT:" | sed 's/^NOTIFICATION_TEXT: //' || true)
if [ -n "$NOTIFICATION_TEXT" ]; then
    osascript -e "display notification \"$NOTIFICATION_TEXT\" with title \"Paper trading — nädala ülevaade\"" || true
fi
