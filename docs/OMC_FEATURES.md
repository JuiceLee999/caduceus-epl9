# om-c-firmware (azqeurio / "db firmware") and Caduceus

Issue #26 asks whether Caduceus can include the E-P7 features of azqeurio's om-c-firmware. Issue #24 asks for
the lens L-Fn button to be assignable like Fn. Checked 2026-11-07, offline. No OM firmware or builder was downloaded.

## What is public

- **Repo** `github.com/azqeurio/om-c-firmware`: one commit holding a 15-byte `README.md` (`# om-c-firmware`). There is
  no source, no wiki and no licence file. This matches the archive we already had (`reference/om-c-firmware-dbv0.3.0.*`).
- **Releases** dbv0.1 to dbv0.3.2 (17 to 31 Oct 2026): closed Windows `.exe` and macOS apps, 80 to 175 MB each, plus one
  `db.firmware.0.3.EP7-R3.exe`. The size suggests they bundle OM firmware. We did not download them.
- **The release notes are the only documentation.** For the E-P7 they give one line: *"E-P7 Feature Enhancements
  (Minimum Shutter Speed, AF Home, D-Pad Customization, Button Remapping, etc.)"*. They name no firmware version, patch
  sites or method. Other features are for other bodies: Panasonic aperture ring (many bodies), Korean UI (OM-1/3/5),
  SH2 12.5/16.7 fps (OM-1), e-shutter sound (OM-1), 5 GHz hotspot, E-M1X ISO 25600 limit.
- **Upstream issues** #1 to #9 contain nothing on the E-P7.

## Licence

There is no licence, so the work is all rights reserved, and the code is closed anyway. **We cannot merge any of
it.** We can **reimplement** features from our own analysis of the E-P7 firmware (ideas and feature names are not
copyrightable), and we can **coordinate** with the author. Nothing of theirs is used in Caduceus.

**Flashing both is not possible.** The camera takes one main firmware, and either update replaces the other. Their
builder patches *stock* firmware. Running it on a Caduceus image (or ours on theirs) would at best fail its byte checks
and at worst produce a broken mix. Users should pick one. A combined build means both sets of patches living in one
image, and that only works if one project owns the whole build.

## Conflicts

Their patch sites are unpublished, so this cannot be checked directly. Likely overlaps, from what the features need:

| Their feature | Firmware area it must touch | Ours there |
|---|---|---|
| Button remapping, D-pad | validator lists/records for sids 47-53 (`0x604cae3c`, `0x604cb00e`, `0x604cda08..`), maybe the Button Function rows `0x611d7dc0` | `patches/buttons` / `omc_buttons` (same bytes). v0.28 itself touches only sid 270's record. |
| AF Home | a button value (code 3340), the Set Home screen | none |
| Minimum shutter | AE program / ISO-auto code, plus a menu value | none |
| Any new code | free space; dead EVF gamma tables are an obvious choice | most of our code lives in those tables (`CODE_SPACE_MAP.md`) |

## Plan, feature by feature

| Feature | Route into Caduceus | State |
|---|---|---|
| **Button remapping** (◉, Fn/AEL) | Reimplement (already ours: `docs/BUTTONS.md`). 23 functions: + AF Home, RAW, Test picture, Keystone, HDR, BKT, ISO/WB, WB/ISO, Multi Function, Level, IS mode | **Built as test o1** |
| **D-pad right / down** | Same patch: 16 functions, + ISO/WB, WB/ISO, Peaking, Magnify, Level, tele-con, Multi Function, RAW | **In o1** |
| **D-pad up / left** | Need a validator record that does not exist (`BUTTONS.md` §4.3); repoint an unused one plus a menu row | Later, medium |
| **AF Home** | The firmware already has it (`setAFHome`, Set Home checkbox). o1 puts AF Home on the ◉/Fn buttons | In o1; camera check: does Set Home appear? |
| **Minimum shutter speed** (ISO-auto lowest shutter) | Reimplement: find the P/A program's slow-shutter limit and drive it from a new value (Extras-style menu). No string or setting for it exists in the E-P7 1.1. | Not started. Medium/hard. |
| **L-Fn button (#24)** | Sids 54/55/56 and their 28/29-function lists exist, and so do the lens key events (`LENS_BUTTONS.md`). Unknown: whether the Button Function menu shows a lens row. 1) camera probe with an L-Fn lens; 2) if the row is hidden, remove its gate; if it is missing, add a row | Needs an L-Fn lens (12-40 / 40-150 PRO etc.) for the probe |
| Panasonic aperture ring | Our own `docs/APERTURE_RING.md` (parked: top suspect in the Test 3 bootloop) | Parked |
| Korean UI, SH2 rates, e-shutter sound, 5 GHz | Not E-P7 features | Out of scope |
| **Coordination** | Ask the author whether they would publish E-P7 patch notes (sites/method) under a compatible licence, so features land in one build | Suggested in the #26 reply |

## Test o1 (`0.28o1`)

- Source `patches/omc_buttons/` (`apply(spec)`, `verify.py`). Output `generated/omc/t1/` (spec + `pkg/`).
- 10 data edits in section 2 (100 B incl. records), in place, no new code, plus the version label `0.28o1`.
  `CODE_SPACE_MAP.md` already reserves these sites. v0.28 has no edit there.
- Emulator, from the built package: validator count/value/step for the 5 sids give the new lists, 24 other sids
  match v0.28, and function→action matches stock for all 28 codes. Alignment is OK. The package reparses, restore ==
  stock, and only our sites (61 B) differ from v0.28.
- Card files (`EP7MOD/*`) are unchanged from v0.28.
- Camera checks: boots; Button Function lists show the new entries on ◉, Fn and right/down; each new function works
  from a button; AF Home returns to the home point; reset Button Function before restoring stock or older builds
  (saved non-stock values stay stored; harmless, see `BUTTONS.md` §3).
