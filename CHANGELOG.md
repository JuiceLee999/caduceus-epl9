# Changelog

Caduceus firmware patches for the Olympus PEN E-P7 (firmware 1.1). All releases are early-development
pre-releases: use at your own risk (see the README).

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
