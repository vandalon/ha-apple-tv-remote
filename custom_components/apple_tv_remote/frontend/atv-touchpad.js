/* atv-touchpad: touchpad remote card for an Apple TV (core "Apple TV" integration).
   type: custom:atv-touchpad
   entity: media_player.living_room_apple_tv   # required: the Apple TV media player (its remote entity is found automatically)
   sources: true                     # a tile per app the Apple TV reports (source_list); false hides them
   hide_sources: [App Store]         # app names to leave out
   source_order: [Netflix, YouTube]  # show ONLY these tiles, in this order; empty = all apps
   source_style: tiles               # tiles (icon + name) or chips (name only)
   source_colors: true               # brand colour for known apps, a stable own colour for every other app; false = neutral
   source_rows: 1                    # lines of tiles, filled evenly (10 tiles: 2 lines = 5+5, 3 lines = 4+4+2); a line wider than the card scrolls sideways; 0 = as many lines as needed
   source_icons:                     # optional: icon (and colour) per app name, overrides the built-in recognition
     Plex: mdi:plex
     My app: { icon: mdi:rocket, color: "#107c10" }
   app_switcher: true                # button: double-press of the TV/home key (app switcher)
   volume: true                      # volume - / + buttons (Apple TV controls the TV or soundbar it is set up for)
   keyboard: true                    # keyboard button on the pad; the text box also opens by itself when a text field has focus
   keyboard_sensor: binary_sensor.x  # optional: the "Keyboard focus" sensor (found automatically)
   remote: remote.x                  # optional: the remote entity (found automatically)
   swipe_slow: 96                    # px of dragging per item when you swipe slowly
   swipe_fast: 22                    # px per item when you swipe fast
   command_gap: 140                  # ms between two pad commands (the Apple TV drops commands that arrive faster)
   haptics: true                     # buzz on taps (HA app haptic event / navigator.vibrate)
   show_border: true                 # false = no border / shadow around the card (for pop-ups and stacks that bring their own frame)
   height: auto                      # auto (default) = content-sized; or any CSS height (70vh, 100%): the pad then takes the spare space
   pad_ratio: 1.3                    # touchpad width : height when height is auto
   Swipe = arrow keys (keeps repeating while you drag), tap = select, tap near an edge = that arrow.
   Power: short press = control centre (the TV key held for 1 s), long press = sleep. The Apple TV has no mute key. */
// Built-in recognition of apps by name (first hit wins, English and Dutch names). Everything else gets a neutral icon.
// MDI 7 dropped several brand icons (AirPlay, Amazon), so AirPlay is an inline path; everything else is a built-in mdi icon.
const AIRPLAY = "M6,22H18L12,16M21,3H3A2,2 0 0,0 1,5V17A2,2 0 0,0 3,19H7V17H3V5H21V17H17V19H21A2,2 0 0,0 23,17V5A2,2 0 0,0 21,3Z";
const KNOWN = [   // [name regex, mdi icon, colour (null = own palette colour), optional inline svg path]
  [/netflix/i, "mdi:netflix", "#e50914"], [/youtube/i, "mdi:youtube", "#ff0000"], [/spotify/i, "mdi:spotify", "#1db954"],
  [/prime|amazon/i, "mdi:play-box", "#00a8e1"], [/disney/i, "mdi:castle", "#3b6cf0"], [/hbo|\bmax\b/i, "mdi:movie-open", "#8b5cf6"],
  [/^tv$|apple\s*tv|^atv$/i, "mdi:apple", "#a2aaad"], [/airplay/i, "mdi:cast", "#2a6df4", AIRPLAY],
  [/twitch/i, "mdi:twitch", "#9146ff"], [/plex/i, "mdi:plex", "#e5a00d"], [/kodi/i, "mdi:kodi", "#17b2e7"], [/steam/i, "mdi:steam", "#66c0f4"],
  [/music|muziek/i, "mdi:music", "#fa2d48"], [/podcast/i, "mdi:podcast", "#9b59d0"], [/photo|foto/i, "mdi:image-multiple", "#f5a623"],
  [/app\s*store/i, "mdi:store", "#1c8ef9"], [/arcade/i, "mdi:gamepad-variant", "#ff4f81"], [/setting|instelling/i, "mdi:cog", null],
  [/computer/i, "mdi:laptop", null], [/facetime/i, "mdi:video", "#34c759"], [/^(search|zoek)/i, "mdi:magnify", null],
  [/fitness|conditie/i, "mdi:run", "#b4e50d"], [/npo|nos\b|rtl|kijk|videoland|ziggo|\bard\b|zdf|arte|bbc|itv|channel\s*4|viki|f1/i, "mdi:television-play", null],
  [/game|spel/i, "mdi:controller", null], [/browser|web|safari/i, "mdi:web", null],
];
// Apps without a brand colour get their own stable colour from this palette (same name = same colour; neighbours never share one).
const PALETTE = ["#ef5350", "#ff7043", "#ffa726", "#ffca28", "#9ccc65", "#26a69a", "#26c6da", "#42a5f5", "#5c6bc0", "#7e57c2", "#ab47bc", "#ec407a"];
const hash = n => { let h = 5381; for (const ch of n) h = ((h << 5) + h + ch.charCodeAt(0)) >>> 0; return h; };
const norm = n => String(n == null ? "" : n).replace(/ /g, " ").replace(/\s+/g, " ").trim();   // app names may contain non-breaking spaces
const iconFor = (name, over) => {
  const o = over && over[name];
  if (o) return typeof o === "string" ? { icon: o, color: null } : { icon: o.icon || "mdi:application-outline", color: o.color || null };
  const k = KNOWN.find(([re]) => re.test(name));
  return k ? { icon: k[1], color: k[2], path: k[3] } : { icon: "mdi:application-outline", color: null };
};
// Swipe step in px for a finger speed in px/ms: slow = one item per `slow` px, fast = one item every `fast` px.
const stepFor = (v, slow, fast) => Math.max(fast, slow - (slow - fast) * Math.min(1, v));
// The tiles: every app the Apple TV lists (names cleaned of non-breaking spaces; `raw` is what select_source needs).
// A non-empty `source_order` shows only those tiles, in that order; empty = all, in the order the Apple TV gives.
function buildItems(c, st) {
  const list = c.sources !== false && st && Array.isArray(st.attributes.source_list) ? st.attributes.source_list : [];
  const hide = (c.hide_sources || []).map(x => norm(x).toLowerCase()), seen = new Set(), items = [];
  list.forEach(raw => { const name = norm(raw), k = name.toLowerCase(); if (!name || seen.has(k) || hide.includes(k)) return; seen.add(k); items.push({ name, raw }); });
  const order = (Array.isArray(c.source_order) ? c.source_order : []).map(x => norm(x).toLowerCase()).filter(Boolean);
  if (!order.length) return items;
  return order.map(o => items.find(i => i.name.toLowerCase() === o)).filter(Boolean);
}
const EDGE = 56;   // width (px) of the edge zone where a tap sends an arrow

