"""Pure helpers (no Home Assistant import) so they can be unit tested."""
from __future__ import annotations

import math
from typing import Any, Iterable


def sibling(entries: Iterable[dict[str, Any]], entity_id: str, domain: str) -> str | None:
    """The entity of `domain` that belongs to the same device (or config entry) as `entity_id`.

    `entries` are entity registry rows as dicts with entity_id, device_id, config_entry_id, platform.
    """
    rows = list(entries)
    me = next((r for r in rows if r["entity_id"] == entity_id), None)
    if me is None:
        return None
    for key in ("device_id", "config_entry_id"):
        if not me.get(key):
            continue
        for r in rows:
            if r["entity_id"].startswith(domain + ".") and r.get(key) == me[key] and r.get("platform") == me.get("platform"):
                return r["entity_id"]
    return None


def normalise_app(name: str) -> str:
    """Apple TV app names may contain non-breaking spaces; compare them with plain ones."""
    return " ".join(str(name).replace(" ", " ").split())


def keyboard_sensor(entries: Iterable[dict[str, Any]], entity_id: str) -> str | None:
    """The core integration's "Keyboard focus" binary sensor of the same device, if there is one."""
    rows = list(entries)
    me = next((r for r in rows if r["entity_id"] == entity_id), None)
    if me is None:
        return None
    for r in rows:
        if r["entity_id"].startswith("binary_sensor.") and r.get("platform") == me.get("platform") and (
                "keyboard_focus" in r["entity_id"] or r.get("translation_key") == "keyboard_focus") and (
                (me.get("device_id") and r.get("device_id") == me["device_id"]) or r.get("config_entry_id") == me.get("config_entry_id")):
            return r["entity_id"]
    return None


TOUCH_MODES = {"press": 1, "move": 2, "hold": 3, "release": 4}   # the Companion touch phases. Apple's Remote app sends 2 for every move of the finger
#                                                              (captured); pyatv's TouchAction only knows 1, 3 and 4
CARD_TOUCH = ("press", "hold", "release")   # what the card may send


