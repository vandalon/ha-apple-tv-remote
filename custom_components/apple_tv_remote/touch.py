"""A touch gesture towards the Apple TV, sent as a smooth 60 Hz stream (no Home Assistant imports, so it can be unit tested)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from .logic import TOUCH_SWEEP_PACE, TOUCH_SWEEP_AHEAD, TOUCH_SWEEP_EDGE, TOUCH_SWEEP_GAP, TOUCH_SWEEP_SPEED, HOLD_KEYS, KEY_HOLD_IDLE, TOUCH_AHEAD, TOUCH_COAST, TOUCH_EDGE, TOUCH_IDLE_RELEASE, TOUCH_MAX, TOUCH_MIN, TOUCH_MODES, TOUCH_RING_REST, TOUCH_TICK, clamp_coord, clamp_inner, glide, limit_ahead, ring_point, touch_step

_LOGGER = logging.getLogger(__name__)


class Wide(int):
    """A touch coordinate that is always sent as a 2-byte number, like Apple's Remote app does.

    pyatv's encoder writes an int as small as it can (it honours a `size` attribute), so a coordinate from 128 to 255 went out as one byte. The
    Apple TV reads that byte as a negative number: every touch that passed through 128..255 made the scrub jump the wrong way first. Measured on a
    real Apple TV: the same swipe is clean at 300..955 and goes back and forth at 200..855; the Remote app's own frames always use 2 bytes."""

    size = 2


class Phase:
    """A touch phase pyatv has no name for (it only reads `.value`)."""

    def __init__(self, value: int):
        self.value = value


def pyatv_mode(name: str):
    from pyatv.const import TouchAction
    try:
        return TouchAction(TOUCH_MODES[name])
    except ValueError:
        return Phase(TOUCH_MODES[name])


async def replay(atv, events, mode: Callable[[str], Any] = pyatv_mode) -> int:
    """Send a scripted touch exactly as given, without easing: `events` = [[ms since the previous event, action, x, y], ...].

    A diagnosis tool (websocket apple_tv_remote/touch_test): any touch stream can be tried on the real Apple TV and compared with what
    pyatv's own swipe does, without changing code. Each event is sent at its planned time (no drift from the sends before it)."""
    due = time.monotonic()
    for wait_ms, action, x, y in events:
        due += max(0.0, min(5000.0, float(wait_ms))) / 1000
        delay = due - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        _LOGGER.debug("replay %s x=%s y=%s t=%.3f", action, x, y, time.monotonic())
        await atv.touch.action(Wide(x), Wide(y), mode(action))
    return len(events)


