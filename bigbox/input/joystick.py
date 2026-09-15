"""Native HID-joystick / gamepad input source for the uConsole.

The ClockworkPi uConsole controller registers its inputs under two
architectures depending on the rear PD2 switch position:

  * keyboard mode (default) — the D-pad arrives as arrow keys, A/B/X/Y
    as ``j/k/u/i``, Start/Select as Enter/Space; bigbox.input.keyboard
    maps those.
  * joystick mode — the gamepad area registers as a USB-HID joystick:
    the D-pad is a hat (ABS_HATx) or BTN_DPAD_* keys, the face buttons
    are gamepad BTN_* codes and Select/Start are the joystick's. The
    trackball + mouse clicks stay a separate HID mouse (handled as
    pygame mouse events) and the QWERTY matrix stays a USB keyboard.

This module reads the joystick device directly over evdev in a
background thread (the same pattern as ``bigbox.input.gpio``) and
translates its events onto the EventBus, so gamepad-mode keys drive
the UI and emulators identically to keyboard-mode. Device discovery is
capability-based and logs what it finds, and every button index / D-pad
flavor is overridable from ``config/buttons.toml [joystick]``.
"""
from __future__ import annotations

import glob
import threading
import time
from typing import TYPE_CHECKING

from bigbox.events import Button, ButtonEvent, EventBus

if TYPE_CHECKING:
    from bigbox.input.config import ButtonConfig

try:
    from evdev import InputDevice, ecodes as e

    HAS_EVDEV = True
except ImportError:  # dev machines without python3-evdev
    HAS_EVDEV = False


# ---------------------------------------------------------------------------
# Defaults — a standard XInput-style layout. Every entry is overridable from
# the [joystick] section of buttons.toml.
# ---------------------------------------------------------------------------
def _default_btnmap() -> dict[int, Button]:
    """evdev BTN_* code → logical Button for a stock / XInput-style pad.

    ``BTN_SOUTH/EAST/NORTH/WEST`` overlap with the classic ``BTN_A/B/X/Y``
    aliases on modern kernels — the dict keys de-duplicate them, so devices
    built against either naming convention map identically.
    """
    return {
        e.BTN_SOUTH: Button.A,  # 0x130  (classic BTN_A)
        e.BTN_EAST: Button.B,   # 0x131  (classic BTN_B)
        e.BTN_NORTH: Button.X,  # 0x133  (classic BTN_X)
        e.BTN_WEST: Button.Y,   # 0x134  (classic BTN_Y)
        e.BTN_TL: Button.LL,    # 0x136  left shoulder
        e.BTN_TR: Button.RR,    # 0x137  right shoulder
        e.BTN_SELECT: Button.SELECT,  # 0x13a
        e.BTN_START: Button.START,    # 0x13b
        e.BTN_DPAD_UP: Button.UP,
        e.BTN_DPAD_DOWN: Button.DOWN,
        e.BTN_DPAD_LEFT: Button.LEFT,
        e.BTN_DPAD_RIGHT: Button.RIGHT,
    }


# Codes that mark an event node as a joystick/gamepad rather than a keyboard,
# mouse, touchpad or special-function device: the classic button block
# (0x120..0x13e) plus the modern BTN_DPAD block.
def _joystick_button_codes() -> set[int]:
    return {
        e.BTN_TRIGGER, e.BTN_THUMB, e.BTN_THUMB2,
        e.BTN_TOP, e.BTN_TOP2, e.BTN_PINKIE, e.BTN_DEAD,
        e.BTN_BASE, e.BTN_BASE2, e.BTN_BASE3, e.BTN_BASE4, e.BTN_BASE5, e.BTN_BASE6,
        e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y, e.BTN_Z,
        e.BTN_TL, e.BTN_TR, e.BTN_TL2, e.BTN_TR2,
        e.BTN_SELECT, e.BTN_START, e.BTN_MODE,
        e.BTN_THUMBL, e.BTN_THUMBR,
        e.BTN_DPAD_UP, e.BTN_DPAD_DOWN, e.BTN_DPAD_LEFT, e.BTN_DPAD_RIGHT,
    }


