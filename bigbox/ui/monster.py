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
    """A retro pixelated monster that lives in the Launcher sidebar."""

    ANIMATIONS = {
        "IDLE": list(range(0, 4)),
        "WALK": list(range(4, 10)),
        "HAPPY": list(range(10, 14)),
        "HURT": list(range(14, 17)),
    }

    def __init__(self):
        self.frames = []
        self.frame_size = 24
        self.display_size = 48 # Scaled up for visibility
        self.current_state = "IDLE"
        self.frame_index = 0
        self.last_update = time.time()
        self.state_start = time.time()
        
        # Default home screen position (Sidebar area)
        self.pos = [85, 300] 
        self.target_x = 85
        
        self._load_assets()

    def _load_assets(self):
        try:
            # Try multiple path variants to be absolutely sure
            possible_paths = [
                Path(__file__).resolve().parents[2] / "assets" / "monster.png",
                Path("assets/monster.png").resolve(),
                Path("/home/sinxneo/projects/bigbox/assets/monster.png")
            ]
            
            img_path = None
            for p in possible_paths:
                if p.exists():
                    img_path = p
                    break
            
            if img_path:
                full_sheet = pygame.image.load(str(img_path)).convert_alpha()
                
                # --- Fast High-Contrast B&W Processing ---
                # Create a white version of the sprite sheet
                white_sheet = full_sheet.copy()
                # This trick fills all non-transparent pixels with white
                white_sheet.fill((255, 255, 255, 255), special_flags=pygame.BLEND_RGBA_MAX)
                
                # Extract frames
                for i in range(24):
                    # Extract 24x24 frame
                    frame_surf = pygame.Surface((self.frame_size, self.frame_size), pygame.SRCALPHA)
                    frame_surf.blit(white_sheet, (0, 0), (i * self.frame_size, 0, self.frame_size, self.frame_size))
                    
                    # Scale up to 48x48 for better visibility on the 800x480 screen
                    scaled = pygame.transform.scale(frame_surf, (self.display_size, self.display_size))
                    self.frames.append(scaled)
                    
                print(f"[monster] Success: {len(self.frames)} frames loaded from {img_path}")
            else:
                print(f"[monster] Error: Could not find assets/monster.png")
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

        # Animation timing
        anim_speed = 0.15
        if self.current_state == "WALK":
            anim_speed = 0.1
        elif self.current_state == "HAPPY":
            anim_speed = 0.08

        if now - self.state_start > anim_speed:
            self.frame_index = (self.frame_index + 1) % len(self.ANIMATIONS[self.current_state])
            self.state_start = now

        # Logic for transitions
        if self.current_state == "HAPPY" and self.frame_index == len(self.ANIMATIONS["HAPPY"]) - 1:
            self.set_state("IDLE")
        
        if self.current_state == "HURT" and self.frame_index == len(self.ANIMATIONS["HURT"]) - 1:
            self.set_state("IDLE")

        # Subtle idle movement
        if self.current_state == "IDLE" and random.random() < 0.01:
            self.target_x = random.randint(40, 130) # Stay within sidebar
            self.set_state("WALK")
        
        if self.current_state == "WALK":
            dx = self.target_x - self.pos[0]
            if abs(dx) < 2:
                self.set_state("IDLE")
            else:
                self.pos[0] += (2 if dx > 0 else -2)

    def render(self, surf: pygame.Surface):
        if not self.frames:
            # Better fallback: a larger, glowing square so you can at least see where he is
            pygame.draw.rect(surf, (255, 255, 255), (self.pos[0] - 10, self.pos[1], 20, 20), 2)
            return

        anim_frames = self.ANIMATIONS.get(self.current_state, self.ANIMATIONS["IDLE"])
        idx = anim_frames[self.frame_index % len(anim_frames)]
        frame = self.frames[idx]
        
        if self.current_x_direction() < 0:
            frame = pygame.transform.flip(frame, True, False)

        # Draw Bitmon
        surf.blit(frame, (self.pos[0] - self.display_size // 2, self.pos[1]))

    def current_x_direction(self):
        return self.target_x - self.pos[0]
