"""Unit tests for the uConsole native joystick input source.

Exercises the pure logic of bigbox.input.joystick — button mapping,
hat/button/stick D-pad reconciling, press/release emit ordering, and the
[joystick] config parsing — with raw evdev ints, so it runs on a dev box
WITHOUT python3-evdev or any gamepad hardware.

Run:
    python -m tests.test_joystick
    pytest -q tests/test_joystick.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from pathlib import Path
import tempfile

from bigbox.events import Button, ButtonEvent, EventBus
from bigbox.input.config import ButtonConfig, load_button_config
from bigbox.input.config import _fmt_toml_value as _fmt

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

# Pull the module in after sys.path fix.
import bigbox.input.joystick as joy  # noqa: E402

# evdev UAPI integers (module pins these even without python3-evdev).
EV_KEY, EV_ABS = joy.EV_KEY, joy.EV_ABS
ABS_HAT0X, ABS_HAT0Y = joy.ABS_HAT0X, joy.ABS_HAT0Y
ABS_X, ABS_Y = joy.ABS_X, joy.ABS_Y
# BTN_* gamepad codes used below (stable kernel UAPI values).
BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST = 0x130, 0x131, 0x133, 0x134
BTN_SELECT, BTN_START = 0x13A, 0x13B
BTN_TL, BTN_TR = 0x136, 0x137
BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT = 0x220, 0x221, 0x222, 0x223

IF_ = sys.modules[__name__]


def _tmp_config(content: str) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "buttons.toml"
    p.write_text(content)
    return p


def _cfg(**kw) -> ButtonConfig:
    defaults = dict(pins={}, keymap={}, joy_enabled=True, joy_devnode="",
                    joy_dpad="auto", joy_deadzone=0.15, joy_buttons={})
    defaults.update(kw)
    return ButtonConfig(**defaults)


def _mk(joy_dpad="auto", joy_buttons=None) -> tuple[joy.JoystickInput, list[ButtonEvent]]:
    bus = EventBus()
    collected: list[ButtonEvent] = []

    class _Bus:
        def put(self, ev: ButtonEvent) -> None:
            collected.append(ev)

    src = joy.JoystickInput(_Bus(), _cfg(joy_dpad=joy_dpad, joy_buttons=joy_buttons or {}))
    # Simulate a gamepad whose only D-pad is hat0 (no BTN_DPAD_*, no sticks).
    src._device = None
    src._src_owner = None
    src._srcs = frozenset({"hat0"})
    src._has = {"hat0": True, "hat1": False, "buttons": False, "stick": False}
    if joy_dpad == "buttons":
        src._srcs = frozenset({"buttons"})
        src._has = {"hat0": False, "hat1": False, "buttons": True, "stick": False}
    if joy_dpad == "stick":
        src._srcs = frozenset({"stick"})
        src._has = {"hat0": False, "hat1": False, "buttons": False, "stick": True}
    # Stub the default map so tests don't need evdev.
    src._btnmap = {
        BTN_SOUTH: Button.A,
        BTN_EAST: Button.B,
        BTN_NORTH: Button.X,
        BTN_WEST: Button.Y,
        BTN_TL: Button.LL,
        BTN_TR: Button.RR,
        BTN_SELECT: Button.SELECT,
        BTN_START: Button.START,
        BTN_DPAD_UP: Button.UP,
        BTN_DPAD_DOWN: Button.DOWN,
        BTN_DPAD_LEFT: Button.LEFT,
        BTN_DPAD_RIGHT: Button.RIGHT,
    }
    return src, collected


def _feed(src, evs: list[tuple[int, int, int]]) -> None:
    for t, c, v in evs:
        src._handle(t, c, v)


# --------------------------------------------------------------------------- #
def test_face_buttons_press_and_release():
    src, out = _mk(joy_buttons={304: Button.A})
    _feed(src, [(EV_KEY, 304, 1), (EV_KEY, 304, 0)])
    assert [(e.button, e.pressed) for e in out] == [(Button.A, True), (Button.A, False)]


def test_face_button_repeat_value_no_double_press():
    src, out = _mk(joy_buttons={304: Button.A})
    _feed(src, [(EV_KEY, 304, 1), (EV_KEY, 304, 2), (EV_KEY, 304, 0)])
    assert [(e.button, e.pressed) for e in out] == [(Button.A, True), (Button.A, False)]


def test_default_face_map_south_is_a():
    src, out = _mk()
    _feed(src, [(EV_KEY, BTN_SOUTH, 1), (EV_KEY, BTN_EAST, 1),
                (EV_KEY, BTN_NORTH, 1), (EV_KEY, BTN_WEST, 1)])
    assert {e.button for e in out if e.pressed} == {Button.A, Button.B, Button.X, Button.Y}


def test_start_select_shoulders():
    src, out = _mk()
    _feed(src, [(EV_KEY, BTN_START, 1), (EV_KEY, BTN_SELECT, 1), (EV_KEY, BTN_TL, 1), (EV_KEY, BTN_TR, 1)])
    assert {e.button for e in out if e.pressed} == {Button.START, Button.SELECT, Button.LL, Button.RR}


def test_unknown_code_ignored():
    src, out = _mk()
    _feed(src, [(EV_KEY, 0xF0, 1)])  # not mapped, not even a gamepad code
    assert out == []


def test_hat_dpad_snap_up_down_left_right():
    src, out = _mk()
    _feed(src, [
        (EV_ABS, ABS_HAT0Y, -1),   # up
        (EV_ABS, ABS_HAT0Y, 0),    # release
        (EV_ABS, ABS_HAT0Y, 1),    # down
        (EV_ABS, ABS_HAT0Y, 0),
        (EV_ABS, ABS_HAT0X, -1),   # left
        (EV_ABS, ABS_HAT0X, 0),
        (EV_ABS, ABS_HAT0X, 1),    # right
        (EV_ABS, ABS_HAT0X, 0),
    ])
    seq = [(e.button, e.pressed) for e in out]
    assert seq == [
        (Button.UP, True), (Button.UP, False),
        (Button.DOWN, True), (Button.DOWN, False),
        (Button.LEFT, True), (Button.LEFT, False),
        (Button.RIGHT, True), (Button.RIGHT, False),
    ]


def test_hat_diagonal_emits_two_and_releases():
    src, out = _mk()
    _feed(src, [
        (EV_ABS, ABS_HAT0Y, -1),   # up+right diagonal
        (EV_ABS, ABS_HAT0X, 1),
        (EV_ABS, ABS_HAT0Y, 0),    # right-only
        (EV_ABS, ABS_HAT0X, 0),    # neutral
    ])
    pressed = {e.button for e in out if e.pressed}
    released = {e.button for e in out if not e.pressed}
    assert pressed == {Button.UP, Button.RIGHT}
    assert released == {Button.UP, Button.RIGHT}


def test_btn_dpad_keys_reconcile():
    src, out = _mk(joy_dpad="buttons")
    _feed(src, [
        (EV_KEY, BTN_DPAD_UP, 1),
        (EV_KEY, BTN_DPAD_RIGHT, 1),   # diagonal via keys
        (EV_KEY, BTN_DPAD_UP, 0),      # up released
        (EV_KEY, BTN_DPAD_RIGHT, 0),
    ])
    pressed = {e.button for e in out if e.pressed}
    released = {e.button for e in out if not e.pressed}
    assert pressed == {Button.UP, Button.RIGHT}
    assert released == {Button.UP, Button.RIGHT}


def test_stick_dpad_uses_deadzone():
    src, out = _mk(joy_dpad="stick", joy_buttons={})
    src._cfg = _cfg(joy_dpad="stick", joy_deadzone=0.3)
    _feed(src, [
        (EV_ABS, ABS_X, 4000),    # 4000/32768 ≈ 0.12 — inside deadzone
        (EV_ABS, ABS_X, 20000),   # ≈ 0.61 — beyond deadzone
        (EV_ABS, ABS_X, 0),
    ])
    seq = [(e.button, e.pressed) for e in out]
    assert seq == [(Button.RIGHT, True), (Button.RIGHT, False)]


# --------------------------------------------------------------------------- #
# [joystick] config parsing
# --------------------------------------------------------------------------- #
def test_config_parses_numeric_button_map():
    p = _tmp_config(
        '[joystick]\n'
        'enabled = false\n'
        'devnode = "/dev/input/event9"\n'
        'dpad = "hat0"\n'
        'deadzone = 0.2\n'
        '304 = "A"\n'
        '305 = "B"\n'
    )
    cfg = load_button_config(p)
    assert cfg.joy_enabled is False
    assert cfg.joy_devnode == "/dev/input/event9"
    assert cfg.joy_dpad == "hat0"
    assert cfg.joy_deadzone == 0.2
    assert cfg.joy_buttons.get(304) is Button.A
    assert cfg.joy_buttons.get(305) is Button.B


def test_config_reserved_keys_not_treated_as_buttons():
    p = _tmp_config(
        '[joystick]\n'
        'enabled   = true\n'
        'dpad      = "both"\n'
        'deadzone  = 0.1\n'
        'devnode   = ""\n'
    )
    cfg = load_button_config(p)
    assert cfg.joy_buttons == {}
    assert cfg.joy_dpad == "both"


def test_config_bad_button_value_ignored():
    p = _tmp_config('[joystick]\n304 = "NOT_A_BUTTON"\n')
    cfg = load_button_config(p)
    assert cfg.joy_buttons == {}


def test_toml_value_formatting():
    assert _fmt(True) == "true"
    assert _fmt(0.2) == "0.2"
    assert _fmt("A") == '"A"'
    assert _fmt("BTN_SOUTH") == '"BTN_SOUTH"'


# --------------------------------------------------------------------------- #
def _main() -> int:
    import traceback

    fails = 0
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception:
            fails += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{fails}/{len(tests)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_main())