_HAT_CODES = (e.ABS_HAT0X, e.ABS_HAT0Y, e.ABS_HAT1X, e.ABS_HAT1Y) if HAS_EVDEV else ()
_DPAD_KEY_CODES = (
    (e.BTN_DPAD_UP, e.BTN_DPAD_DOWN, e.BTN_DPAD_LEFT, e.BTN_DPAD_RIGHT)
    if HAS_EVDEV else ()
)
_REPEATABLE = {Button.UP, Button.DOWN, Button.LEFT, Button.RIGHT}
_RESCAN_SECS = 3.0
_STICK_MAX = 32768.0

# evdev event type / code integers, pinned so the runtime event path works
# (and can be unit-tested) even on hosts without python3-evdev. Values are
# fixed by the kernel UAPI; when evdev is present they're taken from it.
EV_KEY = e.EV_KEY if HAS_EVDEV else 0x01
EV_ABS = e.EV_ABS if HAS_EVDEV else 0x03
ABS_X = e.ABS_X if HAS_EVDEV else 0x00
ABS_Y = e.ABS_Y if HAS_EVDEV else 0x01
ABS_HAT0X = e.ABS_HAT0X if HAS_EVDEV else 0x16
ABS_HAT0Y = e.ABS_HAT0Y if HAS_EVDEV else 0x17
ABS_HAT1X = e.ABS_HAT1X if HAS_EVDEV else 0x18
ABS_HAT1Y = e.ABS_HAT1Y if HAS_EVDEV else 0x19