class AtvTouchpad extends HTMLElement {
  setConfig(c) {
    if (!c || !c.entity) throw new Error("entity (the Apple TV media player) is required");
    this._c = { sources: true, app_switcher: true, volume: true, keyboard: true, haptics: true, show_border: true, source_style: "tiles", source_colors: true, source_rows: 1, source_icons: {}, hide_sources: [], source_order: [], swipe_slow: 96, swipe_fast: 22, command_gap: 140, height: "auto", pad_ratio: 1.3, ...c };
    if (Array.isArray(this._c.source_icons)) {   // list form from the visual editor -> map by app name
      const m = {}; this._c.source_icons.forEach(i => { if (i && i.name && (i.icon || i.color)) m[i.name] = { icon: i.icon || undefined, color: i.color || undefined }; });
      this._c = { ...this._c, source_icons: m };
    }
    this._info = null; this._infoFor = null;
    this._build();
  }
  set hass(h) { this._hass = h; this._resolve(); this._refresh(); }
  getCardSize() { return 6; }
  static getConfigElement() { return document.createElement("atv-touchpad-editor"); }
  static getStubConfig(hass) {
    const ids = Object.keys(hass.states).filter(i => i.startsWith("media_player."));
    const e = ids.find(i => hass.entities && hass.entities[i] && hass.entities[i].platform === "apple_tv") || ids.find(i => /atv|apple/i.test(i)) || ids.find(i => hass.states[i].attributes.source_list);
    return { entity: e || "media_player.apple_tv" };
  }

