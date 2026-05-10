"""Handshake Manager — Manage captured WPA handshakes.

Lists captured files, allows verification of handshake validity,
and handles uploads to remote cracking services.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, List

import pygame

from bigbox import theme, hashopolis
from bigbox.events import Button, ButtonEvent
from bigbox.ui.section import SectionContext

if TYPE_CHECKING:
    from bigbox.app import App

HANDSHAKE_DIR = Path("loot/handshakes")

class HandshakeManagerView:
    def __init__(self) -> None:
        self.dismissed = False
        self.files = self._load_files()
        self.cursor = 0
        self.scroll = 0
        self.status_msg = f"Found {len(self.files)} files"
        
        self.f_title = pygame.font.Font(None, 32)
        self.f_main = pygame.font.Font(None, 24)
        self.f_small = pygame.font.Font(None, 18)

    def _load_files(self) -> List[Path]:
        if not HANDSHAKE_DIR.exists():
            return []
        # Sort by modification time (newest first)
        files = list(HANDSHAKE_DIR.glob("*.cap")) + list(HANDSHAKE_DIR.glob("*.hc22000"))
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    def _verify_selected(self) -> str:
        if not self.files: return "No files to verify"
        path = self.files[self.cursor]
        
        if path.suffix == ".hc22000":
            return "Hash format (hc22000) - Ready for cracking"
        
        # Use hcxpcapngtool if available to check for handshakes
        try:
            # -o /dev/null just to check if it parses and finds something
            proc = subprocess.run(
                ["hcxpcapngtool", "-o", "/dev/null", str(path)],
                capture_output=True, text=True, timeout=5
            )
            if "written to" in proc.stdout or "handshake(s) written to" in proc.stdout:
                return "Handshake VALID (EAPOL found)"
            else:
                return "Handshake INVALID (No EAPOL)"
        except FileNotFoundError:
            # Fallback to aircrack-ng
            try:
                proc = subprocess.run(
                    ["aircrack-ng", str(path)],
                    capture_output=True, text=True, timeout=5
                )
                if "1 handshake" in proc.stdout:
                    return "Handshake VALID (aircrack)"
                else:
                    return "Handshake NOT FOUND"
            except:
                return "Verification tool missing"

    def _upload_selected(self) -> None:
        if not self.files: return
        path = self.files[self.cursor]
        
        self.status_msg = "Uploading to Hashtopolis..."
        
        def _worker():
            ok = hashopolis.upload_hash(path)
            self.status_msg = "Upload SUCCESSFUL" if ok else "Upload FAILED"
            
        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def handle(self, ev: ButtonEvent, ctx: App) -> None:
        if not ev.pressed: return
        if ev.button is Button.B:
            self.dismissed = True
            return

        if not self.files: return

        if ev.button is Button.UP:
            self.cursor = (self.cursor - 1) % len(self.files)
            self._adjust_scroll()
        elif ev.button is Button.DOWN:
            self.cursor = (self.cursor + 1) % len(self.files)
            self._adjust_scroll()
        elif ev.button is Button.X:
            self.status_msg = self._verify_selected()
        elif ev.button is Button.A:
            self._upload_selected()

    def _adjust_scroll(self):
        visible = 12
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + visible:
            self.scroll = self.cursor - visible + 1

    def render(self, surf: pygame.Surface) -> None:
        surf.fill(theme.BG)
        
        # Header
        pygame.draw.rect(surf, theme.BG_ALT, (0, 0, theme.SCREEN_W, 50))
        pygame.draw.line(surf, theme.ACCENT, (0, 49), (theme.SCREEN_W, 49), 2)
        surf.blit(self.f_title.render("HANDSHAKE MANAGER", True, theme.ACCENT), (20, 12))
        
        if not self.files:
            surf.blit(self.f_main.render("NO HANDSHAKES FOUND IN LOOT/", True, theme.FG_DIM), (100, 200))
        else:
            y = 65
            visible = 12
            for i, path in enumerate(self.files[self.scroll : self.scroll + visible]):
                idx = i + self.scroll
                sel = (idx == self.cursor)
                
                rect = pygame.Rect(10, y, theme.SCREEN_W - 20, 28)
                if sel:
                    pygame.draw.rect(surf, theme.SELECTION_BG, rect, border_radius=4)
                    pygame.draw.rect(surf, theme.ACCENT, rect, 1, border_radius=4)
                
                # Filename
                col = theme.FG if not sel else theme.ACCENT
                surf.blit(self.f_main.render(path.name, True, col), (20, y + 4))
                
                # Size / Type
                size_kb = path.stat().st_size / 1024
                meta = f"{size_kb:.1f} KB | {path.suffix.upper()}"
                surf.blit(self.f_small.render(meta, True, theme.FG_DIM), (500, y + 6))
                
                y += 32

        # Status Bar
        pygame.draw.rect(surf, (10, 10, 20), (0, theme.SCREEN_H - 35, theme.SCREEN_W, 35))
        pygame.draw.line(surf, theme.DIVIDER, (0, theme.SCREEN_H - 35), (theme.SCREEN_W, theme.SCREEN_H - 35))
        
        s_surf = self.f_small.render(self.status_msg, True, theme.ACCENT)
        surf.blit(s_surf, (20, theme.SCREEN_H - 25))
        
        hint = self.f_small.render("A: UPLOAD  X: VERIFY  UP/DN: NAVIGATE  B: BACK", True, theme.FG_DIM)
        surf.blit(hint, (theme.SCREEN_W - hint.get_width() - 20, theme.SCREEN_H - 25))
