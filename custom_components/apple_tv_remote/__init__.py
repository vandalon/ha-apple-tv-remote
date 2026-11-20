"""Apple TV Remote: the `custom:atv-touchpad` card plus a small websocket helper.

The card itself only uses services of the core Apple TV integration (remote.send_command, media_player.select_source,
apple_tv.set_keyboard_text). This integration serves the card script and answers one question the frontend cannot:
which config entry (and remote entity) belongs to an Apple TV media player, so nobody has to type ids.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .logic import CARD_TOUCH, HOLD_KEYS, TOUCH_AXES, TOUCH_MODES, TOUCH_RING_RANGE, clamp_coord, clamp_virtual, keyboard_sensor, sibling
from .icons import ICON_DIR, ICON_URL, load_checked, load_index, lookup_icons, refresh_icons, save_checked, stale, store_icons
from .raw import raw_session
from .touch import KeyHold, TouchSession, companion_api, companion_key, replay

_LOGGER = logging.getLogger(__name__)

DOMAIN = "apple_tv_remote"
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Any(None, dict)}, extra=vol.ALLOW_EXTRA)
JS_URL = f"/{DOMAIN}/atv-touchpad.js"
TOUCH_STOP_WAIT = 2.0   # s a new touch waits for the previous one to let go


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Legacy YAML (`apple_tv_remote:`): import it as a config entry once."""
    if DOMAIN in config and not hass.config_entries.async_entries(DOMAIN):
        hass.async_create_task(hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}, data={}))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True   # the card script and the websocket command stay until the next restart


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if hass.data.get(DOMAIN):
        return True
    hass.data[DOMAIN] = True

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/info", vol.Required("entity_id"): cv.entity_id})
    @callback
    def ws_info(hass_, connection, msg):
        """Config entry id and remote entity of an Apple TV entity (media player or remote)."""
        reg = er.async_get(hass_)
        rows = [{"entity_id": e.entity_id, "device_id": e.device_id, "config_entry_id": e.config_entry_id, "platform": e.platform,
                 "translation_key": e.translation_key}
                for e in reg.entities.values() if e.platform == "apple_tv"]
        me = next((r for r in rows if r["entity_id"] == msg["entity_id"]), None)
        if me is None:
            connection.send_error(msg["id"], "not_apple_tv", "This entity does not belong to the Apple TV integration")
            return
        connection.send_result(msg["id"], {
            "config_entry_id": me["config_entry_id"],
            "remote": msg["entity_id"] if msg["entity_id"].startswith("remote.") else sibling(rows, msg["entity_id"], "remote"),
            "keyboard_sensor": keyboard_sensor(rows, msg["entity_id"]),
            "touch": _touch_ok(_atv(hass_, msg["entity_id"])),
            "media_player": msg["entity_id"] if msg["entity_id"].startswith("media_player.") else sibling(rows, msg["entity_id"], "media_player"),
        })

    def _atv(hass_, entity_id):
        """The pyatv connection of the core Apple TV integration that owns `entity_id` (None when it is not connected)."""
        reg = er.async_get(hass_).async_get(entity_id)
        entry = hass_.config_entries.async_get_entry(reg.config_entry_id) if reg and reg.platform == "apple_tv" and reg.config_entry_id else None
        return getattr(getattr(entry, "runtime_data", None), "atv", None)

    reload_at: dict[str, float] = {}   # last reconnect reload, per core config entry

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/reconnect", vol.Required("entity_id"): cv.entity_id})
    @websocket_api.async_response
    async def ws_reconnect(hass_, connection, msg):
        """The core Apple TV integration can stay "not connected" (e.g. the Apple TV slept through a Home Assistant restart): then every
        command fails, turn_on included. When that is the case, reload its config entry (at most once every 30 s) so it connects again."""
        reg = er.async_get(hass_).async_get(msg["entity_id"])
        if not reg or reg.platform != "apple_tv" or not reg.config_entry_id:
            connection.send_error(msg["id"], "not_apple_tv", "This entity does not belong to the Apple TV integration")
            return
        if _atv(hass_, msg["entity_id"]) is not None:
            connection.send_result(msg["id"], {"connected": True, "reloaded": False})
            return
        eid, now = reg.config_entry_id, time.monotonic()
        if now - reload_at.get(eid, -1e9) < 30:
            connection.send_result(msg["id"], {"connected": False, "reloaded": False})
            return
        reload_at[eid] = now
        _LOGGER.info("Apple TV %s is not connected: reloading its config entry", msg["entity_id"])
        await hass_.config_entries.async_reload(eid)
        for _ in range(20):   # up to ~10 s for the connection to come up
            if _atv(hass_, msg["entity_id"]) is not None:
                break
            await asyncio.sleep(0.5)
        connection.send_result(msg["id"], {"connected": _atv(hass_, msg["entity_id"]) is not None, "reloaded": True})

    muted_at: dict[str, float] = {}   # volume before mute, per Apple TV
    sessions: dict[str, TouchSession] = {}   # one running touch per Apple TV

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/touch", vol.Required("entity_id"): cv.entity_id,
        vol.Required("action"): vol.In(list(CARD_TOUCH)), vol.Required("x"): vol.Coerce(float), vol.Required("y"): vol.Coerce(float),
        vol.Optional("axis", default="x"): vol.In(list(TOUCH_AXES)), vol.Optional("pace", default=1.0): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10))})
    @websocket_api.async_response
    async def ws_touch(hass_, connection, msg):
        """Touch like the Siri Remote: press, hold (= move to x) and release. The card only sends where the finger is (a few times a second);
        a session here sends the smoothed 60 Hz stream to the Apple TV, which is what makes the scrubbing smooth (like pyatv's own swipe)."""
        eid, action = msg["entity_id"], msg["action"]
        atv = _atv(hass_, eid)
        if atv is None:
            connection.send_error(msg["id"], "not_connected", "The Apple TV is not connected")
            return
        axis = msg["axis"]   # the coordinate that moves; after the press it may run past the surface (a long drag)
        x, y = clamp_coord(msg["x"]), clamp_coord(msg["y"])
        ring = axis == "ring"   # round the rim: x is the distance along it, y is not used
        along = clamp_virtual(msg["x"], TOUCH_RING_RANGE) if ring or axis == "sweep" else clamp_virtual(msg["y"] if axis == "y" else msg["x"])   # ring and sweep (a circle that keeps going) may run far
        _LOGGER.debug("card %s %s=%s x=%s y=%s t=%.3f", action, axis, along, x, y, time.monotonic())   # what the card sent (debug log)
        try:
            if action == "press":
                old = sessions.get(eid)   # also a released touch that is still catching up: two streams at once would make the Apple TV jump
                if old:   # at most TOUCH_STOP_WAIT s: on a connection that went away (profile switch, reconnect) letting go can hang, and every new touch waited for it
                    try:
                        await asyncio.wait_for(old.stop(), TOUCH_STOP_WAIT)
                    except Exception:   # noqa: BLE001 - the old touch is gone either way
                        if old.task:
                            old.task.cancel()
                    sessions.pop(eid, None)
                sess = sessions[eid] = TouchSession(hass_.async_create_background_task, atv, eid, along if ring else x, y, sessions, axis=axis, pace=msg["pace"])
                await sess.start()
            else:
                sess = sessions.get(eid)
                if sess is None:
                    raise RuntimeError("no touch in progress")
                if sess.error:
                    raise sess.error
                if action == "hold":
                    sess.move(along)
                else:
                    await sess.finish(along)   # stays registered until it has let go (a new press waits for that)
        except Exception as err:   # NotSupportedError (no Companion link), a lost connection, an older pyatv ...
            sessions.pop(eid, None)
            connection.send_error(msg["id"], "not_supported" if type(err).__name__ == "NotSupportedError" else "failed", str(err) or type(err).__name__)
            return
        connection.send_result(msg["id"], {})

    holds: dict[str, KeyHold] = {}   # one held key per Apple TV

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/key", vol.Required("entity_id"): cv.entity_id,
        vol.Required("key"): vol.In(list(HOLD_KEYS)), vol.Required("down"): cv.boolean})
    @websocket_api.async_response
    async def ws_key(hass_, connection, msg):
        """Hold an arrow key down (down: true, repeated as a keep-alive) and let it go (down: false): fast forward / rewind while a finger stays on the pad."""
        eid = msg["entity_id"]
        atv = _atv(hass_, eid)
        if atv is None:
            connection.send_error(msg["id"], "not_connected", "The Apple TV is not connected")
            return
        try:
            cur = holds.get(eid)
            if msg["down"]:
                if cur and cur.key == msg["key"]:
                    cur.keep()
                else:
                    if cur:
                        await cur.release()
                    cur = holds[eid] = KeyHold(hass_.async_create_background_task, companion_key(atv), eid, msg["key"], holds)
                    await cur.start()
            elif cur:
                await cur.release()
        except Exception as err:
            holds.pop(eid, None)
            connection.send_error(msg["id"], "failed", str(err) or type(err).__name__)
            return
        connection.send_result(msg["id"], {})

    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/player", vol.Required("entity_id"): cv.entity_id,
        vol.Required("action"): vol.In(["skip", "captions", "mute"]), vol.Optional("seconds"): vol.All(vol.Coerce(float), vol.Range(min=-600, max=600)),
        vol.Optional("value"): vol.All(vol.Coerce(int), vol.Range(min=0, max=9))})
    @websocket_api.async_response
    async def ws_player(hass_, connection, msg):
        """The player buttons of Apple's Remote app. skip: jump `seconds` (negative = back) in the video on screen.
        captions: read the subtitle setting (no value) or set it (value); answers {"value": the setting before}.
        mute: the Apple TV has no mute key: volume to 0 (the level before is remembered), or back to that level when it is 0; answers {"muted": bool}."""
        atv = _atv(hass_, msg["entity_id"])
        if atv is None:
            connection.send_error(msg["id"], "not_connected", "The Apple TV is not connected")
            return
        try:
            if msg["action"] == "skip":
                sec = msg.get("seconds", 10.0)
                await (atv.remote_control.skip_forward(sec) if sec >= 0 else atv.remote_control.skip_backward(-sec))
                connection.send_result(msg["id"], {})
                return
            from pyatv.protocols.companion.api import MediaControlCommand
            api = companion_api(atv)
            if msg["action"] == "mute":
                level = float((await api.mediacontrol_command(MediaControlCommand.GetVolume)).get("_c", {}).get("_vol", 0))
                eid = msg["entity_id"]
                if level > 0:
                    muted_at[eid] = level
                    await api.mediacontrol_command(MediaControlCommand.SetVolume, {"_vol": 0.0})
                else:
                    await api.mediacontrol_command(MediaControlCommand.SetVolume, {"_vol": muted_at.pop(eid, 0.3)})
                _LOGGER.debug("mute: volume was %s", level)
                connection.send_result(msg["id"], {"muted": level > 0})
                return
            before = (await api.mediacontrol_command(MediaControlCommand.GetCaptionSettings)).get("_c", {}).get("_mcs")
            if "value" in msg:
                await api.mediacontrol_command(MediaControlCommand.SetCaptionSettings, {"_mcs": msg["value"]})
            _LOGGER.debug("captions %s -> %s", before, msg.get("value"))
        except Exception as err:
            connection.send_error(msg["id"], "failed", str(err) or type(err).__name__)
            return
        connection.send_result(msg["id"], {"value": before})

    icon_cache: dict[str, str | None] = {}   # bundle ID -> icon URL at Apple (None = none), for this Home Assistant run
    icon_dir = hass.config.path(ICON_DIR)   # local copies of the icons (outside any repository)
    await hass.async_add_executor_job(lambda: os.makedirs(icon_dir, exist_ok=True))
    icon_index = await hass.async_add_executor_job(load_index, icon_dir)   # bundle ID -> local file (None = none), kept across restarts
    icon_checked = await hass.async_add_executor_job(load_checked, icon_dir)   # bundle ID -> when it was last looked up at Apple
    icon_refreshing: set[str] = set()

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/app_icons", vol.Required("entity_id"): cv.entity_id, vol.Optional("apple", default=False): cv.boolean})
    @websocket_api.async_response
    async def ws_app_icons(hass_, connection, msg):
        """The real icon of each App Store app on the Apple TV: {"icons": {app name: url}, "ids": {app name: bundle ID}}."""
        atv = _atv(hass_, msg["entity_id"])
        if atv is None:
            connection.send_error(msg["id"], "not_connected", "The Apple TV is not connected")
            return
        try:
            apps = await atv.apps.app_list()
        except Exception as err:
            connection.send_error(msg["id"], "failed", str(err) or type(err).__name__)
            return
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        ids = {a.name: a.identifier for a in apps if a.name and a.identifier}
        session = async_get_clientsession(hass_)
        from .icons import wanted
        todo = [b for b in ids.values() if wanted(b, msg["apple"]) and b not in icon_index]   # stored before: no lookup at Apple
        found = await lookup_icons(session, todo, (hass_.config.country or "us").lower(), icon_cache, msg["apple"]) if todo else {}
        local = await store_icons(hass_, session, {b: found.get(b) for b in todo}, icon_dir, icon_index)
        now = time.time()
        if todo:
            icon_checked.update({b: now for b in todo if b in icon_index})
            await hass_.async_add_executor_job(save_checked, icon_dir, dict(icon_checked))
        old = [b for b in stale([b for b in ids.values() if wanted(b, msg["apple"])], icon_index, icon_checked, now) if b not in icon_refreshing]
        if old:   # weekly: check these at Apple again in the background (the card gets the stored copies right away)
            icon_refreshing.update(old)
            async def _refresh(old=old):
                try:
                    await refresh_icons(hass_, session, old, (hass_.config.country or "us").lower(), icon_dir, icon_index, icon_checked, msg["apple"], now)
                finally:
                    icon_refreshing.difference_update(old)
            hass_.async_create_background_task(_refresh(), "apple_tv_remote icon refresh")
        urls = {b: (local.get(b) if b in local else (f"{ICON_URL}/{icon_index[b]}" if icon_index.get(b) else None)) for b in ids.values() if wanted(b, msg["apple"])}
        connection.send_result(msg["id"], {"icons": {name: urls.get(bid) for name, bid in ids.items() if urls.get(bid)}, "ids": ids})   # ids: app name -> bundle ID (the card matches Apple's apps by ID, in every language)

    @websocket_api.require_admin
    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/touch_test", vol.Required("entity_id"): cv.entity_id,
        vol.Exclusive("swipe", "what"): vol.All([vol.Coerce(int)], vol.Length(min=5, max=5)),
        vol.Exclusive("events", "what"): vol.All([vol.ExactSequence([vol.Coerce(float), vol.In(list(TOUCH_MODES)), vol.Coerce(float), vol.Coerce(float)])],
                                                 vol.Length(min=1, max=2000))})
    @websocket_api.async_response
    async def ws_touch_test(hass_, connection, msg):
        """Diagnosis (admins): send a scripted touch to the Apple TV, to find out what its scrubbing reacts to.
        swipe: [start_x, start_y, end_x, end_y, duration_ms] = pyatv's own swipe; events: [[wait_ms, press|move|hold|release, x, y], ...] = sent as is."""
        atv = _atv(hass_, msg["entity_id"])
        if atv is None:
            connection.send_error(msg["id"], "not_connected", "The Apple TV is not connected")
            return
        t0 = time.monotonic()
        try:
            if "swipe" in msg:
                sx, sy, ex, ey, ms = msg["swipe"]
                _LOGGER.debug("test swipe %s,%s -> %s,%s in %s ms", sx, sy, ex, ey, ms)
                await atv.touch.swipe(clamp_coord(sx), clamp_coord(sy), clamp_coord(ex), clamp_coord(ey), max(16, min(10000, ms)))
                sent = None
            else:
                sent = await replay(atv, [[w, a, clamp_coord(x), clamp_coord(y)] for w, a, x, y in msg.get("events", [])])
        except Exception as err:
            connection.send_error(msg["id"], "failed", str(err) or type(err).__name__)
            return
        connection.send_result(msg["id"], {"sent": sent, "ms": round((time.monotonic() - t0) * 1000)})

    @websocket_api.require_admin
    @websocket_api.websocket_command({
        vol.Required("type"): f"{DOMAIN}/raw_session", vol.Required("entity_id"): cv.entity_id,
        vol.Optional("setup", default=list): [vol.All(list, vol.Length(min=3, max=4))],
        vol.Optional("events", default=list): vol.All([vol.ExactSequence([vol.Coerce(float), vol.In(list(TOUCH_MODES)), vol.Coerce(float), vol.Coerce(float)])], vol.Length(max=2000))})
    @websocket_api.async_response
    async def ws_raw_session(hass_, connection, msg):
        """Diagnosis (admins): open a Companion connection of our own, send a scripted set-up ([[request|event, identifier, content, wait_ms?], ...])
        and a scripted touch, close it. To find out which set-up message of Apple's Remote app makes the Apple TV scrub properly."""
        atv = _atv(hass_, msg["entity_id"])
        if atv is None:
            connection.send_error(msg["id"], "not_connected", "The Apple TV is not connected")
            return
        try:
            out = await raw_session(atv, msg["setup"], [[w, a, clamp_coord(x), clamp_coord(y)] for w, a, x, y in msg["events"]])
        except Exception as err:
            connection.send_error(msg["id"], "failed", str(err) or type(err).__name__)
            return
        connection.send_result(msg["id"], {"setup": out})

    def _touch_ok(atv):
        """True / False when the Apple TV says whether touch events work, None when that is not known (not connected)."""
        if atv is None:
            return None
        try:
            from pyatv.const import FeatureName, FeatureState
            return atv.features.in_state(FeatureState.Available, FeatureName.TouchAction)
        except Exception:
            return None

    websocket_api.async_register_command(hass, ws_touch)
    websocket_api.async_register_command(hass, ws_touch_test)
    websocket_api.async_register_command(hass, ws_key)
    websocket_api.async_register_command(hass, ws_player)
    websocket_api.async_register_command(hass, ws_app_icons)
    websocket_api.async_register_command(hass, ws_raw_session)
    websocket_api.async_register_command(hass, ws_info)
    websocket_api.async_register_command(hass, ws_reconnect)
    js = Path(__file__).parent / "frontend" / "atv-touchpad.js"
    await hass.http.async_register_static_paths([StaticPathConfig(JS_URL, str(js), cache_headers=False), StaticPathConfig(ICON_URL, icon_dir, cache_headers=True)])
    add_extra_js_url(hass, f"{JS_URL}?v={int(js.stat().st_mtime)}")   # mtime = cache buster, no dashboard resource needed
    return True
