# What we learnt from Caduceus for OM-3

[androidfanman/caduceus-om3](https://github.com/androidfanman/caduceus-om3) (Apache-2.0, read at `daa453b`, its v0.20) is a camera-tested OM-3 port in the Caduceus family. Details are in its `docs/DEVELOPER_NOTES.md` and `docs/FORMATS.md`. OM-3 addresses don't apply to the E-P7.

## Open question: hue direction

The two bodies' camera results point opposite ways for a positive hue value, though both write the same native value (`-1000 × UI`):

| Body | Evidence | + moves |
|---|---|---|
| E-P7 | Test 7b: greens +7 gave teal (`WORKLOG.md`). One test | Toward the lower-numbered neighbour (Green → Green-cyan) |
| OM-3 | Its `USING.md` and developer notes: "camera-tested direction" | Toward the higher-numbered neighbour (Yellow → Orange, Blue → Blue-cyan) |

**Left for later.** The Control Panel copies hue numbers across unchanged, as the OM-3 project's own panel does, so a look's hue shifts may go the other way on an OM-3. A fair test needs both cameras shooting the same scene with the same setting. `sim/pipeline.py` also still calls the E-P7 direction unverified.

## Ideas to assess later

These are the OM-3 project's reports. We haven't tested them and nothing here has been added to the E-P7.

- **Code loaded from the card.** Out of firmware space, it puts a relocatable code block at the end of `GUIDES.BIN`, loads it at first half-press and runs it only if a tag matches the exact firmware. Without the file, the hooks behave as stock. This would ease our own code-space limit.
- **Art Effects in live view.** It hooks the gate that maps an Art Effect to job flags only for picture mode ≥ 100, and reports glow and Art Effects showing in live view as camera-tested. That is the likely route for our "preview updates immediately" roadmap item.
- **White Edge and Frame on COLOR photos** are camera-tested there, though we dropped them in v0.15. It also replaces the Frame pictures with its own white ones, generated on the user's computer.
- **Value labels per sector.** The label next to the dial value names the sector and its meaning (`NR Low`, `Clarity`), drawn from 1-bit letters in `LABELS.BIN`.
- **Look names as pictures.** `NAMES.BIN` holds one rendered name per look in the camera's label style.
- **`om-emu`** ([flatpanda/om-emu](https://github.com/flatpanda/om-emu)) drives real UI sessions in emulation, which our harness doesn't do.

## Lessons

- **Where hook code lives matters.** An early test bootlooped, likely because a stage hooked in section 2 called code in section 8, which wasn't loaded yet. Code in sections 1-5 was safe on that pipeline. Reflashing a working build recovered the camera.
- **Colour grain through the MONO route is a dead end there too:** the route is luma-only end to end, with Cb and Cr exactly 128.
- Its stills NR override is the same design as ours, and its pixel comparison is also still to do.

## Look translation (Control Panel)

The OM-3 holds 5 looks for each of COLOR 1-4, in `OM3MOD/LOOKS.BIN` and `NAMES.BIN`. The panel exports the first 20 colour looks in list order.

| Look value | On the OM-3 |
|---|---|
| Hue, Light | Limited to ±5; hue numbers copied as they are (above) |
| WB shift | Limited to ±5 |
| Saturation, tone, NR, glow, clarity, Star Light, Pin Hole | Carried over |
| Contrast, Sharpness | Real settings there, limited to ±2 |
| Vignette | Becomes the camera's Shading |
| Halation | Becomes plain glow; glow colour is dropped |
| Blur | Left out |
| Lens correction choice | Left out (not built on the OM-3 yet) |
| Monochrome looks | Left out (COLOR only) |

`webapp/src/om3.ts` and `om3names.ts` are vendored unchanged; our glue is `webapp/src/targets/om3.ts`. One-look (`op1_`) and bank (`ob1_`) links from the OM-3 panel open here. In the other direction, its panel rejects our version 7 and 8 look codes (looks that keep the lens correction), which it could fix by updating its `sharecode.ts`.
