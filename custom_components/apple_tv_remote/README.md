# Apple TV Remote

[![Marketplace: Custom](https://img.shields.io/badge/Marketplace-Custom-41BDF5.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.8%2B-41BDF5.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A Lovelace card plus a small integration that turns a phone into an Apple TV remote: touchpad, circle-to-scrub (including
Apple's jog ring), the player buttons from Apple's Remote app, app tiles with real App Store icons, keyboard, mute and a
progress bar you can drag.

It builds on the core `apple_tv` integration (pyatv). The card uses its remote / media player entities for the basics; the
integration adds websocket commands for what core doesn't expose: touch events, held keys, skip, volume-based mute.

![Apple TV Remote](images/hero.png?v=4)

<sub>Images are rendered from the card's own code with sample data, dark theme. The card follows your HA theme.</sub>

## Why

The core integration gives you arrow keys, which is fine for menus and useless for scrubbing. Apple's Remote app does
scrubbing with a continuous touch stream over the Companion protocol; this card does the same from a dashboard, so you don't
have to leave HA to find your place in a video.

## Requirements

- HA 2024.8+ with the core **Apple TV** integration paired (that pairing also sets up the Companion link this needs).
- Volume / mute only work if the Apple TV controls your TV or soundbar volume (HDMI-CEC or IR).

## Install

**Marketplace (HA 2026.11+):** *Settings → Marketplace → ⋮ → Custom repositories*, add
`https://github.com/vandalon/ha-apple-tv-remote` as type *Integration*, download, restart HA.

[![Open in Marketplace](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=vandalon&repository=ha-apple-tv-remote&category=integration)

**Older HA:** same steps in HACS (sidebar).

**Manual:** copy `custom_components/apple_tv_remote` into `config/custom_components/` and restart.

Then *Settings → Devices & services → Add integration → Apple TV Remote*. Single entry, nothing to configure.
The card registers its own frontend resource; no need to add one.

> The Python side only loads at startup. Restart HA after every update, not just reload.

## Minimal config

```yaml
type: custom:atv-touchpad
entity: media_player.living_room_apple_tv
```

The card finds the remote entity, config entry and keyboard-focus sensor of the same device itself. Editor → *App tiles →
Check setup* shows what it found.

What I run on a phone (the hero image):

```yaml
type: custom:atv-touchpad
entity: media_player.living_room_apple_tv
source_rows: 4
app_names: false        # icons only
player_buttons: true    # 10 s back, info, 10 s forward
edge_arrows: false      # every tap is select
swipe_hold: false
swipe_sensitivity: 1.5
logo_text: tv
volume_row: top
power_position: bottom
nav_order: home,back,play
pad_ratio: 1.15
side_padding: 0         # edge to edge: the card sits in a pop-up with its own frame
top_padding: 0
bottom_padding: 0
show_border: false
```

## How it works

![Card](images/card.png?v=4)

### Touchpad

Swipe = arrow keys, tap = select. Step distance depends on speed (`swipe_slow` / `swipe_fast` px per step), and commands are
spaced at least `command_gap` ms apart because the Apple TV drops faster ones. With `edge_arrows` a tap near an edge sends
that arrow. Swipes on the pad never reach the pop-up around it.

**Swipe and hold** (`swipe_hold`): move ~30 px sideways and rest, and the arrow key is held until you lift (fast forward /
rewind). Moving the finger further out or back steps the speed up or down; what a step means is per app (`hold_profiles`).

### Circle to scrub

![Jog ring](images/card-ring.png?v=4)

With `circle_scrub` on, a faint ring sits round the logo. Going round scrubs: clockwise forward, anticlockwise back, for as
long as you keep turning.

- Start on the ring and it scrubs straight away. Start anywhere else and a circle is recognised after about a quarter turn,
  so straight swipes stay arrow keys.
- Under the hood the turning becomes one long sideways touch on the Apple TV, like a Siri Remote clickpad. One turn at a
  normal pace is one full-width swipe (`circle_turn: 1000`); Netflix scrubs less per swipe, so it gets 2700 by default.
- Faster turns go further (`circle_accel`, 0.1x … 3x; `0` = linear). A light haptic tick every 1/12 turn.
- Netflix ignores short fast swipes, so there a circle becomes calm edge-to-edge swipes (`circle_sweep_apps`).

**Jog ring:** Apple's own player (the Apple TV app, and apps that use it) has the Siri Remote's jog ring. Rest your finger
for `ring_hold` ms (350), then go round: your angle on the pad maps to the angle on the TV's ring. A playing video pauses
for it (`ring_pause`) and resumes when you let go (`ring_resume`). YouTube, Netflix, Disney+ etc. use their own player and
have no ring; a plain circle works there. Resting first is a quick test of which player an app uses.

### Progress bar and time

While the app reports a real position and duration (Apple TV app yes, YouTube / Netflix no), a slim progress bar sits under
the pad and the time shows at the top of it. Dragging calls `media_seek` live, about every 0.3 s, plus a final one on release.
If an app ignores the seek, the bar is hidden for that app on that device.

### Player buttons

`player_buttons: true` adds Apple's Remote-app row to the bottom of the pad: rewind / info / fast forward. Tap = the Apple
TV's own skip (`skip_seconds`), hold = rewind / fast forward until release. Info is a Down press.

### Mute

There's no mute key on an Apple TV. Holding volume down (0.6 s) sets the volume to 0 and remembers the level; hold again
to restore (`mute_hold`).

### Keyboard

![Keyboard](images/card-keyboard.png?v=4)

The core integration has a *Keyboard focus* binary sensor (often hidden). When it turns on, the text box opens and input
goes straight to the Apple TV. The keyboard button toggles it by hand when focus isn't reported.

### Quick settings

![Settings](images/card-settings.png?v=4)

The cogwheel on the pad: swipe sensitivity, circle speed / acceleration per app (applies to the app on screen, or to all
apps when none is open), skip seconds, haptics, tile rows, app names, and the app list (show / hide, drag to reorder,
rename). Changes are written back to the card's config on the dashboard, so they apply to everyone. Admins only.

![App settings](images/card-settings-apps.png?v=4)

### App tiles

![Tiles](images/tiles.png?v=4)

- One tile per app the Apple TV reports. More than fit (`tiles_across` × `source_rows`) go on pages; a swipe moves one page.
- `source_order` is both filter and order. Empty = all.
- A tile wakes a sleeping Apple TV first. While it's off the Apple TV reports no apps, so the card keeps the last list it saw
  (per browser, `localStorage`).
- Icons, in order of precedence: `source_icons` → built-in `OWN_LOGOS` → stock tiles for Apple's apps → App Store icon →
  colour plate with an MDI symbol (stable colour per name).

```yaml
source_icons:
  Plex: mdi:plex
  My app: { icon: mdi:rocket, color: "#107c10" }
  "Foto's": { image: /local/app-logos/photos.svg, color: "#ffffff" }   # your own image on a plate
  TV: { image: /local/app-logos/appletv.svg, fill: true }              # 5:3 image that is the whole tile
```

**App Store icons:** the integration reads the Apple TV's app list (bundle ids), looks each one up once per HA run on
`itunes.apple.com` (your HA country), and caches the icon in `config/apple_tv_remote_icons/` (with `index.json`). HA serves
them at `/apple_tv_remote/icons/...`, so phones never talk to Apple. A weekly background check re-downloads only changed
icons, written atomically. Delete the folder to start over; `app_icons: false` turns it off.

**Apple's own apps** aren't in the App Store under their tvOS ids. They're matched by app id (so any Apple TV language
works) to whole-tile images: this build embeds tvOS-style tiles for them (`STOCK_EMBED` in `atv-touchpad.js`), and files in
`config/www/app-logos/tvos/` (`stock_tiles`) are used where nothing is embedded. File names: `Apple-TV.svg`, `Music.svg`,
`Photos.svg`, `Apple-Arcade.svg`, `Fitness.svg`, `App-Store.svg`, `Podcasts.svg`, `FaceTime.svg`, `Settings.svg`,
`Search.svg`, `Apple-Music-Sing.svg`, `Home-Sharing.svg`. `apple_app_icons: true` uses their iPhone App Store icon instead.

### Editor

Every option except the per-app maps (`circle_turn_apps`, `hold_profiles`) is in the visual editor (*Edit card*): layout and
buttons on top, then *App tiles*, *Touchpad* (swipe and hold, circle scrubbing, player buttons) and *Advanced* (remote and
keyboard sensor, found automatically). Only changed options are saved to YAML.

![Editor](images/editor.png?v=4)

*App tiles* lists the apps your Apple TV reports: drag to reorder, the eye to hide, **Select** for bulk hide / show,
**Show all apps again** and **Check setup**.

| ![App list](images/editor-apps.png?v=4) | ![Select](images/editor-select.png?v=4) |
|---|---|

### Talking to the Apple TV

Keys, apps and keyboard go through core's entities. Touch, held keys, skip and mute go through this integration's websocket
commands, using the Companion connection core already holds (pyatv), with a 60 Hz smoothed touch stream.

Two things worth knowing if you hack on this:

- pyatv's OPACK encoder writes ints as small as possible, so a touch coordinate of 128–255 goes out as one byte and the
  Apple TV reads it as negative (the first scrub jumps the wrong way). The integration always sends 2-byte coordinates,
  like Apple's Remote app.
- Core's Apple TV entry sometimes stays "not connected" (e.g. the Apple TV slept through a restart). `apple_tv_remote/reconnect`
  reloads that entry, only when `runtime_data.atv` is `None` and at most every 30 s. The card calls it before power-on / a
  tile, and once a minute while the remote is on screen and the Apple TV looks off.

Because this reaches into the core integration, a core update can break touch / scrubbing. The rest of the card keeps
working, and the card shows *Touch scrubbing is not available* when the Companion link doesn't answer.

## Options

**General**

| Option | Default | |
|---|---|---|
| `entity` | — | Apple TV `media_player` (required) |
| `remote` / `keyboard_sensor` | auto | Only if auto-detection fails |
| `height` | `auto` | `auto` or any CSS height (pad fills the spare space) |
| `pad_ratio` | `1.3` | Pad width / height with `height: auto` |
| `side_padding` / `top_padding` / `bottom_padding` | `12` | Margins in px; `0` = none |
| `screen_corners` | `true` | Bottom row follows rounded screen corners (iOS) |
| `screen_radius` | built in | Corner radius in px: one number, or per screen size `{"402x874": 62}` |
| `show_border` | `true` | `false` for pop-ups with their own frame |
| `settings_button` | `true` | Cogwheel with quick settings |
| `haptics` | `true` | Vibrate on taps |
| `idle_paused_apps` | `[Netflix]` | Apps that report `idle` while paused; treated as paused |

**App tiles**

| Option | Default | |
|---|---|---|
| `sources` | `true` | Tiles on / off |
| `source_order` | all | Filter + order |
| `hide_sources` | — | Names to leave out |
| `source_names` | — | Own label per app |
| `source_style` | `tiles` | `tiles` or `chips` |
| `source_rows` | `1` | Lines; `0` = as many as needed |
| `tiles_across` | `4` | Tiles across the card width |
| `source_colors` | `true` | Colour the tiles |
| `source_icons` | — | Icon / colour / image per app |
| `app_icons` | `true` | tvOS-shaped tiles with App Store icons; `false` = plain tiles |
| `app_names` | `true` | Name under each tile |
| `stock_tiles` | `/local/app-logos/tvos` | Folder for Apple-app tile images; `false` = off |
| `apple_app_icons` | `false` | iPhone App Store icons for TV, Music, Podcasts, Fitness, Photos |

**Buttons and layout**

| Option | Default | |
|---|---|---|
| `nav_order` | `back,home,play` | Order of the bottom buttons |
| `volume` | `true` | Volume buttons |
| `mute_hold` | `true` | Hold volume down to mute |
| `app_switcher` | `true` | Double-press TV / Home |
| `power_position` | `top` | `bottom` = power replaces the app switcher in the volume row |
| `volume_row` | `bottom` | `top` = volume row above the pad |
| `keyboard` | `true` | Keyboard button |
| `player_buttons` | `false` | Rewind / info / fast forward row on the pad |
| `skip_seconds` | `10` | Seconds per skip |
| `progress_bar` | `true` | Draggable progress bar (apps that report position) |
| `show_time` | `true` | Position / duration on the pad |
| `edge_arrows` | `true` | Arrows on the pad, tap near an edge = that arrow |
| `logo_text` | — | Word after the Apple logo, e.g. `tv` |

**Touchpad**

| Option | Default | |
|---|---|---|
| `swipe_sensitivity` | `1` | Divides `swipe_slow` / `swipe_fast` |
| `swipe_slow` / `swipe_fast` | `96` / `22` | px per step, slow / fast swipe |
| `command_gap` | `140` | ms between pad commands |
| `swipe_hold` | `true` | Swipe and hold = held arrow key |
| `hold_swipe` | `30` | px sideways before a rest starts the hold |
| `swipe_hold_ms` | `500` | ms rest before the hold starts |
| `hold_notch` | `40` | px out / in per speed step |
| `hold_profiles` | TV: `cycle`, YouTube: `smooth`, Netflix: `step` | Per app: `cycle`, `smooth`, `step`, `hold` (YAML only) |

**Circle to scrub**

| Option | Default | |
|---|---|---|
| `circle_scrub` | `true` | On / off |
| `circle_turn` | `1000` | Touch units per turn (1000 = full-width swipe) |
| `circle_turn_apps` | Netflix: `2700` | Per app (YAML only) |
| `circle_speed` / `circle_speed_apps` | `1` | Speed factor, global / per app |
| `circle_accel` / `circle_accel_apps` | `1` | Acceleration, global / per app; `0` = linear |
| `circle_sweep_apps` | `[Netflix]` | Apps that get calm edge-to-edge swipes (`*` = all) |
| `circle_native_apps` | — | Apps where a plain circle uses the jog ring (`*` = all) |
| `ring_hold` | `350` | ms rest for the jog ring |
| `ring_pause` / `ring_resume` | `true` | Pause on the ring, play on release |

## Storage

- Card options: the dashboard.
- Last known app list per Apple TV: browser `localStorage`.
- App Store icons: `config/apple_tv_remote_icons/`.

## Troubleshooting

- **Card missing from the picker:** restart HA, check the integration entry exists, hard-reload (Companion app:
  *Settings → Debugging → Reset frontend cache*).
- **Buttons do nothing:** editor → *Check setup*. If no remote is found, set `remote`.
- **"Integration not updated":** you updated without restarting.
- **No keyboard button:** needs the integration entry and one restart.
- **Text box doesn't open by itself:** enable the *Keyboard focus* sensor, or set `keyboard_sensor`.
- **App switcher does nothing:** it's two Home presses 0.2 s apart; some setups don't react. `app_switcher: false`.
- **Swipes get skipped:** raise `command_gap` or `swipe_slow`.
- **Circles do nothing:** `circle_scrub` on, HA restarted; if the card says *Touch scrubbing is not available* the Companion
  link isn't answering.
- **No jog ring on the TV:** only Apple's player has one, and the progress bar must be on screen. Use a plain circle elsewhere.
- **Scrubs too much / too little:** circle speed and acceleration under the cogwheel.
- **Tile missing:** the Apple TV only lists launchable apps; check `source_order` / `hide_sources`.

## Contributing

Bugs and PRs: [issues](https://github.com/vandalon/ha-apple-tv-remote/issues). This repo is exported from a larger HA
config, so PRs get applied there and re-exported.

## License

MIT
