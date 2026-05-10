"""Beacon Bomber — SSID flood UI.

Uses BeaconFloodEngine to broadcast hundreds of fake Access Points.
"""
from __future__ import annotations

import pygame
import random

from bigbox import theme, hardware
from bigbox.events import Button, ButtonEvent
from bigbox.ui.section import SectionContext
from bigbox.beacon_flood_engine import BeaconFloodEngine

PHASE_PICK_IFACE = "iface"
PHASE_PICK_PRESET = "preset"
PHASE_RUNNING = "running"

PRESETS = {
    "RICKROLL": [
        "Never Gonna", "Give You Up", "Never Gonna", "Let You Down",
        "Never Gonna", "Run Around", "And Desert You"
    ],
    "POLICE": [
        "Surveillance Van 01", "Surveillance Van 02", "FBI Mobile Unit",
        "Police_Guest_WiFi", "DO_NOT_CONNECT_POLICE"
    ],
    "RANDOM": ["Random_" + str(random.randint(1000, 9999)) for _ in range(20)],
    "GHOST": ["\x00" * random.randint(5, 15) for _ in range(10)] # Invisible SSIDs
}

class BeaconBomberView:
    def __init__(self) -> None:
        self.dismissed = False
        self.phase = PHASE_PICK_IFACE
        self.status_msg = "Select monitor-mode adapter"
        
        from bigbox.ui.wifi_attack import _list_wlan_ifaces
        self.ifaces = _list_wlan_ifaces()
        self.iface_cursor = 0
        self.mon_iface: str | None = None
        
        self.presets = list(PRESETS.keys())
        self.preset_cursor = 0
        self.selected_preset = "RICKROLL"
        
        self.engine: BeaconFloodEngine | None = None

    def handle(self, ev: ButtonEvent, ctx: SectionContext) -> None:
        if not ev.pressed: return
        
        if ev.button is Button.B:
            if self.phase == PHASE_RUNNING:
                self._stop_flood()
                self.phase = PHASE_PICK_PRESET
            elif self.phase == PHASE_PICK_PRESET:
                self.phase = PHASE_PICK_IFACE
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
                # Enable monitor mode if not already
                if not pick.is_monitor:
                    from bigbox.ui.wifi_attack import WifiAttackView
                    # Hacky way to reuse monitor mode enabling
                    # In a real app we'd move this to hardware.py
                    self.status_msg = f"Enabling monitor on {pick.name}..."
                    self.mon_iface = hardware.enable_monitor(pick.name)
                else:
                    self.mon_iface = pick.name
                
                if self.mon_iface:
                    self.phase = PHASE_PICK_PRESET
                else:
                    self.status_msg = "Monitor mode FAILED"
            return

        if self.phase == PHASE_PICK_PRESET:
            if ev.button is Button.UP: self.preset_cursor = (self.preset_cursor - 1) % len(self.presets)
            elif ev.button is Button.DOWN: self.preset_cursor = (self.preset_cursor + 1) % len(self.presets)
            elif ev.button is Button.A:
                self.selected_preset = self.presets[self.preset_cursor]
                self._start_flood()
                self.phase = PHASE_RUNNING
            return

    def _start_flood(self):
        if not self.mon_iface: return
        ssids = PRESETS[self.selected_preset]
        self.engine = BeaconFloodEngine(self.mon_iface, ssids)
        self.engine.start()
        self.status_msg = f"Flooding {len(ssids)} SSIDs..."

    def _stop_flood(self):
        if self.engine:
            self.engine.stop()
            self.engine = None
        self.status_msg = "Flood stopped"

    def render(self, surf: pygame.Surface) -> None:
        surf.fill(theme.BG)
        
        f_title = pygame.font.Font(None, 32)
        f_main = pygame.font.Font(None, 24)
        
        title = f_title.render("BEACON BOMBER :: SSID FLOOD", True, theme.ACCENT)
        surf.blit(title, (20, 20))
        
        if self.phase == PHASE_PICK_IFACE:
            surf.blit(f_main.render("SELECT INTERFACE:", True, theme.FG_DIM), (20, 70))
            for i, iface in enumerate(self.ifaces):
                sel = (i == self.iface_cursor)
                color = theme.ACCENT if sel else theme.FG
                label = f"{iface.name} {'(MON)' if iface.is_monitor else ''}"
                surf.blit(f_main.render(label, True, color), (40, 100 + i * 30))
        
        elif self.phase == PHASE_PICK_PRESET:
            surf.blit(f_main.render(f"IFACE: {self.mon_iface}", True, theme.FG_DIM), (20, 60))
            surf.blit(f_main.render("SELECT SSIDs PRESET:", True, theme.FG_DIM), (20, 90))
            for i, p in enumerate(self.presets):
                sel = (i == self.preset_cursor)
                color = theme.ACCENT if sel else theme.FG
                surf.blit(f_main.render(p, True, color), (40, 120 + i * 30))

        elif self.phase == PHASE_RUNNING:
            # Pulsing bomb icon or something
            import time
            pulse = abs((time.time() % 1.0) - 0.5) * 2
            col = (int(255 * pulse), 50, 50)
            
            surf.blit(f_title.render("!!! BOMBER ACTIVE !!!", True, col), (theme.SCREEN_W // 2 - 100, 150))
            surf.blit(f_main.render(f"PRESET: {self.selected_preset}", True, theme.FG), (theme.SCREEN_W // 2 - 80, 200))
            surf.blit(f_main.render(f"TARGET: {self.mon_iface}", True, theme.FG), (theme.SCREEN_W // 2 - 80, 230))
            
            # Show list of SSIDs being flooded
            ssids = PRESETS[self.selected_preset]
            y = 280
            for s in ssids[:5]:
                surf.blit(f_main.render(f"> {s}", True, theme.FG_DIM), (theme.SCREEN_W // 2 - 80, y))
                y += 25

        # Status
        pygame.draw.line(surf, theme.DIVIDER, (0, theme.SCREEN_H - 40), (theme.SCREEN_W, theme.SCREEN_H - 40))
        surf.blit(f_main.render(self.status_msg, True, theme.ACCENT), (20, theme.SCREEN_H - 30))