def clamp_coord(value: Any) -> int:
    """Touch coordinates are in the range 0..1000."""
    try:
        return max(0, min(1000, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def clamp_virtual(value: Any, most: int | None = None) -> int:
    """The finger position of a running touch: the surface coordinate plus everything a long drag has added to it."""
    most = TOUCH_RANGE if most is None else most
    try:
        return max(-most, min(most, int(round(float(value)))))
    except (TypeError, ValueError):
        return TOUCH_CENTRE


TOUCH_TICK = 0.016   # seconds between touch events, the same cadence pyatv uses for its own swipes
# The touch stream copies what Apple's own Remote app sends (captured with pyatv's proxy): the whole 0..1000 surface, the finger's real speed, and
# at the edge a lift and a new press about 400 back, at once (in the capture a touch that ran into 1000 was pressed again at 596 and moved on).
TOUCH_MIN, TOUCH_MAX = 0, 1000
TOUCH_EDGE = {1: 600, -1: 400}   # where a touch that reached TOUCH_MAX / TOUCH_MIN is pressed again


def clamp_inner(value: Any, lo: int = TOUCH_MIN, hi: int = TOUCH_MAX) -> int:
    """A coordinate inside the part of the surface that is not the click ring."""
    return max(lo, min(hi, clamp_coord(value)))


TOUCH_CENTRE = 500
TOUCH_RANGE = 2000000   # the card reports a virtual position that may run far past the 0..1000 surface (long drags; a fast circle asks thousands of units per turn, 20000 cut it off after a few turns)
TOUCH_IDLE_RELEASE = 2.0   # a touch that gets no update for this long is released (card closed, connection lost)


TOUCH_SPEED = 100.0   # the most a touch moves per 16 ms step. A fast swipe of Apple's Remote app runs at 50 to 90 (captured). Faster is worse, not better:
#                       measured three times on a real Apple TV, a touch that outruns a real finger scrubs LESS and with more delay
TOUCH_AHEAD = 2200   # the stream never has more than this left to do while the finger moves ...
TOUCH_COAST = 600   # ... and this after the finger lifted (plus the glide): what a drag asks beyond that is dropped, so it does not trail on


TOUCH_GLIDE = 0.2   # after the finger lifts the touch glides on and slows down, a fifth of what is left per step ...
TOUCH_GLIDE_FROM = 15.0   # ... when it was still moving at least this fast (units per step) ...
TOUCH_GLIDE_LENGTH = 4.0   # ... over this many times its last speed. The Remote app does this: in the capture a swipe let go at about 80 per step ran on
#                            for another 384 units in ever smaller steps (63, 49, 38, 30 ...). It is a good part of how far a flick gets


def touch_step(sent: float, target: float, finishing: bool = False) -> float:
    """One 16 ms step of the touch stream. While the finger is down: go to where it is, at most TOUCH_SPEED per step, no smoothing (the Remote app
    sends the finger's real positions too); a finger faster than that is followed as fast as a real swipe goes. After it lifted: glide to the end point, slowing down."""
    delta = target - sent
    if abs(delta) <= (8.0 if finishing else 1.0):   # the glide ends when it has all but stopped: its last crawl only delays the lift
        return target
    return sent + max(-TOUCH_SPEED, min(TOUCH_SPEED, delta * TOUCH_GLIDE if finishing else delta))


def glide(speed: float) -> float:
    """How far a touch runs on after the finger lifted while moving `speed` units per step."""
    return speed * TOUCH_GLIDE_LENGTH if abs(speed) >= TOUCH_GLIDE_FROM else 0.0


def limit_ahead(sent: float, wanted: float, shift: float, most: float) -> tuple[float, float]:
    """The target for a position the card reports: at most `most` away from where the stream is. What is cut off is remembered in `shift`, so the
    next positions are read from there (a finger that turns around turns the scrub around at once, not after the cut-off distance)."""
    target = wanted - shift
    if target > sent + most:
        shift += target - (sent + most)
        target = sent + most
    elif target < sent - most:
        shift += target - (sent - most)
        target = sent - most
    return target, shift


# Circular scrubbing: a finger that goes round on the rim of the touch surface turns the jog ring of Apple's own video player (the ring of the Siri
# Remote). Measured on a real Apple TV: press at the top of the rim, rest, one clockwise turn of radius 440 = the ring shows and the video scrubs
# forward smoothly. Only Apple's player knows the ring (the Apple TV app; YouTube just follows the sideways part of the circle, Netflix does nothing).
TOUCH_AXES = ("x", "y", "ring", "sweep")   # what a touch moves along: sideways, up / down, round the rim, or sideways in calm long swipes
# "sweep" is for apps that ignore short quick swipes (Netflix, measured: a swipe across the surface in 0.6 s = about 2 min, the same in 0.15 s = 1 min,
# three short quick swipes = nothing, two slow ones 0.1 s apart = both count): never faster than TOUCH_SWEEP_SPEED per step, swipes from edge to edge
# (TOUCH_SWEEP_EDGE) and TOUCH_SWEEP_GAP seconds without a touch between two swipes.
TOUCH_SWEEP_PACE = (0.7, 2.9)   # the card's pace for a sweep (its circle speed setting) is kept within these: 25 .. 100 units per step (B: 100 = 0.15 s per swipe, still counted)
TOUCH_SWEEP_SPEED = 35.0   # 0.43 s per swipe (A: 0.6 s = 2 min, B: 0.15 s = 1 min: still counted)
TOUCH_SWEEP_EDGE = (50, 950)
TOUCH_SWEEP_GAP = 0.03   # F: two fast swipes 0.03 s apart both count (C: straight after each other = nothing; E: a swipe in 0.08 s = nothing)
TOUCH_SWEEP_AHEAD = 400   # a sweep runs at most this far behind the finger (about 0.25 s; more queued up and scrubbed on after you stopped); none after the finger lifts
TOUCH_RING_RADIUS = 440   # units from the centre of the surface
TOUCH_RING_REST = 0.25   # seconds the touch rests on the rim before it starts to turn (the finger's turning in that time is not made up for)
TOUCH_RING_RANGE = 2000000   # the card reports the distance along the rim; it may go round many times


def ring_point(arc: float) -> tuple[int, int]:
    """The place on the rim after `arc` units along it. 0 = the right-hand side; a growing arc goes clockwise as seen on the pad (y points down)."""
    angle = arc / TOUCH_RING_RADIUS
    return clamp_coord(TOUCH_CENTRE + TOUCH_RING_RADIUS * math.cos(angle)), clamp_coord(TOUCH_CENTRE + TOUCH_RING_RADIUS * math.sin(angle))


HOLD_KEYS = {"up": 1, "down": 2, "left": 3, "right": 4}   # pyatv Companion HidCommand values
KEY_HOLD_IDLE = 2.5   # a held key that gets no keep-alive for this long is released (card closed, connection lost)
