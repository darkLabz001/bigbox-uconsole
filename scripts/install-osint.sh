#!/usr/bin/env bash
# Install the OSINT tools used by bigbox/sections/recon.py:
#   - sherlock        (apt) -> /usr/bin/sherlock
#   - subfinder       (binary release for the host arch)
#                     -> /usr/local/bin/subfinder
#   - theHarvester    (cloned from upstream, pip-installed into bigbox venv)
#                     -> /opt/bigbox/.venv/bin/theHarvester
#   - phoneinfoga     (binary release for the host arch)
#                     -> /usr/local/bin/phoneinfoga
#
# Idempotent: re-running is a no-op for already-installed pieces. Called
# from install.sh on a fresh setup; can also be run on its own:
#
#     sudo /opt/bigbox/scripts/install-osint.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root: sudo $0"
    exit 1
fi

VENV="/opt/bigbox/.venv"
HARV_DIR="/opt/theHarvester"
PI_BIN="/usr/local/bin/phoneinfoga"
SF_BIN="/usr/local/bin/subfinder"

echo "STATUS: Initializing OSINT suite..."
echo "PROGRESS: 5"

# --- 1. sherlock from apt ---------------------------------------------------
if ! dpkg-query -W -f='${Status}' sherlock 2>/dev/null | grep -q "ok installed"; then
    echo "STATUS: Installing sherlock..."
    DEBIAN_FRONTEND=noninteractive apt-get update </dev/null >/dev/null 2>&1
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        sherlock </dev/null
else
    echo "==> sherlock already installed"
fi
echo "PROGRESS: 20"

# --- 1b. subfinder binary --------------------------------------------------
ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)  SF_ARCH="arm64" ;;
    x86_64|amd64)   SF_ARCH="amd64" ;;
    armv7l|armhf)   SF_ARCH="arm" ;;
    *)              SF_ARCH="" ;;
esac

if [[ -x "$SF_BIN" ]]; then
    echo "==> subfinder already at $SF_BIN"
elif [[ -z "$SF_ARCH" ]]; then
    echo "WARN: no subfinder release for $ARCH — skipping."
else
    echo "STATUS: Installing subfinder binary..."
    TMP=$(mktemp -d)
    trap "rm -rf $TMP" EXIT
    
    # Get latest version from GitHub API
    SF_LATEST=$(curl -s https://api.github.com/repos/projectdiscovery/subfinder/releases/latest | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')
    if [[ -z "$SF_LATEST" ]]; then
        SF_LATEST="2.14.0" # Fallback
    fi
    
    SF_ASSET="subfinder_${SF_LATEST}_linux_${SF_ARCH}.zip"
    URL="https://github.com/projectdiscovery/subfinder/releases/download/v${SF_LATEST}/$SF_ASSET"
    
    echo "    Downloading $URL ..."
    if curl -fsSL --max-time 60 -o "$TMP/s.zip" "$URL"; then
        unzip -q "$TMP/s.zip" -d "$TMP"
        if [[ -f "$TMP/subfinder" ]]; then
            install -m 0755 "$TMP/subfinder" "$SF_BIN"
        else
            echo "WARN: subfinder binary not found in archive"
        fi
    else
        echo "WARN: subfinder download failed — skipping."
    fi
fi
echo "PROGRESS: 40"

# --- 2. theHarvester (cloned + pip into venv) -------------------------------
if [[ ! -x "$VENV/bin/theHarvester" ]]; then
    echo "STATUS: Installing theHarvester..."
    if [[ ! -d "$HARV_DIR/.git" ]]; then
        rm -rf "$HARV_DIR"
        git clone --depth 1 https://github.com/laramies/theHarvester.git "$HARV_DIR"
    else
        git -C "$HARV_DIR" pull --ff-only --quiet || true
    fi
    if [[ -d "$VENV" ]]; then
        "$VENV/bin/pip" install -q "$HARV_DIR"
    else
        echo "WARN: $VENV not found; theHarvester pip install skipped."
    fi
else
    echo "==> theHarvester already installed at $VENV/bin/theHarvester"
fi
echo "PROGRESS: 70"

# --- 3. phoneinfoga binary --------------------------------------------------
ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)  PI_ASSET="phoneinfoga_Linux_arm64.tar.gz" ;;
    x86_64|amd64)   PI_ASSET="phoneinfoga_Linux_x86_64.tar.gz" ;;
    armv7l|armhf)   PI_ASSET="phoneinfoga_Linux_armv7.tar.gz" ;;
    *)              PI_ASSET="" ;;
esac

if [[ -x "$PI_BIN" ]]; then
    echo "==> phoneinfoga already at $PI_BIN"
elif [[ -z "$PI_ASSET" ]]; then
    echo "WARN: no phoneinfoga release for $ARCH — skipping."
else
    echo "STATUS: Installing phoneinfoga binary..."
    TMP=$(mktemp -d)
    trap "rm -rf $TMP" EXIT
    URL="https://github.com/sundowndev/phoneinfoga/releases/latest/download/$PI_ASSET"
    if curl -fsSL --max-time 60 -o "$TMP/p.tgz" "$URL"; then
        tar xzf "$TMP/p.tgz" -C "$TMP"
        if [[ -f "$TMP/phoneinfoga" ]]; then
            install -m 0755 "$TMP/phoneinfoga" "$PI_BIN"
        else
            echo "WARN: phoneinfoga binary not found in archive"
        fi
    else
        echo "WARN: phoneinfoga download from $URL failed — skipping."
    fi
fi
echo "PROGRESS: 100"
echo "STATUS: OSINT Suite Installed"

cat <<EOF

==> OSINT install done.

  sherlock:     $(command -v sherlock || echo "NOT FOUND")
  subfinder:    $([[ -x "$SF_BIN" ]] && echo "$SF_BIN" || echo "NOT FOUND")
  theHarvester: $([[ -x "$VENV/bin/theHarvester" ]] && echo "$VENV/bin/theHarvester" || echo "NOT FOUND")
  phoneinfoga:  $([[ -x "$PI_BIN" ]] && echo "$PI_BIN" || echo "NOT FOUND")

EOF
