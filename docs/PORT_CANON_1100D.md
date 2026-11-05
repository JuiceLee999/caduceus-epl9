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

## 4. Deeper pass (2026-11-05): routes compared

Desk research again. **No Canon firmware was fetched.** Labels: [V] verified here, [R] reported, [I] inference.

**This changes section 1 and section 3 in two ways.** The checksum looks solved rather than stalled, and hand-made
files are a better first step than a writer.

### What a Picture Style can express

- [R] Specific Colors in Picture Style Editor (PSE): **up to 100 adjustment points**, each with hue, saturation and luminosity
  shifts. Affected range: hue 30–180°, saturation 30–100, luminosity 30–100 ([PSE manual][pse-sc]). Older docs give a default
  of 60° hue, 30° either side [R].
- [I] **So 12 sectors fit:** 12 points at sector centres, each with a 30° hue range, inside the 100-point limit. It is an
  approximation, not a copy:
  - A point is centred on one colour with limited saturation and luminosity reach, so very pale or very dark colours in a
    sector may be untouched.
  - Overlapping regions trigger a warning in PSE [R], so wider blends may need narrow ranges or more points.
  - Units differ from Caduceus, so a calibration table is required.
  - Canon recommends Basic, then Six Color-Axes, then Specific Colors [R]. Six Color-Axes does not survive PF2 [R].
- [R] Not possible in PF2: RGB per-channel tone curve (approximate only), Six Color-Axes, sharpness fineness. Grain, bloom, clarity,
  vignette and WB remain absent, as the table above says.

### Checksum

- [R] Later posts in the [Magic Lantern thread][ml-rev]: **Pf3Decoder.jar** ([post][ml-pf3d], Java source inside, by
  chris_overseas, plus a Python port) was updated to correct the checksum when re-encoding, so a decoded file can be hand-edited and
  re-encoded. Another poster ties it to a "Finalize" tag. A later reply elsewhere says tooling stalled.
- [I] Likely solved, but **unverified**. Forum pages returned 403 to my fetches, so this rests on search excerpts; I did not read
  the code or obtain the tool. No maintained repo was found on GitHub.
- [R] Also reported: tag 0x1009 is the base style ID; two header bytes control the "protected" state. Curve data is count, then
  input/output pairs.
- **Rule for the writer:** work from files PSE outputs, not from PSE itself. [R] Canon's [PSE download disclaimer][pse-dl] bars
  disassembling or reverse engineering the content, and personal non-commercial use applies. [I] Reading files you made yourself
  is a different act from disassembling the program, but check this if a writer ships publicly.

### Routes

| Route | HSL carried | Looks | Firmware risk | Licence | Effort [I] |
|---|---|---|---|---|---|
| **A. Hand-made PF2s** in PSE | Approx. 12 points | Library of about 29 files | None | Own output; no reversing | **About 1 week** |
| **B. PF2 writer** (code to .PF2) | Approx., automated | Any look, Control Panel export | None | File-format work; see rule above | **1–2 days to prove, then 1–2 weeks** |
| C. Recipe cards | User enters by hand | Any | None | None | 1–2 days |
| D. Magic Lantern | Adds nothing beyond PF2 | Style switching only | Low–medium | See below | Not worth it |
| E. Real firmware mod (ISP code on DIGIC IV) | In theory | In theory | High | Blocked: see below | Months, no body, not recommended |

**Magic Lantern**

- [R] The 1100D page lists firmware 1.0.5 with a last development build dated 2025-06-20 (search excerpt; the page returned 403 to
  my fetch). It stays community-maintained, and some builds fail.
- [R] Canon said in 2013 that third-party firmware does not void the warranty, but a brick it causes is not covered
  ([PetaPixel][pp]). ML offers no warranty [R].
- [I] It runs from the card rather than replacing the firmware, but I could not confirm the details from a primary source. It needs
  Canon's 1.0.5 updater on the body, which is another Canon download with its own terms. I did not fetch it.
- It still has no HSL stage. The earlier verdict stands.

**Canon firmware licence**

- [R] Canon's firmware updater agreement is click-to-accept. A Canon support-page excerpt bars altering, disassembling, decompiling
  or reverse engineering. I could not read the exact 1100D agreement (the one page tried returned 403), so **treat it as banned**.
  Nothing downloaded.

### Recommendation

**A, then B. Do not do D or E.**

1. **A first.** Hand-build 5–8 of the most-wanted looks in PSE from a CR2, check in Digital Photo Professional, and publish. Needs
   no format work.
   - [I] Calibration needs a raw file, not an 1100D, because DPP applies a PF2 to any CR2. Register-on-body via EOS Utility 2.1 or
     later still needs one owner to confirm.
   - [R] A free community library of 550 styles already covers many film looks ([MercuryDCD][mdcd]). So measure whether anyone wants
     ours before scaling.
2. **B only if A is wanted.** Proof: PSE save, decode, re-encode must be byte-identical. Then one changed value must open in PSE, and
   then register on a body.
3. C remains the fallback if B fails.

Blocking item: someone with an 1100D to register a file. The risk to them is nil beyond normal use of Canon's own tools.

## Sources

- [PSE manual: Fine-Tuning Specific Colors][pse-sc]
- [Magic Lantern forum: Reverse Engineering Picture Styles][ml-rev], [Pf3Decoder post][ml-pf3d]
- [Canon PSE download page, disclaimer][pse-dl]
- [PetaPixel on third-party firmware warranties][pp]
- [MercuryDCD picture styles library][mdcd]
- [EOS 1100D manual (Picture Style, p.24)][m]
- [Canon: registering Picture Style files][reg]
- [Picture Style Editor: saving files][pse-save]
- [Seller list of PF2/PF3 compatibility][ps3]
- [Magic Lantern forum: PF2 format][ml-pf2]
- [Magic Lantern 1100D builds][ml-builds]
- [Magic Lantern forum: 1100D port][ml-1100d]

[m]: https://www.manualsdir.com/manuals/633199/canon-eos-1100-d.html?page=24
[reg]: https://id.canon/en/support/8200044800
[pse-save]: https://cam.start.canon/he/S004/manual/html/UG-04_Saving_0020.html
[ps3]: https://lehungphotography.gumroad.com/l/canon-picture-style-portrait-2
[ml-pf2]: https://www.magiclantern.fm/forum/index.php?msg=172701
[ml-builds]: https://builds.magiclantern.fm/1100D.html
[ml-1100d]: https://www.magiclantern.fm/forum/index.php?msg=169369
[pse-sc]: https://cam.start.canon/en/S004/manual/html/UG-03_ImageChara_0040.html
[ml-rev]: https://www.magiclantern.fm/forum/index.php?topic=16299.0
[ml-pf3d]: https://www.magiclantern.fm/forum/index.php?msg=172818
[pse-dl]: https://th.canon/en/support/0200746503
[pp]: https://petapixel.com/2013/05/27/will-custom-firmware-void-my-warranty-canon-nikon-and-panasonic-respond/
[mdcd]: https://github.com/MercuryDCD/canon-picture-styles-pf2-pf3

Canon Picture Style site (free PF2 looks): https://global.canon/en/imaging/picturestyle/file/index.html
