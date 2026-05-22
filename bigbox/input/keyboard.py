"""USB-HID keyboard input source for bigbox.

The uConsole's built-in keyboard appears to the OS as a regular USB HID
keyboard. The stock STM32 firmware (Code/uconsole_keyboard in the
clockworkpi/uConsole repo) emits these keysyms for the gamepad-style keys
when the rear PD2 switch is in keyboard mode (the default for most users):

    D-pad           → arrow keys
    A / B / X / Y   → j  /  k  /  u  /  i
    L / R shoulder  → Left Shift  /  Right Shift
    Start           → Enter
    Select          → Space

Mappings below cover both the uConsole and a regular PC keyboard for
desktop dev mode. Where the two conflict (e.g. Space) the uConsole wins
because that's the deployed target.
"""
from __future__ import annotations

import pygame

from bigbox.events import Button, ButtonEvent, EventBus

KEYMAP: dict[int, Button] = {
    # --- D-pad / WASD nav ---------------------------------------------------
    pygame.K_UP: Button.UP,
    pygame.K_DOWN: Button.DOWN,
    pygame.K_LEFT: Button.LEFT,
    pygame.K_RIGHT: Button.RIGHT,
    pygame.K_w: Button.UP,
    pygame.K_s: Button.DOWN,
    pygame.K_a: Button.LEFT,
    pygame.K_d: Button.RIGHT,

    # --- Face buttons -------------------------------------------------------
    # uConsole stock firmware: A=j  B=k  X=u  Y=i
    pygame.K_j: Button.A,
    pygame.K_k: Button.B,
    pygame.K_u: Button.X,
    pygame.K_i: Button.Y,
    # PC dev fallback: Z/X/C/V (matches the README controls table)
    pygame.K_z: Button.A,
    pygame.K_x: Button.B,
    pygame.K_c: Button.X,
    pygame.K_v: Button.Y,

    # --- Console keys -------------------------------------------------------
    # uConsole stock firmware: Start=Enter, Select=Space
    pygame.K_RETURN: Button.START,
    pygame.K_SPACE: Button.SELECT,
    # PC dev fallback for Select
    pygame.K_BACKSPACE: Button.SELECT,
    pygame.K_TAB: Button.SELECT,

    # --- Shoulder buttons ---------------------------------------------------
    # uConsole stock firmware: L=Left Shift, R=Right Shift
    pygame.K_LSHIFT: Button.LL,
    pygame.K_RSHIFT: Button.RR,
    # PC dev fallback
    pygame.K_q: Button.LL,
    pygame.K_e: Button.RR,
    pygame.K_l: Button.LL,
    pygame.K_r: Button.RR,

    # --- Universal back / cancel -------------------------------------------
    pygame.K_ESCAPE: Button.B,

    # --- Hotkey button ------------------------------------------------------
    # uConsole has no dedicated HK key. Pick something convenient.
    # Tweak via /etc/bigbox/buttons.toml [keymap] without code edits.
    pygame.K_h: Button.HK,
    pygame.K_HOME: Button.HK,
}


def apply_keymap_overrides(overrides: dict[int, Button]) -> None:
    """Merge user-supplied keysym→Button overrides on top of the defaults.

    Called once at startup from app._start_input() so /etc/bigbox/buttons.toml
    [keymap] entries take precedence over the bundled mappings.
    """
    KEYMAP.update(overrides)


def translate(ev: pygame.event.Event, bus: EventBus) -> None:
    if ev.type == pygame.KEYDOWN:
        b = KEYMAP.get(ev.key)
        if b:
            bus.put(ButtonEvent(b, pressed=True))
    elif ev.type == pygame.KEYUP:
        b = KEYMAP.get(ev.key)
        if b:
            bus.put(ButtonEvent(b, pressed=False))
