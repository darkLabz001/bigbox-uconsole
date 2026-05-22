"""Loads and saves config/buttons.toml.

uConsole takes input from a USB-HID keyboard rather than GPIO buttons, so the
config is a [keymap] of pygame keysym names → logical Button names. The legacy
[pins] section (BCM pin numbers for the GamePi43) is still parsed so the same
file can boot a CM4 with a custom GPIO hat — see `pins` on ButtonConfig.

Keymap semantics: a non-empty [keymap] in /etc/bigbox/buttons.toml REPLACES
the bundled defaults in bigbox.input.keyboard.KEYMAP. An empty/missing
section leaves the defaults in place. This is what lets the in-app button
mapper (Settings → System → Button Mapper) truly own the keymap, including
unbinding defaults a user doesn't want.
"""
from __future__ import annotations

import os
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


def save_keymap(keymap: dict[int, Button]) -> bool:
    """Atomically write a full keymap to /etc/bigbox/buttons.toml.

    Preserves any [pins] and [behavior] sections found in the existing file
    (or the bundled default if no /etc copy exists yet) so toggles tuned
    via hand-edit aren't blown away by an in-app save.

    Returns True on success, False on any IO/permissions error.
    """
    import pygame

    target = _ETC_OVERRIDE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[input/config] cannot create {target.parent}: {e}")
        return False

    # Pull existing [pins] and [behavior] from /etc copy, falling back to
    # the bundled default so a first-time save still emits sensible
    # behavior tunables.
    existing: dict = {}
    for src in (target, _bundled_path()):
        if src.is_file():
            try:
                existing = tomllib.loads(src.read_text())
                break
            except Exception:
                continue

    pins = existing.get("pins", {})
    behavior = existing.get("behavior", {})

    lines: list[str] = [
        "# bigbox button mapper — written by Settings → System → Button Mapper.",
        "# A non-empty [keymap] here REPLACES the bundled defaults in",
        "# bigbox/input/keyboard.py. Edit by hand or wipe to restore defaults.",
        "",
        "[keymap]",
    ]
    # Sort by keysym name for stable diffs.
    for keysym in sorted(keymap.keys(), key=lambda k: pygame.key.name(k)):
        name = pygame.key.name(keysym).replace('"', '\\"')
        btn = keymap[keysym].value
        lines.append(f'"{name}" = "{btn}"')
    lines.append("")

    if pins:
        lines.append("[pins]")
        for k, v in pins.items():
            lines.append(f"{k} = {int(v)}")
        lines.append("")

    lines.append("[behavior]")
    lines.append(f"debounce_ms        = {int(behavior.get('debounce_ms', 30))}")
    lines.append(f"repeat_delay_ms    = {int(behavior.get('repeat_delay_ms', 400))}")
    lines.append(f"repeat_interval_ms = {int(behavior.get('repeat_interval_ms', 90))}")
    lines.append("")

    content = "\n".join(lines)

    # Atomic replace via tmpfile + os.replace so a power loss mid-write
    # never leaves a half-written buttons.toml.
    tmp = target.with_suffix(".toml.tmp")
    try:
        tmp.write_text(content)
        os.replace(tmp, target)
        return True
    except Exception as e:
        print(f"[input/config] save_keymap write failed: {e}")
        try:
            tmp.unlink(missing_ok=True)  # type: ignore[call-arg]
        except Exception:
            pass
        return False
