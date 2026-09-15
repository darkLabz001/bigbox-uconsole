"""Tests for bigbox.input.keyboard — keysym mapping and the SELECT+START
HK chord, including the edge ordering that a real keyboard produces."""
from __future__ import annotations

import sys
import traceback

import pygame

from bigbox.events import Button, ButtonEvent, EventBus
import bigbox.input.keyboard as kbd


def _down(key: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=key)


def _up(key: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYUP, key=key)


def _run(events: list[pygame.event.Event]):
    kbd.reset_key_state()
    bus = EventBus()
    out: list[ButtonEvent] = []
    for ev in events:
        kbd.translate(ev, bus)
        out.extend(bus.drain())
    return out


def _buttons(events: list[pygame.event.Event]) -> list[tuple[str, bool]]:
    return [(e.button.value, e.pressed) for e in _run(events)]


def test_plain_face_buttons():
    assert _buttons([_down(pygame.K_j)]) == [("A", True)]
    assert _buttons([_down(pygame.K_u)]) == [("X", True)]
    assert _buttons([_down(pygame.K_i)]) == [("Y", True)]
    assert _buttons([_down(pygame.K_k), _up(pygame.K_k)]) == [
        ("B", True), ("B", False)]


def test_plain_shoulders_are_shifts():
    assert _buttons([_down(pygame.K_LSHIFT)]) == [("LL", True)]
    assert _buttons([_down(pygame.K_RSHIFT)]) == [("RR", True)]


def test_select_and_start_alone_still_map():
    assert _buttons([_down(pygame.K_SPACE), _up(pygame.K_SPACE)]) == [
        ("SELECT", True), ("SELECT", False)]
    assert _buttons([_down(pygame.K_RETURN), _up(pygame.K_RETURN)]) == [
        ("START", True), ("START", False)]


def test_chord_emits_hk_not_individuals():
    # Space then Enter completes the chord → HK, never SELECT/START.
    assert _buttons([_down(pygame.K_SPACE), _down(pygame.K_RETURN)]) == [
        ("SELECT", True), ("HK", True)]
    assert _buttons([_down(pygame.K_SPACE), _down(pygame.K_RETURN),
                     _up(pygame.K_SPACE)]) == [
        ("SELECT", True), ("HK", True), ("HK", False), ("SELECT", False)]


def test_chord_breaks_on_absorbed_leg_release():
    # Enter completed the chord (absorbed); releasing it must break HK
    # without emitting a stray START.
    assert _buttons([_down(pygame.K_SPACE), _down(pygame.K_RETURN),
                     _up(pygame.K_RETURN), _up(pygame.K_SPACE)]) == [
        ("SELECT", True), ("HK", True), ("HK", False), ("SELECT", False)]


def test_chord_repeat_no_duplicate_hk():
    # Typematic repeat of the completing leg must not double-fire HK.
    assert _buttons([_down(pygame.K_SPACE), _down(pygame.K_RETURN),
                     _down(pygame.K_RETURN)]) == [
        ("SELECT", True), ("HK", True)]


def test_chord_enter_first_order():
    assert _buttons([_down(pygame.K_RETURN), _down(pygame.K_SPACE),
                     _up(pygame.K_SPACE), _up(pygame.K_RETURN)]) == [
        ("START", True), ("HK", True), ("HK", False), ("START", False)]


def test_home_maps_to_hk():
    assert _buttons([_down(pygame.K_HOME), _up(pygame.K_HOME)]) == [
        ("HK", True), ("HK", False)]


def test_reset_on_focus_loss_unsicks_hk():
    kbd.reset_key_state()
    bus = EventBus()
    kbd.translate(_down(pygame.K_SPACE), bus)
    kbd.translate(_down(pygame.K_RETURN), bus)
    assert bus.drain() == [ButtonEvent(Button.SELECT, True),
                           ButtonEvent(Button.HK, True)]
    releases = kbd.reset_key_state()
    assert releases == [ButtonEvent(Button.HK, False)]
    # Fresh chord still works after the reset.
    bus2 = EventBus()
    kbd.translate(_down(pygame.K_SPACE), bus2)
    kbd.translate(_down(pygame.K_RETURN), bus2)
    got = bus2.drain()
    assert got == [ButtonEvent(Button.SELECT, True),
                   ButtonEvent(Button.HK, True)]


def test_set_keymap_overrides():
    km = dict(kbd.default_keymap())
    km.pop(pygame.K_j)               # unbind a default…
    km[pygame.K_p] = Button.SELECT    # …and add a new one
    kbd.set_keymap(km)
    try:
        assert _buttons([_down(pygame.K_p)]) == [("SELECT", True)]
        assert _buttons([_down(pygame.K_j)]) == []
    finally:
        kbd.set_keymap(kbd.default_keymap())


def _main() -> int:
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passes, failures = 0, []
    for name, fn in tests:
        try:
            fn()
            passes += 1
            print(f"ok   {name}")
        except Exception:
            failures.append(f"FAIL {name}\n{traceback.format_exc()}")
    print()
    print(f"{passes} passed · {len(failures)} failed")
    for line in failures:
        print(line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())