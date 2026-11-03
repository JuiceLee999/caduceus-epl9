# Porting Caduceus to the E-M10 IV: feasibility

Static comparison only (2026-11-03). No E-M10 IV body was available. Sources:
- E-M10 IV `OLY_E_140_1100_0000_0000.BIN` (1.1, latest in OM's catalog, SHA-256 `4f9ea315…9aac`; kept in
  `stock_firmware/em10iv/`, never committed).
- E-P7 1.1.
- Script: a signature search over every edit in `releases/v0.20/edits.json` (294 edits, 20 121 bytes, all in component 0x100).

## Similarity

- **Container: same format.** `oly_container.py` decodes it with valid checksums, the round trip is byte-identical,
  and the file size is the same (111 017 984 B).
  - The component kinds are the same (0x100/101/106/10e/102), at the same addresses and sizes.
  - The one difference is the 0x102 component, at `0x468e0020` instead of `0x467e0020`.
- **Main (0x100):** 26 214 336 B in both, same CPU (MN103/AM33), and the same analysis base `0x60020020`. The model
  strings differ (`E-M10MarkIV`).
  - The code is a close sibling but not the same build. Functions move by a few hundred bytes to about 60 KB
    (common shifts: −61104, −59916, +61316, −9924).
  - The static validator is at `0x604ceed4` instead of `0x604cc98c` (1214 records against 1333).
- **The OSD resource (0x101) differs at 16.6 M bytes**, so the bitmap and string ids and the menu tables have to be
  re-derived.

## Edit-by-edit signature match (E-P7 v0.20 → E-M10 IV main)

"Auto" counts edits that are found at the same address, found at one unique shifted address (±4–64 B context or a
unique `expect`), or are FF free-space claims that are still FF.

| Feature group | Edits | Auto | Unmatched / ambiguous |
|---|---:|---:|---|
| Aspect (XPan/Wide tables, validator, ORF frame) | 129 | 70 % | 29 / 9 |
| Rec limit | 2 | 100 % | 0 |
| LCD tint | 4 | 100 % | 0 |
| Log video (+925 hook) | 3 | 100 % | 0 |
| SD loader | 2 | 100 % | 0 |
| Tone hook | 7 | 42 % | 0 / 4 |
| Grain / bloom / clarity / Art | 20 | 45 % | 8 / 3 |
| fw label | 5 | 40 % | 3 |
| Looks / bundles reader | 23 | 17 % | 18 / 1 |
| Editor / film page / mono presets | 78 | 10 % | 70 |
| **All** | **294** | **≈ 48 %** | 139 / 18 |

When aligned pointer words are masked, another 21 of the 139 misses become unique. **68 are absent** and 50 are
ambiguous. Most misses are in GUI data (`0x611…`: menu, wheel and string tables) and in the profile code.

## Blockers

1. **No Color/Mono Profile system.** The E-M10 IV has no profile settings: sids 1645–1707 are missing from its
   validator. `COLORTONE` debug strings: 62 against 213 on the E-P7. There are no `PROFILE` strings.
   - The COLOR builder (`0x603b0068` on the E-P7) does exist, shifted by +53 337 bytes, and so does the saturation table
     (shifted by −8376). The ISP side is similar.
   - But the gamma selector, job packer and validator signatures do not match exactly.
   - **Every look, editor, film-page and bundle feature hangs off the profile slots**, so these need a new host. Options:
     Art Filter, picture mode, or a My Set.
   - This would be a redesign, not a relocation.
2. **UI and OSD:** a different resource component and menu tables, and the E-M10 IV has a mode dial and an EVF.
   All menu, wheel and label patches need new ids. The LCD and EVF panel tables need re-checking (LCD tint matched
   only for the LCD).
3. **No hardware for testing:** none of the emulator baselines (camera JPEGs, test12x results) exist for it.

## Update path

- The container format and checksum scheme are the same, so the packager works unchanged once the model bytes
  (`1400`) are set.
- The E-M10 IV uses the same SD updater family (`DCOLYMP` present in both). The file name is probably
  **`DCOLYMP/E1409999.BIN`** (model code 140, by analogy with `E1429999.BIN`) [I]. Confirm it on a body before
  telling anyone to flash.

## Recommendation

- **Phase 1 (medium):** the stand-alone patches.
  - Patches: rec limit, log video, aspect, LCD tint, fw label.
  - Method: a signature relocator that finds each `expect` plus context, masks pointers and rewrites relative calls.
    About 70–100 % of those edits relocate automatically. Re-run the emulator checks against the E-M10 IV image.
- **Phase 2 (hard):** looks and the film menu, on a new host instead of profiles.
- **Shipping untested is high risk** (a failed boot needs the SD restore path).
- **Tester plan:**
  1. A volunteer first confirms that the camera's SD updater accepts a stock E-M10 IV file.
  2. Next, a no-op package: stock plus the fw label only.
  3. After that, one feature per release, with the restore file built and hash-checked every time.
