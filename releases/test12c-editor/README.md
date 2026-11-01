# test12c-editor: test 12b + visible axis indicator + refresh after Movie / H-L edits

**Why.** On 12b, with EP7MOD loaded and in the COLOR2 editor, pressing Movie showed nothing. We could not tell
whether `ed_event` ran: the axis had no indicator, and H/L values of 0 look the same as S = 0.

**What changed from 12b** (only when a card table is loaded; with no card, everything is stock):

1. **Axis indicator in the bottom-left guide.** The stock guide label "All colors [INFO]" / "Single color [INFO]"
   (string ids 2755/2756) now reads **`[S] All colors`**, **`[L] All colors`** or **`[H] All colors`** (or
   `... Single color` in ALL mode). The INFO icon is gone while a card table is loaded.
   - It shows `[S]` as soon as the editor opens, and also before the first Movie press.
   - **If Movie never reaches `ed_event`, it stays `[S]`.**
   - How: the Color Profile view rebuilds its screen state by calling 5 "parts". The `.data` init word
     0x6025aa98 (part 3, stock 0x60decbfc, the guide writer) now points to `ed_guide`. `ed_guide` runs the stock
     part, then rewrites only that label as kind 5 (inline text), the same label kind as the test-8 names.
2. **Refresh after Movie.** After a cycle, `ed_poke` reads the editor's cursor setting (1091/1096/1097/1686)
   through the facade and writes the same value back. This is the call the INFO handler makes, so the stock
   settings listeners fire and the screen (guide, numbers) is rebuilt.
3. **Refresh after an H/L dial edit.** `ed_set` writes the heap byte as before, then reads the sector's current S
   value with the stock getter 0x602af887. It then enters the stock settings manager 0x60827440 with that
   unchanged S value, exactly like an S edit to the same value. The manager's listeners run; S does not change.

**Live view will still not show H/L.** This is not a missing refresh:
- The bundle H/L reader runs only on capture jobs (job marker 0xB2; docs/V02_BUNDLES.md residual risk 2;
  WORKLOG "live view shows stock H/L"). Live view never reads the table, so check H/L in the JPEG.
- The picture-mode refresh 0x602ccfcb/0x602cd045 runs inside 0x60827440 only for ids 111, 1645, 1646 and 15271,
  so a stock S edit does not use it either. S reaches live view through the manager's listeners. Change 3 makes
  an H/L edit run those same listeners.
- Showing H/L in live view needs a new reader in the live-view colour path. That path is untraced, and that
  reader is a separate, larger step.

**S edits reach stock unchanged.** On S, `ed_set` jumps straight to 0x60827440 (part W: the state equals the
stock run). The bundle readers do not touch COLOR saturation: `patches/bundles/build.py` keeps saturation out of
the table, and the MONO-colour `sat[12]` patch is not in this build. Nothing here suggests the readers override
stock saturation. If S edits do not move live view on the camera, that is new information, so please report it.

Edits: 102 (12b's 100 + `ed_view` code + the guide word). ed_core is 553 B (claim 608), ed_ui 815 B (unchanged
size), ed_view 287 B at 0x60b9dd10 (sec 5 FF tail, claim 0x60b9dd10–0x60b9de70). `restore-stock.pkg.bin` is
identical to test 11/12/12b. The packages and `card/` (12b's card) are local only (gitignored).

## Camera test plan (one step at a time; stop at the first surprise; SD restore ready)

1. **Card without EP7MOD.** Open the Color Profile editor. The guide should be stock "All colors [INFO]".
   - Press Movie: nothing should happen. INFO should toggle ALL as usual.
   - Edit S and check that live view follows (stock). Leave the editor and record a short movie.
2. **Card with EP7MOD, half-press once**, then open the COLOR2 editor from the OK panel. The guide should read
   **`[S] All colors`**.
   - Stock guide instead: the table is not loaded. Check that the title shows "Portra" etc.
   - Blank or garbled guide: the kind-5 text does not render here. This is cosmetic. Report it; removing the
     card restores stock.
3. **Press Movie once.** Expected: `[L] All colors`. If it still says `[S]`:
   - Turn the dial one notch.
   - Then press INFO, which rebuilds the guide. If it now shows `[L] Single color`, the axis changed and only the
     redraw is missing. If it still shows `[S]`, Movie does not reach `ed_event`.
   - Note what you see and stop.
4. Movie → `[H]`, Movie → `[S]`. The S numbers should be unchanged. Repeat steps 2–4 from the front Profile
   Control switch.
5. On `[H]`, set green to +3. The big number should show +3, and live view will **not** change (expected).
   - Shoot a colour chart. The JPEG greens should shift.
   - Then go to `[S]`, change a sector, and check that live view follows, as on stock.
6. Leave the editor, half-press (save), then do test 12 steps 4–6 (files on the PC, write-protect, COLOR4, ALL).

## Verification (generated/look_editor_12c/verify_*.json; emulator only)

`tools/ep7_verify_look_editor.py releases/test12c-editor/edits.json --base releases/test11/edits.json --jobs 16`
(`--jobs` runs the mutations in parallel). Every image region is mapped read-only.

| Part | Result |
|---|---|
| S static (+ ed_view claim, guide word, part table 0x6025aa90 = stock but entry 3) | PASS |
| G GetValue/GetDefault | 376/376 PASS |
| W setter site. Misses: state == stock at 0x60827443. **H/L hits**: exact heap bytes, then 0x60827443 reached with every register, MDR and the live stack == the stock run of an S edit to the current S value (getter stubbed). ±6/7 refused | 1233/1233 PASS |
| E Delete/Movie cycle on 4 keys, guards, router (as 12b). **Plus**: after each cycle, facade GetValue(cursor) then SetValue(cursor, 0, same value); GetValue failure means no SetValue; fallbacks never touch the facade | 97/97 PASS |
| V **guide hook** through the real `.data` word. 9 label kinds/ids × 11 heap states. Misses: view object, d0/d2/d3/a2/a3/sp and the live stack == stock. Hits: only kind (5) and the 33 text units change (`[S]`/`[L]`/`[H]` + "All colors"/"Single color", NUL-padded over stale bytes) | 99/99 PASS |
| I init word / T save | 16/16, 19/19 PASS |
| M mutations (22 from 12b + 18 new for ed_set refresh, ed_poke and ed_guide, + 1 spec: guide word left stock) | 41/41 detected |
| Package: decoded `patched.pkg.bin` == emulated image; restore == stock | PASS |

The emulator first found that the getter call changed MDR and the frame's scratch slot. That was harmless for
0x60827440, which returns with `ret`, but both are now restored, so the state is exactly stock.

**Not covered by the emulator** (camera only):
- whether the view update 0x60dec790 runs after Movie or an H/L dial: it is triggered by the listeners `ed_poke`
  and the H/L refresh fire, or by the router timer (inferred, not traced);
- whether a kind-5 label renders in this guide slot (kind 5 is camera-proven in the menu lists, not here);
- guide text width/clipping (16 characters at most);
- the text is English only;
- in ALL mode at a ±5 bound, stock hides the guide (kind 0), and the indicator is hidden with it;
- plus 12b's list (Movie delivery on both routes, real file service, polygon).

Rebuild (each in `systemd-run --user --scope -p MemoryMax=8G -p MemoryHigh=7G -q`):
```
.venv/bin/python -I patches/look_editor/build.py --base releases/test11/edits.json --out generated/look_editor_12c
.venv/bin/python -I tools/build_package.py generated/look_editor_12c/merged.json --out <new dir>
```
