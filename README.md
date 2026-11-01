# EP7 Unlocked

Open-source firmware patches for the **Olympus PEN E-P7** (firmware 1.1). Per-profile film looks,
colour grain, bloom, true log video, XPan and 21:9 stills, and longer video recording.

> **Status: early testing.** Every patch is verified in an emulator of the camera's CPU. The SD update and
> recovery path is proven on a real E-P7 (including recovery from a bootloop), and the features marked
> **camera-tested** below run on a real camera. Flashing modified firmware can still brick your camera.
> Read [Safety](#safety) first.

![XPan crop with a Classic Chrome-style look](docs/img/xpan_classic_chrome.jpg)

## Features

| Feature | What you get | Status |
|---|---|---|
| **Profile bundles** | Each Colour Profile slot (COLOR1–4) carries its own full look: per-colour hue and lightness on top of the stock saturation and tone. Switch looks with the profile selector. | Camera-tested |
| **Per-profile WB shift** | Each slot can carry its own A/B and G/M fine-tune, so a warm look stays warm without touching other profiles. | Built, emulator-verified |
| **Colour film grain** | The E-P7's grain hardware, previously Monochrome-only, on colour profiles. | Camera-tested |
| **Bloom** | The Soft Focus glow engine applied subtly to colour profiles, Pro-Mist style. | Camera-tested (adds a short write delay) |
| **True log video** | A hidden OM-Log-style curve already present in the firmware (~12.4% output per stop), unlocked in movie mode. | Camera-tested |
| **XPan 65:24 and 21:9** | Two new still aspect ratios (5184×1912 and 5184×2224) from hidden aspect slots. | Built, emulator-verified |
| **Recording limit** | 29-minute and 2-hour caps raised to 9 hours (file, chapter and heat limits still apply). | Camera-tested |
| Looks from the SD card | Load bundles from `EP7MOD/BUNDLES.BIN` on the first half-press; change looks without reflashing. | Built, emulator-verified |
| Film Simulation menu | Look names from the card shown in the Picture Mode list. | Designed |
| Log View Assist | Normal-looking preview on the LCD while recording log. | Researched (feasible) |
| MONO slots as colour slots | 8 universal look slots. | In progress |
| On-camera HSL editor and profile naming | Edit looks and names in the camera. | Planned |

### Film looks

Recipes inspired by Fujifilm film simulations, built only from controls the patched camera has.
Desktop previews from E-P7 RAW files:

![Ten film looks on one scene](docs/img/film_sims_contact.jpg)

Halation and bloom in the desktop simulator (bloom also runs in-camera; halation is desktop-only for now):

![Halation and bloom test chart](docs/img/halation_bloom_chart.jpg)

### Log video

Left: the camera's standard curve. Right: the hidden log curve, rendered with the firmware's own tone table.

![Standard vs log](docs/img/log_vs_standard.jpg)

### UI

Mock-ups drawn with the camera's own fonts and icons, extracted from its firmware.

| Stock Colour Profile editor | Proposed HSL editor |
|---|---|
| ![](docs/img/ui_colour_profile_stock.jpg) | ![](docs/img/ui_hsl_editor_mock.jpg) |
| **Image Aspect menu with XPan / 21:9** | **XPan framing** |
| ![](docs/img/ui_aspect_menu.jpg) | ![](docs/img/ui_xpan_framing.jpg) |

## How it works

- The stock firmware is downloaded from OM's own update server by `tools/fetch_stock.sh` and checked by hash.
  **This repository contains no OM firmware.**
- Patches are small MN103 assembly routines and data edits. Each one has a build script that checks every
  stock byte it replaces, places code only in verified free space (`docs/CODE_SPACE_MAP.md`), and emits an
  edit list.
- `tools/build_package.py` turns edit lists into an update file for the camera's own SD updater, plus a
  matching stock-restore file. It refuses overlapping edits or unexpected stock bytes.
- Every patch has an emulator test that runs the real camera code, patched against stock, and checks that
  only the intended values change. Mutation tests confirm the tests catch broken patches.
- A desktop colour pipeline (`sim/`), calibrated against the camera's own JPEGs, previews looks on your RAW files.

## Safety

- Only the E-P7 on firmware **1.1** is supported.
- The camera's SD updater (hold **OK** while switching on, file at `DCOLYMP/E1429999.BIN`) is confirmed working:
  LED steady while writing, then a ~2 Hz blink when done. It rejects corrupt files without writing, and stock
  firmware has been restored through it, including from a bootloop.
- A full battery and an uninterrupted write are essential. A failed write can leave the camera unbootable.
- Test one feature at a time, following `docs/REVIEW_v03.md`.

## Build

```bash
git clone --recurse-submodules <repo>
cd ep7-firmware
tools/fetch_stock.sh          # downloads OLY_E_142_1100_0000_0000.BIN from OM and checks its hash
tools/setup_toolchain.sh      # GNU binutils for mn10300
tools/decode_stock.sh
python3 -m venv .venv && .venv/bin/pip install rawpy numpy pillow
```

Per-patch build and verify commands are in each `patches/*/` folder and in `WORKLOG.md`.

## Credits

- [fishcu/oly_fw_analysis](https://github.com/fishcu/oly_fw_analysis): PEN-F firmware research, container
  codec and MN103 emulator harness this project builds on (used as a submodule).
- LightSnowDev, Altsoph/mx3 (CHDK forum), the DVXuser and Personal View Olympus threads, and iKenndac for
  earlier Olympus firmware research.
- Film-look references are listed in `docs/FILM_SIMS.md` and `docs/FILM_LOOK.md`.

Not affiliated with OM Digital Solutions or Fujifilm. "Olympus", "PEN" and film names are trademarks of their owners.
