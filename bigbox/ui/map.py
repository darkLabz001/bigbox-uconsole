"""Map rendering widget using OpenStreetMap tiles with local caching.
Supports Mercator projection, breadcrumbs, and real-time GPS tracking.
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
        self.tiles: dict[tuple[int, int, int], pygame.surface.Surface] = {}
        self._lock = threading.Lock()
        self._pending_tiles: set[tuple[int, int, int]] = set()
        
        # Breadcrumbs: list of (lat, lon)
        self.breadcrumbs: List[Tuple[float, float]] = []
        self.max_breadcrumbs = 500

    def set_location(self, lat: float, lon: float):
        self.lat = lat
        self.lon = lon
        if not self.breadcrumbs or self._dist(self.breadcrumbs[-1], (lat, lon)) > 0.0001:
            self.breadcrumbs.append((lat, lon))
            if len(self.breadcrumbs) > self.max_breadcrumbs:
                self.breadcrumbs.pop(0)

    def _dist(self, p1: tuple[float, float], p2: tuple[float, float]) -> float:
        return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

    def _deg2num(self, lat_deg, lon_deg, zoom) -> tuple[int, int]:
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = int((lon_deg + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
        return (xtile, ytile)

    def _num2deg(self, xtile, ytile, zoom) -> tuple[float, float]:
        n = 2.0 ** zoom
        lon_deg = xtile / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
        lat_deg = math.degrees(lat_rad)
        return (lat_deg, lon_deg)

    def _get_tile_url(self, x: int, y: int, z: int) -> str:
        # Using OSM standard tile server. 
        # Note: Heavy use should use a private server or satisfy OSM Tile Usage Policy.
        return f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    def _fetch_tile(self, x: int, y: int, z: int):
        cache_path = CACHE_DIR / f"{z}_{x}_{y}.png"
        if cache_path.exists():
            try:
                img = pygame.image.load(str(cache_path)).convert()
                with self._lock:
                    self.tiles[(x, y, z)] = img
                return
            except Exception:
                pass

        # Download
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
        except Exception:
            pass
        finally:
            with self._lock:
                if (x, y, z) in self._pending_tiles:
                    self._pending_tiles.remove((x, y, z))

    def render(self, surf: pygame.Surface, x_offset: int, y_offset: int):
        # Calculate center tile and pixel offset within it
        n = 2.0 ** self.zoom
        xtile_f = (self.lon + 180.0) / 360.0 * n
        ytile_f = (1.0 - math.log(math.tan(math.radians(self.lat)) + (1 / math.cos(math.radians(self.lat)))) / math.pi) / 2.0 * n
        
        xtile = int(xtile_f)
        ytile = int(ytile_f)
        
        # Offset from center of widget
        off_x = int((xtile_f - xtile) * 256)
        off_y = int((ytile_f - ytile) * 256)
        
        cx, cy = self.width // 2, self.height // 2
        
        # Range of tiles to draw
        rx = self.width // 256 + 2
        ry = self.height // 256 + 2
        
        # Clip area
        clip_rect = pygame.Rect(x_offset, y_offset, self.width, self.height)
        old_clip = surf.get_clip()
        surf.set_clip(clip_rect)
        
        # Fill background
        pygame.draw.rect(surf, (20, 20, 25), clip_rect)

        for dx in range(-rx, rx + 1):
            for dy in range(-ry, ry + 1):
                tx, ty = xtile + dx, ytile + dy
                if tx < 0 or tx >= n or ty < 0 or ty >= n:
                    continue
                
                tile_key = (tx, ty, self.zoom)
                img = None
                with self._lock:
                    img = self.tiles.get(tile_key)
                
                px = cx + (dx * 256) - off_x + x_offset
                py = cy + (dy * 256) - off_y + y_offset
                
                if img:
                    surf.blit(img, (px, py))
                else:
                    # Draw placeholder and queue download
                    pygame.draw.rect(surf, (30, 30, 40), (px, py, 256, 256), 1)
                    with self._lock:
                        if tile_key not in self._pending_tiles:
                            self._pending_tiles.add(tile_key)
                            threading.Thread(target=self._fetch_tile, args=(tx, ty, self.zoom), daemon=True).start()

        # Render Breadcrumbs
        if len(self.breadcrumbs) > 1:
            points = []
            for blat, blon in self.breadcrumbs:
                # Convert lat/lon to widget-relative pixels
                # x = (lon + 180) * (width / 360)  <- no, mercator
                bn = 2.0 ** self.zoom
                bxtile_f = (blon + 180.0) / 360.0 * bn
                bytile_f = (1.0 - math.log(math.tan(math.radians(blat)) + (1 / math.cos(math.radians(blat)))) / math.pi) / 2.0 * bn
                
                bpx = cx + int((bxtile_f - xtile_f) * 256) + x_offset
                bpy = cy + int((bytile_f - ytile_f) * 256) + y_offset
                points.append((bpx, bpy))
            
            if len(points) >= 2:
                pygame.draw.lines(surf, theme.ACCENT, False, points, 2)

        # Draw Self Marker (Crosshair)
        pygame.draw.circle(surf, (255, 0, 0), (cx + x_offset, cy + y_offset), 6, 2)
        pygame.draw.line(surf, (255, 0, 0), (cx + x_offset - 10, cy + y_offset), (cx + x_offset + 10, cy + y_offset), 2)
        pygame.draw.line(surf, (255, 0, 0), (cx + x_offset, cy + y_offset - 10), (cx + x_offset, cy + y_offset + 10), 2)

        surf.set_clip(old_clip)
        pygame.draw.rect(surf, theme.ACCENT, clip_rect, 1)
