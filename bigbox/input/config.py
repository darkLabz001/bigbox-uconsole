"""Loads config/buttons.toml.

uConsole takes input from a USB-HID keyboard rather than GPIO buttons, so the
config is a [keymap] of pygame keysym names → logical Button names. The legacy
[pins] section (BCM pin numbers for the GamePi43) is still parsed so the same
file can boot a CM4 with a custom GPIO hat — see `pins` on ButtonConfig.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import-not-found]
else:
    import tomli as tomllib  # type: ignore[import-not-found]

from bigbox.events import Button


@dataclass(frozen=True)
class ButtonConfig:
    # Optional GPIO pin map — only used when BIGBOX_USE_GPIO=1.
    pins: dict[Button, int] = field(default_factory=dict)
    # Optional keyboard-override map — pygame keysym int → Button. Applied
    # on top of the bundled defaults in bigbox.input.keyboard.KEYMAP.
    keymap: dict[int, Button] = field(default_factory=dict)
    debounce_ms: int = 30
    repeat_delay_ms: int = 400
    repeat_interval_ms: int = 90


_ETC_OVERRIDE = Path("/etc/bigbox/buttons.toml")


def _bundled_path() -> Path:
    # config/buttons.toml relative to repo root (two levels up from this file).
    return Path(__file__).resolve().parents[2] / "config" / "buttons.toml"


def _resolve_path() -> Path:
    """Pick the active config file. /etc/bigbox/buttons.toml wins if present
    so a user's hand-tuned map survives OTA git resets that overwrite the
    bundled default."""
    if _ETC_OVERRIDE.is_file():
        return _ETC_OVERRIDE
    return _bundled_path()


def _resolve_keysym(name: str) -> int | None:
    """Turn a pygame keysym name (e.g. "j", "return", "lshift") into the
    pygame.K_* int. Returns None for unknown names."""
    import pygame
    # pygame.key.key_code() accepts the human name ("return", "left shift").
    # It raises ValueError on unknown names — swallow and return None.
    try:
        return pygame.key.key_code(name)
    except (ValueError, Exception):
        pass
    # Fall back to attribute lookup ("j" → pygame.K_j).
    attr = f"K_{name.lower()}"
    return getattr(pygame, attr, None)


def load_button_config(path: Path | None = None) -> ButtonConfig:
    p = path or _resolve_path()
    raw = tomllib.loads(p.read_text())

    pins_raw = raw.get("pins", {})
    pins: dict[Button, int] = {}
    for name, pin in pins_raw.items():
        try:
            pins[Button(name.upper())] = int(pin)
        except ValueError:
            continue

    keymap_raw = raw.get("keymap", {})
    keymap: dict[int, Button] = {}
    for key_name, btn_name in keymap_raw.items():
        keysym = _resolve_keysym(str(key_name))
        if keysym is None:
            continue
        try:
            keymap[keysym] = Button(str(btn_name).upper())
        except ValueError:
            continue

    behavior = raw.get("behavior", {})
    return ButtonConfig(
        pins=pins,
        keymap=keymap,
        debounce_ms=int(behavior.get("debounce_ms", 30)),
        repeat_delay_ms=int(behavior.get("repeat_delay_ms", 400)),
        repeat_interval_ms=int(behavior.get("repeat_interval_ms", 90)),
    )
