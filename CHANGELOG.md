# Changelog

Caduceus firmware patches for the Olympus PEN E-P7 (firmware 1.1). Releases from v0.25 are betas; earlier ones
were early-development pre-releases. Use at your own risk (see the README).

## v0.26 — 2026-11-07 (beta)

Flashed and used on an E-P7. **Reports wanted:** long recordings haven't been tested yet, see below.

- **Movie colour:** movie picture mode Vivid becomes its own colour profile, with the same pages as the stills wheel, separate from COLOR1-4 and stored in the new `EP7MOD/MOVIE.BIN`.
  1. Half-press the shutter once after switching on. This loads the profile, and clips shot before it are stock Vivid.
  2. In movie mode, select Vivid in Live Control (the strip up the side of the screen, not the Super Control Panel).
  3. Press **INFO** to open the wheel. Once loaded, the name Vivid reads `Custom - INFO for setup` in movie mode; stills Vivid stays Vivid.
  - Glow and Art Effects are off in movies. Muted still gives log. Without `MOVIE.BIN`, movie Vivid is stock Vivid.
- **Vertical video:** clips shot in portrait or upside down record their rotation, so they no longer import sideways. A clip keeps the rotation the camera had when recording started.
- **Card files:** add `EP7MOD/MOVIE.BIN` and keep your `BUNDLES.BIN`. The builder's card copy leaves an existing `MOVIE.BIN` alone.
- Firmware screen shows `Caduceus: 0.26`.

**Not tested yet:** recordings of 20+ minutes in 4K, chapter splits, players other than ffmpeg's reading of the rotation, and Movie settings surviving a power cycle. The Control Panel can't export `MOVIE.BIN` yet, so edit the Movie profile on the camera.

**Known issues:** the Super Control Panel value cell still shows 4:3 on Panorama and Wide, and a clip started before the first half-press is stock Vivid.

## Control Panel — 2026-11-06

