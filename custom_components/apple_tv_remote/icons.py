"""App icons for the card's tiles: the real icon of App Store apps, looked up by bundle ID in Apple's public App Store lookup.

Only a link to Apple's image server is handed to the card (nothing is stored or copied). Apple's own tvOS apps are not listed under their
tvOS bundle IDs, but several have an iPhone version in the store (APPLE_IOS): their (square) iPhone icon is used. The rest of Apple's apps get
the card's own tile. Results (also misses) are kept in memory for the rest of the Home Assistant run."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)
LOOKUP = "https://itunes.apple.com/lookup"
ICON_SIZE = "400x240bb"   # tvOS icons are wide (5:3)
SQUARE_SIZE = "256x256bb"   # iPhone icons are square
APPLE_IOS = {   # Apple's tvOS apps -> their iPhone version in the App Store (checked: the tvOS IDs give no result)
    "com.apple.TVWatchList": "com.apple.tv", "com.apple.TVMusic": "com.apple.Music", "com.apple.podcasts": "com.apple.podcasts",
    "com.apple.Fitness": "com.apple.Fitness", "com.apple.TVPhotos": "com.apple.mobileslideshow",
}


def icon_url(result: dict, size: str = ICON_SIZE) -> str | None:
    """The icon in `size` from one App Store lookup result (None without artwork)."""
    url = result.get("artworkUrl512") or result.get("artworkUrl100") or result.get("artworkUrl60")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    head, _, tail = url.rpartition("/")
    ext = tail.rsplit(".", 1)[-1] if "." in tail else "jpg"
    return f"{head}/{size}.{ext}"


def wanted(bundle_id: str, apple: bool = False) -> bool:
    """Store apps; Apple's own apps only with `apple` (their iPhone icon, square) and when they have an iPhone version in the store."""
    return bool(bundle_id) and (not bundle_id.startswith("com.apple.") or (apple and bundle_id in APPLE_IOS))


async def lookup_icons(session, bundle_ids: list[str], country: str, cache: dict[str, str | None], apple: bool = False) -> dict[str, str | None]:
    """Icon URL per bundle ID (None = no icon); asks Apple only for IDs not in `cache` (a few at a time)."""
    sem = asyncio.Semaphore(4)

    async def one(bid: str) -> None:
        async with sem:
            try:
                ios = APPLE_IOS.get(bid)
                params = {"bundleId": ios, "country": country} if ios else {"bundleId": bid, "entity": "tvSoftware", "country": country}
                async with session.get(LOOKUP, params=params, timeout=10) as resp:
                    data: Any = await resp.json(content_type=None)
                res = (data or {}).get("results") or []
                cache[bid] = icon_url(res[0], SQUARE_SIZE if ios else ICON_SIZE) if res else None
            except Exception as err:   # no network, Apple busy: no icon this time, try again next run
                _LOGGER.debug("icon lookup %s failed: %s", bid, err)

    await asyncio.gather(*(one(b) for b in bundle_ids if wanted(b, apple) and b not in cache))
    return {b: cache.get(b) if wanted(b, apple) else None for b in bundle_ids}


# Local copies: the icons are kept on the Home Assistant server (config/apple_tv_remote_icons, outside any repository) and served from there,
# so phones do not fetch them from Apple and a restart needs no new lookup. index.json remembers bundle ID -> file (or none).
ICON_DIR = "apple_tv_remote_icons"
ICON_URL = "/apple_tv_remote/icons"


def file_name(url: str) -> str:
    import hashlib
    import re
    ext = url.rsplit(".", 1)[-1].lower() if "." in url.rsplit("/", 1)[-1] else "jpg"
    size = re.search(r"/(\d+x\d+bb)\.", url)   # kept in the name: the card tells square (iPhone) icons from wide ones by it
    return hashlib.sha1(url.encode()).hexdigest()[:16] + ("-" + size.group(1) if size else "") + "." + (ext if ext in ("jpg", "jpeg", "png", "webp") else "jpg")


def load_index(folder: str) -> dict[str, str | None]:
    import json
    import os
    try:
        with open(os.path.join(folder, "index.json"), encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if v is None or os.path.isfile(os.path.join(folder, v))}
    except (OSError, ValueError):
        return {}


def save_index(folder: str, index: dict[str, str | None]) -> None:
    import json
    import os
    _write(os.path.join(folder, "index.json"), json.dumps(index, indent=1, sort_keys=True).encode())


