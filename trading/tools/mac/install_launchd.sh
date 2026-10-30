#!/bin/zsh
# Register the KIS real-time listener as a launchd agent on the Mac (checklist 2.6):
# weekdays 08:55 KST start, listens through the regular session (--minutes 400 = until ~15:35),
# alerts when a held symbol trades near or under its stop. Run once: zsh trading/tools/mac/install_launchd.sh
# Remove:  launchctl bootout gui/$(id -u)/com.beomstar.kis-ws && rm ~/Library/LaunchAgents/com.beomstar.kis-ws.plist
set -e
REPO="${REPO:-$HOME/beomstar_git}"
VENV="${VENV:-$HOME/.venvs/beomstar}"
PLIST="$HOME/Library/LaunchAgents/com.beomstar.kis-ws.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/beomstar/kis_ws"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.beomstar.kis-ws</string>
  <key>ProgramArguments</key><array>
    <string>/bin/zsh</string><string>-lc</string>
    <string>cd "$REPO" && git pull -q --ff-only origin claude/dazzling-ride-a0nb4k; source "$VENV/bin/activate" && caffeinate -i python trading/tools/kis_ws_probe.py --minutes 400 --report-every 1800</string>
  </array>
  <key>StartCalendarInterval</key><array>
$(for d in 1 2 3 4 5; do echo "    <dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>55</integer></dict>"; done)
  </array>
  <key>StandardOutPath</key><string>$HOME/beomstar/kis_ws/launchd.log</string>
  <key>StandardErrorPath</key><string>$HOME/beomstar/kis_ws/launchd.err</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/com.beomstar.kis-ws" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $PLIST (weekdays 08:55, log $HOME/beomstar/kis_ws/launchd.log)"
echo "test now without waiting: launchctl kickstart gui/$(id -u)/com.beomstar.kis-ws"
