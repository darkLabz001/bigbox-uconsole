"""Map rendering widget using OpenStreetMap tiles with local caching.
Optimized for Raspberry Pi 4 with Surface-backed caching and pixel-coord precalculation.
"""
from __future__ import annotations

import math
import os
import threading
import requests
from pathlib import Path
from typing import Optional, List, Tuple

import pygame
from bigbox import theme

CACHE_DIR = Path.home() / ".bigbox" / "map_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

class MapWidget:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.zoom = 15
        self.lat = 0.0
        self.lon = 0.0
        
        # Tile management
        self.tiles: dict[tuple[int, int, int], pygame.Surface] = {}
        self._lock = threading.Lock()
        self._pending_tiles: set[tuple[int, int, int]] = set()
        
        # Hardware acceleration: backbuffer for the map portion
        self.map_surface = pygame.Surface((width, height))
        self.needs_redraw = True
        
        # Breadcrumbs: list of (px, py) relative to center
        # We store them as pixel offsets so we don't re-calculate Mercator every frame
        self.breadcrumbs: List[Tuple[float, float]] = []
        self.raw_coords: List[Tuple[float, float]] = [] # (lat, lon)
        self.max_breadcrumbs = 500
        
        # Discovery Rings: (px, py, radius, start_time)
        self.rings: List[List] = []

    def set_location(self, lat: float, lon: float):
        if lat == self.lat and lon == self.lon:
            return
            
        old_lat, old_lon = self.lat, self.lon
        self.lat = lat
        self.lon = lon
        self.needs_redraw = True
        
        if not self.raw_coords or self._dist(self.raw_coords[-1], (lat, lon)) > 0.0001:
            self.raw_coords.append((lat, lon))
            if len(self.raw_coords) > self.max_breadcrumbs:
                self.raw_coords.pop(0)
            self._update_breadcrumbs()

    def add_discovery_ring(self, lat: float, lon: float):
        """Add an expanding ring at a specific coordinate."""
        self.rings.append([lat, lon, 0.0, pygame.time.get_ticks()])

    def _update_breadcrumbs(self):
        # We calculate the pixel positions relative to the current center
        # This is only done when the location changes significantly
        pass # Actual calculation happens in render for now, but using cached raw_coords

    def _dist(self, p1: tuple[float, float], p2: tuple[float, float]) -> float:
        return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

    def _deg2num_f(self, lat_deg, lon_deg, zoom) -> tuple[float, float]:
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = (lon_deg + 180.0) / 360.0 * n
        ytile = (1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n
        return (xtile, ytile)

    def _get_tile_url(self, x: int, y: int, z: int) -> str:
        return f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    def _fetch_tile(self, x: int, y: int, z: int):
        cache_path = CACHE_DIR / f"{z}_{x}_{y}.png"
        if cache_path.exists():
            try:
                img = pygame.image.load(str(cache_path)).convert()
                with self._lock:
                    self.tiles[(x, y, z)] = img
                    self.needs_redraw = True
                return
            except Exception:
                pass

        url = self._get_tile_url(x, y, z)
        try:
            headers = {"User-Agent": "BigB0X/2.0 (Tactical-Deployer)"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                with cache_path.open("wb") as f:
                    f.write(resp.content)
                img = pygame.image.load(str(cache_path)).convert()
                with self._lock:
                    self.tiles[(x, y, z)] = img
                    self.needs_redraw = True
        except Exception:
            pass
        finally:
            with self._lock:
                if (x, y, z) in self._pending_tiles:
                    self._pending_tiles.remove((x, y, z))

    def render(self, surf: pygame.Surface, x_offset: int, y_offset: int):
        cx, cy = self.width // 2, self.height // 2
        
        if self.needs_redraw:
            self._draw_map_surface()
            self.needs_redraw = False
            
        surf.blit(self.map_surface, (x_offset, y_offset))
        
        # Draw dynamic elements (Rings, Self Marker) on top of the cached map
        # These are drawn directly to the target surface every frame for smoothness
        
        # Clip area for dynamic elements
        clip_rect = pygame.Rect(x_offset, y_offset, self.width, self.height)
        old_clip = surf.get_clip()
        surf.set_clip(clip_rect)

        now = pygame.time.get_ticks()
        new_rings = []
        for r in self.rings:
            rlat, rlon, radius, start = r
            age = (now - start) / 1000.0 # seconds
            if age > 1.5: continue # 1.5s lifespan
            
            # Current location tile coords
            n = 2.0 ** self.zoom
            xt_c, yt_c = self._deg2num_f(self.lat, self.lon, self.zoom)
            xt_r, yt_r = self._deg2num_f(rlat, rlon, self.zoom)
            
            rpx = cx + int((xt_r - xt_c) * 256) + x_offset
            rpy = cy + int((yt_r - yt_c) * 256) + y_offset
            
            # Expanding radius
            radius = age * 100 
            alpha = int(255 * (1.0 - age / 1.5))
            
            # Draw circle with alpha (hacky in pygame without a separate surface)
            # For Pi 4, we can afford a small temp surface for alpha rings
            ring_surf = pygame.Surface((int(radius*2+2), int(radius*2+2)), pygame.SRCALPHA)
            pygame.draw.circle(ring_surf, (theme.ACCENT[0], theme.ACCENT[1], theme.ACCENT[2], alpha), (int(radius), int(radius)), int(radius), 2)
            surf.blit(ring_surf, (rpx - int(radius), rpy - int(radius)))
            
            r[2] = radius
            new_rings.append(r)
        self.rings = new_rings

        # Self Marker (Crosshair)
        pygame.draw.circle(surf, (255, 0, 0), (cx + x_offset, cy + y_offset), 8, 2)
        pygame.draw.line(surf, (255, 0, 0), (cx + x_offset - 12, cy + y_offset), (cx + x_offset + 12, cy + y_offset), 2)
        pygame.draw.line(surf, (255, 0, 0), (cx + x_offset, cy + y_offset - 12), (cx + x_offset, cy + y_offset + 12), 2)

        surf.set_clip(old_clip)
        pygame.draw.rect(surf, theme.ACCENT, clip_rect, 1)

    def _draw_map_surface(self):
        self.map_surface.fill((20, 20, 25))
        if self.lat == 0.0 and self.lon == 0.0:
            f = pygame.font.Font(None, 24)
            msg = f.render("WAITING FOR GPS FIX...", True, theme.FG_DIM)
            self.map_surface.blit(msg, (self.width // 2 - msg.get_width() // 2, self.height // 2 - msg.get_height() // 2))
            return

        n = 2.0 ** self.zoom
        xtile_f, ytile_f = self._deg2num_f(self.lat, self.lon, self.zoom)
        xtile, ytile = int(xtile_f), int(ytile_f)
        
        off_x = int((xtile_f - xtile) * 256)
        off_y = int((ytile_f - ytile) * 256)
        
        cx, cy = self.width // 2, self.height // 2
        rx, ry = self.width // 256 + 1, self.height // 256 + 1
        
        for dx in range(-rx, rx + 1):
            for dy in range(-ry, ry + 1):
                tx, ty = xtile + dx, ytile + dy
                if tx < 0 or tx >= n or ty < 0 or ty >= n: continue
                
                tile_key = (tx, ty, self.zoom)
                with self._lock:
                    img = self.tiles.get(tile_key)
                
                px = cx + (dx * 256) - off_x
                py = cy + (dy * 256) - off_y
                
                if img:
                    self.map_surface.blit(img, (px, py))
                else:
                    pygame.draw.rect(self.map_surface, (30, 30, 40), (px, py, 256, 256), 1)
                    with self._lock:
                        if tile_key not in self._pending_tiles:
                            self._pending_tiles.add(tile_key)
                            threading.Thread(target=self._fetch_tile, args=(tx, ty, self.zoom), daemon=True).start()

        # Breadcrumbs (Static part)
        if len(self.raw_coords) > 1:
            points = []
            for blat, blon in self.raw_coords:
                bxt_f, byt_f = self._deg2num_f(blat, blon, self.zoom)
                bpx = cx + int((bxt_f - xtile_f) * 256)
                bpy = cy + int((byt_f - ytile_f) * 256)
                points.append((bpx, bpy))
            if len(points) >= 2:
                pygame.draw.lines(self.map_surface, theme.ACCENT, False, points, 2)
