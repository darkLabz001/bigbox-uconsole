# BigB0X :: uConsole Edition
### Tactical Pentesting Firmware for the ClockworkPi uConsole
**Ghost Protocol // High-Fidelity Signal Intelligence // Portable Auditing**

BigB0X is a self-contained, keyboard-driven tactical firmware for the
**ClockworkPi uConsole** (CM4 / CM5 core). It turns the device into a
handheld signal intelligence and network auditing rig with a high-contrast
"Ghost Protocol" interface, rendered natively on the uConsole's 5"
1280×720 IPS panel.

This is a fork of the original [BigB0X for Raspberry Pi 4 + GamePi43](https://github.com/darkLabz001/bigbox).
The GPIO button matrix has been replaced with the uConsole's built-in
USB-HID keyboard, the UI re-tuned for 720p, and Pi-only install steps
removed.

---

## Core Tactical Suite

### Reconnaissance & Signals
*   **Signal Scraper** — High-fidelity proximity profiler for Wi-Fi and Bluetooth LE. Real-time RSSI tracking and vendor identification.
*   **FlockSeeker Ultra** — Specialized detection suite for ALPR (Automated License Plate Reader) infrastructure and traffic surveillance nodes.
*   **Camera Interceptor** — Tactical "Dive" mode that hijacks local camera management APs to view internal RTSP/MJPEG streams.
*   **Traffic Cam Browser** — Global uplink to live public traffic and weather feeds.
*   **Wardriving** — GPS-tagged Wi-Fi and BT sweeps with WiGLE-compatible CSV export.

### Wireless Auditing
*   **Wifite 2 Interactive** — Fully manual/interactive auditor for WPS, WPA handshakes, and PMKID attacks with a scrollable tactical terminal.
*   **Wi-Fi Multi-Tool** — Integrated scanner for deauth attacks and handshake captures.
*   **Evil Twin** — Rogue AP suite with captive portal for credential harvesting.

### Social & Communication
*   **Tactical Messenger** — Threaded SMS client (Textbelt + Carrier Gateways).
*   **Tactical Mail** — Full-featured IMAP/SMTP email client optimized for handheld screens.
*   **Global Chat** — In-device encrypted chat client via `darksec.uk`.
*   **Local BBS** — LAN-based message board and dead-drop.

### Media & Entertainment
*   **Internet TV** — Dual-mode HLS/mpv player with a curated list of international news and lifestyle channels.
*   **Media Player** — Local movie/video browser with hardware-optimized playback.

---

## Interface & Controls

BigB0X is designed for fast, one-handed use on the uConsole's built-in
keyboard. The controller is a single STM32 composite USB-HID device that
always exposes a QWERTY keyboard, a trackball mouse and a gamepad at once.
With the stock firmware the D-pad / A·B·X·Y / Select·Start area reports
*either* keyboard keysyms (rear PD2 switch high) *or* a USB joystick
(PD2 low). **Both are supported** — bigbox reads the keysyms when PD2 is
high and the joystick over evdev when PD2 is low, so the controls work in
either position:

| Logical Button | uConsole key (PD2 high) | PC dev fallback |
| :--- | :--- | :--- |
| **Navigate** | D-Pad arrows | Arrows / WASD |
| **A** (Select/Initiate) | A button (sends `j`) | Z |
| **B** (Back/Cancel) | B button (sends `k`) | X / Esc |
| **X** (Secondary) | X button (sends `u`) | C |
| **Y** (Context) | Y button (sends `i`) | V |
| **LL** (Left shoulder) | L button (Left Shift) | Q / L |
| **RR** (Right shoulder) | R button (Right Shift) | E / R |
| **Start** (System menu) | Start (Enter) | Enter |
| **Select** (Tool config) | Select (Space) | Backspace / Tab |
| **HK** (Hotkey overlay) | Select+Start chord, Home | Home |

With PD2 low the same physical keys arrive as a joystick: D-pad = ABS_X/
ABS_Y (0..1023, neutral 511), X/A/B/Y = joystick buttons 1..4, Select/Start
= buttons 9/10. Bigbox maps those in `bigbox.input.joystick` (defaults in
`config/buttons.toml [joystick]`) and they behave identically. L/R are
always keyboard shifts regardless of switch position.

To see exactly which codes your device emits, run bigbox with
`BIGBOX_JOY_DEBUG=1` — every raw evdev event is printed to the journal.

**Custom keymap:** drop a `[keymap]` table into `/etc/bigbox/buttons.toml`
to override any mapping without editing code. See `config/buttons.toml`
for the example format.

---

## Hardware Requirements

*   **Device:** ClockworkPi uConsole with **CM4** or **CM5** core module.
*   **Display:** built-in 5" 1280×720 IPS panel (no extra hardware).
*   **Wi-Fi:** uConsole's onboard 802.11ac. Optional Alfa USB adapter (e.g. **AWUS036ACS**) recommended for monitor-mode attacks — the onboard radio cannot enter monitor mode reliably.
*   **Bluetooth:** uConsole's onboard BT 5.0. Optional **TP-Link UB500** USB adapter for stronger receive.
*   **GPS:** USB NMEA dongle (Quectel LC86L or similar) for Wardriving.

Other core modules (A-06 / R-01) are not officially supported in this
branch — the install script assumes ClockworkOS for CM4 (which is built
on Raspberry Pi OS Lite). The codebase will largely work on A-06, but
audio routing and hardware encoding will need separate verification.

---

## Installation

### On a flashed uConsole
1. Flash the official ClockworkPi uConsole CM4 image (ClockworkOS) to your microSD card using `dd` or Raspberry Pi Imager.
2. Boot the uConsole, connect to Wi-Fi, then over SSH (or directly in a terminal):

```bash
git clone https://github.com/darkLabz001/bigbox-uconsole.git
cd bigbox-uconsole
sudo ./scripts/install.sh
sudo systemctl enable --now bigbox
```

The installer is idempotent — re-running it is safe.

### Optional: GPIO hat support
The uConsole's 40-pin GPIO FPC connector is unused by default. If you've
wired a hat with physical buttons and want them in addition to the
built-in keyboard, install the extras and set `BIGBOX_USE_GPIO=1`:

```bash
/opt/bigbox/.venv/bin/pip install gpiozero lgpio
sudo systemctl edit bigbox          # add  Environment=BIGBOX_USE_GPIO=1
sudo systemctl restart bigbox
```

Then add a `[pins]` section to `/etc/bigbox/buttons.toml` with your BCM
pin numbers (one per logical button).

---

## System Updates (OTA)

BigB0X ships with an OTA update path. **Settings → Check for Updates**
pulls the latest tactical payloads, dependencies, and bug fixes; the
update process can fire a Discord webhook on success.

---

## Custom Theming

BigB0X includes a theme engine. Edit JSON files in `config/themes/` to
change colors, background grids, and icon sets. See the
[Theming Guide](config/themes/README.md). The uConsole panel is 1280×720
— background art should be sized accordingly.

---

## Roadmap

*   **Trackball support** — wire the uConsole's mini-trackball into the launcher as a pointer / scroll source.
*   **4G modem integration** — expose status + connect/disconnect from the COMMS card when the optional cellular expansion is installed.
*   **RTL-SDR / LoRa** — integrate the community RTL-SDR+SX1262 expansion board into the Recon section.
*   **Mesh Intercom** — PTT voice notes over local P2P mesh.
*   **Ghost Intel** — Anonymous target monitoring.

---

## Legal

*For educational and authorized security testing purposes only. Use on
networks without explicit permission is strictly prohibited.*
