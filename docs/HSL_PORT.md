# Porting the PEN-F HSL patch to the E-P7 1.1

Offline research only. Nothing in this document has run on a camera. No flashable image was
produced. "Confidence" is about whether an address *corresponds* to the PEN-F site. It does not mean
the site is safe to patch.

- Source patch: fishcu `patches/hsl/pen-f/patch.json` (PEN-F 3.1 build 3101, release alpha-20261017,
  CPU base 0x60021020). Read-only reference; no code was copied.
- Target: E-P7 1.1 build 1100 main, decoded SHA-256 `5dd9af16…6190`, CPU base 0x60020020.
- Machine-readable map: `patches/hsl/ep7/port_map.json`. Every `ep7_stock_hex` in it is read from the
  decoded main by `tools/ep7_port_map.py`. `--check` re-verifies them and shows that all 153 PEN-F
  `main_ranges` are covered.
- Tools (ours): `tools/ep7_code_space.py`, `tools/ep7_color_probe.py` (emulator),
  `tools/ep7_port_map.py`.

## Summary

| PEN-F sites (153) | high | medium | low | unmapped |
|---|---:|---:|---:|---:|
| Hooks + data edits (135) | 101 | 8 | 3 | 22 |
| Code-space placements (18 + 1 state) | – | 1 | 18 | – |

Of the 101 high-confidence entries, 72 are the range_schema pointer/length edits. 25 more are other
extended_range edits.

| Group | Status |
|---|---|
| image_parameters | **Fully mapped.** 3 high, plus 1 medium for code space. Emulator-validated end to end on the native selector. |
| editor_storage (data path) | Persist hooks (boot, commit, refresh), capture_acquire and raw_acquire are high. capture/recording_to_job are medium. Both compact hooks are low. |
| editor_storage (GUI) | Dispatch is high. Initial/changed update are medium. set/get/default/paint pointers and the wheel hooks are **unmapped**. |
| extended_range | Schema (72), ALL-bounds (6), wheel drawing (13) and wheel_encode are high. EXIF bounds are medium. value_label, digit table and backup enum are unmapped. The E-P7 needs extra edits for a 4th profile and a touch path. |
| settings_backup | Hooks unmapped. The E-P7 named-record exporter was not found. Only the settings-store API is mapped (high). |
| wifi / orf_metadata | Wi-Fi ingress and reader are medium. The rest is low or unmapped. Lowest priority. |

## image_parameters (minimum viable patch): details and evidence

**color_hook, PEN-F 0x604f7506 → E-P7 0x603b02d9 (high).** Stock bytes `cd 8f fd f0 60` decode to
`call 0x603b0068,[d2,d3,a2,a3],96`. This is the same instruction the PEN-F routine re-issues as its
displaced instruction. Evidence:
- The selector is 243 bytes on both models (PEN-F 0x604f747f, E-P7 0x603b0252). The call sits at
  +0x87 in both.
- This is the builder's only caller.
- It is preceded by `add 1816,a3` (saturation in the request) and `mov 0x6051de2c,a0` (COLOR table).
- It rejoins at **0x603b02de**.

**job_callback, PEN-F 0x604c4011 → 0x60355fd4 (high).** The request-header initializer 0x60354cb9
writes 0x60355fd4 to request+0 and 0 to request+4. The same callback is also used by 36-byte
non-job requests (0x603549b4) and stack requests (0x60368c65). The record/parent guard therefore
stays mandatory.

**Constructor edits (high).** The E-P7 job constructor is at 0x603537eb (PEN-F 0x604c1c0a).
- 0x603537f0 `2c 80 3c` (`mov 15488,d0`) is at entry+5, the same position as PEN-F 0x604c1c0f.
  The new value would be `2c 98 3c` (15512).
- 0x6035390c `85 10` (`mov 16,d1`, the memset of job+15472 after the 896-byte record clear) is the
  equivalent of PEN-F 0x604c1d1f `85 0c`. The new value would be `85 28` (40).
