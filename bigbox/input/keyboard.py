"""USB-HID keyboard input source for bigbox.

The uConsole's built-in controller (STM32/GD32F103, see the ClockworkPi
``keyboards_220816`` schematic) is ONE composite USB-HID device exposing a
QWERTY keyboard, a mouse (trackball) and a gamepad all at once. The stock
firmware (Code/uconsole_keyboard in clockworkpi/uConsole) has no "modes" —
the QWERTY matrix always sends normal keys, and only the *gamepad area*
changes what it reports depending on the rear PD2 switch:

    PD2 HIGH (default) — gamepad area arrives as keysyms:
        D-pad           → arrow keys
        X / A / B / Y   → u  /  j  /  k  /  i
        Select          → Space
        Start           → Enter
    PD2 LOW — gamepad area arrives as a USB-HID joystick instead and is
        handled by bigbox.input.joystick (this module ignores those
        events: the keysyms simply never appear).

L and R shoulder keys are the keyboard's Left/Right Shift in EVERY switch
position (they live on the keyboard interface, never the joystick), which
is why they map here and not in the joystick module. The trackball is a
separate HID mouse (delivered as pygame MOUSEMOTION/MOUSEBUTTONDOWN).

This module maps pygame KEYDOWN/KEYUP keysyms to logical Buttons. The
KeyboardMapper / on-screen keyboard consumes printable keys first; the
rest route through translate(). Mappings cover both the uConsole and a
regular PC keyboard for desktop dev mode. Where the two conflict
(e.g. Space) the uConsole wins because that's the deployed target.
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
    # uConsole has no dedicated HK key and no on-device Home key. HK is
    # reachable by a SELECT+START chord (Space+Enter held together) and on
    # desktop dev boxes via Home. Do NOT bind a letter (e.g. 'h') to it — on
    # a full keyboard that fires the hotkey menu mid-typing. Override in
    # /etc/bigbox/buttons.toml [keymap] if you want a different key.
    pygame.K_HOME: Button.HK,
}

# Keys that together form the HK chord (SELECT + START). Held as a chord they
# emit HK instead of their individual buttons; the chord ends when either key
# goes up.
_CHORD_LEGS: dict[int, Button] = {
    pygame.K_SPACE: Button.SELECT,
    pygame.K_RETURN: Button.START,
}

# State used to resolve the chord across the stateless KEYDOWN/KEYUP stream:
#   _PRESSED   — every currently-down keysym.
#   _HK_HELD   — a chord HK press is outstanding (released on chord break).
#   _ABSORBED  — chord legs whose individual press was suppressed because they
#                completed the chord (their release is suppressed too).
_PRESSED: set[int] = set()
_HK_HELD = False
_ABSORBED: set[int] = set()


def apply_keymap_overrides(overrides: dict[int, Button]) -> None:
    """Merge user-supplied keysym→Button overrides on top of the defaults.

    Kept for backward compat — new code should prefer set_keymap() when the
    intent is "replace the entire keymap" (which the in-app Button Mapper
    needs in order to unbind defaults).
    """
    KEYMAP.update(overrides)


# Snapshot of the bundled defaults, captured at import time so the in-app
# Button Mapper has something to restore when the user picks "Reset to
# defaults." Never mutated.
_DEFAULTS: dict[int, Button] = dict(KEYMAP)


def default_keymap() -> dict[int, Button]:
    """Return a fresh copy of the bundled default keymap."""
    return dict(_DEFAULTS)


def set_keymap(km: dict[int, Button]) -> None:
    """Replace the entire active keymap. Mutates KEYMAP in place so any
    callers that captured a reference (none today, but keep the invariant)
    see the change."""
    KEYMAP.clear()
    KEYMAP.update(km)


def reset_key_state() -> list[ButtonEvent]:
    """Drop all internal held-key state (e.g. on window focus loss).

    Returns any synthetic release events needed to un-stick buttons the UI
    still believes are held (currently only an outstanding HK chord)."""
    global _HK_HELD
    _PRESSED.clear()
    _ABSORBED.clear()
    releases: list[ButtonEvent] = []
    if _HK_HELD:
        _HK_HELD = False
        releases.append(ButtonEvent(Button.HK, pressed=False))
    return releases


def translate(ev: pygame.event.Event, bus: EventBus) -> None:
    """Translate a pygame KEYDOWN/KEYUP into Button events.

    The gamepad keysyms (Space/Enter) double as an HK chord: while both are
    held they emit HK instead of SELECT/START. One key alone maps normally.
    """
    if ev.type == pygame.KEYDOWN:
        if ev.key in _CHORD_LEGS:
            _chord_press(ev, bus)
        else:
            _plain(ev, bus)
    elif ev.type == pygame.KEYUP:
        if ev.key in _CHORD_LEGS:
            _chord_release(ev, bus)
        else:
            _plain(ev, bus)


def _chord_press(ev: pygame.event.Event, bus: EventBus) -> None:
    global _HK_HELD
    chord_was_active = _chord_active()
    _PRESSED.add(ev.key)
    if not chord_was_active and _chord_active() and not _HK_HELD:
        # This leg completed the chord → HK replaces the individual button.
        _ABSORBED.add(ev.key)
        _HK_HELD = True
        bus.put(ButtonEvent(Button.HK, pressed=True))
        return
    if ev.key in _ABSORBED:
        # Auto-repeat KEYDOWN of the leg that completed the chord — the
        # press is outstanding, don't emit SELECT/START for it again.
        return
    _plain(ev, bus)


def _chord_release(ev: pygame.event.Event, bus: EventBus) -> None:
    global _HK_HELD
    _PRESSED.discard(ev.key)
    if ev.key in _ABSORBED:
        # Leg that completed the chord — it only ever stood for HK. If it's
        # what breaks the chord, close HK out; never emit the absorbed press.
        _ABSORBED.discard(ev.key)
        if _HK_HELD and not _chord_active():
            _HK_HELD = False
            bus.put(ButtonEvent(Button.HK, pressed=False))
        return
    # The other leg (individually mapped) going up may also break the chord,
    # and always frees its own press.
    if _HK_HELD and not _chord_active():
        _HK_HELD = False
        bus.put(ButtonEvent(Button.HK, pressed=False))
    _plain(ev, bus)


def _plain(ev: pygame.event.Event, bus: EventBus) -> None:
    """"Normal" path: map the keysym straight to its button."""
    # A leg held through a chord but released afterwards maps normally (its
    # press was emitted individually before the chord completed).
    b = KEYMAP.get(ev.key)
    if b:
        bus.put(ButtonEvent(b, pressed=(ev.type == pygame.KEYDOWN)))


def _chord_active() -> bool:
    return set(_CHORD_LEGS).issubset(_PRESSED)
