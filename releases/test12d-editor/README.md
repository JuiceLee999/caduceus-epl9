# test12d-editor: INFO cycles the editor + state label + key probe (+ extras X stop + XPan/21:9 aspect)

One combined build: **look editor 12d** (`patches/look_editor`), the **look_extras X stop** on top of it
(`patches/look_extras`, built with `--key-word 44 --events 0x9014,0x9014`), and the **aspect** patch
(`patches/aspect/edits.json`), merged last with `tools/merge_specs.py`. 204 edits. Not camera-tested.

**Why.** On 12c the guide showed `[S] ...` (so the kind-5 label hook works on the camera), but it never changed:
Movie, the dial and INFO had no effect on it. So 0x9012 never reaches the editor's handler. INFO does reach the
editor (it toggles ALL). The 12c wording was also backwards: stock shows "All colors[INFO]" (id 2755) when ALL
is **off**, meaning "press INFO for all", and "Single color[INFO]" (2756) when ALL is **on**.

## What changed from 12c (card table loaded; with no `EP7MOD/BUNDLES.BIN` everything is stock)

1. **INFO is the cycle key.** Each INFO press steps
   **Sat·Single → Sat·All → Light → Hue → Extras (X) → Sat·Single.**
   - Sat·Single → Sat·All is the stock INFO handler, untouched.
   - Leaving Sat·All calls the stock handler (it turns ALL off), then goes to Light. Only stock code ever changes
     the ALL flags (0x61fc3800/04). If stock refuses, nothing else changes.
   - Light, Hue and X are always Single (ALL stays off). Hue → X is the extras layer; X → Sat·Single is the editor.
   - Movie and Delete are stock again (their 12b/12c hooks were removed).
2. **The guide label shows the current state** (≤16 characters):
   `Sat Single`, `Sat All`, `Lgt Single`, `Hue Single`. On X it shows the field under the cursor: `X Grain 0-3`,
   `X Clarity` (sector 2: right = clarity, left = glow), `X WB A-B`, `X WB G-M`, `X 1-4 only` (sectors 5–12).
3. **Key probe** (build flag; `build.py --no-probe` removes it and the label becomes `Light - Single` etc.):
   4 hex digits after the label = the **last key code that reached the editor router** (0x60e20cdc), e.g.
   `Sat Single 9012`. If the editor object's own entry (0x60dd5250, one level out) saw a code that the router did
   not, it shows `o` + that code instead, e.g. `Sat Single o9012`.
   - Only codes 0x9000–0x90FF are logged. INFO (9014/9015) is not logged because it is the redraw key, and a release
     straight after its press (e.g. 9013 after 9012) is skipped, so you see the press code.
   - The label is only redrawn on INFO or a dial step, so: **press the button you want to test, then press INFO**
     and read the code. (INFO also advances the state; that is fine.)
   - Reading it: `9012` = Movie reaches the router (the 12c hook would have worked); `o9012` = Movie reaches the
     editor but is filtered before the router (lock word 0x61fc1bac); old code unchanged = Movie never reaches
     the editor (eaten by the outer screen). Codes reset to `0000` each time the editor opens.

Heap use: P+684 axis (now 0..3), P+1000/P+1002 probe codes (past the loader's +815 and below film-menu's +1016).
No runtime stores into 0x60020020–0x6191ffe0 (store audit + read-only emulator image).

## Camera test plan (one step at a time; stop at the first surprise; SD restore ready)

1. **Card without EP7MOD.** Boots in 4:3. Color Profile editor: stock guide "All colors [INFO]"; INFO toggles ALL as
   stock; Movie does nothing new. Edit S, leave, shoot one frame.
2. **Card with EP7MOD, half-press once**, open COLOR2 editor (OK panel). Label: **`Sat Single 0000`**.
   (Stock text → table not loaded; blank/garbled → report it.)
3. **Probe:** press Movie, then INFO → note the label (`Sat All ....`). Repeat "button, then INFO" for Delete, OK,
   the arrows and the dial; write down each code. (Each INFO advances the state; keep going round.)
4. **Cycle:** from Sat·Single press INFO 5 times and note each label: `Sat All` → `Lgt Single` → `Hue Single` →
   `X ...` → `Sat Single`. The S numbers must be unchanged after a full round; ALL must be off on Light/Hue/X.
5. **Edits:** on Hue set green +3 (number +3, LV unchanged as before). On X, sector 2 → +3 (`X Clarity`), sector 1 → 2.
   Back to Sat, change one sector and check LV follows (stock). Leave, half-press (save), shoot a colour chart:
   greens shifted, clarity + grain visible. On the PC, `tools/ep7_bundles_bin.py` shows the edits.
6. Repeat 2–4 from the front Profile Control switch, and once on COLOR4.
7. **Aspect** (docs/ASPECT.md §6): Image Aspect lists Panorama and Wide; L shots are 5184×1920 / 5184×2224; playback
   is correct; with Panorama selected, a power cycle comes back in 4:3; 4:3/3:2/16:9 sizes are stock.

## Verification (emulator only)

| Check | Result |
|---|---|
| Editor (`tools/ep7_verify_look_editor.py generated/look_editor_12d/merged.json --base releases/test11/edits.json --jobs 12`) | S, G 376, W 1233, **E 104** (cycle on 4 keys, all axis × ALL-flag combinations, stock declining, guards, no table == stock, router), **V 135** (state text, probe text), **K 42** (probe filter, invalid heap), I 16, T 19: PASS; **M 56/56** |
| `--no-probe` editor build | S/G/W/E/V/I/T PASS; probe words stock |
| look_extras on 12d (`patches/look_extras/verify.py`) | S PASS (layer), G 744, W 4048, E 150, V 648 PASS, M 16/16; G/W/E/V also PASS on the final spec |
| Aspect (`patches/aspect/build.py --base` the 12d+extras spec) | 174/174 PASS |
| Package | `patched.pkg.bin` payload == stock + edits == emulated image; `restore-stock.pkg.bin` == stock (same as test 11/12/12b/12c) |

Integration edits to look_extras (needed for 12d): label mapping 2755/2756 swapped to match stock, texts shortened to
≤16 characters with the probe code appended through the editor's `ed_probe`, `ed_probe` required instead of
`ed_event`, and its E harness given the ALL flags and the INFO stop.

**Not covered by the emulator** (camera only): whether INFO's redraw shows the new label right away; key delivery for
every button (that is what the probe is for); whether the label is clipped before 16 characters; the real stock
INFO handler (a stand-in toggles ALL); live view still does not show H/L or X; plus 12c's list.

Rebuild (each in `systemd-run --user --scope -p MemoryMax=8G -q`):
```
.venv/bin/python -I patches/look_editor/build.py --base releases/test11/edits.json --out generated/look_editor_12d
.venv/bin/python -I patches/look_extras/build.py --editor generated/look_editor_12d/merged.json --key-word 44 --events 0x9014,0x9014 --out generated/look_extras_12d
.venv/bin/python -I tools/merge_specs.py generated/test12d/merged.json generated/look_extras_12d/merged.json patches/aspect/edits.json
.venv/bin/python -I tools/build_package.py generated/test12d/merged.json --out <new dir>
```
`card/` = 12c's card (EP7MOD/BUNDLES.BIN). The packages and `card/` are local only (gitignored).
