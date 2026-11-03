# Picture-in-picture focus assist (issue #18): feasibility

Request: a small magnified window over the full live view (as on the Lumix GM1), ideally with peaking,
for manual focus with vintage lenses. This is a short static study (strings and existing docs, no code
traced, nothing built). [V] = seen in the firmware, [I] = inferred.

## Short answer

**Hard / long shot.** No OM/Olympus body of this generation has it. The E-P7 display path has one live-view
image window per output. A useful PiP needs real detail from the sensor, not an enlarged copy of the
640×480 live-view frame, so the live-view job itself would have to produce a second, cropped output.

## 1. How stock Magnify / MF Assist works

- [V] `CapThr_ThroughImage` (the LV controller in ASPECT.md §1e) keeps `_MFAssistClipCoordinate` and
  `_MovieTeleconClipCoordinate`, and `execUpdateThrough` sends the LV pipeline `info.clip XY/WH`,
  `info.through_zoom`, `info.through_mode` and `info.sensor_type`. The magnification levels are x3/x5/x7/x10/x14
  (`ZOOM_FRAME_MAGNIFICATION`), with the states `LvMode1 ZOOM_FRAME` / `LvMode2 … ZOOM_SCROLL`.
  `getOutputSizeForFineZoom` (0x60882ec4) is a separate output-box switch for the zoomed view.
- [V] The sensor mode list has only `CAM_SENSOR_MODE_STILL` and `CAM_SENSOR_MODE_MOVIE_*`. There is no
  sensor mode just for magnify.
- [I] So magnify is a **crop inside the LV development** (the clip rectangle is applied before the resize
  to the LV output box). It is not a display-side zoom of the finished 640×480 frame. Whether the sensor
  readout also changes (a windowed or less binned readout at x10/x14) is not traced.
- [V] `execUpdateThrough() set Peaking` shows that peaking is part of the same LV update. Stock already
  allows peaking together with magnify.

## 2. Can the display show two images?

- [V] The SDK API has `API_OSD_PLANE_LAYER1..3` + `WORK` (the three 256-colour palettised OSD layers in
  OSD.md) and **one** image plane, `API_IMAGE_PLANE_NORMAL` / `_WIDE`.
- [V] `display_through_info` / `MVR_IMG_PARAM out_size` holds a single image rectangle per output (`image`,
  `image_clip`, `image_movie` XY/WH). `sub_out_size`, `sub_display_mode` and `ctrlSubDisplayLayer` belong to the
  second output (HDMI sub display, see `make_image_hdmi_sub_display`). They do not add a second window on the
  LCD.
- [V] There is a blit/transfer descriptor (`Img2Info`: FromArea, FromCoordinate, ToTarget, ToCoordinate,
  AddressTrans, LayerType) that copies regions between buffers or layers.
- [V] The siblings E-M5 III (1.7), E-M10 IV (1.1) and E-M1 III (1.6) have the same magnify strings
  (`startMFAssist`, `ZoomFrame`, `MODE_LV_MAGNIFY`, `MODE_PEAKING_ENABLE`) and no PiP, sub-window or
  windowed-magnify strings. There is no OM code to borrow.

## 3. Possible implementations

| Option | How | Problems | Rating |
|---|---|---|---|
| A. OSD-plane window | Each frame, the CPU copies a crop of the LV buffer (or uses the `Img2` blit) into one OSD layer, as grey levels through a grey palette | The crop comes from the 640×480 LV frame, so a "×3" window shows no more detail than the normal view. It is only enlarged pixels, of little use for focusing. It is also mono or palettised, the CPU copy runs at low fps, and the OSD palette is shared with the UI | Medium effort, low value |
| B. Second LV-job output | Add a stage to the LV job that writes a 1:1 crop (around 200×150) of the pre-resize image to a side buffer, then blend or blit it into a corner of the LV output. Stock Soft Focus LV already writes a side buffer (the 144×108 reduce) and blends it back in one pass (LV_ART_PREVIEW.md §1.3) | Needs the stage format for an offset crop at full scale, a corner-placed blend, and the LV readout resolution (untraced). It adds a pass per frame (frame rate), a buffer from the job pool, and AF/peaking interplay | **Hard**, the only option that gives real detail |
| C. Second display window | A second image layer on the LCD fed by the magnify crop | No second LCD image plane appears in the API. It would need display controller registers that nobody has mapped | Long shot |

Peaking can stay on the main view in every option, because stock already has it.

**Cheapest believable path:** B. First trace what stock magnify sends to the LV job (`execUpdateThrough`
clip fields → job), to learn whether the job reads a higher-resolution readout. If it does not, B gives no
more detail than A, and the feature is not worth building.

## Next steps (if pursued)

1. Trace `execUpdateThrough` → the LV job: where `info.clip` and `through_zoom` land, and the LV readout size.
2. Check in the emulator whether the Soft Focus reduce/blend stage can take an offset source rectangle and a
   destination rectangle.
3. Camera test: frame rate with one extra LV pass (the bloom preview already measures this cost).
