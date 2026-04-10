#!/bin/bash
# Install_OpenBOR.sh — Downloads and installs OpenBOR for MiSTer
#
# Run from MiSTer Scripts menu. Downloads all files from GitHub
# and sets up auto-launch. After install, just load the OpenBOR
# core from the console menu.
#

REPO="MiSTerOrganize/MiSTer_OpenBOR"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/$REPO/$BRANCH"

echo "=== OpenBOR Installer for MiSTer ==="
echo ""

# ── Kill ALL existing OpenBOR processes and daemons ─────────────────
killall OpenBOR 2>/dev/null
killall openbor_daemon.sh 2>/dev/null
kill $(cat /tmp/openbor_arm.pid 2>/dev/null) 2>/dev/null
rm -f /tmp/openbor_arm.pid
rm -rf /tmp/openbor_daemon.lock
sleep 1

# ── Download files from GitHub repo ───────────────────────────────
echo "Downloading OpenBOR..."

mkdir -p /media/fat/_Console
mkdir -p /media/fat/games/OpenBOR/Paks
mkdir -p /media/fat/saves/OpenBOR
mkdir -p /media/fat/config/inputs
mkdir -p /media/fat/docs/OpenBOR

FAIL=0

echo "  Downloading FPGA core..."
rm -f /media/fat/_Console/OpenBOR_*.rbf /media/fat/_Console/OpenBOR.rbf
RBF_NAME=$(wget -q -O - "https://api.github.com/repos/$REPO/contents/_Console" | grep -o '"OpenBOR_[0-9]*.rbf"' | tr -d '"')
if [ -z "$RBF_NAME" ]; then
    RBF_NAME="OpenBOR.rbf"
fi
wget -q --show-progress -O "/media/fat/_Console/$RBF_NAME" "$BASE_URL/_Console/$RBF_NAME" || FAIL=1

echo "  Downloading ARM binary..."
wget -q --show-progress -O /media/fat/games/OpenBOR/OpenBOR "$BASE_URL/games/OpenBOR/OpenBOR" || FAIL=1

echo "  Downloading daemon..."
wget -q --show-progress -O /media/fat/games/OpenBOR/openbor_daemon.sh "$BASE_URL/games/OpenBOR/openbor_daemon.sh" || FAIL=1

echo "  Downloading README..."
wget -q --show-progress -O /media/fat/docs/OpenBOR/README.md "$BASE_URL/docs/OpenBOR/README.md" || FAIL=1

if [ "$FAIL" -ne 0 ]; then
    echo ""
    echo "Error: One or more downloads failed. Check your internet connection."
    exit 1
fi

# Make files executable
chmod +x /media/fat/games/OpenBOR/OpenBOR
chmod +x /media/fat/games/OpenBOR/openbor_daemon.sh

# ── Install daemon into user-startup.sh ───────────────────────────
STARTUP=/media/fat/linux/user-startup.sh

# Remove ALL old OpenBOR daemon entries
if [ -f "$STARTUP" ]; then
    sed -i '/openbor_daemon\.sh/d' "$STARTUP"
    sed -i '/OpenBOR auto-launch/d' "$STARTUP"
fi

# Add single launcher line
echo "" >> "$STARTUP"
echo "# OpenBOR auto-launch daemon" >> "$STARTUP"
echo "/media/fat/games/OpenBOR/openbor_daemon.sh &" >> "$STARTUP"

echo "Auto-launcher installed."

# ── Start daemon now ──────────────────────────────────────────────
/media/fat/games/OpenBOR/openbor_daemon.sh &

echo ""
echo "=== OpenBOR installed successfully! ==="
echo ""
echo "Load the OpenBOR core from the console menu to play."
echo "Place .pak game modules in: games/OpenBOR/Paks/"
echo ""
