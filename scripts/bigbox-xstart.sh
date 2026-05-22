#!/bin/sh
# X-session bootstrap for bigbox on the ClockworkPi uConsole.
#
# bigbox.service invokes this script via xinit. We:
#   1. Rotate the X screen to compensate for the uConsole's physical-portrait
#      MIPI panel. KMS/X11 reports the panel as landscape but it lands sideways
#      without an xrandr rotation. Default is `right` (90° clockwise) which
#      puts the top of the UI on top for a stock uConsole. Override with
#      BIGBOX_ROTATE=normal|left|right|inverted in /etc/systemd/system/
#      bigbox.service.d/ if your panel is mounted differently.
#   2. Disable X11's screen-blanking / DPMS so bigbox doesn't get blanked
#      out from under itself. (bigbox does this in-process too; doing it
#      here as well makes the boot-to-render window safe.)
#   3. exec into the python process — no extra PID in the cgroup.

ROT="${BIGBOX_ROTATE:-right}"

# Find the first connected output. Stock uConsole CM4 is DSI-1; HDMI users
# might see HDMI-1. Be defensive — apply to whatever's actually attached.
OUTPUT="$(xrandr --query 2>/dev/null | awk '/ connected/{print $1; exit}')"
if [ -n "$OUTPUT" ]; then
    xrandr --output "$OUTPUT" --rotate "$ROT" 2>/dev/null || true
fi

# Keep the panel awake — both X-side and DPMS-side.
xset s off       2>/dev/null || true
xset -dpms       2>/dev/null || true
xset s noblank   2>/dev/null || true

exec /opt/bigbox/.venv/bin/python -m bigbox
