#!/bin/bash
# Build the CineSFX macOS installer disk image (CineSFX-Installer.dmg).
#
# Run on macOS (needs hdiutil + python3). Produces a .dmg containing:
#   payload/                 -> the self-contained plugin
#   "Install CineSFX.command"-> double-click to install
#
# Optional: drop static FFmpeg binaries in build/dmgroot/payload/ffmpeg before
# packing so the plugin needs nothing else. Code-sign/notarise afterwards for
# distribution (see packaging/README.md).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD="$REPO_ROOT/build"
DMGROOT="$BUILD/dmgroot"
DMG="$BUILD/CineSFX-Installer.dmg"
VOLNAME="CineSFX Installer"

rm -rf "$DMGROOT" "$DMG"
mkdir -p "$DMGROOT"

# 1) Stage the payload (+ vendored deps) into the dmg root.
python3 "$REPO_ROOT/packaging/stage_payload.py" --out "$DMGROOT/payload"

# 2) Add the double-clickable installer.
cp "$REPO_ROOT/packaging/macos/Install CineSFX.command" "$DMGROOT/"
chmod +x "$DMGROOT/Install CineSFX.command"

# 3) Pack a compressed disk image.
hdiutil create -volname "$VOLNAME" -srcfolder "$DMGROOT" -ov -format UDZO "$DMG"

echo ""
echo "✅ Built: $DMG"
echo "   (For public distribution, codesign + notarize — see packaging/README.md.)"
