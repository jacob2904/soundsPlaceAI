#!/bin/bash
# Double-clickable macOS installer for CineSFX.
# Copies the bundled plugin payload into DaVinci Resolve's Workflow Integration
# Plugins folder (asking for admin rights, since it lives under /Library).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD="$HERE/payload"
DEST="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins/com.soundsplaceai.cinesfx"

if [ ! -d "$PAYLOAD" ]; then
  echo "Error: payload folder not found next to this installer." >&2
  exit 1
fi

echo "Installing CineSFX to:"
echo "  $DEST"

# Use an authenticated copy so it works without opening Terminal as root.
/usr/bin/osascript <<EOF
do shell script "mkdir -p \"$DEST\" && cp -R \"$PAYLOAD/\" \"$DEST/\"" with administrator privileges
EOF

echo ""
echo "✅ CineSFX installed. Restart DaVinci Resolve, then open:"
echo "   Workspace ▸ Workflow Integrations ▸ CineSFX AI"
read -r -p "Press Return to close…" _ || true
