"""Pure helpers (no Home Assistant import) so they can be unit tested."""
from __future__ import annotations

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
