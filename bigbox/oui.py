"""Offline OUI lookup — vendor + device-class for a MAC address.

Loads whichever IEEE OUI database is already present on disk (Kali ships
`nmap-mac-prefixes` and `arp-scan/ieee-oui.txt`; Wireshark adds `manuf`).
Falls back to "Unknown" if none of them exist. The DB is parsed once on
first call and held in module memory.

Locally-administered MAC bit (LSB-2 of the first octet) is detected
separately and reported as "Randomized" — every modern phone uses a
random MAC for probe requests, so the lookup would otherwise return
nothing useful for the most interesting traffic.
"""
from __future__ import annotations

import os


_DB_PATHS = (
    "/usr/share/nmap/nmap-mac-prefixes",
    "/usr/share/arp-scan/ieee-oui.txt",
    "/usr/share/wireshark/manuf",
)


# Vendor substring → device class. First match wins after sorting by
# substring length (longest wins) so e.g. "samsung electronics" can map
# differently from a generic "samsung" if we ever add the latter.
_CLASS_RULES: tuple[tuple[str, str], ...] = (
    ("apple", "phone/mac"),
    ("samsung electronics", "phone/tv"),
    ("xiaomi", "phone"),
    ("huawei device", "phone"),
    ("huawei tech", "phone/network"),
    ("oneplus", "phone"),
    ("guangdong oppo", "phone"),
    ("vivo mobile", "phone"),
    ("realme", "phone"),
    ("motorola mobility", "phone"),
    ("google", "phone/iot"),
    ("amazon technol", "echo/fire"),
    ("espressif", "iot (esp)"),
    ("tuya", "iot"),
    ("shelly", "iot"),
    ("particle industries", "iot"),
    ("arduino", "iot"),
    ("sonoff", "iot"),
    ("philips lighting", "iot (hue)"),
    ("signify", "iot (hue)"),
    ("ring llc", "iot (ring)"),
    ("nest labs", "iot (nest)"),
    ("wyze", "iot (cam)"),
    ("hikvision", "iot (cam)"),
    ("dahua", "iot (cam)"),
    ("axis communications", "iot (cam)"),
    ("sonos", "speaker"),
    ("bose", "speaker"),
    ("roku", "tv stick"),
    ("vizio", "tv"),
    ("hisense", "tv"),
    ("lg electronics", "tv/appliance"),
    ("dell", "laptop/pc"),
    ("hewlett packard", "laptop/printer"),
    ("hp inc", "laptop/printer"),
    ("lenovo", "laptop/pc"),
    ("acer", "laptop"),
    ("asustek", "laptop/router"),
    ("intel corp", "pc nic"),
    ("realtek", "pc nic"),
    ("microsoft", "pc/xbox"),
    ("raspberry pi", "raspberry pi"),
    ("beagleboard", "sbc"),
    ("brother industries", "printer"),
    ("canon", "printer"),
    ("seiko epson", "printer"),
    ("xerox", "printer"),
    ("lexmark", "printer"),
    ("zebra technologies", "printer"),
    ("cisco", "network"),
    ("aruba", "network"),
    ("ubiquiti", "network"),
    ("netgear", "network"),
    ("juniper", "network"),
    ("mikrotik", "network"),
    ("ruckus", "network"),
    ("d-link", "network"),
    ("zyxel", "network"),
    ("linksys", "network"),
    ("tp-link", "network/iot"),
    ("garmin", "wearable"),
    ("fitbit", "wearable"),
    ("nintendo", "console"),
    ("sony interactive", "console"),
    ("tesla", "vehicle"),
    ("ford motor", "vehicle"),
    ("hon hai", "manufactured"),
    ("foxconn", "manufactured"),
)

# Sort longest-first so longer substrings win ties.
_CLASS_RULES_SORTED = tuple(
    sorted(_CLASS_RULES, key=lambda sc: len(sc[0]), reverse=True)
)


_DB: dict[str, str] = {}
_LOADED = False
_CACHE: dict[str, tuple[str, str]] = {}


def _load_db():
    global _DB, _LOADED
    if _LOADED:
        return
    
    # Process all available databases to build the most complete picture.
    # Pi 4 has plenty of RAM to hold the full consolidated dictionary.
    for path in _DB_PATHS:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(None, 1)
                    if len(parts) != 2:
                        continue
                    prefix, rest = parts
                    # Standardize prefix (hex string, no separators)
                    prefix = prefix.replace(":", "").replace("-", "").replace(".", "")
                    if "/" in prefix:
                        prefix = prefix.split("/", 1)[0]
                    if len(prefix) < 6:
                        continue
                    prefix = prefix[:6].upper()
                    
                    # Wireshark format has short name followed by tab and long name
                    vendor = rest.split("\t", 1)[0].strip()
                    
                    if prefix and vendor and prefix not in _DB:
                        _DB[prefix] = vendor
        except Exception:
            continue
    _LOADED = True


def is_randomized(mac: str) -> bool:
    """True if the locally-administered bit is set in the first octet."""
    try:
        first = int(mac.split(":")[0], 16)
    except Exception:
        return False
    return bool(first & 0x02)


def classify(vendor: str) -> str:
    if not vendor:
        return ""
    v = vendor.lower()
    for sub, klass in _CLASS_RULES_SORTED:
        if sub in v:
            return klass
    return ""


def lookup(mac: str) -> tuple[str, str]:
    """Return ``(vendor, device_class)`` for a MAC address.

    ``vendor`` is the IEEE-registered vendor name, "Randomized" if the
    address is locally-administered, or "Unknown" if not in the DB.
    ``device_class`` is a short heuristic guess ("phone", "iot", …) or
    "" if no rule matches.
    """
    if not mac:
        return ("", "")
    
    # Fast path: cache lookups for frequently seen MACs
    if mac in _CACHE:
        return _CACHE[mac]

    if is_randomized(mac):
        res = ("Randomized", "privacy MAC")
        _CACHE[mac] = res
        return res

    prefix = mac.replace(":", "").replace("-", "").upper()[:6]
    if len(prefix) < 6:
        return ("", "")
    
    _load_db()
    vendor = _DB.get(prefix, "")
    if not vendor:
        res = ("Unknown", "")
    else:
        res = (vendor, classify(vendor))
    
    _CACHE[mac] = res
    return res
