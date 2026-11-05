# Caduceus

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-cakelesscoder-FFDD00?logo=buymeacoffee&logoColor=000)](https://buymeacoffee.com/cakelesscoder)

**Caduceus** is a set of open-source firmware patches for the **Olympus PEN E-P7** (firmware 1.1). It adds
film simulations you pick and edit in the camera, per-colour hue and lightness, bloom, clarity and Art
Effects on your colour profiles, B&W film presets, true log video, XPan and 21:9 stills, and longer video
recording.

*Named after the caduceus, the staff of Hermes: messenger between gods and mortals and guide of travellers.*

**Latest release: [v0.25](https://github.com/cakelesscoder/caduceus-ep7/releases/tag/v0.25)** ·
**[Install guide](docs/INSTALL.md)** · **[Changelog](CHANGELOG.md)** · **[Caduceus Control Panel](https://cakelesscoder.github.io/caduceus-ep7/)** (make and share looks in your browser) · The camera's Setup › Firmware screen shows the Caduceus version.

> [!WARNING]
> **Early development, use at your own risk.** Caduceus is unofficial, experimental firmware modification.
> Bugs will turn up, and flashing modified firmware can crash, freeze or brick your camera, corrupt photos or
> damage your SD card's data. **The author accepts no responsibility for any damage, data loss or other harm**
> to your camera, cards, files or anything else. It is provided "as is", without warranty of any kind (see the
> [Apache License 2.0](LICENSE), sections 7–8). Using it may affect your warranty with OM Digital Solutions.
>
> Every patch is checked in an emulator of the camera's CPU before it goes on a camera, the SD update and
> restore path is proven on a real E-P7 (including recovery from a bootloop), and features marked
> **camera-tested** below have run on a real camera. Read [Safety](#safety) before flashing.

![Film looks on four scenes](docs/img/film_looks_v3.jpg)

## Features

| Feature | What you get | Status |
|---|---|---|
| **Film simulations** | 29 colour looks in `EP7MOD/LOOKS.BIN`: Velvia, Astia, Classic Chrome, Classic Neg, Provia 400, Reala Ace, Eterna, Bleach Bypass, Kodachrome 25 and 64, Portra 160 and 400, Ektar 100, Gold 200, Ektachrome, UltraMax 400, CineStill 50D and 800T, Vision3 250D and 500T, Pro 400H, Fujicolor 200, Cuban Neg (inspired by Osan's Classic Cuban Neg), Agfa Vista, Cibachrome, Polaroid, Cross Process, Atrophy (inspired by [Gx]Ace) and Faux IR (an infrared-inspired false-colour look). Pick one per Colour Profile slot; its name shows in Picture Mode. | Camera-tested |
| **On-camera look editor** | The stock Colour Profile wheel gains pages: Saturation, Hue, Light, Film and Extras (INFO cycles). The wheel follows the page; modified looks are marked `*`. | Camera-tested |
| **Looks on the SD card** | Looks load from `EP7MOD/BUNDLES.BIN` on the first half-press. Edits made in the camera save back to the card (with a `.BAK` of the previous file). | Camera-tested |
| **Tone per look** | Every film look carries its own tone curve: Highlights, Midtones and Shadows (applied through the camera's own tone control) plus new **Blacks** and **Whites** that move the very ends of the curve (crushed slide-film blacks, faded instant-film blacks, rolled-off negative highlights). Picking a look applies it, and from v0.24 sets the look's per-colour saturation too; Blacks/Whites are also adjustable per profile (Extras 6/7). Shown in live view too. | New in v0.20 |
| **LCD colour fix** | The rear screen no longer looks slightly pink (+8 % green by default), and Monitor Adjust's colour slider becomes a green ↔ magenta slider (−7..+7, about 2.3 % per step) instead of warm/cool. Display only: photos, movies and HDMI are unchanged. | New in v0.20 |
| **Extras per profile** | Bloom ↔ clarity (one slider), WB amber/blue and green/magenta shift, and Art Effects (Star Light, Pin Hole; Blur removed in v0.21, it could restart the camera). | Camera-tested |
| **Noise reduction per look** | Each colour look can set the camera's own noise reduction (Noise Filter) per profile. Less noise reduction keeps the sensor's natural fine texture instead of smoothing it away. Extras sector 1 **NR**: **Camera** (use the camera's setting), **Std**, **Low** or **Off** (most texture). It applies at each photo and follows a profile switch, without changing the menu setting. The difference shows mostly at higher ISO. True film grain is on the roadmap (the camera's grain stages add nothing visible to colour photos). | Camera-tested (setting recorded in the photo; pixel comparison still to do) |
| **Lens vignette correction off per look** | Picking a look turns the camera's lens shading correction off for that profile, for natural corners, without changing the menu setting. Extras sector 8 changes it (**VigFix Off** / **VigFix Camera**), and a look can keep the correction in the Control Panel. | **New in v0.25, please report:** not yet confirmed on photos. See [how to test](#vignette-correction-reports-wanted) |
| **Mono film presets** | Pan F 50, Acros, T-Max 100, SFX 200, Tri-X 400, HP5 Plus, Delta 3200, Sepia Print, Selenium, Cyanotype for Monochrome Profiles, built from OM's own mono settings. Label `<name>`, `*` when modified. | Camera-tested |
| **Live-view preview** | Hue, lightness and bloom show in live view, not only in the saved photo. | Camera-tested |
| **True log video** | A log curve Olympus left hidden in the firmware, switched on with the **movie** picture mode set to Muted. | Camera-tested |
| **XPan 65:24 and 21:9** | Panorama (5184×1920) and Wide (5184×2224) in the menu and Super Control Panel, with matching live view and playback framing, `XP` and `21:9` icons in the Super Control Panel option strip, and `XPAN`/`UW` size labels. Boots back to 4:3 each power-on, for safety. | Camera-tested |
| **Recording limit** | 29-minute and 2-hour caps raised to 9 hours (file, chapter and heat limits still apply). | Camera-tested |

## Install

You need: an E-P7 on firmware **1.1** (check *Setup › Firmware*), a **fully charged battery**, an SD card,
and a computer with [Python 3.10+](https://www.python.org/downloads/) (Windows, macOS or Linux).

### 1. Get Caduceus

On this page click **Code › Download ZIP** and unzip it (or `git clone` the repo).

### 2. Build the update file on your computer

OM's licence doesn't allow anyone to share their firmware, so the update file is made on your own computer.
The builder downloads OM's official 1.1 firmware from OM's server, checks it, and applies the Caduceus patches.

- **Easiest:** in the unzipped folder, double-click the launcher for your system:
  - Windows: `Build Caduceus (Windows).bat`
  - macOS: `Build Caduceus (Mac).command` (the first time: right-click › **Open**)
  - Linux: `build-caduceus-linux.sh`
- **Or from a terminal** in that folder: `python3 caduceus.py build --release v0.25`
  (Windows: `py caduceus.py build --release v0.25`).

It creates a folder with:

```
DCOLYMP/E1429999.BIN   the patched firmware update      → goes on the SD card
EP7MOD/                the film looks and your slots      → goes on the SD card
restore/E1429999.BIN   the original stock firmware        → keep on your computer (to undo Caduceus)
```

### 3. Copy to the SD card

Put the camera's SD card in your computer and copy the **`DCOLYMP`** and **`EP7MOD`** folders to the top
level of the card (next to the `DCIM` folder). The launcher offers to do this for you. Eject the card properly.

### 4. Flash the camera

1. Put the card in the camera. **Battery fully charged**, camera **off**.
2. **Hold the OK button** and switch the camera **on**. Keep holding OK until the status light comes on.
3. The light stays **steady** while the update is written (it can take as little as 10 seconds). **Do not switch off, open the
   battery door or remove the card.**
4. When the light starts **blinking (about twice a second)**, it's finished. Switch the camera off.
5. Switch it on normally. *Setup › Firmware* now shows **Caduceus** and the version.
6. On a computer, delete `DCOLYMP/E1429999.BIN` from the card (keep `EP7MOD`: that's where your looks live).

If the light blinks fast straight away with no steady phase, the camera rejected the file and nothing was
written. Rebuild and copy again.

### 5. Shoot

Switch on, **half-press the shutter once** (that loads the looks from the card), then open a Colour Profile
and press **INFO** to reach the Film page. See [Using it](#using-it).

### Undo / go back to stock

Copy `restore/E1429999.BIN` from your computer to the card as `DCOLYMP/E1429999.BIN` (replacing the patched
one) and flash it exactly as in step 4. The camera is then completely stock 1.1 again.

More detail, troubleshooting and FAQ: **[docs/INSTALL.md](docs/INSTALL.md)**.

## Make your own looks: Caduceus Control Panel

**[Caduceus Control Panel](https://cakelesscoder.github.io/caduceus-ep7/)** is where you edit the built-in looks
and make new presets, right in your browser:

- Tweak any look (per-colour hue, lightness and saturation, noise reduction, glow/clarity, WB shift, Art Effect), or
  start a new one, with a live preview on example photos or your own (your photo never leaves your browser).
- **Share a look with a short code:** press *Share*, send the code or link, and anyone can paste it into the
  Control Panel to get the same look.
- **Export** your pack as `LOOKS.BIN`, copy it to `EP7MOD/` on your SD card, half-press, and your looks are
  on the camera's Film page.
- **RapidRAW presets (no firmware needed):** a look's *Share* button (or *Export › RapidRAW presets*) saves it as a
  `.rrpreset` for [RapidRAW](https://github.com/CyberTimon/RapidRAW), the free raw editor; Export can also zip all
  of them, one preset per look (unzip, then Presets › Import and select the files). Use
  it to apply the looks to your ORF files after the shot, or to raws from **any camera**, so you can use the looks
  without a modded body. It's an approximation: RapidRAW starts from its own raw rendering, so expect the look's
  character rather than an exact match to the camera JPEG. Colour, tone, white balance, glow/halation, clarity,
  vignette and the mono filter carry over; noise reduction and Art Effects don't.
- **Install firmware:** the *Install firmware* button walks you through installing Caduceus step by step, with
  links to the latest release and the full guide.

## Using it

**On the card** (copy `EP7MOD` from the build to the card's top level):

```
EP7MOD/LOOKS.BIN     the film library (the looks you can pick)
EP7MOD/BUNDLES.BIN   your 4 Colour Profile slots: which look each holds, plus your edits (the camera rewrites it)
```

**Every time you switch on:** **half-press the shutter once**. That loads your looks from the card (nothing is
read at boot). No `EP7MOD` folder = the camera behaves almost stock.

**Pick a film look**
1. Picture Mode → a **Colour Profile** (COLOR1–4); its name shows in the Picture Mode list.
2. Open that profile's colour wheel, press **INFO** until the page shows `Film: <name>` (the Film page).
3. Turn the dial to scroll looks (`Film: Velvia`, `Film: Portra 400`, … `Stock`). Leave the editor and **half-press** to save.

Picking a look sets that profile's colours, noise reduction, glow/clarity, WB shift, Art Effect and tone curve.
Saturation stays yours. A `*` after the name means you've changed something since picking it.

**Fine-tune a look** (same colour wheel, **INFO** cycles the pages):

| Page | What the dial does |
|---|---|
| Saturation (· All) | stock per-colour saturation (INFO also toggles single colour / all colours) |
| Hue / Light | shift or brighten/darken one colour sector (pick the sector with the other dial) |
| Film | choose a look from the library |
| Extras | sector 1 NR Camera / Std / Low / Off (noise reduction) · 2 glow ← → clarity · 3 WB amber/blue · 4 WB green/magenta · 5 Art Effect · 6 Blacks · 7 Whites · 8 VigFix Off / Camera (lens vignette correction) |

Highlights/Midtones/Shadows are on the camera's normal tone-curve screen; picking a look sets them for you.

**Mono film presets:** Picture Mode → a **Monochrome Profile** → open its Colour Filter (or Shading) editor →
**INFO** steps Pan F, Acros, T-Max, Tri-X, HP5, Delta 3200, Sepia… (name shown on screen).

**Make, change or share looks:** use the [Caduceus Control Panel](https://cakelesscoder.github.io/caduceus-ep7/).
Edit sliders with a live preview, press **Share** for a short code anyone can paste in, and **Export** a new
`LOOKS.BIN` to copy into `EP7MOD/`.

**Log video:** in movie mode set the **movie** picture mode to **Muted**. You record the camera's hidden log curve
(live view looks flat too). Grade it afterwards.

**XPan / 21:9:** Image Aspect (menu or Super Control Panel) → **Panorama** (65:24) or **Wide** (21:9). The camera
boots back to 4:3 each time, on purpose.

**Screen too pink or green?** Setup › Monitor Adjust: the colour slider is now green ↔ magenta (0 = corrected).

**Quick answers**
- *Nothing changed?* Half-press once after switching on, and check `EP7MOD/` is at the card's top level.
- *Want stock back for a moment?* Remove the `EP7MOD` folder. *For good?* Flash the restore file (see Install).
- *Will updating lose my looks?* No: keep your `EP7MOD/BUNDLES.BIN`, and just replace `LOOKS.BIN` and the firmware.
- *Live view vs photo:* Star Light and some effects only show in the saved photo.
- *Black screen during Rec View on bloom/clarity looks?* Known issue: the review goes dark while the effect is
  processed. The photo is fine: set Rec View to **Auto ▶** or press **▶** to see it.
- *Sector 1 "NR"?* It sets the camera's noise reduction (Noise Filter), not film grain; Off keeps the most texture. It shows mostly at higher ISO and applies per profile at each photo.
- *Super Control Panel shows 4:3 on Panorama or Wide?* Known issue: the option strip shows `XP` and `21:9`, but the current-value cell still shows the 4:3 icon. The setting and the photo are right.

### Vignette correction: reports wanted

v0.25 turns the camera's lens vignette correction off for each look. The firmware setting is confirmed, but whether it changes the corners of a photo isn't yet. If you try it, a report helps a lot, as an [issue](https://github.com/cakelesscoder/caduceus-ep7/issues) with your lens and the two photos if you can:

1. Use M mode on a tripod, with an evenly lit plain wall, at the lens's widest focal length and aperture.
2. Take one photo with Extras sector 8 on `VigFix Off` and one on `VigFix Camera`, at the same exposure.
3. Compare the corners: with correction off they should be darker, and should match the camera's Shading Comp. Off menu setting.

### On-camera UI

The images below are **mock-ups made on a computer to preview the features**. On the camera nothing new is
drawn: Caduceus reuses the camera's own screens, fonts and icons, so everything looks exactly like the
stock E-P7 UI. The colour wheel gets extra pages and its guide line shows the page or look name.

| Stock Colour Profile editor | Look editor (mock-up) |
|---|---|
| ![](docs/img/ui_colour_profile_stock.jpg) | ![](docs/img/ui_look_editor_mock.jpg) |
| **Image Aspect menu (mock-up)** | **XPan framing (mock-up)** |
| ![](docs/img/ui_aspect_menu.jpg) | ![](docs/img/ui_xpan_framing.jpg) |

### Film looks

Recipes built only from controls the patched camera has. The previews above are from the desktop simulator
on E-P7 RAW files, so the camera's JPEGs can differ slightly. Several looks are converted from community
Olympus recipes (GarethB's Kodachrome 25 on mu-43.com, and om-recipes.com); sources and credits are in
[docs/LIBRARY_V1.md](docs/LIBRARY_V1.md).

### Make and share look packs

Use the **[Caduceus Control Panel](https://cakelesscoder.github.io/caduceus-ep7/)**: edit or create looks, share
them as short codes, download `LOOKS.BIN` for your card, or export them as RapidRAW presets for raw files
from any camera. Nothing to install. (Developers: the source is in
[`webapp/`](webapp/README.md).)

### Log video

The E-P7 firmware already contains a proper log curve (about 12.4 % of output per stop) and a Flat curve:
the same kind of profiles Olympus ships as OM-Log400 and Flat on other TruePic VIII bodies. On the E-P7 they
are simply hidden: no menu can select them. Caduceus switches the log curve on when the movie picture mode is
Muted. Left: the standard curve. Right: the hidden log curve, rendered with the firmware's own tone table.

![Standard vs log](docs/img/log_vs_standard.jpg)

## Build on Caduceus

Caduceus is meant to be a starting point, not a walled garden. The goal is an **open film-recipe community for
Micro Four Thirds**, the way Fujifilm shooters share film simulation recipes, but for OM/Olympus bodies.
Fork it, port it, remix it:

- **Port it to your camera.** The patch tooling (`caduceus.py`, `tools/build_package.py`, the edit-list format and
  the emulator checks) is camera-agnostic. Other TruePic VIII bodies share most of the code base; see
  [docs/PORT_EM10IV.md](docs/PORT_EM10IV.md) for what carries over to the E-M10 IV.
- **Keep the shared formats.** Please keep `LOOKS.BIN`, the look parameters and the **share codes** compatible (or
  versioned) so a look made on one project works everywhere. The format is documented in
  [webapp/README.md](webapp/README.md).
- **Use the Control Panel.** [Caduceus Control Panel](https://cakelesscoder.github.io/caduceus-ep7/) is the common
  place to make, preview and share looks. Fork it for your camera, or send changes back so everyone gets them.
- **Share your looks.** Post the share code with a sample photo (Reddit, forums, socials); anyone can paste it into
  the Control Panel. Good community looks can be added to the built-in library: open an issue or PR with the
  code, a sample, and credit for any recipe it's based on.
- **Credit and licence.** Apache 2.0: use it in your own projects, commercial or not. Keep the `NOTICE`, credit
  recipe authors, and never redistribute OM firmware (ship edit lists plus a builder, like Caduceus does).

## Roadmap

Grouped by how likely and how hard each item is. Feasibility notes for the video and lens items are in
`docs/VIDEO_HIDDEN.md`.

**Likely / easy**
- Art Effect live-view preview that updates immediately.
- More film looks, and a cross-platform web app to build and share `LOOKS.BIN` files.
- Control Panel camera selector: export the same looks for other cameras (built, hidden until other cameras have known-good builds).

**Possible / medium effort**
- Super Control Panel current-value cell: show `XP` / `21:9` instead of 4:3 on Panorama and Wide.
- Clean HDMI output: stock Record Mode (sid 1276) exists, but more than one gate is involved (`docs/VIDEO_HIDDEN.md` §1).
- Rec View that shows the photo and then updates it with bloom/clarity, instead of a black screen (`docs/ISSUES_19_20.md`).
- **True film grain on colour photos** (the camera's own grain stages add nothing visible to colour; needs a new approach).
- ISO Auto in movie M: the movie ISO list already includes Auto; the dynamic gate in the AE code still has to be found.
- Blacks/Whites page on the camera's own tone-curve screen (today they live on Extras 6/7; `docs/TONE_ENDS.md` §8).
- An added vignette for colour profiles, using the stock shading stage (`docs/VIGNETTE.md`).
- Tinted halation (red glow around white lights), probably via a mask built from the exposure meter grid.
- Maybe: use the ART position on the mode dial as a quick "silent shutter" switch.
- **Lens buttons (L-Fn / AF stop on Pro lenses):** the key events, the button settings (sids 54-56 with 28-29-function lists)
  and the movie-mode key gate all exist in the E-P7 firmware; whether the Button Function menu shows a lens row, and
  whether the body receives the lens key, needs a camera probe. If only the row is hidden this moves to "easy"
  (`docs/LENS_BUTTONS.md`). Next step is tracing which Button Function row is the lens button and what gates it (a few hours,
  then a small patch if gated, about half a day if a row has to be added); testing needs an OM Pro lens with an L-Fn button.
- Canon 1100D (Rebel T3): no firmware hack; export looks as Canon Picture Style (.PF2) files, if the PF2 checksum can be
  solved, else as recipe cards (`docs/PORT_CANON_1100D.md`).

**Hard / long shot**
- C4K video: hidden, not removed (C4K drive mode, 4096×2160 tables and HDMI C4K are present); the sensor, encoder
  and thermal setup are unknown and need camera tests.
- FHD 120p high-speed: the E-P7 only has a 720p 120 mode; this needs a new readout and encoder setup.
- Highlight-weighted metering and snap focus (Ricoh GR-style).
- Picture-in-picture focus assist (GM1-style magnified window over the full view, issue #18): no second LV window in
  stock; needs a second, cropped output from the LV job (`docs/PIP_FOCUS.md`).
- E-M10 IV port: same container and CPU, ~48 % of v0.20 edits relocate by signature, but it has no Colour/Mono
  profiles (looks need a new host) and no test body (`docs/PORT_EM10IV.md`).
- E-M5 III port: ~36 % of v0.20 edits relocate by signature (recording limit and LCD tint do; SD loader and log hook do
  not), and it has no Colour/Mono profiles. **Needs an owner of the camera to try it and test on the body**
  (`docs/PORT_EM5III.md`, checker `tools/port_sigmatch.py`). More body assessments are welcome.

**Parked**
- Finer JPEGs: measured, and the gain left is very small, not worth the file-size and buffer risk (`docs/JPEG_QUALITY.md`).
- Live ND: the code exists only on E-M1-class bodies, not in the E-P7 or E-M5 III; it would mean new ISP code.
- Panasonic/Leica aperture ring (issue #14): needs a redesign, starting with a read-only probe, and a ring lens to test with; the old patch is not safe to flash (`docs/APERTURE_RING.md`).
- Colour looks on Monochrome slots or extra profile slots; a list-style menu instead of the wheel; 4:3 "open gate" video.

## How it works

- **This repository contains no OM firmware.** The builder downloads OM's official file from OM's own update
  server and checks its hash.
- Patches are small MN103 assembly routines and data edits. Each one has a build script that checks every
  stock byte it replaces, places code only in verified free space (`docs/CODE_SPACE_MAP.md`), and emits an
  edit list.
- `caduceus.py` (and `tools/build_package.py` for developers) turns an edit list into an update file for the
  camera's own SD updater, plus a matching stock-restore file. It refuses unexpected stock bytes, and every
  output must match the release's published hashes.
- Every patch has an emulator test that runs the real camera code, patched against stock, and checks that
  only the intended values change. Every package is checked to decode to exactly the emulated image, and its
  restore file to exactly stock.
- Runtime state lives only in heap memory the loader allocates; patches never write into the firmware image
  in RAM.
- A desktop colour pipeline (`sim/`), calibrated against the camera's own JPEGs, previews looks on RAW files.

## Safety

- **No responsibility is accepted for damage of any kind.** You flash this at your own risk. This is
  early-development software: expect bugs.
- Only the E-P7 on firmware **1.1** is supported.
- The camera's SD updater (hold **OK** while switching on, file at `DCOLYMP/E1429999.BIN`) is confirmed working:
  LED steady while writing, then a ~2 Hz blink when done. It rejects corrupt files without writing, and stock
  firmware has been restored through it, including from a bootloop.
- A full battery and an uninterrupted write are essential. A failed write can leave the camera unbootable.
- Keep the stock restore file the builder makes (`restore/E1429999.BIN`). Flashing it returns the camera
  completely to stock 1.1.
- **No `EP7MOD` folder on the card = almost stock.** All film looks, the look editor pages, Extras and mono
  presets only run when `EP7MOD/BUNDLES.BIN` is on the card, and nothing is read from the card until the
  first half-press. Without the folder (or with no card in) only these small, always-on changes remain:
  - log video when the **movie** picture mode is Muted;
  - the extra Panorama / Wide aspect options (the camera always boots back to 4:3);
  - the longer recording limit;
  - the Caduceus version on the Setup › Firmware screen.
- If something misbehaves: remove the `EP7MOD` folder first. If that doesn't help, flash the restore file.

## For developers

```bash
git clone --recurse-submodules https://github.com/cakelesscoder/caduceus-ep7
cd caduceus-ep7
tools/fetch_stock.sh          # downloads OLY_E_142_1100_0000_0000.BIN from OM and checks its hash
tools/setup_toolchain.sh      # GNU binutils for mn10300
tools/decode_stock.sh
python3 -m venv .venv && .venv/bin/pip install rawpy numpy pillow
```

Per-patch build and verify commands are in each `patches/*/` folder and in `WORKLOG.md`. Design notes are in
`docs/`.

## Support

Caduceus is free and open source. If it brings your E-P7 to life and you'd like to say thanks, you can
[buy me a coffee](https://buymeacoffee.com/cakelesscoder). Bug reports and camera test results are just as
welcome: please open an issue.

## Credits

- **Inspiration:** [u/fischgurke](https://www.reddit.com/user/fischgurke/) and his PEN-F HSL firmware mod, which
  showed an Olympus body could get in-camera HSL editing and started this whole project.
- [fishcu/oly_fw_analysis](https://github.com/fishcu/oly_fw_analysis): PEN-F firmware research and the MN103
  emulator harness this project builds on (used as a submodule).
- LightSnowDev, Altsoph/mx3 (CHDK forum), the DVXuser and Personal View Olympus threads, and iKenndac for
  earlier Olympus firmware research.
- **[Gx]Ace** (Casey Cavanaugh, [gxace.com](https://gxace.com)): his videos inspired the **Atrophy** look and the
  **XPan** aspect ratio.
- Community film recipes: GarethB (Kodachrome 25, mu-43.com), om-recipes.com contributors; see
  `docs/LIBRARY_V1.md`. Film-look references: `docs/FILM_SIMS.md` and `docs/FILM_LOOK.md`.

## License

Caduceus patch code, tools and docs are released under the [Apache License 2.0](LICENSE). The OM firmware itself is
not included or redistributed: the builder downloads it from OM's own server on your machine. The
`external/oly_fw_analysis` submodule (developer tools only) keeps its own licence. See [NOTICE](NOTICE).

Not affiliated with OM Digital Solutions or Fujifilm. "Olympus", "PEN" and film names are trademarks of their
owners.