class JoystickInput:
    """evdev joystick → ButtonEvent pusher.

    Started from App._start_input(); best-effort and never raises. If no
    gamepad is present (or evdev/permissions are missing) it quietly logs
    and idles, rescanning for a hot-plug every few seconds.
    """

    def __init__(self, bus: EventBus, cfg: "ButtonConfig") -> None:
        self._bus = bus
        self._cfg = cfg
        # Effective button map: config [joystick] overrides win, defaults
        # underneath them. Absent an explicit [joystick] map the bundled
        # default layout (see _default_btnmap) is used verbatim.
        if HAS_EVDEV:
            self._btnmap: dict[int, Button] = dict(_default_btnmap())
            self._btnmap.update(cfg.joy_buttons)
        else:
            self._btnmap = {}

        self._device: InputDevice | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        # D-pad state, split by source so "buttons" and "hat" device flavors
        # (and mixed reports) all reconcile to a single emitted direction set.
        self._dpad_keys: set[Button] = set()           # held via BTN_DPAD_*
        self._hats: dict[int, tuple[int, int]] = {}    # hat idx → (x, y)
        self._stick: tuple[float, float] = (0.0, 0.0)  # ABS_X / ABS_Y
        self._dpad_pressed: set[Button] = set()        # currently emitted
        self._held_since: dict[Button, float] = {}
        self._repeater: threading.Thread | None = None
        # Cached per-device dpad source set / capability flags.
        self._src_owner: InputDevice | None = None
        self._srcs: frozenset[str] = frozenset()
        self._has: dict[str, bool] = {}

    # ---------- lifecycle ----------
    def start(self) -> None:
        if not HAS_EVDEV:
            print("[input] joystick disabled — python3-evdev not installed")
            return
        self._device = self._discover()
        self._refresh_sources()
        self._repeater = threading.Thread(target=self._repeat_loop, daemon=True)
        self._repeater.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        dev = self._device
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass

    # ---------- device discovery ----------
    def _discover(self) -> InputDevice | None:
        """Pick the joystick device. Prefers an explicit joy_devnode from
        config; otherwise scans /dev/input/event* and favors the node with
        the most gamepad button codes (a USB hub full of dongles won't
        out-rank the controller)."""
        if self._cfg.joy_devnode:
            try:
                dev = InputDevice(self._cfg.joy_devnode)
                if self._is_gamepad(dev):
                    print(f"[input] joystick: using {self._cfg.joy_devnode}")
                    return dev
                print(f"[input] joystick: {self._cfg.joy_devnode} is not a gamepad")
            except Exception as ex:
                print(f"[input] joystick: can't open {self._cfg.joy_devnode}: {ex}")
            return None

        best: InputDevice | None = None
        best_score = 0
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                dev = InputDevice(path)
            except OSError:
                continue
            score = self._score(dev)
            if score and (best is None or score > best_score):
                best = dev
                best_score = score
        if best is not None:
            print(
                "[input] joystick: %s %s (%s, %d gamepad codes)"
                % (best.path, best.name, best.info, best_score)
            )
            self._log_caps(best)
        return best

    @staticmethod
    def _score(dev: InputDevice) -> int:
        caps = dev.capabilities(absinfo=False)
        keys = caps.get(EV_KEY, [])
        score = sum(1 for c in keys if c in _joystick_button_codes())
        hats = [c for c in caps.get(EV_ABS, []) if c in _HAT_CODES]
        if hats:
            score += 4  # hats strongly imply a gamepad
        return score

    @staticmethod
    def _is_gamepad(dev: InputDevice) -> bool:
        return JoystickInput._score(dev) > 0

    def _log_caps(self, dev: InputDevice) -> None:
        try:
            from evdev import categorize
            from evdev import ecodes as ec

            caps = dev.capabilities(absinfo=False)
            codes = [
                c for c in caps.get(EV_KEY, []) if c in _joystick_button_codes()
            ] + [c for c in caps.get(EV_ABS, []) if c in _HAT_CODES]
            names = [ec.KEY.get(c, ec.ABS.get(c, hex(c))) for c in codes]
            print(f"[input] joystick: cap codes: {', '.join(names) or '(dpad via axes only)'}")
        except Exception:
            pass

    # ---------- main read loop (runs in a daemon thread) ----------
    def _run(self) -> None:
        while not self._stop.is_set():
            dev = self._device
            if dev is None:
                if self._stop.wait(_RESCAN_SECS):
                    return
                self._device = self._discover()
                self._refresh_sources()
                continue
            try:
                for ev in dev.read_loop():
                    if self._stop.is_set():
                        return
                    self._handle(ev.type, ev.code, ev.value)
            except OSError:
                print(f"[input] joystick: {dev.path} closed; rescanning")
            except Exception as ex:
                print(f"[input] joystick read error: {ex}")
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
                self._device = None
                self._srcs = frozenset()
            if self._stop.wait(_RESCAN_SECS):
                return

    # ---------- event translation ----------
    def _handle(self, etype: int, code: int, value: int) -> None:
        if etype == EV_KEY:
            self._on_key(code, value)
        elif etype == EV_ABS:
            self._on_abs(code, value)

    def _on_key(self, code: int, value: int) -> None:
        btn = self._btnmap.get(code)
        if btn is None:
            return
        # evdev key values: 1 = press, 0 = release, 2 = kernel-key repeat.
        # Gamepad buttons don't autorepeat, but skip value 2 defensively so a
        # repeated press can't double-fire (our D-pad generates its own repeats).
        if value == 2:
            return
        pressed = value != 0
        # BTN_DPAD_* keys feed the shared D-pad reconciler so they can't
        # double-fire against a hat on devices that report both.
        if btn in _REPEATABLE and code in _DPAD_KEY_CODES:
            if pressed:
                self._dpad_keys.add(btn)
            else:
                self._dpad_keys.discard(btn)
            self._sync_dpad()
            return
        self._emit(btn, pressed)

    def _on_abs(self, code: int, value: int) -> None:
        if code in (ABS_HAT0X, ABS_HAT0Y):
            self._set_hat(0, code, value)
        elif code in (ABS_HAT1X, ABS_HAT1Y):
            self._set_hat(1, code, value)
        elif code in (ABS_X, ABS_Y):
            v = max(-1.0, min(1.0, float(value) / _STICK_MAX))
            x, y = self._stick
            self._stick = (v if code == ABS_X else x, v if code == ABS_Y else y)
            self._sync_dpad()
        # Trigger/other axes intentionally unhandled (the uConsole's zero
        # analog stick reports neutral, and the trackball is a mouse device).

    def _set_hat(self, idx: int, code: int, value: int) -> None:
        x, y = self._hats.get(idx, (0, 0))
        sign = 1 if value > 0 else -1 if value < 0 else 0
        if code in (ABS_HAT0X, ABS_HAT1X):
            self._hats[idx] = (sign, y)
        else:
            self._hats[idx] = (x, sign)
        self._sync_dpad()

    # ---------- D-pad reconciler ----------
    def _refresh_sources(self) -> None:
        dev = self._device
        if dev is None:
            self._srcs = frozenset()
            self._src_owner = None
            return
        self._src_owner = dev
        want = self._cfg.joy_dpad
        try:
            caps = dev.capabilities(absinfo=False)
            abs_axes = set(caps.get(EV_ABS, []))
            keys = set(caps.get(EV_KEY, []))
        except Exception:
            abs_axes, keys = set(), set()
        has = {
            "hat0": ABS_HAT0X in abs_axes and ABS_HAT0Y in abs_axes,
            "hat1": ABS_HAT1X in abs_axes and ABS_HAT1Y in abs_axes,
            "buttons": any(c in keys for c in _DPAD_KEY_CODES),
            "stick": ABS_X in abs_axes and ABS_Y in abs_axes,
        }
        if want == "auto":
            self._srcs = frozenset(
                [k for k, present in has.items() if present][:1]
            )
        elif want == "both":
            self._srcs = frozenset(k for k, present in has.items() if present)
        elif want in has:
            self._srcs = frozenset([want]) if has[want] else frozenset()
        else:
            self._srcs = frozenset()
        self._has = has

    def _current_dpad(self) -> set[Button]:
        if self._device is not self._src_owner:
            self._refresh_sources()
        out: set[Button] = set()
        srcs = self._srcs
        if "buttons" in srcs:
            out |= self._dpad_keys
        if "hat0" in srcs or "hat1" in srcs:
            for idx in (0, 1):
                if f"hat{idx}" not in srcs:
                    continue
                x, y = self._hats.get(idx, (0, 0))
                if x == -1:
                    out.add(Button.LEFT)
                elif x == 1:
                    out.add(Button.RIGHT)
                if y == -1:
                    out.add(Button.UP)
                elif y == 1:
                    out.add(Button.DOWN)
        if "stick" in srcs:
            x, y = self._stick
            dz = self._cfg.joy_deadzone
            if x <= -dz:
                out.add(Button.LEFT)
            elif x >= dz:
                out.add(Button.RIGHT)
            if y <= -dz:
                out.add(Button.UP)
            elif y >= dz:
                out.add(Button.DOWN)
        return out

    def _sync_dpad(self) -> None:
        cur = self._current_dpad()
        for b in cur - self._dpad_pressed:
            self._dpad_pressed.add(b)
            self._emit(b, True)
        for b in self._dpad_pressed - cur:
            self._dpad_pressed.discard(b)
            self._emit(b, False)

    # ---------- emit / repeats ----------
    def _emit(self, b: Button, pressed: bool) -> None:
        if pressed:
            self._held_since.setdefault(b, time.monotonic())
        else:
            self._held_since.pop(b, None)
        self._bus.put(ButtonEvent(b, pressed=pressed))

    def _repeat_loop(self) -> None:
        delay = self._cfg.repeat_delay_ms / 1000.0
        interval = self._cfg.repeat_interval_ms / 1000.0
        last_fire: dict[Button, float] = {}
        while not self._stop.is_set():
            now = time.monotonic()
            for btn, t0 in list(self._held_since.items()):
                if btn not in _REPEATABLE:
                    continue
                if now - t0 < delay:
                    continue
                if now - last_fire.get(btn, 0.0) >= interval:
                    last_fire[btn] = now
                    self._bus.put(ButtonEvent(btn, pressed=True, repeat=True))
            time.sleep(0.01)