- The heap allocator 0x60022700 serves ≤16384 bytes from class 2, so 15512 stays in the same class.

**Emulator validation** (`tools/ep7_color_probe.py`, all PASS). The runner is fishcu's libsim; every
region is ours.
- A: the native builder writes records at output+688, with hue at rec+18 and L at rec+22. Table H/L
  overrides propagate, and the control word at +976 is 0xfff.
- B: the native selector runs on a synthetic job, request and context, and returns cleanly.
- C: a 5-byte `jmp d32` at 0x603b02d9 goes to a stub at 0x6055e5c0. This exists only in emulator
  RAM; the stub is our own test code, not a port. The stub re-issues the call, applies the guard,
  writes H/L from job+15488 and resumes at 0x603b02de. Results:
  - All 12 records get the expected H/L in wheel order, `2*(r%6)+r/6`.
  - Saturation results are identical to stock.
  - Stack, callee-saved registers and context are unchanged.
  - Records 0, 5 and 15 are all accepted.
  - Wrong-callback and foreign-parent controls leave the output byte-identical to stock.

The test LUT is H×1023 and L×50, not PEN-F's tuned tables.

## Structure offsets that must be translated

| Where | PEN-F | E-P7 | Evidence |
|---|---|---|---|
| Job size = H/L trailer offset | 14920 | **15488** | `mov 15488,d0` @0x603537f0 |
| New job size / tail memset | 14944 / 12→36 | **15512 / 16→40** | memset @0x60353906 |
| Embedded request in job | 12228 | **11364** | wrappers 0x60355409… `mov 11364,a2` |
| Request size | 1132 | **1884** | `mov 1884,d1` @0x60354ce7 |
| Records rel. to request | 1848 | **3212** (job+14576) | 0x60354b8f |
| Record stride × count | 52 × 16 | **56 × 16** | multiply-by-56 in 0x60354b96; memset 896 |
| Parent check (request − X) | −12228 | **−11364** | as above |
| Request saturation | 1076 | **1816** | 0x603b02c8 |
| Params-block saturation (job+36+X) | 5684 | **5538** | packer 0x60354ce4 |
| Colour output records / control | 676 / 964 | **688 / 976** | builder |
| Output hue field, record 0 | 0x2b6 | **0x2c2** (706); L at +4 | builder + emulator A |
| Context+4 request, +12 output; request+0 callback, +4 record | – | unchanged | selector, 0x60354cb9 |
| Capture params: mode / 12×S / profile | 18595 / 18600 / 18625 | 24053 / 24058 / 24083 | fork A, converter 0x603e62d1 |
| Converter extension add (params→job+ext) | 14884 | 15452 | 15488 − 36 |
| Capture-owner table | 0x618689b8, 41×20 | 0x6223d178, 26×24 (IDs 1..25) | fork A |
| Compact ring / slot S / skip flag | 0xa1c6cab8 632 B×5 / +382 / +204 bit 0x8000 | 0xa2731098 980 B×? / +704 / +180 bit 0x4000 | low confidence |
| Compact temporary saturation | 1703 | 2119 | fork A |
| Settings words per part / bank stride | 1274 / 2548 | **1769 / 3538** | ACTIVE get 0x602cc0a7 (`cmp 1768`, ×1769) |
| Saturation setting IDs (H/L cells in part 1) | 931–966 | **927–962** (+4th profile 1655–1666) | conversion table 0x604cd5f8; builder 0x602b7b71 |
| Conversion descriptor table | 0x603dffcc, 968×20 | 0x604cd5f8, 1174×20 | same layout; ±7 list exists at 0x604cc20c |
| Loaded-section mask word | 0xa1c58404 | **0xa272e420** (bit id−1) | loader 0x600457e7 |
| Pending Wi-Fi ID/type/value | 0xa1c8a8b4 | 0xa26a4524 | fork C (medium) |
| Display params (wheel / aux) | 179 / 209 | 115 / 205 (tentative) | fork B |