class TouchSession:
    """Press, then a 16 ms loop that moves the sent position towards the latest finger position, then release.

    The card only tells where the finger is (a few times a second, over the network). Sending those jumps straight on made the Apple TV
    scrub unevenly: it derives the scrub speed from the size and timing of the touch moves. pyatv sends its own swipes as small steps every
    16 ms, so this does the same.

    Positions are virtual: they start at the pressed x and may run far outside 0..1000. A touch stays off the rim of the surface (logic.TOUCH_MIN / TOUCH_MAX);
    when it gets there it is lifted and pressed again further back, at once, and moves on (see logic.TOUCH_EDGE).

    With axis "ring" the touch goes round the rim of the surface instead (the jog ring of Apple's video player): x is then the distance along the rim
    (see logic.ring_point), which has no edge, and the touch rests a moment before it starts to turn.
    """

    def __init__(self, spawn: Callable[[Any, str], Any], atv, entity_id: str, x: int, y: int, registry: dict, mode: Callable[[str], Any] = pyatv_mode, axis: str = "x", pace: float = 1.0):
        self.spawn, self.atv, self.entity_id, self.registry, self.mode, self.axis = spawn, atv, entity_id, registry, mode, axis
        self.ring = axis == "ring"
        self.sweep = axis == "sweep"
        self.sweep_speed = TOUCH_SWEEP_SPEED * max(TOUCH_SWEEP_PACE[0], min(TOUCH_SWEEP_PACE[1], float(pace or 1.0)))   # sweep: units per step
        along, across = (x, y) if axis != "y" else (y, x)   # a touch moves along one axis (sideways, or up / down with axis "y"); the other coordinate stays put
        self.across = clamp_inner(across, 300, 700)   # well away from the rim
        self.sent = self.target = float(along)
        self.last_int = int(along)
        self.origin, self.base = float(along), clamp_inner(along)   # virtual position where the running touch was pressed, and its place on the Apple TV
        self.shift = 0.0   # distance a fast drag asked for and did not get (see logic.limit_ahead)
        self.speed = 0.0   # how fast the touch is moving, units per step (for the glide after the finger lifts)
        self.finishing = False
        self.error: Exception | None = None
        self.last_update = time.monotonic()
        self.task: Any = None

    def _action(self, name: str, v: int):
        if self.ring:
            x, y = (Wide(c) for c in ring_point(v))
        else:
            v = Wide(clamp_coord(self.base + v - self.origin))   # virtual -> the Apple TV's touch surface
            x, y = (Wide(self.across), v) if self.axis == "y" else (v, Wide(self.across))
        _LOGGER.debug("touch %s x=%s y=%s target=%s t=%.3f", name, x, y, int(self.target), time.monotonic())   # sent to the Apple TV (debug log: custom_components.apple_tv_remote)
        return self.atv.touch.action(x, y, self.mode(name))

    async def start(self) -> None:
        await self._action("press", int(self.sent))   # a failure (not supported, not connected ...) shows up right here
        self.task = self.spawn(self._run(), "apple_tv_remote touch")

    def move(self, x: int) -> None:
        self.target, self.shift = limit_ahead(self.sent, float(x), self.shift, TOUCH_SWEEP_AHEAD * self.sweep_speed / TOUCH_SWEEP_SPEED if self.sweep else TOUCH_AHEAD)
        self.last_update = time.monotonic()

    async def finish(self, x: int) -> None:
        self.target, self.shift = (self.sent, 0.0) if self.sweep else limit_ahead(self.sent, float(x), self.shift, TOUCH_COAST)   # a sweep stops where it is
        if not self.ring and not self.sweep and (self.target - self.sent) * self.speed >= 0:   # still going the way it was moving: glide on, like the Remote app
            self.target += glide(self.speed)
        self.finishing = True
        if self.task:
            await self.task

    async def stop(self) -> None:
        """Let go right where the touch is now (a new touch starts while this one is still catching up with a fast drag)."""
        self.speed = 0.0   # no gliding: the new touch takes over
        await self.finish(int(round(self.sent + self.shift)))

    async def _run(self) -> None:
        try:
            if self.ring:   # rest on the rim first, then turn from where the finger is by then
                await asyncio.sleep(TOUCH_RING_REST)
                self.shift += self.target - self.sent
                self.target = self.sent
            while True:
                was = self.sent
                self.sent = touch_step(self.sent, self.target, self.finishing)
                if self.sweep:   # calm: never faster than a slow swipe
                    self.sent = max(was - self.sweep_speed, min(was + self.sweep_speed, self.sent))
                edge_lo, edge_hi = TOUCH_SWEEP_EDGE if self.sweep else (TOUCH_MIN, TOUCH_MAX)
                lo, hi = (float("-inf"), float("inf")) if self.ring else (self.origin - (self.base - edge_lo), self.origin + (edge_hi - self.base))   # where this touch reaches the rim
                self.sent = max(lo, min(hi, self.sent))
                if self.finishing and self.sent == self.target:
                    break
                if not self.finishing and time.monotonic() - self.last_update > TOUCH_IDLE_RELEASE:
                    break   # nobody is updating any more: let go of the touch
                xi = int(round(self.sent))
                if xi != self.last_int:
                    await self._action("move", xi)
                    self.last_int = xi
                if not self.finishing:
                    self.speed = 0.5 * self.speed + 0.5 * (self.sent - was)
                await asyncio.sleep(TOUCH_TICK)
                if (self.sent >= hi and self.target > hi) or (self.sent <= lo and self.target < lo):   # at the edge and the finger goes on: lift, press again, move on
                    await self._action("release", xi)
                    fwd = self.sent >= hi
                    if self.sweep:   # the next swipe starts at the other edge, after a short pause
                        self.origin, self.base = self.sent, TOUCH_SWEEP_EDGE[0 if fwd else 1]
                        await asyncio.sleep(TOUCH_SWEEP_GAP)
                        self.last_update = time.monotonic()
                    else:
                        self.origin, self.base = self.sent, TOUCH_EDGE[1 if fwd else -1]
                    await self._action("press", xi)
                    await asyncio.sleep(TOUCH_TICK)
            await self._action("release", int(round(self.sent)))
        except Exception as err:   # reported to the card with its next update
            self.error = err
            _LOGGER.debug("touch stream stopped: %s", err)
        finally:
            if self.registry.get(self.entity_id) is self:
                self.registry.pop(self.entity_id, None)


def companion_api(atv):
    """The Companion link's own API (commands pyatv's public API does not have); raises when there is no Companion link."""
    from pyatv.const import Protocol
    remote = atv.remote_control.get(Protocol.Companion)
    if remote is None:
        raise RuntimeError("no Companion link")
    return remote.api


def companion_key(atv) -> Callable[[str, bool], Any]:
    """Key down / key up towards the Apple TV. pyatv's public API only has whole presses (a 'hold' there is a fixed second), so this uses the
    Companion link's own key command; raises when there is no Companion link."""
    from pyatv.const import Protocol
    from pyatv.protocols.companion.api import HidCommand
    remote = atv.remote_control.get(Protocol.Companion)
    if remote is None:
        raise RuntimeError("no Companion link")
    return lambda name, down: remote.api.hid_command(down, HidCommand(HOLD_KEYS[name]))


class KeyHold:
    """A key that is held down (fast forward / rewind, like holding the ring of the Siri Remote) until the card lets go.

    The card repeats 'down' as a keep-alive; without one for KEY_HOLD_IDLE seconds the key is released, so it can never stay stuck."""

    def __init__(self, spawn: Callable[[Any, str], Any], send: Callable[[str, bool], Any], entity_id: str, key: str, registry: dict):
        self.spawn, self.send, self.entity_id, self.key, self.registry = spawn, send, entity_id, key, registry
        self.last = time.monotonic()
        self.done = False
        self.task: Any = None

    async def start(self) -> None:
        _LOGGER.debug("key %s down", self.key)
        await self.send(self.key, True)
        self.task = self.spawn(self._watch(), "apple_tv_remote key hold")

    def keep(self) -> None:
        self.last = time.monotonic()

    async def release(self) -> None:
        if self.done:
            return
        self.done = True
        if self.registry.get(self.entity_id) is self:
            self.registry.pop(self.entity_id, None)
        _LOGGER.debug("key %s up", self.key)
        await self.send(self.key, False)

    async def _watch(self) -> None:
        while not self.done:
            await asyncio.sleep(0.25)
            if not self.done and time.monotonic() - self.last > KEY_HOLD_IDLE:
                try:
                    await self.release()
                except Exception as err:
                    _LOGGER.debug("key release failed: %s", err)
