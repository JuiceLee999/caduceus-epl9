# Installing Caduceus

> [!WARNING]
> **Use at your own risk.** Caduceus is early-development, unofficial firmware modification: bugs will appear,
> and flashing can brick your camera or lose data. The author accepts **no responsibility for any damage**.
> Without the `EP7MOD` folder on the card the camera is almost stock; the restore file returns it fully to stock.

Caduceus patches the Olympus PEN **E-P7 firmware 1.1**. This repository contains no OM firmware: you build
the update file yourself from OM's official 1.1 download. Flashing modified firmware can brick your camera.
You do this at your own risk.

## Requirements

- An Olympus PEN E-P7 on firmware **1.1** (Setup > Firmware). No other model or version.
- A fully charged battery.
- An SD card, formatted in the camera.
- Python **3.10 or newer** (Windows, macOS or Linux). Nothing else to install.
- This repository (git clone or the release zip).

## Build

```
python3 caduceus.py build --release v0.15
```

On Windows, type `py` instead of `python3`.

The command:

1. downloads `OLY_E_142_1100_0000_0000.BIN` (111 MB) from OM Digital Solutions' update server, the same
   request OM Workspace makes;
2. checks its SHA-256 (`9d1610124ad98f6edae4540182205f06c9c703d9033ef0c4f19847193f95eaeb`);
3. applies `releases/v0.15/edits.json`. Every byte it replaces must match stock;
4. checks every output against `releases/v0.15/SHA256SUMS`. If any hash differs, it writes nothing.

If you already have the OM file: `python3 caduceus.py build --release v0.15 --stock path/to/OLY_E_142_1100_0000_0000.BIN`.
Use `--out DIR` for a different output folder (it must be new or empty). `python3 caduceus.py list` shows releases.

Output (`out/`):

```
out/DCOLYMP/E1429999.BIN   the patched firmware update
out/EP7MOD/BUNDLES.BIN     your four Colour Profile slots (the camera rewrites this)
out/EP7MOD/LOOKS.BIN       the film library
out/restore/E1429999.BIN   stock 1.1 restore file. Keep it on your computer.
out/SHA256SUMS             hashes of the above
```

Re-check at any time with `python3 caduceus.py verify out`.

## Copy to the card

Copy `DCOLYMP` and `EP7MOD` from `out/` to the root of the card. Do **not** copy `restore/` to the card.

```
(card root)
  DCIM/                    (the camera's photos)
  DCOLYMP/E1429999.BIN     patched update (remove after flashing)
  EP7MOD/BUNDLES.BIN
  EP7MOD/LOOKS.BIN
```

## Flash

1. Full battery. Camera off, card in.
2. Hold **OK** and switch the camera on. Keep holding OK until the LED lights.
3. The LED stays **steady** while it writes (a few minutes). **Do not switch off, open the battery door or
   remove the card.**
4. When the LED **blinks at about 2 Hz**, it is done. Switch off.
5. Switch on normally. Setup > Firmware shows `Body Caduceus v0.15`.
6. Delete `DCOLYMP/E1429999.BIN` from the card on a computer (formatting the card would also erase `EP7MOD`).

If the LED blinks fast right away, without a long steady phase, the camera rejected the file and wrote nothing.
Rebuild and copy again.

## First use

- Switch on and **half-press the shutter once**. The looks load from `EP7MOD` at the first half-press, not at boot.
- Open a Colour Profile's colour wheel. **INFO** steps through Saturation, Hue, Light, Film and Extras.
- Leave the editor and half-press: your changes are saved to `EP7MOD/BUNDLES.BIN` (the previous file is kept
  as `.BAK`).
- Without the `EP7MOD` folder the camera behaves as stock.

See the [README](../README.md#using-it) for the full feature list.

## Restore stock firmware

1. Copy `out/restore/E1429999.BIN` to the card as `DCOLYMP/E1429999.BIN` (replace the patched one; it must be
   the only file there).
2. Flash exactly as above. Setup > Firmware then shows 1.1 again.
3. Delete the file from the card. You can leave or remove `EP7MOD`.

The restore file rewrites the whole main firmware, so it also recovers from a bad patched flash, including a
camera that will not boot (proven on an E-P7).

## Known issues

- Art Effects on colour profiles: the live-view preview does not always update straight away. The photo is right.
- XPan and 21:9 reset to 4:3 at each power-on (on purpose).
- Halation is desktop-only; bloom works in the camera.
- Builds are only reproducible from the exact OM 1.1 file. Any other file is refused.

## FAQ

**Why do I have to build it myself?** OM's licence forbids redistributing their firmware. The release only
contains our edit list, which is applied to your own copy of OM's file.

**The download fails.** Check your connection and try again. On macOS with python.org Python, run
"Install Certificates.command" in the Python folder once. Or download the file with OM's tools or
`tools/fetch_stock.sh` and use `--stock`.

**"stock firmware SHA-256 is ..., expected ..."** The file is not the official E-P7 1.1 update (wrong model,
wrong version, or a corrupt download). Download it again.

**"edits.json does not match SHA256SUMS"** Your copy of the repository is half updated. Pull or download it again.

**Can I flash over an older Caduceus version?** Yes. The updater rewrites each firmware component in the package
whole, so no restore is needed in between.

**Where are my looks stored?** In `EP7MOD/BUNDLES.BIN` on the card. Back it up before formatting the card.

**How do I go back to stock without flashing?** Remove `EP7MOD` from the card: all look features then behave as
stock. Log video, XPan and the recording limit stay until you flash the restore file.