The capture-population hook has a **register difference**: on E-P7 the capture pointer is in d3,
not d2.

## Code space

The method follows CODE_SPACE.md (our implementation is `tools/ep7_code_space.py`).
- The descriptor table is at **0x60027068**: nine 12-byte entries `{start, logical source,
  destination}`, with source = start − 0x60020020 + 0x406a0020.
- The end getter **0x60045786** is a jump table at 0x60046780 of `mov imm32,d0` stubs.
- The loader **0x600457e7** reads `end − start` bytes from the converted source, then sets bit
  (id−1) at 0xa272e420.
- Boot loads the sections in the order 1, 7, 2, 3, 4, 5, 6, 8, 9 (state machine 0x60044afb).
- The initializer lists are dispatched from 0x6018e19e…: each is a `mov count,d2; mov ptr,a2` pair
  followed by a call per entry.

| Sec | Load (end excl.) | FF suffix inside load | Bytes | Real refs into suffix | Notes |
|---|---|---|---:|---|---|
| 1 | 600d7800–60211000 | **602108ec–60211000** | 1812 | none | 129 KB more FF outside the load (not usable). The one jmp-looking hit 0x6020ec90 is a pointer table. |
| 2 | 60280800–6055e800 | **6055e5b0–6055e800** | 592 | none | Initializer list 0x6055e580+48 ends exactly at the suffix. Holds the COLOR builder/hook. |
| 3 | 6057b200–605b7800 | **605b7180–605b7800** | 1664 | none | All hits are mid-instruction or data; no initializer list. |
| 4 | 605baa00–60748000 | 60747f1c–60748000 | 228 | **zero-count initializer ptr** 0x6018e1bd → 0x60747f1c | Avoid, or keep the count at 0. |
| 5 | 6075a800–60b9e000 | **60b9dd00–60b9e000** | 768 | none | Hits are data tables and mid-instruction bytes. |
| 6 | 60ba7000–61243000 | **612429b0–61243000** | 1616 | none | Initializer list 0x61242884+300 ends exactly at the suffix. Holds GUI and RAW code. |
| 7 | 612c7000–61379000 | **61378c68–61379000** | 920 | none | Initializer list 0x61378c54+20 ends exactly at the suffix. |
| 8 | 613bd000 (length 0) | – | 0 | – | Empty section. |
| 9 | 613c1000–6143a800 | **6143a350–6143a800** | 1200 | `cmp 0x6143a350,a0` @0x613feff6 | Bound of a 16×8 hash table that wraps; it does not scan into the suffix. |

That is 8800 bytes in total; the full PEN-F patch uses 4816. Proposed placements are in
port_map.json and all have a 16-byte guard:
- image_parameters goes in the sec-2 suffix at 0x6055e5c0, the same section as the hook.
- Persistence, transport and the writable transport rows go in sec 1, which loads before sec 2.
- hsl_cycle, hsl_ui and raw_acquire go in sec 6, alongside the GUI and RAW hooks.
- Backup and Wi-Fi go in sec 9; ORF goes in sec 3. These are provisional.

**Not proven:**
- That nothing overwrites the suffix at runtime (BSS/heap computed from bases, DMA).
- That a section reload (the loaded bit is per section) cannot reset writable state kept in padding.
- That flash-package checks accept changed padding.

Keep added code in the **same section as its hook**, or in an earlier-loaded section.

## Mapping table

All `E-P7 stock bytes` are read from our decoded main. The 72 `range_schema_9xx` and 24 E-P7-only
schema edits are summarised in one row; the full list is in port_map.json.

