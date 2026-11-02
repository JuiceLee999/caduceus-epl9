# Caduceus Looks (web app)

A small static web app for making and sharing Caduceus look packs: the `EP7MOD/LOOKS.BIN` file the camera's look
picker reads, plus an optional starter `EP7MOD/BUNDLES.BIN`. Everything runs in the browser. There is no backend,
and no photo or pack is ever uploaded.

- Start from the built-in library (the repo's `bundles/library_v3.json`) or an empty pack. Add, remove, reorder
  (drag, the arrows, or Alt+↑/↓) and rename looks (max 32, names ≤ 12 characters).
- Per-look editor: 12-sector hue / lightness (±7) and saturation advice (±5), grain, glow ↔ clarity (+ glow colour),
  WB A–B / G–M, Art Effect, notes. Mono looks get the Monochrome filter advice instead of the colour sliders.
- Live **approximate** preview on four CC0 sample photos or your own photo (decoded locally, never sent anywhere).
- Export `LOOKS.BIN`, a pack file (`*.caduceus.json`, which can be imported again), or a card zip with the
  `EP7MOD/` folder. The same validation as the desktop tools runs first.
- Share a look as a short code, or a whole pack as a link (see [Share codes](#share-codes)).

The output targets the **released v0.17 firmware** (= v0.16 firmware: hue/light ±7). It is byte-compatible with
`tools/ep7_looks_bin.py` / `tools/ep7_bundles_bin.py` as of commit `e477637`. The tests check this.

## Why plain TypeScript + Vite

The app has no runtime dependencies. Vite (dev server + bundler) and TypeScript are build-time only, and Vitest runs
the tests on the same modules the page uses. The encoder must be byte-exact, so types help. A framework would add
weight without helping with that. The build output is ~60 kB of JS/CSS plus the sample images.

| File | What |
|---|---|
| `src/format.ts` | LOOKS.BIN / BUNDLES.BIN encoders, the camera-side checks, validation rules |
| `src/pack.ts` | Pack model (`caduceus-pack/1`), parsing of pack files |
| `src/sharecode.ts` | Look codes and pack links |
| `src/preview.ts` | Approximate preview (Canvas 2D, a rough port of `sim/pipeline.py` + `sim/film.py`) |
| `src/main.ts`, `src/style.css` | UI |
| `scripts/library.mjs`, `scripts/gen-library.mjs` | Resolve the repo library + recipes into `src/data/library.json` |
| `tests/` | Encoder tests (byte-identical vs the release file and the Python tools), validation rejects, share codes |
| `public/samples/` | Sample images, all CC0 ([CREDITS.md](public/samples/CREDITS.md)) |

## Run it locally

Node 20+:

```bash
cd webapp
npm ci
npm run dev        # http://localhost:5173
npm test           # encoder + share-code tests
npm run build      # static site in dist/ (serve it from any web server, at / or any sub-path)
```

If you change `bundles/library_v3.json` or `sim/recipes/*.json`, run `npm run gen-library` and commit
`src/data/library.json`. A test fails while it is stale. The Python cross-check test needs `python3` and the git
history. It extracts the `e477637` tools with `git archive`, and it is skipped when either is missing.

## Self-host on a NAS (Docker)

The image is a two-stage build: Node builds the site, then plain `nginx:alpine` serves it on port **8080** as the
unprivileged `nginx` user. The same files are served at `/` and at `/caduceus/`. A health check is at `/healthz`.

```bash
cd webapp
docker compose up -d --build          # or: docker build -t caduceus-looks . && docker run -d -p 8080:8080 caduceus-looks
curl -fsS http://localhost:8080/healthz
```

`docker-compose.yml` runs the container read-only, with a tmpfs `/tmp`, all capabilities dropped and
`no-new-privileges`.

### Behind a tunnel at your own domain (e.g. Cloudflare Tunnel)

You don't need to open any port on the NAS:

1. In Cloudflare Zero Trust → Networks → Tunnels, create a tunnel and copy its token.
2. Add a public hostname for it. For the app on its own subdomain: `looks.example.com` → `http://caduceus-looks:8080`.
   For a sub-path: hostname `example.com`, path `caduceus*` → `http://caduceus-looks:8080`. The tunnel forwards
   `/caduceus/...` unchanged and the container serves the app there, so no rewrite is needed.
3. Uncomment the `cloudflared` service in `docker-compose.yml`, put `TUNNEL_TOKEN=...` in a `.env` file next to it,
   then run `docker compose up -d`. You can then remove the `ports:` mapping if only the tunnel should reach the app.

Any other reverse proxy (Caddy, Traefik, nginx, Tailscale Funnel) works the same way. Proxy to port 8080, and either
keep the `/caduceus/` prefix or strip it: both paths serve the app. The build uses relative URLs, so it also works
under any other sub-path if you serve `dist/` yourself. Share links are made from the page's own address
(`https://example.com/caduceus/#...`).

## Share codes

The format is stable. Version 1 codes must keep decoding in every later version of the app. A new format gets
a new version prefix. It never changes the meaning of an old one.

### Look code (v1)

Example: `1BM9Y-B0K8X-PVAC8-KB9ND-BFVKG-0YAYT-SC59H-5W548-8TYZ0` (CineStill800). Codes for the built-in looks are
18–52 characters (about 43 on average). The name takes about a third of that.

- **Alphabet**: Crockford base32, `0123456789ABCDEFGHJKMNPQRSTVWXYZ`. On input, case is ignored, spaces, `-`, `_`
  and `.` are dropped, `O` reads as `0`, and `I`/`L` read as `1`. Anything up to a `#` is dropped, so a whole link
  can be pasted. The app shows codes in groups of 5 with hyphens.
- **Layout**: `V` + `BODY` + `CCC`.
  - `V` = version symbol, `1`. The decoder reports a code starting with `2`–`9` as made by a newer app.
  - `BODY` = one non-negative integer in base 32, most significant symbol first.
  - `CCC` = CRC-15/CAN (poly 0x4599, init 0, MSB first, no reflection, no final xor) over the 5-bit values of
    `V` + `BODY`, as 3 symbols (high bits first). This catches every single-symbol typo and every swap of two
    adjacent symbols. Most other damage is caught too (about 1 in 32768 gets through).
- **Body integer**: a mixed-radix number. Each field is a digit `d` with radix `r`. The first field is the least
  significant: `N = d0 + r0·(d1 + r1·(d2 + …))`. To decode, take `d = N mod r` and `N = N div r` in the same order.
  After the last field, `N` must be 0. Fields, in order:

  | # | Field | Radix | Digit |
  |---|---|---|---|
  | 1 | kind | 2 | 0 colour, 1 mono |
  | 2 | hue[12] | vector, limit 7 | see below |
  | 3 | light[12] | vector, limit 7 | |
  | 4 | sat[12] | vector, limit 5 | (all zero for mono) |
  | 5 | grain | 4 | off, low, medium, high |
  | 6 | WB shift | 226 | 0 = none, else 1 + (a_b+7)·15 + (g_m+7) |
  | 7 | effect | 56 | 0 none; 1–25 bloom 1 + (strength−1)·5 + tint; 26–50 halation (same, +25); 51–55 clarity 1–5 |
  | 8 | vignette | 11 | value + 5 |
  | 9 | Art Effect | 6 | off, star_light, pin_hole, blur, white_edge, frame |
  | 10 | mono filter advice | 19 | 0 none given, else 1 + colour·3 + (strength−1); colours none, yellow, orange, red, green, blue |
  | 11 | name length − 1 | 12 | |
  | 12… | name characters | 94 | index in printable ASCII 0x20–0x7E without `@` (0x20 → 0, …, 0x3F → 31, 0x41 → 32, …) |

  Tint order: neutral, red, amber, warm, cool (a stored tint of `neutral` and no tint are the same byte).
  **Vector** of 12 values in −L..L (`R = 2L+1`): first a mode digit (radix 3).
  - 0 = all zero.
  - 1 = sparse: 12 mask digits (radix 2, 1 = non-zero), then each non-zero value in order, radix `R−1`, coded as
    `v+L` if `v<0`, else `v+L−1`.
  - 2 = dense: 12 digits `v+L`, radix `R`.

  The encoder picks the shorter of sparse and dense.
- **Not in a look code**: notes and the tone/contrast advice. Use a pack link to share those.

### Pack link (v1)

`pk1_` + base64url without padding (`-`, `_`) of the zlib stream (RFC 1950, `CompressionStream('deflate')`) of
the UTF-8 JSON pack file. The JSON is the same `caduceus-pack/1` object as the downloadable `.caduceus.json`, with
keys `schema`, `name`, `looks`, `slots`. zlib's Adler-32 catches damage. Pack links are case-sensitive, so they are
meant for links, not for typing. The built-in 32-look library makes a link of about 3.9 kB, which every current
browser handles in a URL fragment. The fragment (`#...`) is never sent to the server.

Opening `https://<host>/<path>/#<code>` imports the code automatically. A look is added to the pack. If the pack
is full, the app asks which look to replace or offers a new pack. A pack link asks before replacing the pack you
are editing.

## Pack file (`caduceus-pack/1`)

```json
{ "schema": "caduceus-pack/1", "name": "My pack", "slots": { "COLOR1": 0, "MONO1": 3 },
  "looks": [ { "name": "Velvia", "notes": "", "kind": "colour",
               "hue": [0,0,0,-1,-1,-1,1,2,2,-2,0,0], "light": [...12], "sat": [...12],
               "grain": "off", "wb": null, "effect": { "type": "bloom", "strength": 2, "tint": "red" },
               "vignette": 0, "art_effect": "off",
               "advice": { "tone": { "highlights": 1, "shadows": -4, "midtones": 0 }, "contrast": 2,
                           "mono_filter": { "colour": "yellow", "strength": 2 } } } ] }
```

The values use the vocabulary of the repo's bundle JSON (`patches/bundles/build.py`). The sector order is yellow,
orange, orange-red, red, magenta, violet, blue, blue-cyan, cyan, green-cyan, green, yellow-green. `slots` maps
`COLOR1–4` / `MONO1–4` to look indexes for the starter BUNDLES.BIN. Mono looks only go in MONO slots. `advice` is
only used by the preview.

## What goes into the card files

- **LOOKS.BIN** record per look: hue, light, grain, WB override, effect + strength, vignette (stored, not rendered
  by v0.17), the H/L flag, sat (colour looks, used when one is placed in a MONO slot), class, slot mask, bloom
  tint and the name. Colour looks always carry sat, so they can go in COLOR and MONO slots.
- **The Art Effect** has no field in LOOKS.BIN. It lives in the slot. The app keeps it in the pack file and share
  codes, and writes it into the COLOR slots of the starter BUNDLES.BIN.
- **Saturation, tone and contrast** are advice: they are the camera's own picture settings. The camera renders a
  look with whatever you have set there.

## Limits of the preview

The preview is a rough port of the desktop simulator, applied to finished JPEGs instead of RAW files. Use it for
the direction and relative strength of a look. Exact colours will differ from the camera. The grain is drawn a
little stronger than the full-size grain would look when scaled down, so you can still see it. Vignette and Art
Effects are not previewed.