def is_image(data: bytes) -> bool:
    """A whole JPEG, PNG or WebP (a cut-off download misses the end marker)."""
    if data[:3] == b"\xff\xd8\xff":
        return data.rstrip(b"\x00")[-2:] == b"\xff\xd9"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data[-8:-4] == b"IEND"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return len(data) == int.from_bytes(data[4:8], "little") + 8
    return False


async def store_icons(hass, session, urls: dict[str, str | None], folder: str, index: dict[str, str | None], replace: bool = False) -> dict[str, str | None]:
    """Download each icon URL once into `folder`; returns bundle ID -> local URL (None = no icon). `index` is updated and saved.

    replace: download even when the app has a stored icon (the weekly refresh). The stored copy is only swapped for a new file that
    arrived whole and is a valid image; a failed, cut-off or broken download keeps the previous version.
    """
    import os
    changed = False
    old_files: set[str] = set()

    async def one(bid: str, url: str | None) -> None:
        nonlocal changed
        if (bid in index and not replace) or url is None:
            if bid not in index:
                index[bid] = None
                changed = True
            return
        name = file_name(url)
        try:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return
                data = await resp.read()
                size = getattr(resp, "content_length", None)
            if not data or len(data) > 2_000_000 or (size is not None and size != len(data)) or not is_image(data):
                _LOGGER.debug("icon download %s incomplete or not an image, kept the old one", url)
                return
            await hass.async_add_executor_job(_write, os.path.join(folder, name), data)
            if index.get(bid) and index[bid] != name:
                old_files.add(index[bid])
            index[bid] = name
            changed = True
        except Exception as err:   # try again next time
            _LOGGER.debug("icon download %s failed: %s", url, err)

    await asyncio.gather(*(one(b, u) for b, u in urls.items()))
    if changed:
        await hass.async_add_executor_job(save_index, folder, dict(index))
    unused = old_files - set(index.values())
    if unused:   # only after the new index is saved
        await hass.async_add_executor_job(_remove, folder, unused)
    return {b: (f"{ICON_URL}/{index[b]}" if index.get(b) else None) for b in urls}


def _write(path: str, data: bytes) -> None:
    """Write a whole file or nothing: a temporary file first, then renamed over the old one (atomic)."""
    import os
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _remove(folder: str, names) -> None:
    import os
    for n in names:
        try:
            os.remove(os.path.join(folder, n))
        except OSError:
            pass


REFRESH_DAYS = 7   # a stored icon is checked at Apple again after this many days, in the background (only downloaded when it changed)


def load_checked(folder: str) -> dict[str, float]:
    import json
    import os
    try:
        with open(os.path.join(folder, "checked.json"), encoding="utf-8") as f:
            return {k: float(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def save_checked(folder: str, checked: dict[str, float]) -> None:
    import json
    import os
    _write(os.path.join(folder, "checked.json"), json.dumps(checked, indent=1, sort_keys=True).encode())


def stale(bundle_ids, index: dict, checked: dict[str, float], now: float) -> list[str]:
    """Stored icons (and misses) not checked at Apple for REFRESH_DAYS."""
    return [b for b in bundle_ids if b in index and now - checked.get(b, 0) > REFRESH_DAYS * 86400]


async def refresh_icons(hass, session, bundle_ids: list[str], country: str, folder: str, index: dict, checked: dict[str, float], apple: bool, now: float) -> None:
    """Look the given apps up at Apple again; store a new file only where the icon changed. Quiet: failures wait for the next time."""
    import os
    fresh: dict[str, str | None] = {}
    found = await lookup_icons(session, bundle_ids, country, fresh, apple)
    changed = {}
    for b in bundle_ids:
        if b not in fresh:   # the lookup failed (no network ...): try again next time
            continue
        url = found.get(b)
        if url is None or (index.get(b) and index[b] == file_name(url) and os.path.isfile(os.path.join(folder, index[b]))):
            checked[b] = now   # gone from the store (the stored icon stays) or unchanged
            continue
        changed[b] = url
    if changed:   # the old file stays until a new one arrived whole
        await store_icons(hass, session, changed, folder, index, replace=True)
        checked.update({b: now for b, url in changed.items() if index.get(b) == file_name(url)})   # a failed download is tried again next time
    await hass.async_add_executor_job(save_checked, folder, dict(checked))