- **OM-3 export:** set your camera in the setup pop-up (the **Camera** button later), and Export translates your looks to `OM3MOD/LOOKS.BIN` and `NAMES.BIN` for [Caduceus for OM-3](https://github.com/androidfanman/caduceus-om3). It shows which looks go where and what changed. The card's OM-3 `LOOKS.BIN` and OM-3 share links open here too.
- **The editor adapts to your camera:** slider ranges, Art Effects, glow colour, monochrome, lens correction and the preview follow the selected camera, and the OM-3 gains Contrast, Sharpness and Shading sliders. A wider value from another camera is kept until you move that slider.
- **About button:** what Caduceus is, who to go to for each camera, and credits.
- Translator and name renderer by androidfanman. Not yet tried on an OM-3.
- The setup pop-up appears once more for existing users, to ask for the camera.

## v0.25 — 2026-11-06 (beta)

First beta release. E-M10 IV firmware is in development and needs a volunteer to test it and report issues ([issue #21](https://github.com/cakelesscoder/caduceus-ep7/issues/21)).

Flashed and used on an E-P7. **Reports wanted:** whether the vignette change alters photos hasn't been confirmed yet ([how to test](README.md#vignette-correction-reports-wanted)).
NR is confirmed in each photo's recorded settings; a side-by-side pixel comparison is still to do.

- **`XP` and `21:9` icons:** the Super Control Panel option strip shows them for Panorama and Wide. They are drawn over four headphone icons the E-P7 appears not to use.
  **Known issue:** the current-value cell in the Super Control Panel still shows the 4:3 icon when either is selected. The setting and the photo are right.
- **Lens vignette correction off by default for looks:** picking a look turns the camera's lens shading correction (Shading Comp.) off for that colour
  profile, without changing the menu setting. A look can keep the correction (Control Panel). Extras sector 8 changes it on the camera: `8 VigFix Off` (natural corners) or
  `8 VigFix Camera` (follow the camera's Shading Comp. setting). It follows a profile switch. Profiles already set up keep following the camera until you pick a look or change sector 8.
  A `BUNDLES.BIN` saved with Shading Off, or a `LOOKS.BIN` with a look that keeps correction, is rejected by v0.24 and older.
- **Look NR now reaches photos:** Extras sector 1 and a look's NR now apply to stills at each shot, and follow a profile switch. v0.22-v0.24
  wrote setting 1334, whose reader is the live-view/movie path, and the camera's stills value is a different setting. Looks no longer change
  a camera setting; if a past look changed your movie Noise Filter, set it again in the menu. Looks with NR Low or Off (for example
  Provia 400) can now look different at high ISO.
- **Control Panel:** a look can keep the lens correction, and a firmware selector (asked on first visit, then the Firmware button) makes card files for your version.
- Firmware screen shows `Caduceus: 0.25`.

## v0.24 — 2026-11-05

- **A Film pick now sets the look's saturation:** picking a look writes its 12 per-colour values to the profile's
  saturation, as it already did for Highlights, Midtones and Shadows. It replaces whatever that profile's saturation was.
  Every colour look now shows its designed saturation for the first time, so strong looks like Velvia will look stronger.
  Own and Stock picks don't change saturation.
- **New `LOOKS.BIN`:** tone records carry saturation as nibbles at +38..43 with marker +44 = 1. **v0.23 and older reject this
  file**, so install it with v0.24. An older `LOOKS.BIN` on v0.24 still works and leaves saturation alone. Control Panel
  exports need v0.24 or later.
- Control Panel preview always shows saturation. Firmware screen shows `Caduceus: 0.24`.

## Looks — 2026-11-05

- **Provia 400 replaces Nostalgic** (same Film-page position), designed from a tripod comparison of real Provia 400X and
  100F slides plus Fujifilm's bulletin and reviews: WB G-3 (magenta-red cast), warm-sector hue toward red, blue hue +1, light
  -1 on red, blue, blue-cyan, green-cyan and yellow-green, -2 on green, tone S-1 M-1 Blacks -1 Whites -3, NR Low, no bloom.
  Saturation +1 warm, +2 blue (applied on a pick from v0.24); set contrast +1 on the camera.
- `releases/v0.23/card/EP7MOD/LOOKS.BIN` rebuilt (SHA256SUMS updated). Card file only, no re-flash.
- Control Panel: a saved, unedited Nostalgic becomes Provia 400 in place; an edited one is kept as your own look.

## Control Panel — 2026-11-04

- **RapidRAW preset export:** a look's *Share* dialog and *Export › RapidRAW presets* save it as a `.rrpreset` for
  RapidRAW, for ORF files or raws from any camera; Export also zips every look as its own preset. The 12-sector colour settings are fitted to
  RapidRAW's 8 HSL bands; tone and contrast go into the luma curve; WB, glow/halation, clarity, vignette and the mono
  filter are mapped as well. An approximation of the camera rendering, not an exact match.
- **Install firmware** button: a step-by-step install guide with links to the latest release and `docs/INSTALL.md`.

## v0.23 — 2026-11-03

- **No more duplicate looks on the Film page:** when a profile was already on a library look, turning the dial
  showed that look twice (its saved copy and the library entry). An unedited copy is now skipped; if you've edited
  the look (`*`), your edited version stays in the cycle so you can get back to it.
- **`Film: ` prefix is back** on the colour Film page, for every name: `Film: Velvia`, `Film: Kodachrome64*`
  (label up to 19 characters).
- Firmware screen shows `Caduceus: 0.23`. Card files (`LOOKS.BIN`) unchanged from v0.22.

## v0.22 — 2026-11-03

- **Noise reduction per look** (replaces colour grain): camera tests showed the camera's grain stages add nothing
  visible to colour photos (the v0.16–v0.21 route and a Monochrome-route probe, both dropped). Extras sector 1 is now
  **NR**: `1 NR Camera` (leave the camera's Noise Filter alone), `1 NR Std`, `1 NR Low`, `1 NR Off` (most texture).
  Set on a look pick and on a sector-1 edit through the stock settings path. The Noise Filter is camera-wide, so it
  stays at the last value when you switch profiles. True film grain is on the roadmap.
- Card values: 0 Global (old cards' "off"), 6 Std (new), 1 Low (old low), 2–5 Off (old medium/high). Library: no
  grain → Global, low → Low, medium/high → Off. Web app: "Noise reduction: Camera / Standard / Low / Off (most texture)"; older packs
  and share codes still load (Standard uses new code prefixes 5/6). Card loaders accept 0..6.
- Firmware screen shows `Caduceus: 0.22`.

## v0.21 — 2026-11-03

- **Five colour grain levels:** a COLOR slot's grain is now Off / 1–5 (Extras sector 1 shows `1 Grain Off`,
  `1 Grain 1` … `1 Grain 5`; the value stops at 0 and 5). Gains 220 / 600 / 1200 / 1500 / 1800: levels 1–3 are the
  old Low / Medium / High, unchanged, so existing cards and looks keep their strength; 4 (heavy) and 5 (extreme) are
  new. MONO grain is stock. The card loaders accept grain 0..5 (a v0.21 look with grain 4/5 is rejected by older
  firmware's loader, which allows 0..3). Web app: grain Off/1–5; share codes for grain 4/5 use new prefixes 3/4,
  every other code is unchanged.
- **Blur Art Effect removed (issue #20):** on a colour profile, Blur could restart the camera without saving the
  photo. Blur is now Off everywhere: the photo path, the live-view preview and Extras sector 5, which now cycles
  Off / Star Light / Pin Hole. A slot that already has Blur saved keeps the byte on the card, but it does nothing and
  shows as Off. Web app: Blur is listed only as a legacy value (Off on v0.21+). docs/ISSUES_19_20.md.
- Firmware screen shows `Caduceus: 0.21`.

**Known issue (all versions):** colour film grain adds no visible grain to full-size colour photos. Camera
measurements (v0.21) show grain 5 and grain off are identical; the grain route used only works on small images.
A fix is on the roadmap.

## v0.20 — 2026-11-02

- **Rear LCD less pink, and adjustable:** the stock LCD has a slight magenta cast. Setup › Monitor Adjust's
  colour slider (−7..+7) is now a **green ↔ magenta** slider for the LCD: 0 (default) adds 8 % green (about two WB
  green fine-tune steps), each step ±2.3 %, so −7 is 8 % more magenta than stock and +7 is 24 % greener than stock.
  The warm/cool setting is gone (one slider, one axis); brightness is unchanged. Data-only change to the LCD
  panel's own registers: photos, movies, HDMI out and the View Assist / log paths are byte-identical to v0.19.
  Build-time sizes: `patches/lcd_tint/build.py --green-pct 8 --span-pct 16`.
- Firmware screen shows `Caduceus: 0.20`.

## v0.20 — 2026-11-02

- **LCD pink cast fixed:** the rear screen's panel colour table sent green lower than red/blue at every Monitor
  Adjust step, giving live view a pink cast. Green is now raised (+8 % at the default).
- **Monitor Adjust colour is now green↔magenta:** Setup › Monitor Adjust's colour slider shifts the LCD from
  magenta to green (about 2.3 % per step; 0 = corrected default). Display only: photos, movies and HDMI are
  unchanged. (The warm/cool screen adjustment is replaced.)
- Firmware screen shows `Caduceus: 0.20`.

## v0.19 — 2026-11-02

- **Blacks and Whites per Colour Profile:** two new tone controls that move the ends of the tone curve, which
  the stock Highlight/Shadow controls never touch. Blacks + lifts the black point (matte, faded), − deepens the
  shadows; Whites − rolls the white point off, + pushes the brightest tones. Set them on the colour editor's
  Extras page, sectors 6 and 7 (−5..+5). Live view shows them.
- Fix (camera): in live view Blacks/Whites kept getting stronger frame by frame. The curve is now bent once per
  stock rebuild and left alone otherwise (JPEGs were already right).
- **Picking a look on the Film page applies its tone:** the look's Blacks/Whites go into the slot and its
  Highlight/Midtone/Shadow become that profile's stock tone settings (shown on the stock tone screen). Own and
  Stock picks leave tone as before. The card LOOKS.BIN carries each colour look's tone (same v3 format; old
  LOOKS.BIN files still load, without tone).
- Needs v0.19 firmware: v0.18 rejects a BUNDLES.BIN that uses Blacks/Whites.
- Look tweaks: Polaroid is punchier (narrow dynamic range), Atrophy's faded blacks toned down (+1), Cuban Neg
  bloom 3.
- Firmware screen shows `Caduceus: 0.19`.
- Caduceus Control Panel: tone sliders (Highlights/Midtones/Shadows/Blacks/Whites), tone in share codes, exports
  the v0.19 `LOOKS.BIN`.

## v0.18 — 2026-11-02

- **Cleaner look names on camera:** the Film page and the mono preset picker show just the look's name
  (`Velvia`, `Velvia*`, `Acros*`) instead of `Film: Velvia`. Long names have more room. `*` still marks a
  look you've modified.
- Firmware screen shows `Caduceus: 0.18`.

## v0.17 — 2026-11-02 (not released separately; included in v0.18)

- **New looks:** **Cuban Neg** (inspired by Osan's "Classic Cuban Neg" Fujifilm recipe; bloom 4) and
  **Atrophy** (inspired by [Gx]Ace's Atrophy pack: decayed, industrial tones).
- **Faux IR:** the "Aerochrome" look is renamed *Faux IR*. The camera's per-colour hue range can't turn green
  foliage red, so it's an infrared-inspired false-colour look rather than true Aerochrome.
- Library changes: Provia and Superia 400 removed (they duplicated the stock profile and Classic Neg).
- An experimental extended hue range (±15) was tried and **reverted**: it blanked the Hue label in the editor.
  v0.17/v0.18 firmware is otherwise identical to v0.16.
- Firmware screen shows the version in its own `Caduceus` row.

## v0.16 — 2026-11-02

- **Stronger colour grain:** Low/Medium/High about 4×/8×/12× stronger (colour profiles only; Monochrome grain
  stays stock).
- **One-press builder:** double-click launchers for Windows, macOS and Linux; can copy straight to the SD card.
- Clearer install and flashing guide.

## v0.15 — 2026-11-02 (first public release)

- Film simulations picked and edited in the camera (Film page in the Colour Profile editor), 29+ looks.
- Look editor pages: Saturation, Hue, Light, Film, Extras (INFO cycles); edits save to the SD card.
- Extras per profile: grain, bloom ↔ clarity, WB shift, Art Effects (Star Light, Pin Hole, Blur).
- Mono film presets (Pan F, Acros, T-Max, SFX, Tri-X, HP5, Delta 3200, Sepia, Selenium, Cyanotype).
- Hidden log video (movie picture mode = Muted), XPan 65:24 and 21:9 stills, longer recording limit,
  live-view preview of looks.

## Tools

- **Caduceus Control Panel** (https://cakelesscoder.github.io/caduceus-ep7/): make, edit and share looks in the
  browser, with short share codes, undo/redo and reset; exports `LOOKS.BIN`.
