# Caduceus on the Olympus PEN E-PL9: what we found

A plain-language summary of the E-PL9 investigation in this fork, for anyone with an E-PL9 (firmware 1.1) who
wondered whether Caduceus-style in-camera film looks are possible. **Short answer: the camera has the right colour
engine and the patch is built and verified in an emulator — but it cannot be installed, because this body refuses
SD-card firmware updates in a way nothing in the firmware file can change.** Nothing here was ever flashed, and the
test camera was never at risk.

All of this is offline reverse engineering plus a CPU emulator, with a handful of safe, read-only checks on a real
E-PL9 (holding OK at power-on with a deliberately harmless file). Full detail is in
[`PORT_EPL9.md`](PORT_EPL9.md), [`EPL9_LOOK_HOOK.md`](EPL9_LOOK_HOOK.md) and [`EPL9_RECOVERY.md`](EPL9_RECOVERY.md).

## The good news: the colour engine is there

Caduceus's film looks work by injecting per-hue hue, saturation and lightness into the camera's **COLOR picture
mode** — the same path the PEN-F HSL mod uses. The E-PL9 (a 2018 body) carries that whole engine, nearly identical
to the E-P7's:

- The COLOR **builder**, **selector**, per-hue **table** and output **writer** all match, with one constant address
  shift per area. 113 of 117 code windows of the builder line up.
- We ran the stock E-PL9 code in a strict MN103 emulator (`tools/epl9_color_probe.py`, 9/9 checks): a per-hue table
  really does change the output, exactly as on the E-P7.
- The only catch: the E-PL9's menus have no COLOR profile, so stock firmware never reaches that engine. We traced
  how the picture mode flows through capture, the converter, the work list **and** live view, and confirmed that
  making one stock mode report as COLOR (mode 11) lights the whole engine up.

## The patch we built

`patches/epl9_look` turns the **Custom** picture mode into a film look (design and decisions in
[`EPL9_LOOK_HOOK.md`](EPL9_LOOK_HOOK.md)):

- Three tiny in-place edits make Custom report as COLOR in stills, in per-frame/bracketing capture, and in live view
  (so the preview shows the look too).
- One hook feeds a look's per-hue hue/lightness into the colour builder; saturation rides the camera's own path.
- Everything else stays byte-for-byte stock — pick any mode but Custom and the firmware runs unchanged.
- `tools/epl9_look_verify.py` checks it end to end in the emulator (8/8), and three deliberately broken variants are
  each caught. The package is built and its decoded firmware matches the verified image.

## The blocker: this body won't take an SD firmware update

To install anything we need to get a firmware file onto the camera. The E-P7 (and Caduceus generally) uses the
SD-card updater: a file at `DCOLYMP/E????9999.BIN`, flashed by holding OK at power-on. On the E-PL9 we tested that
path with safe files only:

| Test | File on the card | Result |
|---|---|---|
| Dry run | stock firmware with one byte of the checksum flipped | updater runs, **refused** (fast blink), still 1.1 |
| Restore | stock main firmware, unmodified | **refused**, still 1.1 |
| No file | empty folder | no response (updater finds nothing) |
| Official | **OM's own complete, unmodified 1.1 file** | **refused**, still 1.1 |

The camera finds and reads the file (the empty-folder test proves that), then refuses it — **including OM's own
original firmware.** We then traced the entire SD update path in the firmware (the client that finds the file, the
service that handles it, the validator, and the flash writer) and found **no version check, no size limit, and no
gate a file could fail.** The camera's own code should accept and write a stock, same-version file.

So the refusal is not in the firmware we can read or change. It lives in the layer below it — the pre-boot code or
the sub-CPU that decides when an SD update is allowed — which on the E-PL9 does not permit a write in the
hold-OK-at-power-on state. The most likely reason is simply that the E-PL9's supported update method is **OM
Workspace over USB**, and the SD path is reserved for a service condition we can't reproduce.

**What this means:** the look patch can't be installed over SD on an E-PL9, and changing the file won't help, since
OM's own file is refused the same way. The only remaining firmware avenue is the USB protocol, which is a separate
and uncertain investigation (the camera may still refuse a same-version image). It has not been attempted.

## What E-PL9 owners can use today

The **[Caduceus Control Panel](https://juicelee999.github.io/caduceus-epl9/)** includes an E-PL9 profile that needs
no firmware change. Build a look there and it prints a card with the closest stock E-PL9 settings — Picture Mode,
Contrast/Sharpness/Saturation, Gradation, Highlight & Shadow Control (highlights, midtones, shadows), WB
compensation, and the Monochrome filter and colour — checked against the E-PL9 manual. For RAW files it also exports
a RapidRAW preset that adds the per-colour and tone-curve parts the stock camera can't do.

## Status in one line

Colour engine: **present and verified.** Patch: **built and emulator-verified.** Install over SD: **not possible on
this body.** Looks today: **the Control Panel, no firmware change.**