| Group | PEN-F site | PEN-F addr | E-P7 addr | Len | Role | Conf. | E-P7 stock bytes |
|---|---|---|---|---:|---|---|---|
| image_parameters | constructor | `0x604c1c0f` | `0x603537f0` | 3 | job allocation size: 'mov 14920,d0' -> 14944 (+24-byte H/L trailer) | high | `2c803c` |
| image_parameters | constructor | `0x604c1d1f` | `0x6035390c` | 2 | zero-fill of the job tail after the records: 'mov 12,d1' -> 36 so the trailer starts ne... | high | `8510` |
| image_parameters | color_hook | `0x604f7506` | `0x603b02d9` | 5 | 5-byte 'call builder,[d2,d3,a2,a3],96' inside the HSL selector; replaced by 'jmp d32' t... | high | `cd8ffdf060` |
| image_parameters | extension | `0x6069b2b0` | `0x6055e5c0` | 224 | H/L override routine (PEN-F: 220 B in its section-3 FF tail); E-P7: section-2 FF tail, ... | medium | `ffffffffffff… (sha 7c2d694d)` |
| editor_storage | capture_acquire | `0x60253c7f` | `0x602a86b7` | 6 | large capture population: after 12 effective-S halfwords copied; displaced mov 63401,d0 | high | `fccca9f70000` |
| editor_storage | persist_boot_hook | `0x602b9f10` | `0x602af9ee` | 5 | startup: displaced CALL stock_boot_reset,[],4 then publish all-profile H/L | high | `cd720b0004` |
| editor_storage | persist_refresh_hook | `0x602c50be` | `0x602b8916` | 5 | current/staged COLOR refresh entry (d0=context 0 current/1 staged): mov d0,d2; extbu d2... | high | `8216883c50` |
| editor_storage | persist_commit_hook | `0x602f0c52` | `0x602cc612` | 6 | commit return tail: mov a2,d0; exthu d0; ret [d2,d3,a2,a3],36 (a2 = changed-ID count) | high | `f1d81cdff024` |
| editor_storage | hsl_persistence | `0x60427c70` | `0x60210900` | 480 | PEN-F FF padding used for added code/data (472 B) | low | `ffffffffffff… (sha bf9b62d4)` |
| editor_storage | capture_to_job | `0x605205f9` | `0x603e669f` | 6 | large-capture converter: after COLOR S narrowed to params+5684; inject H/L into job+14920 | medium | `5c14fa40165e` |
| editor_storage | recording_to_job | `0x605323f8` | `0x603e91e4` | 6 | separate recording converter (PEN-F rec_ImgPro_ImageParam): old SP+24 capture, SP+20 jo... | medium | `5c18fa40165e` |
| editor_storage | compact_acquire | `0x605576ec` | `0x6030bb19` | 5 | compact/live slot acquisition after effective S copied into slot (PEN-F slot+382) | low | `cdb301f014` |
| editor_storage | compact_to_job | `0x6055a28a` | `0x60322155` | 5 | per-frame compact update: displaced CALL compact_setter,[d2,d3,a2,a3],52; snapshot sp+1... | low | `cd1c1ff038` |
| editor_storage | transport | `0x6069b38c` | `0x60210ae0` | 512 | PEN-F FF padding used for added code/data (500 B) | low | `ffffffffffff… (sha 9f56cda7)` |
| editor_storage | transport_rows | `0x6069b590` | `0x60210ce0` | 544 | PEN-F FF padding used for added code/data (540 B) | low | `ffffffffffff… (sha af71f904)` |
| editor_storage | hsl_axis | `0x6069b7b8` | `-` | 1 | 1-byte RAM axis state in PEN-F section-3 FF tail | unmapped | `` |
| editor_storage | hsl_set_hook | `0x6073659d` | `-` | 7 | GUI property setter: call to UserSettingManager explicit-value adapter | unmapped | `` |
| editor_storage | hsl_wheel | `0x6081b83a` | `-` | 149 | wheel request COLOR2 149-byte span (12x raw_get loop) replaced | unmapped | `` |
| editor_storage | hsl_wheel3_hook | `0x6081b8df` | `-` | 3 | wheel request COLOR3 branch first MOV | unmapped | `` |
| editor_storage | hsl_wheel1_hook | `0x6081b984` | `-` | 3 | wheel request COLOR1 branch first MOV | unmapped | `` |
| editor_storage | hsl_get_pointer | `0x609a4668` | `-` | 4 | vtable slot -> stock property getter | unmapped | `` |
| editor_storage | hsl_default_pointer | `0x609a46ec` | `-` | 4 | vtable slot -> stock default getter | unmapped | `` |
| editor_storage | hsl_ui | `0x60a4feb0` | `-` | 246 | code-space body (not a GUI site) | unmapped | `` |
| editor_storage | hsl_dispatch_hook | `0x60bcba63` | `0x60d1145e` | 5 | editor FSM common dispatcher body: stock `call fsm_descriptor,[],0` replaced by jmp hsl... | high | `cd64010000` |
| editor_storage | hsl_initial_update | `0x60c17373` | `0x60db3072` | 5 | viewer initial update: stock call stock_update,[d2,d3,a2,a3],60 | medium | `cda603f03c` |
| editor_storage | hsl_changed_update | `0x60c17415` | `0x60db3113` | 5 | viewer changed-parameter update: stock call stock_update,[d2,d3,a2,a3],60 | medium | `cd0503f03c` |
| editor_storage | hsl_paint_pointer | `0x60e04828` | `-` | 4 | vtable slot -> COLOR child paint | unmapped | `` |
| editor_storage | hsl_cycle | `0x60fdc2e0` | `-` | 1060 | code-space body (not a GUI site) | unmapped | `` |
| raw_development | raw_acquire_hook | `0x60af2f56` | `0x60c6625f` | 6 | play_edit_raw_set_exif_default: displaced mov (a2),a2; movbu (18595,a2),d0 (picture mode) | high | `f00afa42f55d` |
| raw_development | raw_acquire | `0x60fdc750` | `0x61242ef0` | 96 | PEN-F FF padding used for added code/data (82 B) | low | `ffffffffffff… (sha ce65609c)` |
| orf_metadata | cmio_stream | `0x601caa50` | `0x605b72b0` | 32 | PEN-F FF padding used for added code/data (32 B) | low | `ffffffffffff… (sha af961376)` |
| orf_metadata | cmio_table | `0x601caaca` | `0x605b7250` | 96 | PEN-F FF padding used for added code/data (91 B) | low | `ffffffffffff… (sha ce65609c)` |
| orf_metadata | cmio_table_tail | `0x601cac00` | `0x605b7370` | 112 | PEN-F FF padding used for added code/data (105 B) | low | `ffffffffffff… (sha d583aef5)` |
| orf_metadata | native_orf_export | `0x601cade0` | `0x605b7190` | 192 | PEN-F FF padding used for added code/data (191 B) | low | `ffffffffffff… (sha 8f62c344)` |
| orf_metadata | text | `0x601caed0` | `0x605b72d0` | 160 | PEN-F FF padding used for added code/data (155 B) | low | `ffffffffffff… (sha 00525168)` |
| orf_metadata | native_orf_hook | `0x6053caff` | `-` | 7 | the single call to native CMIO copy inside rec_raw_make_header; replaced by call to exp... | low | `` |
| settings_backup | backup_import | `0x601cac70` | `0x6143a360` | 368 | PEN-F FF padding used for added code/data (363 B) | low | `ffffffffffff… (sha 0b46df9d)` |
| settings_backup | backup_export_hook | `0x602c1829` | `-` | 6 | export kind-2 bank: emit 2,PENF_HSL_V1 line before native continuation 0x602c182f | unmapped | `` |
| settings_backup | backup_scratch_allocate | `0x602c1d7f` | `-` | 3 | restore operation allocation size 2048 -> 2112 (+64 extension state) | unmapped | `` |
| settings_backup | backup_scratch_initialize | `0x602c1d9d` | `-` | 3 | restore scratch clear size 2048 -> 2112 | unmapped | `` |
| settings_backup | backup_header_hook | `0x602c1e8f` | `-` | 6 | accepted bank header: reset extension parse state, resume 0x602c1e95 | unmapped | `` |
| settings_backup | backup_line_hook | `0x602c1ed2` | `-` | 6 | type-2 record line: intercept PENF_HSL_V1 before native name lookup | unmapped | `` |
| settings_backup | backup_footer_hook | `0x602c1f73` | `-` | 6 | type-3 bank terminator: apply decoded H/L, resume 0x602c1f79 | unmapped | `` |
| settings_backup | backup_lifecycle | `0x60427e48` | `0x6143a4d0` | 48 | PEN-F FF padding used for added code/data (46 B) | low | `ffffffffffff… (sha 80a76a18)` |
| settings_backup | backup_export | `0x60427ed0` | `0x6143a500` | 224 | PEN-F FF padding used for added code/data (216 B) | low | `ffffffffffff… (sha 7c2d694d)` |
| extended_range | range_backup_enum_export | `0x602c25a9` | `-` | 7 | settings backup enum conversion: call to backup descriptor lookup | unmapped | `` |
| extended_range | range_backup_enum_import | `0x602c25fd` | `-` | 8 | settings backup enum conversion: call to backup descriptor lookup | unmapped | `` |
| extended_range | range_wheel_encode | `0x602fc3a7` | `0x602dce4c` | 28 | value-code conversion for C3d async draw: S range check + jump table -> code S+5 | high | `a0fbc040a005… (sha f4280523)` |
| extended_range | range_exif_minimum | `0x6054da74` | `0x60301678` | 2 | EXIF/makernote range record min | medium | `80fb` |
| extended_range | range_exif_maximum | `0x6054da78` | `0x6030167c` | 2 | EXIF/makernote range record max | medium | `8005` |
| extended_range | range_draw_frame | `0x60ac9e02` | `0x60c50ce3` | 4 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fafe90fe` |
| extended_range | range_polygon_step | `0x60ac9eea` | `0x60c50dcb` | 3 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `f90009` |
| extended_range | range_polygon_origin | `0x60ac9ef5` | `0x60c50dd6` | 6 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fccc0000b841` |
| extended_range | range_ticks_step | `0x60aca073` | `0x60c50f54` | 6 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fccc00001041` |
| extended_range | range_ticks_origin | `0x60aca081` | `0x60c50f62` | 6 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fccc0000b841` |
| extended_range | range_ticks_y | `0x60aca09c` | `0x60c50f7d` | 4 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fac0ec00` |
| extended_range | range_ticks_tangent_x | `0x60aca0a5` | `0x60c50f86` | 4 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fac01801` |
| extended_range | range_ticks_tangent_y | `0x60aca0ae` | `0x60c50f8f` | 4 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fac04401` |
| extended_range | range_ticks_compute_count | `0x60aca0d6` | `0x60c50fb7` | 2 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `af0b` |
| extended_range | range_ticks_draw_y | `0x60aca100` | `0x60c50fe1` | 4 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fad0ec00` |
| extended_range | range_ticks_draw_count | `0x60aca124` | `0x60c51005` | 2 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `ba0b` |
| extended_range | range_selected_y | `0x60aca15c` | `0x60c5103d` | 4 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fad1ec00` |
| extended_range | range_draw_unframe | `0x60aca181` | `0x60c51062` | 4 | C3d wheel drawing geometry (polygon/ticks for 11->15 positions) | high | `fafe7001` |
| extended_range | range_value_label | `0x60c84c75` | `-` | 38 | numeric viewer label: value -> sign code + magnitude bytes | unmapped | `` |
| extended_range | range_all_minimum_1 | `0x60cb2755` | `0x60e23115` | 2 | ALL group decrement stop at bound, COLOR1 | high | `a0fb` |
| extended_range | range_all_minimum_2 | `0x60cb278f` | `0x60e23153` | 2 | ALL group decrement stop at bound, COLOR2 | high | `a0fb` |
| extended_range | range_all_minimum_3 | `0x60cb27c8` | `0x60e2318d` | 2 | ALL group decrement stop at bound, COLOR3 | high | `a0fb` |
| extended_range | range_all_maximum_1 | `0x60cb2812` | `0x60e23214` | 2 | ALL group increment stop at bound, COLOR1 | high | `a005` |
| extended_range | range_all_maximum_2 | `0x60cb284b` | `0x60e23251` | 2 | ALL group increment stop at bound, COLOR2 | high | `a005` |
| extended_range | range_all_maximum_3 | `0x60cb2883` | `0x60e2328a` | 2 | ALL group increment stop at bound, COLOR3 | high | `a005` |
| extended_range | range_digit_count | `0x60e04475` | `-` | 1 | numeric widget digit count/table (07 -> 08; table 0x60e03f28 -> 0x60ec3654) | unmapped | `` |
| extended_range | range_digit_table | `0x60e04478` | `-` | 4 | numeric widget digit count/table (07 -> 08; table 0x60e03f28 -> 0x60ec3654) | unmapped | `` |
| extended_range | ep7_only_target_bound_0x60e22f49 | `None` | `0x60e22f49` | 2 | E-P7 editor direct-target bound (likely touch/slider): cmp 5,d2 / cmp -5,d2 before repe... | low | `aa05` |
| extended_range | ep7_only_target_bound_0x60e22f4d | `None` | `0x60e22f4d` | 2 | E-P7 editor direct-target bound (likely touch/slider): cmp 5,d2 / cmp -5,d2 before repe... | low | `aafb` |
| extended_range | ep7_only_all_minimum_mode64 | `None` | `0x60e231ca` | 2 | ALL bound for E-P7 4th profile (public mode 64) | high | `a0fb` |
| extended_range | ep7_only_all_maximum_mode64 | `None` | `0x60e232c6` | 2 | ALL bound for E-P7 4th profile (public mode 64) | high | `a005` |
| wifi | wifi_validate | `0x601caa70` | `0x6143a6c0` | 96 | PEN-F FF padding used for added code/data (88 B) | low | `ffffffffffff… (sha ce65609c)` |
| wifi | wifi_body | `0x601cab25` | `0x6143a5e0` | 224 | PEN-F FF padding used for added code/data (219 B) | low | `ffffffffffff… (sha 7c2d694d)` |
| wifi | wifi_read_head | `0x601cae9f` | `0x6143a720` | 48 | PEN-F FF padding used for added code/data (34 B) | low | `ffffffffffff… (sha 80a76a18)` |
| wifi | wifi_read_tail | `0x601caf6b` | `0x6143a750` | 80 | PEN-F FF padding used for added code/data (75 B) | low | `ffffffffffff… (sha 6d92a8ea)` |
| wifi | wifi_receiver_hook | `0x607ab916` | `-` | 5 | application receiver: 5-byte CALL f0,24 to stock_receive replaced by JMP to bridge | unmapped | `` |
| wifi | wifi_bridge | `0x60a4ffa8` | `0x605b73e0` | 16 | PEN-F FF padding used for added code/data (12 B) | low | `ffffffffffff… (sha 5ac6a594)` |
| wifi | wifi_reader_hook | `0x60aa23c7` | `0x60bd2785` | 7 | get_mcon: replace the setting-getter call with HSL1 discovery/H/L readback | medium | `dd85946fff0004` |
| wifi | wifi_ingress_hook | `0x60aa26f0` | `0x60bd2aba` | 10 | set_mcon: replace 'call stock_raw_set,[d2,d3],12; mov 200,d0' with marked-value ingress | medium | `dda3916fffc0… (sha 404c3e28)` |
| wifi | wifi_allowed | `0x60fdc704` | `0x6143a7a0` | 80 | PEN-F FF padding used for added code/data (68 B) | low | `ffffffffffff… (sha 6d92a8ea)` |
| extended_range | range_schema_931…966 (72) | `0x603e40a8…` | `0x604d1058…0x604d13f8` | 4/2 | conversion-descriptor pointer → ±7 list, length 0x16→0x1e; E-P7 IDs 927–962 | high | per entry in JSON |
| extended_range (E-P7 only) | schema 1655…1666 (24) | – | `0x604d1094…0x604d140c` | 4/2 | 4th COLOR profile (public mode 64) | medium | per entry in JSON |

Per-site evidence strings are in port_map.json (`evidence`, `notes`).

## Biggest risks

1. **The E-P7 has 4 COLOR profiles.** Mode 64 uses IDs 1655–1666, and the IDs are shifted by −4.
   Every 3-profile edit, the transport, persistence and backup format need a 4th branch.
2. **The GUI editor hooks are unmapped:** set, get/default vtable slots, paint, wheel requests and
   the editor RAM globals. The touch path adds a ±5 bound (0x60e22f49/4d) that PEN-F lacks.
3. **Image transport differs.** There are two converters: 0x603e62d1, shared by four job builders,
   and 0x603e8af1 for CPU2. There are 25 capture owners, not 40. The compact/CPU2 path is not
   traced, so compact_acquire/compact_to_job are low and must not be used.
4. **A second builder path bypasses the hook.** 0x603afb94 is called at 0x603b027c when
   request+1524 ≠ 0 and context+60 bit 0x10000000 is set. It is unclear which images use it.
5. **settings_backup cannot be ported until the E-P7 Workspace exporter is found.** Do not patch
   the look-alike 2048-byte allocator at 0x602c95a3/af. It is a message pool.
6. **Wi-Fi:** `set_mcon` truncates the value to a signed byte, which breaks the PEN-F marked-value
   protocol.
7. **Wheel-geometry "after" bytes** are copied from PEN-F. That assumes identical on-screen geometry.
8. **Code-space residency** is a static argument only (see above). PEN-F also keeps *writable* state
   (axis, transport rows) in padding.

## Open questions

- Where is the COLOR profile number (1–4) available at the builder hook? Answering this would allow
  per-profile H/L without the transport.
- Which of the 13 IDs per profile read by the parameter builder 0x602b7b71 are the 12 sectors
  (927…938 + 1667…)?
- What do the hue and lightness units mean on E-P7? The COLOR table is byte-identical to PEN-F
  (same SHA), but the ISP response is unverified.
- When does the alternate builder path 0x603afb94 run?
- What drives the compact ring 0xa2731098: slot count, profile byte, acquisition state?
- Which settings-backup code exists on E-P7 at all (schema in the 0x106 asset)?

## Recommended minimal first patch (design only, nothing built)

**"Fixed H/L in COLOR mode."** It reuses only the high-confidence sites and needs no struct
changes:

1. **Hook:** replace `cd 8f fd f0 60` at **0x603b02d9** with `jmp d32` to **0x6055e5c0** (sec-2
   suffix, same section).
2. **Routine (~120–200 B):**
   - Re-issue `call 0x603b0068,[d2,d3,a2,a3],96`.
   - Save the scratch registers without a second CALL, so MDR is preserved.
   - Read output = (12,a2).
   - Overwrite the hue at output+706+24·r and L at +710+24·r for r = 0..11, from a constant
     24-halfword table placed after the routine.
   - Restore the registers and `jmp 0x603b02de`.

   The selector only reaches this call for picture mode 11 (COLOR) and not on the 0xf00d bypass.
   Every image with a COLOR profile, including all 4 profiles, then gets the same H/L.
3. **No constructor edits, and no reads of job memory.** These are only needed once per-image H/L
   arrives through the trailer. When they are added, use the guard (callback 0x60355fd4,
   records request+3212 ×56 ×16, parent = request−11364) and the edits at 0x603537f0 and
   0x6035390c.

Before any camera test:
- Extend `tools/ep7_color_probe.py` to run the real routine.
- Diff all changed bytes against the stock image.
- Check that the restore image is built from the verified stock BIN.
- Get an explicit go-ahead.

Changed bytes would be 5 bytes of code plus about 250 bytes of padding.
