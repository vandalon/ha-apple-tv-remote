"""Diagnosis: a Companion connection of our own to the Apple TV, to send exactly what Apple's Remote app sends.

Touch events that are identical to the Remote app's still scrub badly over the core integration's connection, so the difference has to be in
how the app sets its session up. This opens a second connection (with the credentials the core integration already has), sends a scripted
set-up and then a scripted touch, and closes again. Only pyatv internals can do that, which is why it lives in its own file.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .logic import TOUCH_MODES
from .touch import Wide

_LOGGER = logging.getLogger(__name__)


def opack_message(kind: str, identifier: str, content: dict) -> dict:
    """One Companion message: kind request (expects an answer) or event."""
    return {"_i": identifier, "_t": 2 if kind == "request" else 1, "_c": content}


def touch_event(action: str, x: int, y: int, ns: int) -> dict:
    return opack_message("event", "_hidT", {"_ns": ns, "_tFg": 1, "_cx": Wide(x), "_tPh": TOUCH_MODES[action], "_cy": Wide(y)})


async def run_script(proto, frame, setup: list, events: list, linger: float = 1.0) -> list:
    """Send `setup` ([[request|event, identifier, content, wait_ms?], ...]) and then the touch `events` ([[wait_ms, action, x, y], ...]) over `proto`.
    Returns what happened per set-up message; a message that fails does not stop the rest."""
    out = []
    for item in setup:
        kind, ident, content = item[0], item[1], item[2] or {}
        try:
            if kind == "request":
                resp = await proto.exchange_opack(frame, opack_message(kind, ident, dict(content)), timeout=4.0)
                out.append([ident, repr(resp.get("_c"))[:400]])
            else:
                proto.send_opack(frame, opack_message(kind, ident, dict(content)))
                out.append([ident, "sent"])
        except Exception as err:
            out.append([ident, "ERROR " + (str(err) or type(err).__name__)])
        if len(item) > 3 and item[3]:
            await asyncio.sleep(min(5.0, float(item[3]) / 1000))
    due = time.monotonic()
    for wait_ms, action, x, y in events:
        due += max(0.0, min(5000.0, float(wait_ms))) / 1000
        delay = due - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        proto.send_opack(frame, touch_event(action, x, y, time.monotonic_ns()))
    await asyncio.sleep(linger)
    return out


async def raw_session(atv, setup: list, events: list) -> list:
    from pyatv.auth.hap_srp import SRPAuthHandler
    from pyatv.const import Protocol
    from pyatv.core import MutableService
    from pyatv.protocols.companion.connection import CompanionConnection, FrameType
    from pyatv.protocols.companion.protocol import CompanionProtocol

    remote = atv.remote_control.get(Protocol.Companion)
    if remote is None:
        raise RuntimeError("no Companion link")
    core = remote.api.core
    port = core.service.port
    conn = CompanionConnection(core.loop, str(core.config.address), port)
    proto = CompanionProtocol(conn, SRPAuthHandler(), MutableService(None, Protocol.Companion, port, {}, credentials=core.service.credentials))
    from pyatv.auth.hap_pairing import parse_credentials
    client_id = parse_credentials(core.service.credentials).client_id   # "$CLIENT_ID" in a set-up message stands for the id this pairing has (as pyatv sends it)
    setup = [[i[0], i[1], {k: (client_id if v == "$CLIENT_ID" else v) for k, v in (i[2] or {}).items()}, *i[3:]] for i in setup]
    await proto.start()
    try:
        return await run_script(proto, FrameType.E_OPACK, setup, events)
    finally:
        proto.stop()
