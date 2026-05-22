#!/usr/bin/env bash
# bigbox installer for ClockworkPi uConsole (CM4 / CM5).
#
# The uConsole's CM4 image (ClockworkOS) is built on top of Raspberry Pi OS
# Lite, so this script is the standard apt + venv + systemd dance with the
# Pi-specific GPIO bits stripped out — the uConsole's built-in keyboard
# replaces the GamePi43's GPIO button matrix.
#
# Idempotent: re-running is safe. Logs everything it changes so you can roll
# back by inspecting /etc/bigbox.installed.
#
# Run as root (sudo ./scripts/install.sh) on the uConsole.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root: sudo $0"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="/opt/bigbox"
LOG="/etc/bigbox.installed"

echo "==> bigbox install (uConsole)"
echo "    repo:    $REPO_DIR"
echo "    target:  $INSTALL_DIR"

# --- 1. apt packages ----------------------------------------------------------
echo "==> apt packages"
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    python3-pygame \
    libturbojpeg0 \
    nmap arp-scan \
    aircrack-ng iw wireless-tools \
    tcpdump mdk4 wifite reaver bully pixiewps tshark \
    hashcat macchanger \
    cryptsetup bettercap \
    bluez \
    alsa-utils \
    mpv \
    mgba-sdl \
    mednafen \
    pcsxr \
    xserver-xorg xinit x11-xserver-utils \
    python3-serial rfkill \
    curl ca-certificates \
    fonts-dejavu-core unzip

# --- 1b. tailscale ------------------------------------------------------------
if ! command -v tailscale >/dev/null 2>&1; then
    echo "==> tailscale"
    curl -fsSL https://tailscale.com/install.sh | sh
fi

# --- 2. copy source to /opt/bigbox -------------------------------------------
echo "==> copy source -> $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
# Skip the copy if we're already running from $INSTALL_DIR (sdcard-prepare
# pre-stages the source there, so install.sh would self-copy).
if [[ "$REPO_DIR" != "$INSTALL_DIR" ]]; then
    rsync -a --delete \
        --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
        --exclude='.claude' --exclude='.vscode' --exclude='.idea' \
        --exclude='memory' \
        "$REPO_DIR"/ "$INSTALL_DIR"/
fi

# --- 3. python venv (system pygame is fine; venv keeps deps isolated) --------
echo "==> python venv"
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    python3 -m venv --system-site-packages "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# NOTE: we intentionally do NOT touch /boot/firmware/config.txt — ClockworkOS
# ships with the right MIPI panel + audio config for the uConsole, and the
# uConsole keyboard handles its own backlight/audio routing via the STM32
# firmware. Edits here have historically broken the display on first boot.

# --- 4. OSINT tools (sherlock + theHarvester + phoneinfoga) ------------------
# Idempotent installer — see scripts/install-osint.sh for what it does.
if [[ -x "$REPO_DIR/scripts/install-osint.sh" ]]; then
    echo "==> OSINT tools"
    "$REPO_DIR/scripts/install-osint.sh"
fi

# --- 5. systemd service + OTA update timer (timer is installed but disabled) -
echo "==> systemd units"
install -m 0644 "$REPO_DIR/scripts/bigbox.service" /etc/systemd/system/bigbox.service
install -m 0644 "$REPO_DIR/scripts/bigbox-update.service" /etc/systemd/system/bigbox-update.service
install -m 0644 "$REPO_DIR/scripts/bigbox-update.timer"   /etc/systemd/system/bigbox-update.timer
systemctl daemon-reload
systemctl enable bigbox.service

# /etc/bigbox is the config-override directory — buttons.toml lives here so
# OTA git resets never touch user-tuned keymaps.
install -d -m 0755 /etc/bigbox

# --- 6. record what we did ----------------------------------------------------
{
    echo "# bigbox install log (uConsole)"
    echo "installed_at=$(date -Iseconds)"
    echo "repo=$REPO_DIR"
    echo "target=$INSTALL_DIR"
} > "$LOG"

cat <<EOF

==> done.

Next steps:
  - reboot, or:  sudo systemctl start bigbox
  - inspect logs with:  journalctl -u bigbox -f
  - to stop autostart:  sudo systemctl disable bigbox

OTA updates:
  - one-shot now:    sudo systemctl start bigbox-update.service
  - hourly auto:     sudo systemctl enable --now bigbox-update.timer
  - manual via UI:   Settings -> Check for updates (OTA)
  - your keymap:     /etc/bigbox/buttons.toml (overrides bundled default; survives updates)

Tip: the uConsole's gamepad keys map to A=j B=k X=u Y=i, Start=Enter,
Select=Space, L/R=Shift in keyboard mode (back switch up). If they don't
respond, flip the rear PD2 switch — joystick mode bypasses keyboard events.
EOF
