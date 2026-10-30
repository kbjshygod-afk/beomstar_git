#!/usr/bin/env bash
# Pixel Agents office setup: one character per staff desk, seated in its own painted Area.
#   pixel_office.sh install [--force]   merge settings into ~/.pixel-agents/config.json and install the layout
#   pixel_office.sh status              show what is configured
# Backups are written next to the originals (config.json.bak-YYYYMMDD-HHMMSS). Restart Pixel Agents afterwards
# (bash pixel.sh, or wait for the next hourly launchd start).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA="${PIXEL_AGENTS_HOME:-$HOME/.pixel-agents}"
CFG="$PA/config.json"; LAYOUT="$PA/layout.json"
cmd="${1:-status}"; force="${2:-}"
mkdir -p "$PA"
case "$cmd" in
  install)
    python3 - "$CFG" "$DIR/pixel/config-office.json" <<'PY'
import json, os, sys, time
cfg_path, frag_path = sys.argv[1:3]
frag = json.load(open(frag_path))["standalone"]
cfg = {"vscode": {}, "standalone": {}, "externalAssetDirectories": [], "hooksConsent": {}, "hooksEnabled": {}}
if os.path.exists(cfg_path):
    try:
        cfg = json.load(open(cfg_path))
    except ValueError:
        sys.exit("cannot parse %s; fix or remove it first" % cfg_path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    os.replace(cfg_path, cfg_path + ".bak-" + stamp)
    json.dump(cfg, open(cfg_path, "w"), ensure_ascii=False, indent=2)  # keep a readable copy in place
std = cfg.setdefault("standalone", {})
for k, v in frag.items():
    if k == "areaMappings":
        m = std.get("areaMappings") if isinstance(std.get("areaMappings"), dict) else {}
        m.update(v)
        std["areaMappings"] = m
    else:
        std[k] = v
json.dump(cfg, open(cfg_path, "w"), ensure_ascii=False, indent=2)
print("settings merged into", cfg_path)
PY
    if [ -f "$LAYOUT" ] && [ "$force" != "--force" ]; then
      echo "layout kept: $LAYOUT already exists (use --force to replace, a backup is made)"
      echo "  or import $DIR/pixel/layout-office.json from the Pixel Agents editor (Settings → Import layout)"
    else
      [ -f "$LAYOUT" ] && cp "$LAYOUT" "$LAYOUT.bak-$(date +%Y%m%d-%H%M%S)"
      cp "$DIR/pixel/layout-office.json" "$LAYOUT" && echo "layout installed: $LAYOUT"
    fi
    mkdir -p "$DIR/state/office/desks"/{secretary,gate,notice,cost,runner}
    echo "desks: $DIR/state/office/desks/{secretary,gate,notice,cost,runner}"
    echo "restart Pixel Agents to apply (bash $DIR/pixel.sh)"
    ;;
  status)
    python3 - "$CFG" "$LAYOUT" <<'PY'
import json, os, sys
cfg_path, layout_path = sys.argv[1:3]
if os.path.exists(cfg_path):
    std = json.load(open(cfg_path)).get("standalone", {})
    for k in ("watchAllSessions", "alwaysShowLabels", "ghostHeadlessAgents", "showAreas"):
        print("%-20s %s" % (k, std.get(k)))
    print("areaMappings         %s" % json.dumps(std.get("areaMappings", {}), ensure_ascii=False))
else:
    print("no config:", cfg_path)
if os.path.exists(layout_path):
    lay = json.load(open(layout_path))
    print("layout areas         %s" % [a.get("label") for a in lay.get("areas", [])])
else:
    print("no layout:", layout_path)
PY
    ;;
  *) echo "usage: pixel_office.sh install [--force] | status"; exit 64 ;;
esac
