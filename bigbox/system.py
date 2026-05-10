"""System statistics and hardware monitoring."""
from __future__ import annotations

import os
import psutil
import socket
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from bigbox import power

class SystemStats:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SystemStats, cls).__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self._last_check = 0.0
        self._cache: Dict[str, Any] = {}
        self._hostname = socket.gethostname()

    def get_stats(self) -> Dict[str, Any]:
        now = time.monotonic()
        if now - self._last_check < 2.0:
            return self._cache

        stats = {
            "hostname": self._hostname,
            "cpu_usage": psutil.cpu_percent(),
            "mem_usage": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage("/").percent,
            "temp_f": self._get_temp_f(),
            "wifi": self._get_wifi_info(),
            "battery": self._get_battery_info(),
            "load": os.getloadavg()[0],
        }
        
        self._cache = stats
        self._last_check = now
        return stats

    def _get_temp_f(self) -> Optional[float]:
        try:
            # Try /sys/class/thermal/thermal_zone0/temp (millidegrees C)
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_c = int(f.read().strip()) / 1000.0
                return (temp_c * 9/5) + 32
        except:
            return None

    def _get_wifi_info(self) -> Dict[str, Any]:
        # Try to get SSID and signal level using iwgetid and /proc/net/wireless
        info = {"ssid": None, "signal": None}
        try:
            # SSID
            ssid_out = subprocess.check_output(["iwgetid", "-r"], text=True, stderr=subprocess.DEVNULL).strip()
            if ssid_out:
                info["ssid"] = ssid_out
            
            # Signal level (dBm or percentage)
            with open("/proc/net/wireless", "r") as f:
                lines = f.readlines()
                for line in lines:
                    if "wlan0" in line:
                        parts = line.split()
                        # Link quality is parts[2], level is parts[3]
                        qual = int(parts[2].strip("."))
                        info["signal"] = qual # Usually 0-70 or 0-100
                        break
        except:
            pass
        return info

    def _get_battery_info(self) -> Optional[Dict[str, Any]]:
        info = power.battery()
        if info:
            return {
                "percent": info.percent,
                "charging": info.charging,
                "voltage": info.voltage
            }
        return None

def get_system_stats() -> Dict[str, Any]:
    return SystemStats().get_stats()
