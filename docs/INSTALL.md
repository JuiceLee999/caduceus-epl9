# Installing Caduceus

> [!WARNING]
> **Use at your own risk.** Caduceus is early-development, unofficial firmware modification: bugs will appear,
> and flashing can brick your camera or lose data. The author accepts **no responsibility for any damage**.
> Without the `EP7MOD` folder on the card the camera is almost stock; the restore file returns it fully to stock.

Caduceus patches the Olympus PEN **E-P7 firmware 1.1**. This repository contains no OM firmware: you build
the update file yourself from OM's official 1.1 download. Flashing modified firmware can brick your camera.
You do this at your own risk.

## Quick version

It really is mostly drag and drop. The only extra step is a one-click build on your computer, because OM's
licence doesn't allow us to share a ready-made firmware file:

1. **Get Python 3.10+** once: Windows/macOS from [python.org/downloads](https://www.python.org/downloads/)
   (Windows: tick **Add python.exe to PATH**; macOS: afterwards run **Install Certificates.command** in the
   Python folder); Linux: usually already installed, else `sudo apt install python3` (or your distro's package).
2. **Build:** in the unzipped Caduceus folder, double-click the launcher for your OS:
   - Windows: `Build Caduceus (Windows).bat`
   - macOS: `Build Caduceus (Mac).command`. The first time, **right-click › Open** (then **Open** again),
     because macOS blocks downloaded scripts on a plain double-click.
   - Linux: `build-caduceus-linux.sh` ("Run in Terminal", or `./build-caduceus-linux.sh`).

   It downloads OM's official 1.1 file, builds the latest release into `Caduceus-<version>/` and checks every
   hash. If exactly one camera SD card (one with a `DCIM` folder) is plugged in, it offers to copy the update
   onto it (an existing `EP7MOD/BUNDLES.BIN`, your saved looks, is never overwritten); otherwise it opens the
   output folder. The window stays open until you press Enter.
3. **Drag and drop** (if it didn't copy for you): copy the `DCOLYMP` and `EP7MOD` folders from
   `Caduceus-<version>/` to the root of the SD card. Keep `restore/` on your computer.
4. **Flash:** hold **OK**, switch on, wait for the blinking LED.
5. **Shoot:** half-press once, and the film looks load from the card.

The command-line route (`caduceus.py build --release ...`, below) still works if you prefer it.

## Requirements

- An Olympus PEN E-P7 on firmware **1.1** (Setup > Firmware). No other model or version.
- A fully charged battery.
- An SD card, formatted in the camera.
- Python **3.10 or newer** (Windows, macOS or Linux). Nothing else to install.
- This repository (git clone or the release zip).

## Get the files and Python

**Get Caduceus:** on the GitHub page click **Code → Download ZIP** and unzip it (or `git clone` it).

**Get Python 3.10+** (one-time):

| | How |
|---|---|
| **Windows** | Install from [python.org](https://www.python.org/downloads/) (tick "Add python.exe to PATH") or the Microsoft Store. |
| **macOS** | Install from [python.org](https://www.python.org/downloads/), then run "Install Certificates.command" in the Python folder once. (`brew install python` also works.) |
| **Linux** | Usually already installed. Otherwise `sudo apt install python3` / `sudo dnf install python3`. |

**Open a terminal in the unzipped folder:**

- **Windows:** open the folder in File Explorer, click the address bar, type `cmd`, press Enter.
- **macOS:** right-click the folder in Finder → **New Terminal at Folder** (or `cd` into it in Terminal).
- **Linux:** right-click → **Open in Terminal** (or `cd` into it).

## Build

Windows:
```
py caduceus.py build --release v0.23
```
macOS / Linux:
```
python3 caduceus.py build --release v0.23
```

The command:

1. downloads `OLY_E_142_1100_0000_0000.BIN` (111 MB) from OM Digital Solutions' update server, the same
   request OM Workspace makes;
2. checks its SHA-256 (`9d1610124ad98f6edae4540182205f06c9c703d9033ef0c4f19847193f95eaeb`);
3. applies `releases/v0.23/edits.json`. Every byte it replaces must match stock;
4. checks every output against `releases/v0.23/SHA256SUMS`. If any hash differs, it writes nothing.

If you already have the OM file: `python3 caduceus.py build --release v0.23 --stock path/to/OLY_E_142_1100_0000_0000.BIN`.
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

Put the card in your computer (card reader, or the camera over USB in storage mode), then drag the `DCOLYMP`
and `EP7MOD` folders from `out/` onto the card's top level (same level as `DCIM`). This works the same in
Windows Explorer, macOS Finder and Linux file managers. Do **not** copy `restore/` to the card. Eject the card
properly before removing it (Windows "Eject", macOS eject button, Linux "Unmount").

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
3. The LED stays **steady** while it writes (it can take as little as 10 seconds). **Do not switch off, open the battery door or
   remove the card.**
4. When the LED **blinks at about 2 Hz**, it is done. Switch off.
5. Switch on normally. Setup > Firmware shows a `Caduceus` row with the version (e.g. `0.16`).
6. Delete `DCOLYMP/E1429999.BIN` from the card on a computer (formatting the card would also erase `EP7MOD`).

If the LED blinks fast right away, without a long steady phase, the camera rejected the file and wrote nothing.
Rebuild and copy again.

## First use

- Switch on and **half-press the shutter once**. The looks load from `EP7MOD` at the first half-press, not at boot.
- Open a Colour Profile's colour wheel. **INFO** steps through Saturation, Hue, Light, Film and Extras.
- Leave the editor and half-press: your changes are saved to `EP7MOD/BUNDLES.BIN` (the previous file is kept
  as `.BAK`).
- Without the `EP7MOD` folder the camera is almost stock (log video, XPan/21:9 and the recording limit stay).

See the [README](../README.md#using-it) for the full feature list.

## Restore stock firmware

1. Copy `out/restore/E1429999.BIN` to the card as `DCOLYMP/E1429999.BIN` (replace the patched one; it must be
   the only file there).
2. Flash exactly as above. Setup > Firmware then shows 1.1 again.
3. Delete the file from the card. You can leave or remove `EP7MOD`.

The restore file rewrites the whole main firmware, so it also recovers from a bad patched flash, including a
camera that will not boot (proven on an E-P7).

## Colour wheel looks stock after updating (no film names, INFO only toggles all colours / one colour)

The firmware reads `EP7MOD/LOOKS.BIN` and `EP7MOD/BUNDLES.BIN` from the card at the first half-press. If it
cannot read them, it quietly falls back to stock behaviour. Check, in order:

1. **Setup > Firmware shows a `Caduceus` row with the version?** If not, the update did not run or you flashed
   `restore/E1429999.BIN` (the stock file, which has the same name). Flash `DCOLYMP/E1429999.BIN` from the build.
2. **Card layout:** on the card's top level, next to `DCIM`, there must be `DCOLYMP` and `EP7MOD` (not inside
   another folder such as `Caduceus-v0.23`), with `EP7MOD/LOOKS.BIN` (2112 bytes) and `EP7MOD/BUNDLES.BIN` (680 bytes).
3. **Eject properly.** On macOS use the eject button in Finder; on Windows "Eject"; on Linux "Unmount". Pulling the
   card early can leave the files cut short, which the camera ignores. Copy them again and eject first.
4. **Half-press the shutter once** after switching on, then reopen the colour wheel.
5. **macOS: "not allowed to write to ..."** when the builder copies to the card: System Settings > Privacy & Security >
   Files and Folders (or Full Disk Access), allow Terminal to access Removable Volumes, and run it again, or drag
   `DCOLYMP` and `EP7MOD` across in Finder.

If it still looks stock, open an issue with the answers to 1–3 and the card's size and format.

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
