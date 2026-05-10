"""Achievement View — Operational stats and milestones.

Displays rank, level, XP, and a list of unlocked achievement medals.
"""
from __future__ import annotations

import pygame

from bigbox import theme, achievements
from bigbox.events import Button, ButtonEvent
from bigbox.ui.section import SectionContext


class AchievementView:
    def __init__(self) -> None:
        self.dismissed = False
        self.state = achievements.get_state()
        self.cursor = 0
        
        self.f_title = pygame.font.Font(None, 36)
        self.f_main = pygame.font.Font(None, 24)
        self.f_small = pygame.font.Font(None, 18)
        self.f_huge = pygame.font.Font(None, 72)

    def handle(self, ev: ButtonEvent, ctx: SectionContext) -> None:
        if not ev.pressed: return
        if ev.button is Button.B:
            self.dismissed = True
            return

    def render(self, surf: pygame.Surface) -> None:
        surf.fill(theme.BG)
        
        # Header
        pygame.draw.rect(surf, theme.BG_ALT, (0, 0, theme.SCREEN_W, 60))
        pygame.draw.line(surf, theme.ACCENT, (0, 59), (theme.SCREEN_W, 59), 2)
        surf.blit(self.f_title.render("OPERATIONAL ACHIEVEMENTS", True, theme.ACCENT), (20, 15))
        
        # 1. Big Rank & Level
        col_left = 300
        rank_str = self.state.get_rank()
        surf.blit(self.f_small.render("CURRENT_RANK", True, theme.FG_DIM), (20, 80))
        surf.blit(self.f_title.render(rank_str, True, theme.ACCENT), (20, 100))
        
        surf.blit(self.f_small.render("LEVEL", True, theme.FG_DIM), (20, 160))
        lvl_surf = self.f_huge.render(str(self.state.level), True, theme.FG)
        surf.blit(lvl_surf, (20, 180))
        
        # XP Progress
        next_xp = self.state.next_rank_xp()
        needed = next_xp - 0 # Simplified
        got = self.state.xp
        
        bar_w = 200
        bar_y = 260
        pygame.draw.rect(surf, (30, 35, 45), (20, bar_y, bar_w, 15), border_radius=5)
        if next_xp > 0:
            pct = min(1.0, got / next_xp)
            pygame.draw.rect(surf, theme.ACCENT, (20, bar_y, int(bar_w * pct), 15), border_radius=5)
        surf.blit(self.f_small.render(f"{self.state.xp} / {next_xp} XP", True, theme.FG_DIM), (20, bar_y + 20))

        # 2. Stats Column
        sx = 350
        surf.blit(self.f_small.render("OPERATIONAL_STATS", True, theme.FG_DIM), (sx, 80))
        stats = [
            ("HANDSHAKES", str(self.state.total_handshakes)),
            ("WI-FI NODES", str(self.state.total_nodes)),
            ("BT TRACKERS", str(self.state.total_bt)),
            ("DRIVE TIME", f"{int(self.state.total_wardrive_s / 60)}m"),
        ]
        
        for i, (lbl, val) in enumerate(stats):
            y = 110 + i * 40
            surf.blit(self.f_main.render(lbl, True, theme.FG), (sx, y))
            surf.blit(self.f_main.render(val, True, theme.ACCENT), (sx + 150, y))

        # 3. Medals (Bottom Row)
        mx = 20
        my = 340
        surf.blit(self.f_small.render("UNLOCKED_MEDALS", True, theme.FG_DIM), (mx, my))
        
        medals = [
            ("HANDSHAKE_HUNTER", "10 PCAPS"),
            ("WI-FI_WARRIOR", "1K NODES"),
            ("BT_STALKER", "100 BLE"),
            ("ROAD_TRIP", "1HR DRIVE"),
        ]
        
        for i, (key, desc) in enumerate(medals):
            unlocked = key in self.state.unlocked_milestones
            color = theme.ACCENT if unlocked else (40, 40, 50)
            rect = pygame.Rect(mx + i * 190, my + 25, 180, 60)
            pygame.draw.rect(surf, (20, 25, 35) if unlocked else (15, 15, 20), rect, border_radius=8)
            pygame.draw.rect(surf, color, rect, 1, border_radius=8)
            
            # Icon (Star)
            if unlocked:
                pygame.draw.circle(surf, theme.ACCENT, (rect.x + 25, rect.y + 30), 10, 2)
            
            surf.blit(self.f_small.render(key.replace("_"," "), True, theme.FG if unlocked else theme.FG_DIM), (rect.x + 45, rect.y + 10))
            surf.blit(self.f_small.render(desc, True, theme.FG_DIM), (rect.x + 45, rect.y + 30))

        # Hint
        hint = self.f_small.render("B: BACK", True, theme.FG_DIM)
        surf.blit(hint, (theme.SCREEN_W - 80, theme.SCREEN_H - 30))
