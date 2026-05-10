"""Hacker Achievement System — XP, Leveling, and Ranks.

Tracks operational success (handshakes, wardriving, scans) and assigns
XP and persistent ranks.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from dataclasses import dataclass

STATE_PATH = Path("/etc/bigbox/achievements.json")

RANKS = [
    (0, "SCRIPT_KIDDIE"),
    (500, "WARDRIVER"),
    (2500, "NETRUNNER"),
    (10000, "CYBER_GHOST"),
    (50000, "DAEMON_LORD"),
]

@dataclass
class UserState:
    xp: int = 0
    level: int = 1
    total_handshakes: int = 0
    total_nodes: int = 0
    total_bt: int = 0
    total_wardrive_s: float = 0.0
    unlocked_milestones: list[str] = None

    def __post_init__(self):
        if self.unlocked_milestones is None:
            self.unlocked_milestones = []

    def get_rank(self) -> str:
        current_rank = RANKS[0][1]
        for xp_req, name in RANKS:
            if self.xp >= xp_req:
                current_rank = name
            else:
                break
        return current_rank

    def next_rank_xp(self) -> int:
        for xp_req, _ in RANKS:
            if xp_req > self.xp:
                return xp_req
        return self.xp

_APP_REF = None

def set_app_ref(app):
    global _APP_REF
    _APP_REF = app

def _load() -> UserState:
    try:
        if STATE_PATH.exists():
            with STATE_PATH.open(encoding="utf-8") as f:
                data = json.load(f)
            return UserState(**data)
    except Exception:
        pass
    return UserState()

def _save(state: UserState) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with STATE_PATH.open("w", encoding="utf-8") as f:
            data = {
                "xp": state.xp,
                "level": state.level,
                "total_handshakes": state.total_handshakes,
                "total_nodes": state.total_nodes,
                "total_bt": state.total_bt,
                "total_wardrive_s": state.total_wardrive_s,
                "unlocked_milestones": state.unlocked_milestones
            }
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[achievements] save failed: {e}")

def get_state() -> UserState:
    return _load()

def add_xp(amount: int):
    state = _load()
    state.xp += amount
    import math
    new_level = int(math.sqrt(state.xp / 100)) + 1
    if new_level > state.level:
        state.level = new_level
        if _APP_REF:
            _APP_REF.toast(f"LEVEL UP: {new_level} !!")
            _APP_REF.play_notification()
    
    _check_milestones(state)
    _save(state)

def _check_milestones(state: UserState):
    milestones = [
        ("HANDSHAKE_HUNTER", state.total_handshakes >= 10, "Captured 10 handshakes"),
        ("WI-FI_WARRIOR", state.total_nodes >= 1000, "Found 1,000 nodes"),
        ("BT_STALKER", state.total_bt >= 100, "Tracked 100 BT devices"),
        ("ROAD_TRIP", state.total_wardrive_s >= 3600, "1 hour of wardriving"),
    ]
    
    for key, condition, msg in milestones:
        if condition and key not in state.unlocked_milestones:
            state.unlocked_milestones.append(key)
            if _APP_REF:
                _APP_REF.toast(f"ACHIEVEMENT: {key}")
                _APP_REF.play_notification()

def report_handshake():
    state = _load()
    state.total_handshakes += 1
    _save(state)
    add_xp(100)

def report_node(is_bt: bool = False):
    state = _load()
    if is_bt:
        state.total_bt += 1
        xp = 5
    else:
        state.total_nodes += 1
        xp = 1
    _save(state)
    add_xp(xp)

def report_wardrive_time(seconds: float):
    state = _load()
    state.total_wardrive_s += seconds
    _save(state)
    # 1 XP per minute
    if seconds > 60:
        add_xp(int(seconds / 60))