  _build() {
    const c = this._c;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
<style>
ha-card{${c.show_border === false ? "border:none !important;box-shadow:none !important;--ha-card-border-width:0px;" : ""}padding:12px;display:flex;flex-direction:column;gap:10px;height:${c.height};box-sizing:border-box;overflow:hidden;position:relative;--ratio:${Number(c.pad_ratio) > 0 ? Number(c.pad_ratio) : 1.3}}
button{cursor:pointer;-webkit-tap-highlight-color:transparent;border:0;color:var(--primary-text-color);font:500 13px var(--paper-font-body1_-_font-family,system-ui)}
.src{display:grid;grid-template-columns:repeat(var(--cols,1),max-content);justify-content:start;align-content:start;gap:8px;overflow-x:auto;overflow-y:hidden;overscroll-behavior-x:contain;touch-action:pan-x pan-y;scrollbar-width:none;flex:0 0 auto}   /* source_rows lines, evenly filled; a line wider than the card scrolls sideways (all lines together) */
.src.tiles{grid-template-columns:repeat(var(--cols,1),78px)}
.src.all{overflow:visible}
.src.center{justify-content:center}   /* everything fits: centred */
.src:empty{display:none}
.src button{flex:0 0 auto;border-radius:12px;padding:9px 14px;background:var(--secondary-background-color)}
.src.tiles button{width:78px;height:64px;box-sizing:border-box;justify-content:center;padding:6px 4px;display:flex;flex-direction:column;align-items:center;gap:4px;font-size:11px;line-height:1.15}
.src.tiles ha-icon{--mdc-icon-size:28px;color:var(--ic,var(--secondary-text-color))}
.src.tiles.col button{background:color-mix(in srgb,var(--ic) 16%,var(--secondary-background-color))}
.src.tiles.col button.on{background:color-mix(in srgb,var(--ic) 30%,var(--secondary-background-color))}
.src.tiles span{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.src button.on{background:color-mix(in srgb,var(--primary-color) 22%,var(--secondary-background-color));box-shadow:inset 0 0 0 2px var(--primary-color)}
.src.chips button.on{background:var(--primary-color);color:var(--text-primary-color,#fff);box-shadow:none}
#pad{position:relative;flex:1 1 0;min-height:110px;border-radius:20px;background:var(--secondary-background-color);touch-action:none;user-select:none;-webkit-user-select:none;overflow:hidden}
ha-card.auto #pad{flex:none;aspect-ratio:var(--ratio)}   /* height: auto = content-sized card; _sizePad keeps the size constant when the text box shows */
#pad ha-icon{position:absolute;opacity:.25;--mdc-icon-size:26px;pointer-events:none}
#pad ha-icon.logo{left:50%;top:50%;margin:-70px 0 0 -70px;--mdc-icon-size:140px;opacity:.07}
#pad .u{top:10px;left:50%;margin-left:-13px}#pad .d{bottom:10px;left:50%;margin-left:-13px}
#pad .l{left:10px;top:50%;margin-top:-13px}#pad .r{right:10px;top:50%;margin-top:-13px}
#pad.flash{background:color-mix(in srgb,var(--primary-color) 25%,var(--secondary-background-color))}
.tg{position:absolute;top:8px;right:8px;width:38px;height:38px;border-radius:50%;background:rgba(127,127,127,.15);opacity:.75;display:none;align-items:center;justify-content:center;padding:0}
.tg.on{background:var(--primary-color);color:var(--text-primary-color,#fff);opacity:1}
#pad .tg ha-icon{position:static;opacity:1;--mdc-icon-size:22px}
#kb{display:none;flex:0 0 auto}
#kb.on{display:block}
#kb input{width:100%;box-sizing:border-box;height:44px;border:0;border-radius:12px;padding:0 14px;background:var(--secondary-background-color);color:var(--primary-text-color);font:16px var(--paper-font-body1_-_font-family,system-ui);outline:2px solid var(--primary-color)}
.row{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.row button{border-radius:12px;background:var(--secondary-background-color);padding:12px 4px;display:flex;align-items:center;justify-content:center}
.row button:active{filter:brightness(1.4)}
.row button.off{color:var(--error-color)}
button[hidden]{display:none !important}
</style>
<ha-card class="${String(c.height).trim() === "auto" ? "auto" : ""}">
  <div class="src" id="src"></div>
  <div id="pad">
    <button class="tg" id="kbbtn" title="Keyboard"><ha-icon icon="mdi:keyboard"></ha-icon></button>
    <ha-icon class="u" icon="mdi:chevron-up"></ha-icon><ha-icon class="d" icon="mdi:chevron-down"></ha-icon>
    <ha-icon class="l" icon="mdi:chevron-left"></ha-icon><ha-icon class="r" icon="mdi:chevron-right"></ha-icon>
    <ha-icon class="logo" icon="mdi:apple"></ha-icon>
  </div>
  <div id="kb"><input type="text" placeholder="Type to the Apple TV" autocomplete="off" autocapitalize="off" enterkeyhint="done"></div>
  <div class="row" id="rowa">
    <button id="pwr" title="Power: tap = control centre, hold = sleep, wakes the Apple TV when it is asleep"><ha-icon icon="mdi:power"></ha-icon></button>
    <button data-k="back" title="Back"><ha-icon icon="mdi:chevron-left"></ha-icon></button>
    <button data-k="home" title="TV / Home"><ha-icon icon="mdi:television"></ha-icon></button>
    <button data-k="play" title="Play / pause"><ha-icon icon="mdi:play-pause"></ha-icon></button>
  </div>
  <div class="row" id="rowb">
    <button data-k="vdown" title="Volume down"><ha-icon icon="mdi:volume-minus"></ha-icon></button>
    <button data-k="vup" title="Volume up"><ha-icon icon="mdi:volume-plus"></ha-icon></button>
    <button data-k="switcher" title="App switcher (double-press TV / Home)"><ha-icon icon="mdi:card-multiple-outline"></ha-icon></button>
  </div>
</ha-card>`;
    const $ = s => this.shadowRoot.querySelector(s);
    this.shadowRoot.querySelectorAll("[data-k]").forEach(b => b.onclick = () => { this._buzz(); this._send(b.dataset.k); });
    // power: tap = control centre (TV key held 1 s) or wake; hold = sleep
    const pw = $("#pwr"); let pt = null, long = false;
    pw.onpointerdown = () => { long = false; clearTimeout(pt); pt = setTimeout(() => { long = true; this._buzz(); this._power(true); }, 600); };
    pw.onpointerup = pw.onpointerleave = pw.onpointercancel = () => clearTimeout(pt);
    pw.onclick = () => { if (!long) { this._buzz(); this._power(false); } };
    // keyboard: typing is mirrored to the focused text field (apple_tv.set_keyboard_text)
    const kbi = $("#kb input");
    kbi.addEventListener("input", () => this._text(kbi.value));
    kbi.addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter") { kbi.blur(); this._send("ok"); } });
    $("#kbbtn").onclick = () => { this._buzz(); this._kbManual = !this._kbManual; this._refresh(); if (this._kbManual) setTimeout(() => kbi.focus(), 50); };
    this._pad($("#pad"));
    // the tile strip scrolls on its own: while it can scroll, its touch/wheel events must not reach page / pop-up gestures
    const strip = $("#src");
    ["touchstart", "touchmove", "touchend", "touchcancel", "pointerdown", "pointermove", "pointerup", "wheel"].forEach(t =>
      strip.addEventListener(t, e => { if (strip.scrollWidth > strip.clientWidth + 1) e.stopPropagation(); }, { passive: true }));
    if (this._ro) this._ro.disconnect();
    if (window.ResizeObserver) { this._ro = new ResizeObserver(() => { const w = $("ha-card").clientWidth; if (w === this._lw) return; this._lw = w; this._layout(); this._sizePad(); }); this._ro.observe($("ha-card")); }
    this._refresh();
  }

  _buzz() {
    if (!this._c.haptics) return;
    try { window.dispatchEvent(new CustomEvent("haptic", { detail: "light" })); } catch (e) {}
    try { navigator.vibrate && navigator.vibrate(8); } catch (e) {}
  }
  _st() { return this._hass && this._hass.states[this._c.entity]; }

  // The remote entity, the config entry and the keyboard sensor are found from the media player: first in the frontend's entity list
  // (same device), and the integration answers the rest (config entry id) over a websocket command. Options win when set.
  _resolve() {
    const c = this._c, h = this._hass; if (!c || !h) return;
    if (!this._remoteId || this._remoteFor !== c.entity) {
      this._remoteFor = c.entity;
      let r = c.remote || (c.entity.startsWith("remote.") ? c.entity : null);
      const reg = h.entities && h.entities[c.entity];
      if (!r && reg && reg.device_id) r = Object.keys(h.entities).find(i => i.startsWith("remote.") && h.entities[i].device_id === reg.device_id && h.entities[i].platform === reg.platform) || null;
      this._remoteId = r;
    }
    if (this._infoFor !== c.entity && h.connection && !this._infoBusy) {
      this._infoBusy = true;
      h.connection.sendMessagePromise({ type: "apple_tv_remote/info", entity_id: c.entity })
        .then(r => { this._info = r; this._infoFor = c.entity; if (!this._remoteId && r.remote) this._remoteId = c.remote || r.remote; })
        .catch(() => { this._info = null; this._infoFor = c.entity; })
        .finally(() => { this._infoBusy = false; this._refresh(); });
    }
  }
  _remote() { return this._c.remote || this._remoteId || (this._info && this._info.remote) || null; }
  _kbSensor() { return this._c.keyboard_sensor || (this._info && this._info.keyboard_sensor) || null; }
  _awake() {   // the remote entity is "on" while the Apple TV is awake; without it use the media player
    const h = this._hass, r = this._remote(), rs = r && h && h.states[r], ms = this._st();
    if (rs && !["unavailable", "unknown"].includes(rs.state)) return rs.state === "on";
    return !!ms && !["off", "standby", "unavailable", "unknown"].includes(ms.state);
  }
  _cmd(command, extra = {}) {
    const r = this._remote(); if (!this._hass || !r) return;
    this._hass.callService("remote", "send_command", { entity_id: r, command, ...extra });
  }
  _text(text) {
    const id = this._info && this._info.config_entry_id; if (!this._hass || !id) return;
    this._hass.callService("apple_tv", "set_keyboard_text", { config_entry_id: id, text });
  }
  _send(k) {
    const map = { up: "up", down: "down", left: "left", right: "right", ok: "select", back: "menu", home: "home", play: "play_pause", vup: "volume_up", vdown: "volume_down" };
    if (k === "switcher") return this._cmd("home", { num_repeats: 2, delay_secs: 0.2 });   // double-press of the TV / Home key
    if (map[k]) this._cmd(map[k]);   // the Apple TV has no mute key
  }
  _power(long) {
    const h = this._hass, r = this._remote(); if (!h || !r) return;
    if (!this._awake()) h.callService("remote", "turn_on", { entity_id: r });
    else if (long) h.callService("remote", "turn_off", { entity_id: r });   // sleep
    else this._cmd("home", { hold_secs: 1 });   // control centre
  }
  async _tile(it) {
    const h = this._hass, id = this._c.entity.startsWith("media_player.") ? this._c.entity : (this._info && this._info.media_player); if (!h || !id) return;
    const off = () => ["off", "standby"].includes((h.states[id] || {}).state);
    if (off()) { h.callService("media_player", "turn_on", { entity_id: id }); for (let i = 0; i < 20 && off(); i++) await new Promise(r => setTimeout(r, 300)); }   // an app tile wakes a sleeping Apple TV first
    h.callService("media_player", "select_source", { entity_id: id, source: it.raw });
  }

  _refresh() {
    if (!this.shadowRoot || !this._c) return;
    const c = this._c, st = this._st(), $ = s => this.shadowRoot.querySelector(s);
    const vol = c.volume !== false, sw = c.app_switcher !== false;
    $('[data-k="vdown"]').hidden = $('[data-k="vup"]').hidden = !vol; $('[data-k="switcher"]').hidden = !sw;
    $("#rowb").style.display = vol || sw ? "" : "none";
    $("#rowb").style.gridTemplateColumns = "repeat(" + ((vol ? 2 : 0) + (sw ? 1 : 0) || 1) + ",1fr)";
    $("#pwr").classList.toggle("off", !this._awake());
    const ks = this._kbSensor(), kst = ks && this._hass && this._hass.states[ks];
    const focus = !!kst && kst.state === "on" && !!(this._info && this._info.config_entry_id);
    const kbOn = focus || (c.keyboard !== false && !!this._kbManual && !!(this._info && this._info.config_entry_id));
    $("#kbbtn").style.display = c.keyboard !== false && this._info && this._info.config_entry_id ? "flex" : "none";
    $("#kbbtn").classList.toggle("on", !!this._kbManual);
    if (kbOn !== $("#kb").classList.contains("on")) { $("#kb").classList.toggle("on", kbOn); if (!kbOn) $("#kb input").value = ""; this._sizePad(); }
    this._items(st);
    this._layout();
    const cur = norm(st && (st.attributes.source || st.attributes.app));
    $("#src").querySelectorAll("button").forEach(b => b.classList.toggle("on", !!cur && b.dataset.s === cur));
  }
  _items(st) {
    const c = this._c, el = this.shadowRoot.querySelector("#src");
    const items = buildItems(c, st), tiles = c.source_style !== "chips", rows = Math.max(0, Math.floor(Number(c.source_rows))) || 0, col = tiles && c.source_colors !== false;
    const key = tiles + "|" + col + "|" + rows + "|" + JSON.stringify(c.source_icons) + "|" + JSON.stringify(items);
    if (el.dataset.k === key) return;   // only rebuilt when the tiles change, never on every hass update (that reset the scroll position)
    el.dataset.k = key; el.textContent = ""; el.className = "src " + (tiles ? "tiles" : "chips") + (rows ? "" : " all") + (col ? " col" : ""); this._n = items.length; this._rowsCfg = rows; this._tilesMode = tiles; this._laySig = "";
    const taken = new Set(), own = {};   // own colours: probe from the name's hash to the next free palette slot (alphabetical order keeps it stable)
    if (col) [...items].sort((x, y) => x.name.localeCompare(y.name)).forEach(it => {
      const i = iconFor(it.name, c.source_icons); if (i.color) { taken.add(i.color); return; }
      let k = hash(it.name) % PALETTE.length; for (let j = 0; j < PALETTE.length && taken.has(PALETTE[k]); j++) k = (k + 1) % PALETTE.length;
      own[it.name] = PALETTE[k]; taken.add(PALETTE[k]);
    });
    items.forEach(it => {
      const n = it.name, b = document.createElement("button"); b.title = n; b.dataset.s = n;
      if (tiles) {
        const i = iconFor(n, c.source_icons), t = document.createElement("span");
        if (col) i.color = i.color || own[n];
        if (i.color) b.style.setProperty("--ic", i.color);
        let ic;
        if (i.path) { ic = document.createElementNS("http://www.w3.org/2000/svg", "svg"); ic.setAttribute("viewBox", "0 0 24 24"); ic.setAttribute("width", "28"); ic.setAttribute("height", "28"); ic.innerHTML = `<path fill="currentColor" d="${i.path}"/>`; ic.style.color = i.color || "var(--secondary-text-color)"; }
        else { ic = document.createElement("ha-icon"); ic.setAttribute("icon", i.icon); }
        t.textContent = n; b.append(ic, t);
      } else b.textContent = n;
      b.onclick = () => { this._buzz(); this._tile(it); };
      el.appendChild(b);
    });
  }
  // Tiles fill source_rows lines evenly (10 tiles: 2 lines = 5+5, 3 lines = 4+4+2); fewer lines when everything fits; a line wider than the card scrolls sideways.
  _layout() {
    const el = this.shadowRoot && this.shadowRoot.querySelector("#src"); if (!el || !this._n) return;
    const rows = this._rowsCfg || 0, w = el.clientWidth, sig = this._n + "|" + rows + "|" + w + "|" + (this._tilesMode ? 1 : 0);
    if (sig === this._laySig || !w) return;   // only when the tiles or the width change: it must not disturb a scroll in progress
    this._laySig = sig;
    const fits = Math.max(1, Math.floor((w + 8) / ((this._tilesMode ? 78 : 96) + 8))), need = Math.ceil(this._n / fits);
    const lines = Math.max(1, rows ? Math.min(rows, need) : need), cols = Math.ceil(this._n / lines);
    if (el.style.getPropertyValue("--cols") !== String(cols)) el.style.setProperty("--cols", cols);
    el.classList.remove("center");   // measure left-aligned: when nothing needs to scroll the tiles are centred instead
    if (el.scrollWidth <= el.clientWidth + 1) el.classList.add("center");
  }
  // Constant card size: with height auto the pad has the same size with and without the text box (it gives up the box's height).
  _sizePad() {
    const sr = this.shadowRoot, card = sr && sr.querySelector("ha-card"); if (!card || !card.classList.contains("auto")) return;
    const w = card.clientWidth - 24; if (w <= 0) return;
    const kb = sr.querySelector("#kb").classList.contains("on") ? 54 : 0, ratio = Number(this._c.pad_ratio) > 0 ? Number(this._c.pad_ratio) : 1.3;
    const pad = sr.querySelector("#pad"); pad.style.aspectRatio = "auto"; pad.style.height = Math.max(110, Math.round(w / ratio) - kb) + "px";
  }

  _pad(el) {
    let id = null, x0 = 0, y0 = 0, sx = 0, sy = 0, t0 = 0, moved = 0, lx = 0, ly = 0, ls = 0, sv = 0, lsend = 0;
    const flash = () => { el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 90); };
    el.addEventListener("pointerdown", e => {
      if (e.target.closest && e.target.closest(".tg")) return;
      id = e.pointerId; x0 = sx = lx = e.clientX; y0 = sy = ly = e.clientY; t0 = Date.now(); moved = 0; ls = 0; sv = 0;
      try { el.setPointerCapture(id); } catch (err) {}
      e.preventDefault();
    });
    el.addEventListener("pointermove", e => {
      if (e.pointerId !== id) return;
      const c = this._c, dx = e.clientX - x0, dy = e.clientY - y0;
      moved = Math.max(moved, Math.hypot(e.clientX - sx, e.clientY - sy));
      // acceleration: slow drags step one item at a time, fast swipes repeat quickly
      const dtm = Math.max(1, e.timeStamp - (ls || e.timeStamp - 16)), v = Math.hypot(e.clientX - lx, e.clientY - ly) / dtm;
      sv = 0.6 * sv + 0.4 * v; ls = e.timeStamp; lx = e.clientX; ly = e.clientY;
      const step = stepFor(sv, Number(c.swipe_slow) || 96, Number(c.swipe_fast) || 22);
      if (Math.abs(dx) < step && Math.abs(dy) < step) return;
      if (e.timeStamp - lsend < (Number(c.command_gap) || 140)) return;   // the Apple TV drops commands that arrive too fast; the drag keeps accumulating and fires on the next move after the gap
      const k = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up");
      lsend = e.timeStamp; this._buzz(); flash(); this._send(k);
      x0 = e.clientX; y0 = e.clientY;   // restart so that keeping the drag repeats the key
    });
    el.addEventListener("pointerup", e => {
      if (e.pointerId !== id) return;
      const tap = moved < 12 && Date.now() - t0 < 350; id = null;
      if (!tap) return;
      const r = el.getBoundingClientRect(), dl = sx - r.left, dr = r.right - sx, dt = sy - r.top, db = r.bottom - sy, m = Math.min(dl, dr, dt, db);
      const k = m > EDGE ? "ok" : m === dl ? "left" : m === dr ? "right" : m === dt ? "up" : "down";   // inside = select, near an edge = that arrow
      if (k === "ok") this._buzz();
      flash(); this._send(k);
    });
    el.addEventListener("pointercancel", () => { id = null; });
    // A pop-up around the card must not react to swipes on the pad: custom_components/tv_touchpad (swipe down to close, side swipes) skips gestures that
    // start on an element flagged __ptzOn, and the touch/pointer events stay on the pad for handlers further up. Harmless without that component.
    el.__ptzOn = true;
    ["touchstart", "touchmove", "touchend", "touchcancel", "mousedown", "mousemove", "mouseup", "pointerdown", "pointermove", "pointerup", "wheel"].forEach(t => el.addEventListener(t, e => e.stopPropagation(), { passive: true }));
  }
}
if (!customElements.get("atv-touchpad")) customElements.define("atv-touchpad", AtvTouchpad);

// ---- Visual editor (card picker / "Edit card"): ha-form with selectors, plus our own app list (drag to reorder, eye = hide, select mode) ----
const DEFAULTS = { sources: true, app_switcher: true, volume: true, keyboard: true, haptics: true, show_border: true, source_style: "tiles", source_colors: true, source_rows: 1, swipe_slow: 96, swipe_fast: 22, command_gap: 140, height: "auto", pad_ratio: 1.3 };
const FIELD_LABELS = { name: "App name", icon: "Icon", color: "Colour (for example #e50914)" };
const LABELS = {
  entity: ["Apple TV", "The Apple TV media player (core Apple TV integration). Its remote is found automatically."],
  height: ["Card height", "auto = as tall as the content (default). Or any CSS value, for example 70vh or 100% to fill a pop-up; the touchpad then takes the spare space."],
  pad_ratio: ["Touchpad shape (width / height)", "Only with height auto. Higher = flatter touchpad, lower = taller."],
  sources: ["App tiles", "Show a tile for every app the Apple TV reports."],
  app_switcher: ["App switcher button", "Double-presses the TV / Home key, which opens the app switcher."],
  volume: ["Volume buttons", "Volume down / up. The Apple TV passes them on to the TV or soundbar it is set up to control."],
  keyboard: ["Keyboard button", "A keyboard button on the touchpad. The text box also opens by itself when a text field on the Apple TV has focus."],
  show_border: ["Card border", "Show the border and shadow around the card. Turn it off when the card sits inside a pop-up or stack that has its own frame."],
  haptics: ["Haptics", "Vibrate on taps (HA app haptics or the browser vibration)."],
  source_style: ["App style", "Tiles = icon and name (known apps get their icon and colour, the rest a neutral icon), chips = name only."],
  source_rows: ["Tile rows", "How many lines of tiles. They are filled evenly and scroll sideways when a line is wider than the card. 0 = as many lines as needed."],
  source_colors: ["Colour the tiles", "On: brand colour for known apps, a stable own colour for every other app. Off: neutral tiles."],
  source_icons: ["App icons", "Give an app (by name) its own icon and/or colour. Overrides the built-in recognition."],
  swipe_slow: ["Slow swipe distance (px)", "How far you drag for one step when you swipe slowly. Higher = less sensitive."],
  swipe_fast: ["Fast swipe distance (px)", "How far you drag for one step when you swipe fast. Lower = faster scrolling."],
  command_gap: ["Time between commands (ms)", "The Apple TV ignores commands that arrive faster than about every 140 ms."],
  remote: ["Remote entity", "Only needed when the remote is not found automatically."],
  keyboard_sensor: ["Keyboard focus sensor", "Only needed when it is not found automatically: the binary sensor that is on while a text field has focus."],
};
const btnCss = "padding:8px 14px;border-radius:8px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);cursor:pointer;font:inherit";
class AtvTouchpadEditor extends HTMLElement {
  setConfig(c) { this._c = c || {}; this._render(); }
  set hass(h) {
    this._hass = h;
    if (!this._form) return this._render();
    this._form.hass = this._formB.hass = h;
    const sig = JSON.stringify(this._appNames());   // the app list can arrive after setConfig
    if (sig !== this._sig) { this._sig = sig; this._renderList(); }
  }
  _appNames() { const st = this._hass && this._c && this._hass.states[this._c.entity]; return buildItems({ ...DEFAULTS, ...this._c, source_order: [], hide_sources: [] }, st).map(i => i.name); }
  // rows of the app list: first the apps of source_order (shown), then all other apps (shown when source_order is empty, else hidden)
  _rows() {
    const all = this._appNames(), order = (Array.isArray(this._c.source_order) ? this._c.source_order : []).map(norm).filter(Boolean), rows = [];
    order.forEach(n => { const m = all.find(a => a.toLowerCase() === n.toLowerCase()); rows.push({ name: m || n, shown: true, missing: !m }); });
    all.forEach(n => { if (!rows.some(r => r.name.toLowerCase() === n.toLowerCase())) rows.push({ name: n, shown: !order.length }); });
    return rows;
  }
  _commit(rows) {   // write source_order: empty (= all apps) while everything is shown in the natural order
    const all = this._appNames(), shown = rows.filter(r => r.shown).map(r => r.name), same = shown.length === all.length && shown.every((n, i) => n === all[i]);
    const out = { ...this._c }; if (same) delete out.source_order; else out.source_order = shown;
    this._c = out; this._rows_ = null; this._emit(out); this._renderList();
  }
  _buzz() { try { window.dispatchEvent(new CustomEvent("haptic", { detail: "light" })); } catch (e) {} try { navigator.vibrate && navigator.vibrate(8); } catch (e) {} }
  _emit(out) { this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: out }, bubbles: true, composed: true })); }
  _status(t) { if (this._stat) this._stat.textContent = t || ""; }
  _listUi() {
    const box = document.createElement("div"); box.style.cssText = "margin:16px 4px 8px;display:flex;flex-direction:column;gap:8px";
    const head = document.createElement("div"); head.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px";
    const title = document.createElement("div"); title.textContent = "App tiles"; title.style.cssText = "font-weight:500";
    const mkBtn = (label, fn) => { const b = customElements.get("ha-button") ? document.createElement("ha-button") : document.createElement("button"); b.textContent = label; if (b.tagName === "BUTTON") b.style.cssText = btnCss; b.addEventListener("click", fn); return b; };
    this._selBtn = mkBtn("Select", () => { this._selMode = !this._selMode; this._sel = new Set(); if (this._filter) this._filter.value = ""; this._renderList(); });
    head.append(title, this._selBtn);
    const help = document.createElement("div"); help.textContent = "The apps your Apple TV reports. Drag to reorder, the eye hides an app (hidden apps are greyed out). Select hides or shows many at once. Without any change all apps are shown in the order the Apple TV gives."; help.style.cssText = "font-size:12px;opacity:.7";
    this._bar = document.createElement("div"); this._bar.style.cssText = "display:none;flex-direction:column;gap:6px;padding:8px;border:1px solid var(--divider-color);border-radius:10px";
    this._filter = document.createElement("input"); this._filter.type = "search"; this._filter.placeholder = "Filter by name";
    this._filter.style.cssText = "padding:8px 10px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);font:inherit;min-width:0;box-sizing:border-box;width:100%";
    this._filter.addEventListener("input", () => this._applyFilter());
    const mk = (label, fn) => { const b = document.createElement("button"); b.textContent = label; b.style.cssText = btnCss + ";padding:6px 10px;font-size:13px"; b.addEventListener("click", fn); return b; };
    const r1 = document.createElement("div"); r1.style.cssText = "display:flex;flex-wrap:wrap;gap:6px";
    r1.append(mk("Select shown", () => { this._visible().forEach(r => this._sel.add(r._row)); this._renderList(); }), mk("Select none", () => { this._sel = new Set(); this._renderList(); }),
      mk("Hide selected", () => this._bulk(false)), mk("Show selected", () => this._bulk(true)));
    this._count = document.createElement("div"); this._count.style.cssText = "font-size:12px;opacity:.7";
    this._bar.append(this._filter, r1, this._count);
    this._lRows = document.createElement("div"); this._lRows.style.cssText = "display:flex;flex-direction:column;gap:4px";
    const tools = document.createElement("div"); tools.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;margin-top:6px";
    tools.append(mkBtn("Show all apps again", () => this._resetOrder()), mkBtn("Check setup", () => this._check()));
    this._stat = document.createElement("div"); this._stat.style.cssText = "font-size:13px;min-height:18px;color:var(--primary-color)";
    const note = document.createElement("div"); note.textContent = "Check setup looks up the remote, the config entry (needed for the keyboard) and the keyboard focus sensor of this Apple TV."; note.style.cssText = "font-size:12px;opacity:.7";
    box.append(head, help, this._bar, this._lRows, tools, this._stat, note);
    return box;
  }
  _resetOrder() {
    if (!window.confirm("Show all apps again in the order the Apple TV gives?")) return;
    const out = { ...this._c }; delete out.source_order; this._c = out; this._emit(out); this._renderList(); this._status("All apps are shown again");
  }
  async _check() {
    const e = this._c && this._c.entity; if (!e || !this._hass) return this._status("Pick the Apple TV first.");
    this._status("Checking...");
    try {
      const r = await this._hass.connection.sendMessagePromise({ type: "apple_tv_remote/info", entity_id: e });
      this._status("Remote: " + (r.remote || "not found") + ". Config entry: " + (r.config_entry_id ? "found" : "not found") + ". Keyboard focus sensor: " + (r.keyboard_sensor || "not found (the keyboard button still works)") + ".");
    } catch (err) {
      this._status(err && (err.code === "unknown_command" || /unknown/i.test(String(err.message || ""))) ? "The integration has not been updated yet. Restart Home Assistant (Settings > System > Restart) and try again." : "This entity is not an Apple TV of the core Apple TV integration.");
    }
  }
  _scrollParent(el) { for (let n = el.parentElement || (el.getRootNode() && el.getRootNode().host); n; n = n.parentElement || (n.getRootNode && n.getRootNode().host)) { const cs = getComputedStyle(n); if (/(auto|scroll)/.test(cs.overflowY) && n.scrollHeight > n.clientHeight + 1) return n; } return document.scrollingElement; }
  _visible() { return [...this._lRows.children].filter(r => r._row && r.style.display !== "none"); }
  _applyFilter() { const q = (this._filter.value || "").trim().toLowerCase(); [...this._lRows.children].forEach(r => { if (r._row) r.style.display = !q || r._row.name.toLowerCase().includes(q) ? "flex" : "none"; }); this._info(); }
  _info() { if (this._count) this._count.textContent = this._sel.size + " selected, " + this._visible().length + " shown"; }
  _bulk(show) { if (!this._sel.size) return; const rows = this._model; this._sel.forEach(r => { r.shown = show; }); this._sel = new Set(); this._commit(rows); }
  _renderList() {
    if (!this._lRows) return;
    this._sel = this._sel || new Set();
    const rows = this._lRows; rows.textContent = ""; this._model = this._rows();
    this._bar.style.display = this._selMode ? "flex" : "none"; this._selBtn.textContent = this._selMode ? "Done" : "Select";
    if (!this._model.length) { const d = document.createElement("div"); d.textContent = "No apps yet. The Apple TV has not reported its app list (is it on, and is the Apple TV picked above?)."; d.style.cssText = "font-size:13px;opacity:.7"; rows.appendChild(d); return; }
    const iconBtn = (icon, title, fn) => { const b = document.createElement("button"); const ic = document.createElement("ha-icon"); ic.setAttribute("icon", icon); ic.style.setProperty("--mdc-icon-size", "20px"); b.appendChild(ic); b.title = title; b.style.cssText = "flex:none;width:30px;height:30px;border:0;background:none;color:var(--secondary-text-color);cursor:pointer;padding:0;border-radius:50%;display:inline-flex;align-items:center;justify-content:center"; if (fn) b.addEventListener("click", fn); return b; };
    this._model.forEach(r => {
      const row = document.createElement("div"); row._row = r; row.style.cssText = "display:flex;align-items:center;gap:2px;padding:0 6px;border:1px solid var(--divider-color);border-radius:10px;min-height:34px;background:var(--card-background-color);box-sizing:border-box";
      if (!r.shown || r.missing) row.style.opacity = ".4";
      let handle;
      if (this._selMode) {
        const cell = document.createElement("div"); cell.style.cssText = "flex:none;width:46px;height:34px;display:flex;align-items:center;justify-content:center";
        const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = this._sel.has(r); cb.style.cssText = "width:20px;height:20px;margin:0;pointer-events:none;accent-color:var(--primary-color)"; cell.appendChild(cb); handle = cell;
        row.style.cursor = "pointer"; row.addEventListener("click", () => { if (this._sel.has(r)) this._sel.delete(r); else this._sel.add(r); cb.checked = this._sel.has(r); this._info(); });
      } else { handle = iconBtn("mdi:drag-horizontal-variant", "Drag to reorder"); handle.style.cursor = "grab"; handle.style.touchAction = "none"; }
      const nm = document.createElement("span"); nm.textContent = r.name + (r.missing ? " (not on this Apple TV)" : ""); nm.style.cssText = "flex:1;min-width:0;font-size:15px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
      row.append(handle, nm);
      if (!this._selMode) row.append(iconBtn(r.shown ? "mdi:eye" : "mdi:eye-off", r.shown ? "Hide this app" : "Hidden: show this app", () => { r.shown = !r.shown; this._commit(this._model); }));
      if (!this._selMode) {   // drag by the handle: the row lifts (scale + shadow), follows the finger and the others flow out of its way; it settles into its slot on release
        const EASE = "cubic-bezier(.2,.8,.2,1)", GAP = 4;
        let st = null;
        const place = () => {   // the lifted row follows the pointer; the rows it has passed flow aside by its height
          if (!st) return;
          const dy = st.y - st.y0 + (st.scroller ? st.scroller.scrollTop - st.s0 : 0);
          if (!st.moved && Math.abs(dy) > 2) { st.moved = true; row.style.transition = "box-shadow .18s"; }
          row.style.transform = "translateY(" + dy + "px) scale(1.03)";
          const dc = st.c[st.i] + dy; let to = st.i;
          if (dy > 0) { for (let k = st.i + 1; k < st.c.length; k++) if (st.c[k] <= dc) to = k; } else { for (let k = st.i - 1; k >= 0; k--) if (st.c[k] >= dc) to = k; }
          if (to === st.to) return;
          st.to = to; this._buzz();
          st.els.forEach((x, k) => { if (x === row) return; const sh = to > st.i && k > st.i && k <= to ? -(st.h[st.i] + GAP) : to < st.i && k >= to && k < st.i ? st.h[st.i] + GAP : 0; x.style.transform = sh ? "translateY(" + sh + "px)" : ""; });
        };
        handle.addEventListener("pointerdown", e => {
          e.preventDefault(); try { handle.setPointerCapture(e.pointerId); } catch (err) {}
          const els = [...rows.children].filter(x => x._row), scroller = this._scrollParent(rows);
          st = { els, i: els.indexOf(row), y0: e.clientY, y: e.clientY, scroller, s0: scroller ? scroller.scrollTop : 0, moved: false, h: els.map(x => x.offsetHeight), c: els.map(x => x.offsetTop + x.offsetHeight / 2) };
          st.to = st.i;
          els.forEach(x => { if (x !== row) x.style.transition = "transform .22s " + EASE; });
          row.style.cssText += ";position:relative;z-index:3;cursor:grabbing;box-shadow:0 10px 28px rgba(0,0,0,.5);background:color-mix(in srgb,var(--primary-color) 10%,var(--card-background-color))";
          row.style.transition = "transform .18s " + EASE + ", box-shadow .18s"; row.style.transform = "scale(1.03)";   // pops up on grab
          this._buzz();
          st.timer = setInterval(() => {   // near the top / bottom edge the list scrolls along
            if (!st.scroller) return;
            const rb = st.scroller === document.scrollingElement ? { top: 0, bottom: innerHeight } : st.scroller.getBoundingClientRect();
            if (st.y > rb.bottom - 70) st.scroller.scrollTop += 12; else if (st.y < rb.top + 70) st.scroller.scrollTop -= 12; else return;
            place();
          }, 16);
        });
        handle.addEventListener("pointermove", e => { if (st) { st.y = e.clientY; place(); } });
        const drop = () => {
          if (!st) return; const s = st; st = null; clearInterval(s.timer);
          let off = 0; if (s.to > s.i) for (let k = s.i + 1; k <= s.to; k++) off += s.h[k] + GAP; else for (let k = s.to; k < s.i; k++) off -= s.h[k] + GAP;
          row.style.transition = "transform .22s " + EASE + ", box-shadow .22s"; row.style.boxShadow = "0 0 0 transparent";
          row.style.transform = "translateY(" + off + "px) scale(1)";   // settles into its slot
          setTimeout(() => { if (s.to !== s.i) { const m = this._model, [it] = m.splice(s.i, 1); m.splice(s.to, 0, it); this._commit(m); } else this._renderList(); }, 240);
        };
        handle.addEventListener("pointerup", drop); handle.addEventListener("pointercancel", drop);
      }
      rows.appendChild(row);
    });
    if (this._selMode) this._applyFilter();
  }
  _schema() {
    return [
      { name: "entity", required: true, selector: { entity: { filter: [{ integration: "apple_tv", domain: "media_player" }] } } },
      { name: "height", selector: { text: {} } },
      { name: "pad_ratio", selector: { number: { min: 0.8, max: 2.5, step: 0.05, mode: "slider" } } },
      { name: "", type: "grid", schema: [{ name: "sources", selector: { boolean: {} } }, { name: "app_switcher", selector: { boolean: {} } },
                                         { name: "volume", selector: { boolean: {} } }, { name: "keyboard", selector: { boolean: {} } }, { name: "haptics", selector: { boolean: {} } }, { name: "show_border", selector: { boolean: {} } }] },
      { type: "expandable", title: "App tiles", icon: "mdi:apps", schema: [
        { name: "source_style", selector: { select: { mode: "dropdown", options: [{ value: "tiles", label: "Tiles (icon + name)" }, { value: "chips", label: "Chips (name only)" }] } } },
        { name: "source_rows", selector: { number: { min: 0, max: 6, step: 1, mode: "slider" } } },
        { name: "source_colors", selector: { boolean: {} } },
        { name: "source_icons", selector: { object: { multiple: true, label_field: "name", description_field: "icon", fields: {
          name: { required: true, selector: { text: {} } }, icon: { selector: { icon: {} } }, color: { selector: { text: {} } } } } } }] },
      { type: "expandable", title: "Touchpad", icon: "mdi:gesture-swipe", schema: [
        { name: "swipe_slow", selector: { number: { min: 30, max: 200, step: 1, mode: "slider" } } },
        { name: "swipe_fast", selector: { number: { min: 10, max: 100, step: 1, mode: "slider" } } },
        { name: "command_gap", selector: { number: { min: 60, max: 400, step: 10, mode: "slider" } } }] },
      { type: "expandable", title: "Advanced", icon: "mdi:tune", schema: [
        { name: "remote", selector: { entity: { filter: [{ integration: "apple_tv", domain: "remote" }] } } },
        { name: "keyboard_sensor", selector: { entity: { filter: [{ integration: "apple_tv", domain: "binary_sensor" }] } } }] },
    ];
  }
  _mkForm(onChange) {
    const f = document.createElement("ha-form");
    f.computeLabel = s => (LABELS[s.name] || [FIELD_LABELS[s.name] || s.title || s.name])[0];
    f.computeHelper = s => (LABELS[s.name] || [])[1] || "";
    f.addEventListener("value-changed", onChange); return f;
  }
  _panel(title, icon) {   // like the expandable sections of ha-form
    let panel;
    if (customElements.get("ha-expansion-panel")) {
      panel = document.createElement("ha-expansion-panel"); panel.header = title; panel.outlined = true; panel.setAttribute("outlined", ""); panel.leftChevron = true;
      const ic = document.createElement("ha-icon"); ic.setAttribute("slot", "icons"); ic.setAttribute("icon", icon); panel.appendChild(ic);
    } else { panel = document.createElement("details"); const sm = document.createElement("summary"); sm.textContent = title; sm.style.cssText = "cursor:pointer;padding:12px 4px;font-weight:500"; panel.appendChild(sm); }
    panel.style.cssText = "display:block;margin:8px 0";
    return panel;
  }
  _render() {
    if (!this._c) return;
    if (!this._form) {
      const onChange = e => {
        e.stopPropagation();
        const v = { ...e.detail.value }, out = { type: this._c.type || "custom:atv-touchpad" };
        Object.keys(v).forEach(k => { if (v[k] !== undefined && v[k] !== "" && !(Array.isArray(v[k]) && !v[k].length) && !(k in DEFAULTS && v[k] === DEFAULTS[k] && !(k in this._c))) out[k] = v[k]; });   // keep the YAML short: untouched defaults are not written
        this._c = out; this._emit(out);
        if (this._sigE !== out.entity) { this._sigE = out.entity; this._renderList(); }
      };
      const all = this._schema(), i = all.findIndex(x => x.title === "App tiles");
      this._form = this._mkForm(onChange); this._formB = this._mkForm(onChange);
      this._form.schema = all.slice(0, i); this._formB.schema = all.slice(i + 1);
      const sectionForm = this._mkForm(onChange); sectionForm.schema = all[i].schema; this._formS = sectionForm;
      const panel = this._panel("App tiles", "mdi:apps"), inner = document.createElement("div"); inner.style.cssText = "padding:4px 8px 8px";
      inner.append(sectionForm, this._listUi()); panel.appendChild(inner);
      this.append(this._form, panel, this._formB);
    }
    if (this._hass) this._form.hass = this._formS.hass = this._formB.hass = this._hass;
    this._sig = JSON.stringify(this._appNames()); this._sigE = this._c.entity;
    this._renderList();
    const d = { ...DEFAULTS, ...this._c };
    if (d.source_icons && !Array.isArray(d.source_icons)) d.source_icons = Object.entries(d.source_icons).map(([name, v]) => typeof v === "string" ? { name, icon: v } : { name, ...v });
    if (!Array.isArray(d.source_icons)) d.source_icons = [];
    this._form.data = this._formS.data = this._formB.data = d;
  }
}
if (!customElements.get("atv-touchpad-editor")) customElements.define("atv-touchpad-editor", AtvTouchpadEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "atv-touchpad", name: "Apple TV remote", description: "Touchpad remote with app tiles for an Apple TV" });
