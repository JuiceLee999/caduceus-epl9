# Caduceus looks on a Canon EOS 1100D (Rebel T3): feasibility

Desk research only (2026-11-03, about 30 minutes). No 1100D body, no firmware work. The question: can the 1100D
(DIGIC IV, 2011) get in-camera HSL / film looks from the Caduceus look format?

## 1. No-hack route: Canon Picture Style files (.PF2)

- **The 1100D takes user Picture Styles.** It has three User Def. slots. EOS Utility (USB) registers a Picture Style
  file into a slot, and the camera can still adjust that slot's sharpness, contrast, saturation and colour tone
  afterwards [1100D manual p.24][m], [Canon: registering a Picture Style file][reg].
- **PF2, not PF3.** PF3 adds Six Color-Axes, the Basic-pane tone curve and sharpness fineness/threshold; saving as
  PF2 drops those [PSE manual: saving][pse-save]. PF3 seems limited to bodies from about the 1300D/T6 and M3/M5
  onward (seller claim, not Canon's list) [ps3], so assume **PF2 only** on the 1100D. EOS Utility 2.x is probably
  the right version for this body (to check).
- **What PF2 can still hold:** a base style (Standard/Neutral/Faithful/Monochrome…), contrast, saturation, colour
  tone, sharpness, **specific-colour edits** (eyedropper picks, each with hue/saturation/luminance shifts and a
  hue/sat/lum range), the gamma/tone characteristic, and the Monochrome filter/toning effects.
- **Format: only partly reverse-engineered.** A 2015–16 Magic Lantern thread decoded the layout (Java decoder,
  Python and PHP ports, a spreadsheet guide annotated with Technicolor CineStyle values), but **re-encoding stalled
  on a checksum of unknown construction** [ml-pf2]. There is no maintained open-source PF2 writer and no Canon spec.

### Caduceus → PF2 mapping

| Caduceus field | PF2 | Notes |
|---|---|---|
| hue / light / sat, 12 sectors | **Yes, approx.** | One specific-colour point per non-zero sector (the sector centre), with its hue range set to the 30° sector width. Canon's units and blending differ, so values need a calibration table. |
| Tone H/S/M, Blacks/Whites | **Partly** | Via the PF2 gamma/tone characteristic if the writer can set it; otherwise only contrast. |
| Mono looks + filter | **Yes** | Monochrome base with filter (Y/O/R/G) and toning. |
| WB A–B / G–M | **No** (not in the file) | The 1100D has a global WB shift; the converter can print the setting to dial in. |
| Grain, bloom/halation, clarity, vignette, aspect | **No** | DIGIC IV has no such stage; JPEG-only post work. |

## 2. Magic Lantern route

The 1100D is in ML's build list but has always been a limited, community-maintained port: nightly builds tied to
one Canon firmware, features disabled to avoid errors, and a raw-video test build from 2016 that "needs some more
work" [ml-builds], [ml-1100d]. ML's colour features (picture style switching, Image Fine-tuning on some bodies)
choose between or tweak stock styles; nothing gives a per-hue in-camera editor beyond what PF2 already does. The
DIGIC IV colour pipeline is not documented, so a real HSL stage would be a new research project on a body with a
small, quiet community. **Not realistic** for Caduceus; ML adds risk and little colour capability.

## 3. Recommendation

Build **`caduceus-canon`**: share code / look JSON → `.PF2`, plus a Control Panel "Export for Canon" button.

1. **Verify first (half a day, no risk):** save two PF2 files in Picture Style Editor that differ by one setting
   (e.g. one specific-colour hue +1) and diff them. Check whether the checksum is a known CRC/sum. Then register
   one PSE-made PF2 on the 1100D via EOS Utility to confirm the path works on this body.
2. **If the checksum is crackable (≈1–2 weeks):** a Python/TS writer, a sector-to-colour-point table calibrated by
   shooting a ColorChecker with the stock style against each generated style, and the export button. Also print
   the WB shift and "no grain/bloom/clarity" next to the download.
3. **If not:** fall back to a "Canon recipe card" from the Control Panel: PSE settings (specific colours, contrast,
   saturation, mono filter) for the user to enter by hand. Zero risk, more friction.

Effort: medium for step 2, low for step 3. Firmware risk on the camera: none in either case (stock EOS Utility
and stock file format).

## Sources

[m]: https://www.manualsdir.com/manuals/633199/canon-eos-1100-d.html?page=24
[reg]: https://id.canon/en/support/8200044800
[pse-save]: https://cam.start.canon/he/S004/manual/html/UG-04_Saving_0020.html
[ps3]: https://lehungphotography.gumroad.com/l/canon-picture-style-portrait-2
[ml-pf2]: https://www.magiclantern.fm/forum/index.php?msg=172701
[ml-builds]: https://builds.magiclantern.fm/1100D.html
[ml-1100d]: https://www.magiclantern.fm/forum/index.php?msg=169369

Canon Picture Style site (free PF2 looks): https://global.canon/en/imaging/picturestyle/file/index.html
