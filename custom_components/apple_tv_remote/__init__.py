"""Apple TV Remote: the `custom:atv-touchpad` card plus a small websocket helper.

The card itself only uses services of the core Apple TV integration (remote.send_command, media_player.select_source,
apple_tv.set_keyboard_text). This integration serves the card script and answers one question the frontend cannot:
which config entry (and remote entity) belongs to an Apple TV media player, so nobody has to type ids.
"""
from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .logic import keyboard_sensor, sibling

DOMAIN = "apple_tv_remote"
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Any(None, dict)}, extra=vol.ALLOW_EXTRA)
JS_URL = f"/{DOMAIN}/atv-touchpad.js"


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
            "media_player": msg["entity_id"] if msg["entity_id"].startswith("media_player.") else sibling(rows, msg["entity_id"], "media_player"),
        })

    websocket_api.async_register_command(hass, ws_info)
    js = Path(__file__).parent / "frontend" / "atv-touchpad.js"
    await hass.http.async_register_static_paths([StaticPathConfig(JS_URL, str(js), cache_headers=False)])
    add_extra_js_url(hass, f"{JS_URL}?v={int(js.stat().st_mtime)}")   # mtime = cache buster, no dashboard resource needed
    return True
