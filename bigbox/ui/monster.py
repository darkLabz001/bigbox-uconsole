from __future__ import annotations
import time
import random
import pygame
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bigbox.app import App

from bigbox import theme

class Monster:
    """A highly detailed evil demon companion for the Operator."""

    # 10752 x 2048 sheet with 256x256 frames
    ANIMATIONS = {
        "IDLE": list(range(0, 8)),        # Row 0
        "WALK": list(range(42, 50)),      # Row 1
        "HAPPY": list(range(84, 92)),     # Row 2 (Attack)
        "HURT": list(range(126, 134)),    # Row 3 (Die)
    }

    def __init__(self):
        self.frames = []
        self.frame_size = 256
        self.display_size = 96 
        self.current_state = "IDLE"
        self.frame_index = 0
        self.last_update = time.time()
        self.state_start = time.time()
        
        # Position in the sidebar
        self.pos = [85, 280] 
        self.target_x = 85
        
        self._loaded = False

    def _load_assets(self):
        if self._loaded:
            return
            
        try:
            if not pygame.display.get_init() or pygame.display.get_surface() is None:
                return

            ROOT = Path(__file__).resolve().parents[2]
            img_path = ROOT / "assets" / "monster.png"
            
            if not img_path.exists():
                img_path = Path("assets/monster.png").resolve()
            
            if img_path.exists():
                # Load the high-res 4MB sheet
                full_sheet = pygame.image.load(str(img_path.absolute())).convert_alpha()
                
                # Extract frames (256x256 each)
                cols = full_sheet.get_width() // self.frame_size
                rows = full_sheet.get_height() // self.frame_size
                
                self.frames = []
                # We only need the first 4 rows
                for r in range(min(rows, 4)):
                    for c in range(8): # Just grab 8 frames per row for efficiency
                        frame_surf = pygame.Surface((self.frame_size, self.frame_size), pygame.SRCALPHA)
                        frame_surf.blit(full_sheet, (0, 0), (c * self.frame_size, r * self.frame_size, self.frame_size, self.frame_size))
                        
                        # Scale down for the sidebar
                        scaled = pygame.transform.smoothscale(frame_surf, (self.display_size, self.display_size))
                        self.frames.append(scaled)
                
                # Update animation indices to match the 8x4 grid we just built
                self.ANIMATIONS = {
                    "IDLE": list(range(0, 8)),
                    "WALK": list(range(8, 16)),
                    "HAPPY": list(range(16, 24)),
                    "HURT": list(range(24, 32)),
                }
                
                self._loaded = True
                print(f"[monster] Success: High-res detailed demon loaded ({len(self.frames)} frames)")
            else:
                print(f"[monster] Error: monster.png missing")
        except Exception as e:
            print(f"[monster] Load failure: {e}")

    def set_state(self, state: str):
        if state in self.ANIMATIONS and self.current_state != state:
            self.current_state = state
            self.frame_index = 0
            self.state_start = time.time()

    def update(self, app: App):
        now = time.time()
        self.last_update = now

        anim_speed = 0.12 # Faster animation for detailed high-res sprite
        if self.current_state == "WALK":
            anim_speed = 0.1
        elif self.current_state == "HAPPY":
            anim_speed = 0.08

        if now - self.state_start > anim_speed:
            # Cycle through frames
            anim_frames = self.ANIMATIONS.get(self.current_state, self.ANIMATIONS["IDLE"])
            self.frame_index = (self.frame_index + 1) % len(anim_frames)
            self.state_start = now

        if self.current_state == "HAPPY" and self.frame_index == len(self.ANIMATIONS["HAPPY"]) - 1:
            self.set_state("IDLE")
        
        if self.current_state == "HURT" and self.frame_index == len(self.ANIMATIONS["HURT"]) - 1:
            self.set_state("IDLE")

        if self.current_state == "IDLE" and random.random() < 0.01:
            self.target_x = random.randint(40, 130)
            self.set_state("WALK")
        
        if self.current_state == "WALK":
            dx = self.target_x - self.pos[0]
            if abs(dx) < 2:
                self.set_state("IDLE")
            else:
                self.pos[0] += (2 if dx > 0 else -2)

    def render(self, surf: pygame.Surface):
        if not self._loaded:
            self._load_assets()

        if not self.frames:
            pygame.draw.circle(surf, (50, 0, 0), (self.pos[0], self.pos[1]), 5)
            return

        anim_frames = self.ANIMATIONS.get(self.current_state, self.ANIMATIONS["IDLE"])
        idx = anim_frames[self.frame_index % len(anim_frames)]
        
        if idx < len(self.frames):
            frame = self.frames[idx]
            if self.current_x_direction() < 0:
                frame = pygame.transform.flip(frame, True, False)
            surf.blit(frame, (self.pos[0] - self.display_size // 2, self.pos[1] - self.display_size // 2))

    def current_x_direction(self):
        return self.target_x - self.pos[0]
