# test12b-editor: test 12 editor with Movie as the axis key

**What changed from test12-editor.** On the camera, Delete (0x9016) never reaches the Color Profile editor,
whether it is opened from the OK panel or from the front Profile Control switch. In this screen the Movie
button (event 0x9012) has no stock function, so it is now the key that cycles the axis.

- The +52 word of each COLOR1–4 editor record (0x61185c10/…c48/…c80/…cb8, stock 0) now points to `ed_event`.
  Editor init copies it to parent+88, and the router 0x60e20cdc sends 0x9012 there.
- `ed_event` accepts 0x9016 **or** 0x9012 and cycles S → L → H → S. If any guard fails, 0x9012 goes to the stock
  +52 default 0x60e228fb (`clr d0; retf` = "not handled"), and everything else goes to 0x60e22191 as before.
- The Delete hook (+36) is unchanged. INFO (0x9014/0x9015), OK and the dials are unchanged.
- Everything else is as in test12-editor (H/L live edit, card save on the next half-press, start on S).

Edits: 100 (test 12's 96 + 4 record words). `ed_ui` is now 815 B (claim 816). `restore-stock.pkg.bin` is
identical to test 11/12. The packages and `card/` are local only (gitignored). `card/` is test 12's.

## Camera test plan (one step at a time; stop at the first surprise; SD restore ready)

Run test12-editor's plan (`releases/test12-editor/README.md`), but press **Movie** wherever it says Delete.
Check each Movie step on **both routes** into the colour wheel:
**(a)** the OK panel → Color Profile editor, and **(b)** the front Profile Control switch.

1. **Card WITHOUT EP7MOD**, routes (a) and (b): press Movie in the editor. Nothing should happen: no movie starts,
   the axis does not change, and the editor stays open. INFO still toggles ALL. Then leave the editor and check that
   Movie records as normal.
2. **Card with EP7MOD, half-press once**, then route (a) on COLOR2: Movie → Light, Movie → Hue, Movie → S (S values
   unchanged). If the numbers do not redraw, turn the dial one notch. Repeat via route (b).
3. Then steps 3–6 of test 12 (Hue on green and the JPEG check, save on half-press, write-protect, COLOR4 and ALL).
   Also press Delete once. Expected: nothing happens, as on test 12.

## Verification (generated/look_editor_12b/verify.json; emulator only)

`tools/ep7_verify_look_editor.py releases/test12b-editor/edits.json --base releases/test11/edits.json`

| Part | Result |
|---|---|
| S static (record +52 words included in the "ours" set) | PASS |
| G GetValue/GetDefault | 376/376 PASS |
| W setter site | 1233/1233 PASS |
| E Delete via +36 (as in test 12), **plus Movie**: cycle on 4 keys via the +52 word; Delete and Movie share one axis; first use; 7 guards and 5 heap states fall back to 0x60e228fb with state == stock; router 0x60e20cdc with the parent slots built as init does: INFO 0x9014, 0x9015 and OK reach the same stock handlers with equal state, and 0x9012 goes 0x60e228fb (stock) → ed_event (patched) | 96/96 PASS |
| I init word | 16/16 PASS |
| T save | 19/19 PASS |
| M mutations (16 old + 4 Movie-path source + 2 spec: +52 left stock / pointed at 0x60e22191) | 22/22 detected |
| Package: decoded `patched.pkg.bin` == emulated image; restore == stock | PASS |

Not covered by the emulator: which physical key sends 0x9012 in this screen (camera report: Movie), and whether
the outer screen FSM delivers it on both routes. Plus test 12's list (refresh, file service, redraw, polygon).

Rebuild (each in `systemd-run --user --scope -p MemoryMax=3G -p MemoryHigh=2500M -q`):
```
.venv/bin/python -I patches/look_editor/build.py --base releases/test11/edits.json --out generated/look_editor_12b
.venv/bin/python -I tools/build_package.py generated/look_editor_12b/merged.json --out <new dir>
```
