# 名建筑拆解 kit (Blender 5.2, EEVEE) — styles paper + real, exploded views

Every episode uses the same code path. The only things that change are the **episode spec** (a JSON file) and, for a complex building, a short **builder** (Python that calls kit components). Colours, shader, the lighting presets, animation curves, the section cut and the render settings all live in the kit, so every episode meets the same standard. The one look decision per episode is its lighting preset (`real_look.preset`, chosen for the building and held for the whole episode, see "Lighting presets").

Repo layout, standard and process: see the top-level README.md, docs/STANDARD.md and docs/PROCESS.md.
All commands below run from the repo root; paths come from `kit/config.py` (env vars `ARCH_KIT_MODELS`, `ARCH_KIT_MUSIC`,
`ARCH_KIT_OUT`, `ARCH_KIT_FONTS`, `ARCH_KIT_SERIF`, `ARCH_KIT_DIN`, `BLENDER`, `ARCH_BLENDER_LOCK`). In episode / prep JSON files a path
starting with `models/`, `music/` or `out/` resolves under those folders; other relative paths resolve next to the JSON.

```
kit/
  config.py              paths + env vars, resolve() for JSON paths, find_config() for the episode argument
  produce.py             one command per video: anchors -> frames (render segments, resumable) -> overlay -> finish
  finish.py              music under the silent overlay video (two-pass loudnorm to -14 LUFS, fades) + share copy
                         (1080x1920, two-pass 5 Mb/s)
  import_scan.py         photogrammetry GLB: downscale textures outside Blender, then scale/align/save a .blend
  import_mesh.py         detailed closed mesh (STL, e.g. a 3D-print model) -> aligned, segmented (Manifold booleans,
                         filled cut faces), material-tagged skin pieces a builder loads in place of its procedural exterior
  paperkit.py            the kit: paper shader, components, rise/fold/pop presets, section cut,
                         camera rig, anchor export, render settings, JSON part builder
  realkit.py             style "real": procedural PBR recipes, sky/sun/haze lighting, bloom, and detailed
                         classical components (Corinthian column, entablature, pediment, ring cornice, step rings)
  light_presets.py       lighting preset library (golden_hour, blue_hour, overcast_drama, night_flood, morning_mist,
                         noon_hard): look + ground palette + grade per preset; one preset per episode
  preset_stills.py       one hero still per preset + labelled contact sheet (python3; drives Blender one at a time)
  blueprint.py           optional blueprint / x-ray graphics layer (episode "graphics"); off unless the JSON has it
  diagram.py             structural diagram helpers: growing load / thrust lines with riding arrow heads, glowing
                         rings, pour shells, translucent ghost material, episode "ghost" keys (see "Ghosting")
  run_episode.py         one command per episode (build -> animate -> anchors / stills / frames)
  overlay.py             colour grade + 2D labels + leader lines + top captions over the frames, then H.264 (BT.709)
                         + silent AAC
                         (plain python3, stateless per-frame compositing, --workers 2)
  render_final.sh        final 1080x1920 frames: one Blender process per render segment, resumable
  bench_render.py        time/compare render-setting variants on a few frames in one Blender process
  build_pantheon.py      ep01 geometry (Pantheon) from kit components
  episodes/ep01_pantheon_paper.json   the early PAPER-style ep01 spec (rise from the ground; style rejected, kept for reference)
  lookdev/               look-dev still scripts (scan exterior comparison, hero reveal still)
episodes/ep01_pantheon/episode.json   the current ep01 spec (real style, exploded view) -- the template for new episodes
```

## Commands (one Blender process at a time, 8 GB machine)

```bash
B=kit/blender_locked.sh      # = Blender -b ..., but only one Blender at a time on the machine (waits for the lock)
E=episodes/ep01_pantheon/episode.json
# look check: named stills from the spec, 540x960
$B -b --factory-startup -P kit/run_episode.py -- $E --draft --stills out/ep01_stills
# only some stills / stills at arbitrary times
$B -b --factory-startup -P kit/run_episode.py -- $E --draft --stills out/ep01_stills --only s05
$B -b --factory-startup -P kit/run_episode.py -- $E --draft --samples 8 --stills out/ep01_test --still-t 0 5.5 13.2
# label anchors for the 2D overlay: per-frame pixel positions
$B -b --factory-startup -P kit/run_episode.py -- $E --anchors out/ep01_anchors.json
# frames 1080x1920 PNG (frame 1 == t 0 s), render_segments applied per frame, resumable
$B -b --factory-startup -P kit/run_episode.py -- $E --anim out/frames --frames 1:960 --skip-existing
# save the .blend if you want to inspect it by hand
$B -b --factory-startup -P kit/run_episode.py -- $E --save-blend out/ep01.blend
# quality overrides for tests:  --samples 8   --set shadow_res=0.35 raytracing=0 shadows=0   (--no-scan skips the scan)
# fixed-camera stills of the finished building from the JSON "shots"
$B -b --factory-startup -P kit/run_episode.py -- $E --shots out/lookdev_real
# try another lighting preset without editing the JSON (replaces real_look, drops the episode grade)
$B -b --factory-startup -P kit/run_episode.py -- $E --look night_flood --draft --stills out/test --still-t 0
# one hero still per lighting preset + labelled sheet (python3; runs Blender one at a time, ~6 s per preset)
python3 kit/preset_stills.py $E out/light_presets --presets blue_hour night_flood --draft
# the whole video (anchors, frames, overlay, music) in one command:
python3 kit/produce.py $E draft        # or: final (one Blender per render segment, like render_final.sh)
```

The process exits when it finishes, so nothing stays resident. Do not run two renders at the same time.

## Episode spec (JSON)

| key | meaning |
|---|---|
| `palette` | `{name: "#hex"}` paper colours **by material** (brick, travertine, granite_grey…). Never pure white. Every face references one of these names. |
| `builder` | Python file with `build(pk, spec)` (looked up next to the JSON, then in `kit/`). Use it for buildings that need computed geometry. |
| `parts` | Used when there is no builder: `[{"part": "ring_wall", "component": "cylinder_wall", "role": "drum", "args": {...}}]`, built in list order. Components are listed below. |
| `schedule` | Build order, which must follow the narration and labels: `[{part, t, dur, stagger, mode, order, overshoot, fold_angle, ring_step, rings:[..], role:"..."}]` |
| `section` | `[{t, dur, az, from}]` sweeps the cutting plane in from camera azimuth `az` to the centre. `{t, dur, az, restore:true}` closes it again. |
| `camera` | Keys `{t, az, el, dist, target:[x,y,z], lens, interp: EASE/LINEAR/HOLD}`. `az 0` = camera on −Y looking +Y (front), `90` = on +X. Negative `el` looks up. `{t, loc, target}` is also accepted. |
| `anchors` | Label anchor points: `{"name", "pos":[x,y,z]}` or `{"name", "part", "where": "top/front/center"}` (follows the part's animated bbox). |
| `stills` | `[{name, t}]` named proof frames. |
| `extra_parts` | Same format as `parts`, built after the `builder` (e.g. an inscription via `text_piece`). |
| `spots` | `[{name, pos, target, radius, power, color, blend, soft}]` narrow spot lights (ep01: sunlight pool through the oculus). |
| `poche_bands` | `[[z_m, "#hex"], ...]` section-cut fill by world height instead of one poche colour (ep01: heavy → light aggregate). |
| `overlay` | For `overlay.py`: `labels`, `captions` (files next to the episode JSON), `anchor_for` {label id: anchor name}, `place` {label id: {zone: top/bottom, side: left/right, y}}; unplaced labels are laid out automatically from the anchor path. |
| `render` | `{samples, shadow_res, raytracing, fast_gi, shadow_rays, shadow_steps}` (paper style; `real_render` overrides it in real style). Paper ep01 uses 24 / 0.4 / on / on. |
| `render_segments` | `[{name, t:[t0,t1], samples, shadow_res, raytracing, fast_gi, vol_tile, vol_samples, denoise}]` per-time-range settings on top of `render`/`real_render` (then `--samples`/`--set` win). `--anim` switches them in-process; `render_final.sh` runs one Blender per segment. See "Final render settings". |
| `look` | Paper style lighting: `sun_az, sun_el, sun_angle (soft shadow), sun_strength, fill_strength, fill_az, fill_el, sky_*`. |
| `real_look` | Real style lighting: `{"preset": "<name>", ...LOOK overrides}`. The preset (`kit/light_presets.py`) sets sun, sky, clouds, rim, floods, shaft, mist, exposure, bloom; any other key overrides it. Without `preset` the `realkit.LOOK` defaults apply. `sun_keys` `[[t, mult], ...]` keys the key-sun strength over time (ep01: 10 % under the relieving-arch diagram). See "Lighting presets". |
| `real_palette` | Real style: colour overrides by palette name, on top of the preset's `palette` (warm-stone ground). |
| `grade` | `overlay.py` colour grade of every rendered frame, before labels. Without it the preset's grade applies. See "Grade". |
| `ghost` | `[{select, keys: [[t, v], ...]}]` keys the object prop `pk_ghost` (0 opaque .. 1 gone) on real pieces: fade parts out / in (ep02: the first-dome ghost; the print's window band crossfading into the builder's window ring, so the swap is never a cut; the N/S window walls dissolving in L7). Applied after `apply_episode`; hide fully faded pieces with `visibility` (a fully transparent dithered piece still costs render time, and lying on another piece it draws black). |
| `diagram` | Builder-specific timings for the structural diagram, read by the builder's `after_episode(pk, spec)` hook (run_episode calls it after `apply_episode`, so diagram pieces never move a flood lamp). ep02: `ribs`, `pendentives`, `first_dome`, `half_domes`, `buttresses`, each with a `show` window and `t0` / `speed` / `fade` per line set; `ribs.pulses` = thin dim lines with staggered comet pulses (a lead pulse alone on the labelled rib, then small waves), so only a fraction of the 40 lines is bright at any moment. |
| `graphics` | Optional blueprint / x-ray layer (`blueprint.py` + overlay dimension lines / blueprint cards). Off unless present; not part of the standard. |
| `fps`, `duration`, `lens` | 24 fps. Duration in seconds. |

**Timing contract.** All times are in seconds, and frame = round(t·24)+1. The narration/label script should be written first, and each schedule entry's `t` is set to its label's `t`. Schedule `mode` values:
- `grow`: the piece extrudes upward from its own base, with a small BACK-easing overshoot ("平地而起").
- `fold`: a pop-up piece. It is hinged at its bottom edge, starts lying flat outward and folds up. Walls and dome rings use this; combined with `order:"ring"` and `ring_step`, the dome closes ring by ring.
- `pop`: scales up from the piece's centre. Used for floor tiles, coffers, arches and the sphere.
- `vanish`: shrinks the piece away.
- `sink`: reverse of the rise for loop endings: the piece drops straight down under the paper board, then switches off.

`order: "az"` accepts `az0` (start azimuth in plan degrees), e.g. to make arches light up left to right from the camera.

Values for `order`: `index` (build order), `reverse`, `az`, `az_from_front`, `x`, `-x`, `y`, `-y`, `z`, `radial`, `ring`, `random`.

### Anchor JSON (for leader lines)
```
{fps, width:1080, height:1920, frame_start, frame_end, step,
 anchors: {name: [[x_px, y_px, flags] | null, ...one per frame...]}}
```
Pixels are measured in the full 1080×1920 frame, origin at the top left. `flags & 1` means in front of the camera and inside the frame. `flags & 2` means a ray from the camera hits geometry first (occluded). The occlusion test ignores the shader section clip and the sphere wireframe, so trust `&1` and treat `&2` as a hint. `null` means the anchor's part has no visible pieces yet. Exporting all 961 frames of ep01 takes about 40 s.

## Components (`paperkit.py`), all in metres. Each returns a list of paper-piece objects.

| function | what it builds |
|---|---|
| `box_piece(part, x0,x1,y0,y1,z0,z1, col, top_col, side_col)` | block |
| `sheet(part, poly, thickness, col, normal)` | flat card with visible thickness and a dark rim (the solidify look) |
| `revolve_pieces(part, profile[(r,z)], n_seg, cols=[per edge], az0, az1, skip, ring)` | any solid of revolution, cut into sector pieces. Each piece carries hinge metadata for `fold`. |
| `cylinder_wall(part, r_in, r_out, z0, z1, n_seg, cols=[bottom,outer,top,inner])` | thick drum wall |
| `ring_band(part, r_in, r_out, z0, z1, col, n_seg, skip)` | cornice or step ring |
| `column(part, x,y,z, h, d, shaft, base, capital)`, `columns_at(part, pts, h, d)`, `column_ring(part, radius, count, h, d)` | simplified classical columns |
| `gable(part, x0,x1, y_front, y_back, z_base, rise, entab_h, …)` | entablature + pediment + raking cornice + 2 roof slabs |
| `dome_shell(part, center, r_in, el0, el1, n_rings, n_seg, outer=thickness or fn(u)->(r,z), ring0, az0, az1, meta)` | dome built from rings, with optional oculus (`el1` < 90); `az0/az1` = only that plan sector (half domes, exedrae), `meta` = props on every piece |
| `ribbed_dome(part, center, r_in, thick, el0, el_c, n, az0, rib_w, rib_out, rib_in, …)` | spherical shell in n gores, each with a rib on its centre line outside and inside (ribs converge on a crown medallion, `el_c`..90, 2 pieces); ep02: the brick dome with 40 ribs |
| `window_crown(part, center, r_in, r_out, z0, h, n, az0, az1, win_w, sill, rect_h, seg_az, fin, extra_openings, cols, glass)` | drum / window ring with n arched windows cut right through it, a buttress fin on each pier, glass panes as separate pieces (outer face `window_glass`, inner face `window_sky`); full ring = seams through the window centres; arc = pieces split at `seg_az`; `extra_openings` = bigger arches below (into exedrae). Returns (band, glass) |
| `pendentive(part, center, side, z_spring, z_top, inset, rings, col_in, col_back, col_top)` | the 4 pendentives of a square bay: spherical triangles of the sphere through the corners, solid back to the arch planes (inset 4 cm), top edges = the circle the dome sits on; `z_top` adds a vertical collar up to the arch extrados |
| `arch_barrel(part, center, span, thick, depth, axis, z_spring, n_vous, leg, col_soffit, col_face, col_ext, col_joint)` | semicircular barrel arch with real depth, one piece per voussoir (even n = joint on the crown seam); `col_face` may be (inner face, outer face); `leg` seats the end voussoirs in the piers |
| `windowed_wall(mb, P, ua, ub, z_lo, top, windows, w0, w1, cols, glass_mb, glass)` + `P_cyl` / `P_plane` / `uv_strip` / `uv_runs` | any wall (cylindrical or planar mapping P(u, v, w)) from z_lo up to a constant or curved top, with arched openings [(uc, w, z_sill, z_spring)] cut right through as column strips (no booleans, no coplanar faces); optional glass slab per opening. ep02: tympana, facades, connector arches |
| `profile_prism(part, poly[(o, z)], origin, out_dir, width, col, top_col)` / `profile_faces` / `poly_prism(mb, plan_poly, z0, z1, edge_cols, top_col)` | buttress / fin / sloped wall from a side profile (up-facing faces get `top_col`, e.g. lead on setbacks); vertical prism over any (concave) plan polygon with a colour per edge (ep02 end blocks round the exedrae) |
| `battered_prism(part, poly[(o, z)], origin, out_dir, w_bot, w_top, col, top_col, side_col, top_k)` | battered (sloping) buttress / fin: side profile like `profile_prism`, width tapering w_bot -> w_top with height so the side faces lean in too; faces with up-normal > top_k get top_col (ep02: N/S great buttresses, west-corner buttresses, exonarthex fins) |
| `coffers(part, center, r, rows, cols, el0, el1, depth, rib, recess, back)` | stepped recessed coffers on the inside of a sphere |
| `arches(part, center, r_wall, z_spring, az_list, span, band, protrude, col)` | relieving-arch strips on a curved wall |
| `stairs(part, x0,x1, y_front, z0, n, tread, rise, col)` | steps, one piece each |
| `door(part, x, y, z, w, h, leaf, frame, facing)` | frame + two panelled leaves |
| `floor_disc(part, center, radius, thick, base, tile, tile_cols, circle_col)` | round floor with a tile pattern |
| `uv_sphere_globe(part, center, r, line_hex, fill_hex)` | outlined translucent sphere for diagrams (not clipped) |
| `text_piece(part, text, pos, size, col, facing='-y', depth, font)` | raised lettering (inscriptions) as a paper piece |
| low level: `MB()` builder (`face`, `prism`, `box`, `cylinder`, `revolve`, `island`) + `finish(mb, name, part, pivot, bevel)` | any custom piece |

**Look rules.** These are the reason episodes stay consistent, so keep them:
- There is **one** shader, `PK_paper`. It reads colour from the face attribute `paper_col` and darker edge lines from `paper_edge`, which comes from bevel chamfers at creases or card rims. Each piece gets a ±7 % tint from Object-Info Random, plus fibre mottling and a fine bump.
- Back faces render as a flat poché colour (`paperkit.POCHE`). As a result, a section through any closed piece reads as a solid cut.
- The section cut is a shader clip against the empty `PK_SectionPlane`. It has no booleans, so it costs nothing per piece. The plane stops 8 cm past the centre so that piece end-caps never show as cut faces.
- Lighting is a soft sun (angle 9°) as key, a large area softbox as fill, and a sky world. AgX Medium High Contrast.
- Keep piece seams off the section plane. For a centred X cut, avoid segment boundaries at az 90/270 or rely on the 8 cm offset.

## Render budget (M2, measured)
- 1080×1920, 12 samples, `shadow_res` 0.4–0.5 (the 24-sample setting has not been re-timed at this shadow_res), consecutive frames, machine otherwise idle: exterior frames **1.27–1.4 s per frame**, interior dome frames **1.26 s per frame** (with `shadow_res 0.35`). The first frame of a run adds about 1–2 s for shader compile.
- Shadows are the dominant cost. Sample count barely matters (8, 12 and 24 samples all took the same time). If a shot goes over budget, lower `shadow_res` first.
- When other heavy processes are running, the same frames take about 6 s. Check `sysctl vm.loadavg` before timing anything.
- Scene size for ep01: 627 pieces, 102k tris, build time under 2 s.

## Making a new episode (target 45–90 min)
1. **Script and labels first**: a list of (t, label, part). That list becomes `schedule` and `anchors`.
2. Copy `episodes/ep01_pantheon/episode.json`, then replace `palette` (colours by material) and `title`, and set the
   lighting preset that suits the building: replace ep01's `real_look` (its golden-hour values and `sun_keys`) with
   `{"preset": "<name>"}`, and drop ep01's `grade` (an episode `grade` replaces the preset's) and the ground colours
   in `real_palette` (the preset brings them). See "Lighting presets".
3. Geometry. For a simple building, write a `parts` list in the JSON (columns, `gable`, `box_piece`, `cylinder_wall`, `dome_shell` …). For a complex one, copy `build_pantheon.py` as `build_X.py`: about 150 lines of component calls, with proportions as named constants from one module.
4. Run `--draft --stills` with 4–6 named stills, read them, and fix colours, camera and timing. Each cycle takes about 30 s.
5. Run `python3 kit/produce.py EPISODE.json draft` (anchors + frames + overlay + music), or by hand `--anchors` and
   `--anim` (one Blender run can do both), then `python3 kit/overlay.py EPISODE.json FRAMES/ ANCHORS.json OUT.mp4 --contact SHEET.jpg`
   and `python3 kit/finish.py EPISODE.json OUT.mp4 FINAL.mp4 --share SHARE.mp4`.
   Layout test without encoding: `--only-check --check DIR --check-t 6.5 11.5 ...` on an existing frame sequence.

## Known limits / next steps
- `overlay.py` uses Noto Sans SC (OFL) from `ARCH_KIT_FONTS` (default ~/Library/Fonts) and writes a silent track;
  `finish.py` mixes the music from the episode's `music` block.
- `gable()` always faces −Y. Rotate the finished pieces for other orientations.
- The piazza board is currently close in colour to the backdrop. If a visible "model base" is wanted, give it a stronger colour or a smaller size.

## Detailed meshes as the exterior skin (kit/import_mesh.py)

A closed, untextured mesh (STL; ep02: the user's 3D-print model of Hagia Sophia, licence unknown, so nothing derived
from it is ever committed) becomes the episode's exterior while the builder keeps the structural core.

```bash
python3 kit/import_mesh.py prepare episodes/ep02_hagia_sophia/mesh_prep.json                       # ~15 s, numpy/scipy
kit/blender_locked.sh -b --factory-startup -P kit/import_mesh.py -- segment episodes/ep02_hagia_sophia/mesh_prep.json   # ~45 s
```
`prepare` welds the STL, aligns it (pivot = dome axis, rotate so east = +Y / south = +X, `scale_xy` / `scale_z`,
plaza level -> z 0), measures heights, gives every face a palette name (region + normal: lead on domes, roof_lead
on flat tops, the region's wall colour, window panels -> window_grille, radial window recesses -> window_glass) and
writes an OBJ. `segment` intersects it with one cutter per region (box / cylinder / plan polygon; each cutter minus
the earlier ones, so the parts partition the mesh; Manifold solver, about 1.5 s per region on 1.4 M tris; cut faces
take material slot 0 = the cut colour, e.g. brick_byz), applies per-region post transforms (minaret vertical
rescale) and saves `models/.../print_prepped.blend` + `.json` (object -> part, pivot, meta). Regions carry the part
names and meta the episode's selectors use, so explode / visibility / ghost / anchors resolve unchanged.
Window detection: per wall direction, the d-facing faces are projected to (u, z); a window panel framed by a
bevelled reveal is its own island of d-facing cells (mask eroded by one cell to close the dotted outline);
window-sized islands become windows. It finds only part of the windows on ep02's print mesh (76 panels); `episodes/ep02_hagia_sophia/mesh_windows.py` adds the rest (recesses in high-passed facade depth maps -> 66 grille panels 4 cm proud of the recess back, `models/hagia_sophia/print_windows.json`, merged into their pieces by the builder).
Region `post` transforms: `scale_z` (+ `about_z`) = linear vertical rescale; `z_map` [[z_in, z_out], ...] = piecewise-linear vertical remap (ep02: the dome lead compressed about the window-ring top, eased so the springing keeps its height). `post` is read from the prepare output, so re-run `prepare` after editing it.
The builder side (ep02 `build_hagia_sophia.py`, `SKIN = "mesh" | "procedural"`, episode key `skin`): procedural
skin pieces are taken out of `pk.PARTS` (selectors, anchors and the lights' building box only see the mesh) and
rendered only where the camera is inside the solid mesh (the interior reveal); the mesh pieces are hidden there. `MESH_PROC_PARTS` keeps chosen parts procedural in mesh mode (ep02: half domes, exedrae, apse, minarets, plus our lead dome) and skips the print's pieces of those parts; `_remap_z` applies a piecewise vertical map to one print piece (ep02 narthex, `MESH_NARTHEX_Z`). Checking a mesh skin against measured drawings: cut it with `bmesh.ops.bisect_plane` (section x = const, plan z = const) and draw the segments over the scaled drawing (ep02: `out/ep02_hagia_sophia_real/`).

## Real scans (kit/import_scan.py)

Photogrammetry GLB -> real-scale, aligned .blend the kit can append. Never let Blender load 8K textures.

```bash
python3 kit/import_scan.py downscale models/pantheon/the_pantheon_interior.glb models/pantheon/the_pantheon_interior_4k.glb --size 4096
kit/blender_locked.sh -b --factory-startup -P kit/import_scan.py -- prep episodes/ep01_pantheon/scan_prep.json   # add key=value overrides, e.g. "render.res=[270,480]"
```
`prep` imports, bakes to world space, measures (rotunda: drum radius at floor+5 m, dome sphere apex, oculus, entrance = widest empty sector),
scales/centres/rotates (floor z=0, entrance to az 270 = -Y), removes a sky cap over the oculus, joins per material, sets the
emission+principled scan shader, adds the sun + beam volume, renders the check still, saves the .blend (textures packed) and a JSON
(transform, measurements, object names, append hint). Pantheon: `models/pantheon/interior_prepped.{blend,json}`, collection
`pantheon_interior_scan`. Scan textures carry baked light: render them with view transform Standard.

## Style "real" (realkit.py): real building instead of paper

`--style real` (or `"style": "real"` in the episode JSON; default is `paper`, which is unchanged). Builders do not change:
faces still name palette colours. In real style the **palette name picks a recipe** and the colour tints it
(`realkit.RECIPE`, unknown names match by prefix, else `stucco`). Realistic colours come from `realkit.REAL_COLOURS`,
then the episode's `real_palette`. One material per recipe, so grey and pink granite share one shader.

| recipe | palette names (ep01) | what it draws |
|---|---|---|
| `granite` | granite_grey, granite_pink | speckled (dark grains + light flecks), per-column tint, polished (rough 0.26) weathering to matte |
| `marble` | marble_white, tympanum, attic, niche | faint veins, AO crevice dirt, rain streaks, dust on ledges |
| `travertine` | travertine(_dark) | horizontal banding, elongated pores (bump) |
| `brick` | brick | Roman coursing + mortar (bump) mapped round the drum (seam at +Y), bipedales bonding course every 1.19 m, soot + lime-render weathering bands |
| `brick_arch` | brick_dark | relieving arches: radial voussoirs around the arch centre (uses the piece's `az`) |
| `lead_dome` | lead | 128 sheets with standing seams + overlapping laps on the dome sphere (`real_look.dome_center`), white oxidation, dark run-off. A piece marked with `realkit.dome_props(ob, center, radius, sheets)` (object props `pk_dome_on/center/r/sheets`) radiates its seams from its own centre: half domes, exedrae, minaret cones (ep02) |
| `lead_roof` | roof_lead | same sheeting, seams across Y (pitched roofs, flat tops) |
| `stucco` | lead_light, step_ring, coffer_*, ceiling, mortar (any unknown name) | lime render |
| `render` | render_ochre, render_red (ep02) | exterior lime render on big walls: broad blotchy discolouration, light rain streaks (the `stucco` streaks read as wood planks on large flat walls) |
| `plaster` | render_inner (ep02) | interior plaster: soft mottling + crevice AO, no rain streaks or ledge dust |
| `bronze` | bronze(_dark), bronze_gold | metallic, verdigris in crevices |
| `paving` / `ground` | paving(_light) / piazza | slabs; `ground` fades into the haze colour between `ground_fade` radii (95-420 m) |
| `polished` | giallo, porphyry | polished floor marble |
| `brick_byz` | brick_byz | Byzantine brickwork: thin bricks in mortar beds almost as thick (pinkish lime mortar), no Roman bonding courses; cut faces and brick shells (ep02 dome) |
| `gold_mosaic` | gold_mosaic | gold glass tesserae (irregular ~11 cm cells, per-tile tilt / roughness, dark grout), metallic 0.22 and low specular: with screen-space effects off, specular light is not occluded indoors, so a metallic interior would mirror the outdoor sky |
| `window_glow` | window_glass | window pane seen from outside: dark glass reflecting the sky, + warm emission when the look has a lit `interior` (`window_glow` strength, default 4; `window_glow_hex`, default the interior colour) |
| `window_sky` | window_sky | window pane seen from inside: flat emission in the camera sky's colours (`window_sky` strength, `window_sky_hex`) |
| `window_grille` | window_grille (ep02) | `window_glow` pane behind a dark iron diamond lattice (~0.34 m mesh, drawn in the pane's plane from its normal), so lit windows read as grilles, not flat glowing slabs |
| `window_ring` | window_glow_dim (ep02) | the `window_glow` pane at `window_glow_dim` x the strength (LOOK key, default 0.35; ep02 0.025): panes the camera flies right up to, so the arch and the reflecting glass read instead of a white blob |
| `render_byz` | render_salmon, render_rose (ep02) | weathered salmon lime render over brick: blotchy discolouration, faint coursing, worn horizontal bands every ~2.6 m and patches where the thin Byzantine bricks show (brick_byz pattern), light rain streaks |
| `travertine` (also) | ashlar_grey, ashlar_light (ep02) | grey ashlar of the Ottoman setting (türbe, şadırvan, garden wall) and the stone minarets |

Shared by every recipe: textures live in REST world space (`object coords + ob["pk_rest"]`, set by `finish`), so they
stay continuous across segments and stick to a piece while it moves (explode views); weathering = AO node (EEVEE) +
streak noise + up-facing dust; back faces = poche and the `PK_SectionPlane` clip still work. No image textures.

Geometry changes in real style (paperkit): revolve segments meet flush (`REAL_GAP` 4 mm, end caps never bevelled),
bevels x`REAL_BEVEL` 0.6, islands turned inside out by `recalc_face_normals` are flipped back (signed volume).

**Look** (`real_look` in the JSON overrides `realkit.LOOK`; episodes set a lighting preset, see "Lighting presets",
and the defaults below apply only without one): sun `sun_az -65, sun_el 21, sun_angle 1.6, sun_strength 6.5,
sun_hex #FFC994`; physical sky (`SINGLE_SCATTERING` = Nishita, no sun disc) lights the scene at `sky_strength 0.14`; the
camera sees `haze_hex` at the horizon blending to the sky (`sky_cam_strength`, `haze_band`), matching the far piazza, so
labels sit on a calm background. AgX Medium High Contrast, exposure -0.2, compositor Glare/Bloom (`bloom 0.1`,
threshold 1.2). `real_render` in the JSON overrides `render` in real style (ep01: 16 samples, shadow_res 0.45).

**Components** (style-agnostic, pieces animate like any other):

| function | builds |
|---|---|
| `column_real(part, x,y,z, h, d, shaft, base, capital)` / `columns_real(part, pts, h, d, ...)` | 3 pieces per column (`sub` = base / shaft / capital, pivots at their own bottoms): Attic base (plinth, torus, scotia, torus), entasis shaft, Corinthian capital (astragal, bell, 2x8 lobed acanthus leaves with curling tips, 4 corner volutes on stalks, concave abacus + fleurons). ~6.3k faces per capital |
| `entablature_real(part, path, z, col, depth, ceiling, inscription, font, text_col, text_size)` | architrave (3 fascias), frieze, cornice with dentils, swept round a plan polyline with mitred corners; optional ceiling slab; raised inscription centred on the longest segment. Profiles: `ARCHITRAVE`, `FRIEZE_H`, `CORNICE` |
| `pediment_real(part, x0,x1, y_face, y_back, z, rise, ...)` | tympanum, mitred raking cornices with dentils, two roof slabs |
| `cornice_ring(part, r_face, z0, h, proj, col, ...)` | moulded drum cornice (revolve pieces) |
| `step_rings(part, z0, n, step_h, r0, step_in, sph_r, col)` | dome step rings with nosing |
| `minaret_real(part, x, y, z, h, d, balconies, col, top_col, cap_col, alem_col, base_w, base_h, n_shaft, cap_h, alem_az, base_style, flare, base_col, balcony_col, drum_col)` | Ottoman minaret: square pedestal + polygonal transition, polygonal tapering shaft, one serefe per `balconies` entry (corbelled rings, floor, parapet), upper drum, lead cone (own seam centre) and gilded alem (rod, 2 bulbs, crescent facing `alem_az`). Pieces `sub` base / shaft / balcony / top / cap / alem, each pivoting at its own foot. Styles: `base_style="pyramid"` + `flare` (low plinth + tall tapering flare, Sinan's thick minarets), `base_col` / `balcony_col` / `drum_col` (ep02 SE: stone pedestal, brick shaft, white balcony + drum); defaults = the plain minaret |
| `turret_real(part, x, y, z, h, r, col, dome_col, slits, slit_col)` | small round stair turret: drum + cornice, arched window slits facing out, hemispherical lead dome (own seam centre) + finial; one piece (ep02 E/W end blocks) |
| `turbe(part, x, y, z, w, h, dome_d, drum_h, col, trim_col, roof_col, dome_col, win_col, eave, rows)` | Ottoman octagonal domed mausoleum: ashlar body `w` across the flats with rows of framed grilled windows, cornice, optional lean-to lead portico `eave`, octagonal drum, lead dome + finial; pieces body / dome (ep02 setting) |
| `sadirvan(part, x, y, z, w, h, col, roof_col, dome_col, grille_col)` | Ottoman octagonal ablution fountain: basin + grilled screen, 8 columns, wide octagonal lead eave roof, small cupola; one piece (ep02 setting) |
| `dome_props(ob, center, radius, sheets)` | mark a `lead_dome` piece with its own dome centre (see the recipe table) |
| `sweep`, `dentils`, `tube`, `mitre_frames` | low level: profile along a mitred polyline, dentil rows, round tubes |

ep02 (Hagia Sophia) builder: `episodes/ep02_hagia_sophia/build_hagia_sophia.py` (next to its JSON; parts and teardown
meta in its docstring). 541 pieces, 240k tris, build 1.2-2.3 s.

ep01 real parts: same part names and roles; the pediment part also carries `role` entablature / inscription / gable
(`sub` architrave, frieze, cornice, ceiling, inscription, tympanum, raking_cornice, roof). 666 pieces, 382k tris, build 2.3 s.
Inscription font: Times New Roman (macOS system font).

**Budget (M2, 1080x1920, measured 2026-09-29 with other apps loading the machine, load avg 3.5-6):** 16 samples +
shadow_res 0.45: hero 3.2-3.6 s, portico close-up 3.2-6.5 s per frame (varies with load); 24 samples + 0.6: 3.8-5.5 s.
First run in a fresh cache adds ~15 s of shader compile. Peak RSS 0.7 GB (`/usr/bin/time -l`: 730-780 MB).
If a sequence runs over 3 s/frame on an idle machine: `--samples 12` first (see "Final render settings": samples are the main lever at 1080; lower shadow_res costs sharpness).
Proof stills: `out/lookdev_real/hero_exterior.png`, `portico_closeup.png` (iterations in `out/lookdev_real/iterations/`).


## Exploded views (paperkit: `explode`, `reassemble`, groups) — the ep01 format since "real"

Everything below is driven from the episode JSON; `apply_episode` runs `groups` -> `schedule` -> `explode` ->
`visibility`. The building starts complete (no `schedule` rise needed) and every move is relative to where a piece
is at that moment, so moves stack in time order. Reassembly returns pieces/groups to their built position.

**Selectors** (used by `explode`, `groups`, `visibility`, `hide`, follow-anchors): `{part | parts:[..], role (str|list),
rings:[..], side: "R"|"L" (meta side, else plan az, else rest x sign), match:{meta: value|[values]}, only:[names],
objects:[names], not:{selector}}`. Builders put the meta on pieces (`layer`, `side`, `front`, `ring`, `az`, `sub` ...).

| JSON | effect |
|---|---|
| `"groups": [{name, pivot:[x,y,z], parent, select | members:[sel,..]}]` | pivot empty; pieces are parented to it at rest (local location == world rest). Rotating it swings them like a door on a hinge. `parent` nests hinges (child angle adds to the parent's). A piece joins the first group that selects it. |
| `{t, dur, select, offset:[x,y,z]}` | translate by offset |
| `... step:[x,y,z], step_by:"ring"|"index"` | + rank x step: vertical spread of rings/bands (exploded stack) |
| `... radial: d, center` | + d metres outward in plan |
| `... order, stagger, ring_step` | timing per piece as in `rise()` (`order:"ring", ring_step` = band after band) |
| `... easing: EASE|LINEAR|BACK|SINE|QUAD|CUBIC|EXPO|IN|OUT, overshoot` | curve; `BACK` = settle with overshoot |
| `{t, dur, group:"name", rotate:{axis:"Z", angle}, offset}` | move a group (angle added to its current angle) |
| `{t, dur, reassemble:true, select | select:null, groups:[..]|"all", group_stagger}` | back to rest (default easing BACK 1.3). No `select` key = every moved piece; `select:null` = groups only |
| `"visibility": [{select, show:[[t0,t1],..]}]` | render only inside the windows (keyed `hide_render`) |
| `"hide": [selector,..]` | never rendered (parts a scan replaces) |
| anchors `{"name", "pos":[rest xyz], "follow": {selector + "az": deg | "near":[xyz]}}` | leader-line anchor that rides on the chosen piece (rest matrix captured at frame 1) |
| camera key `"interp": "HOLD"` | hard cut: holds until the next key (put it one frame before the cut); the approach and the exit are linear |

Python: `pk.explode(objs, t, dur, offset, step, step_by, radial, stagger, order, easing, overshoot)`,
`pk.reassemble(objs, t, dur, stagger, order, overshoot)`, `pk.make_group`, `pk.group_move`, `pk.select`.

**Rules that keep exploded views clean** (ep01 lessons): no section-cut planes (coplanar flicker) — open the building
instead (a half on a hinge = cutaway); parts that separate must not share coplanar faces (offset 3-6 cm in the
builder: ep01 dome ring 0 vs drum ledge, skin lip vs core); move nested shells by the same increment or on the same
hinge (the outer one never crosses the inner one); bring a stack down with the same easing bottom-first so the
order never inverts; BACK overshoot only where a small interpenetration is hidden (reassembly into a wall).

### Making an exploded episode (ep01 is the template: `episodes/ep01_pantheon/episode.json`)
1. Script first: list (t, beat, label, part). Labels in `labels.json` (id, t_in, t_out, text, sub), top captions in
   `captions.json`. The loop episode ends on the first frame: last camera key at `(frames-1)/fps` == first key.
2. Builder: give pieces the meta the explode needs — layers (`layer: skin/core`), halves (`side`, seams on the
   hinge plane, e.g. 32 segments from az 270), bands (`ring`) — and aggregate/cut colours on faces that become
   visible when parts separate (ep01 `AGG`, `cut_cols` of `realkit.step_rings`, per-ring `dome_shell` calls).
3. `groups` for hinged halves/doors, then `explode` moves in time order, `schedule` only for diagram pieces
   (sphere pop/vanish), `visibility` for expensive pieces only needed in a window (scan, sunbeam volume).
4. Anchors with `follow` for labels on moving pieces; `overlay.anchor_for` maps label id -> anchor.
5. Stills first (fast loop, ~3 s each at draft):
   `kit/blender_locked.sh -b --factory-startup -P kit/run_episode.py -- episodes/ep01_pantheon/episode.json --draft --samples 8 --stills out/test --still-t 0 5.5 9 13.2 24 29.5`
6. Draft video: `python3 kit/produce.py episodes/ep01_pantheon/episode.json draft` (quality from `draft_render`:
   6 samples, shadow_res 0.3, no raytracing, which override the render segments). Final: `... final` renders every
   `render_segments` entry in its own Blender process (`--segment NAME --skip-existing`), then overlay + music.

## Setting (per-episode `"setting"`, realkit.build_setting) — so the model never stands in a void
`{"ground": {"variation": 0.12}, "props": [{"type": "bollards", "path": [[x,y],..], "spacing", "h", "d"},
{"type": "fountain_obelisk", "pos": [x,y], "basin_r", "obelisk_h"}, {"type": "fountain", "pos": [x,y], "basin_r"}
(round basin with a two-tier centre bowl, no obelisk; ep02)], "backdrop": {"type": "city_ring", "r0", "r1",
"count", "rows", "h": [min,max], "w": [min,max], "seed", "tower_p", "gaps": [[az0,az1],..], "colors": [palette names]}}`.
Paving variation = large worn/warm patches in the `ground` recipe. City ring = boxes + hipped terracotta roofs
(recipe `facade`: tinted render, window grid, blended into the haze colour by camera distance, `real_look`
`city_near/city_far/city_haze0/city_haze1`, ep01 0.5 -> 0.88), no shadows; ~150 objects, negligible render cost.
Props use recipe `setting` (travertine, lightly hazed). Setting pieces are not parts (never animated, selected or anchored).

## Scan inside a real-style episode (`"scan"`, realkit.load_scan) and colour management
`{"blend", "collection", "tex": 2048, "z_split", "split_x", "floor_z", "floor_r", "shading", "sat", "back_hex", "volumetric"}`
appends the prepped scan, splits it into parts `scan_dome` (above z_split), `scan_wall`, `scan_floor`, each R/L by
x sign, so groups/explode treat it like built parts (ep01: the scan dome IS the coffered inner shell; its outside
renders as plain lime concrete via a back-face shader). The scan sun is light-linked (receiver + blocker = scan).
`kill_inner` deletes our inner skins where the scan's walls sit behind them.

**One view transform for the whole film.** The scan textures are display-referred (they looked right with
Standard); the exterior is tuned for AgX. `load_scan` reads the textures as raw display values (Non-Color) and pushes
them through an inverse-AgX LUT computed from Blender's own OCIO config at load time (view + look + exposure of the
scene; 32-point ColorRamp per channel, + saturation 1.08), so AgX displays the scan as Standard would. Cuts between
the scan interior and the exterior then share one transform, one bloom, one exposure. If the scene's view settings
`real_look` look/exposure change, the LUT follows (it is computed at scan load from `realkit.LOOK`, which is what
`post_render_setup` applies; do not change the view settings by hand afterwards). Checked on ep01 draft2 (t 14.2 vs
`out/lookdev_real/interior_scan.png`): mean RGB 0.399/0.382/0.361 vs 0.407/0.396/0.381, the residual is the LUT's
saturation 1.08.

## Ghosting and the ep01 wall diagram
Every `realkit` material reads the object property `pk_ghost` (0 = opaque, 1 = fully transparent; missing = 0), so any
real piece can be faded by keying `ob["pk_ghost"]` (from the JSON: episode `ghost`, see the spec table). Dithered
ghosts between ~0.5 and 0.97 read as a speckle field at 8-16 samples; for a part that should vanish, fade it to 1 and
hide it with `visibility` while gone. A piece that should stay visible as a translucent "ghost" (ep02: the first dome
of 537) gets `diagram.ghost_mat` (alpha-blended, rim-lit, no shadows, still faded by `pk_ghost`) via `diagram.set_mat`.

**kit/diagram.py** (ep02 onwards; ep01's `build_pantheon._wall_diagram` keeps its own copy): `flow_mat` (emissive line,
visible where the geometry attribute `s` < `pk_len`, pulses with `pk_phase`, fades with `pk_fade`), `glow_mat`
(`pk_glow`, optionally invisible at 0), `pour_mat` (fills a shell from z_top down as `pk_glow` 0 -> 1), `ghost_mat`,
`tube` (rotation-minimising frames, any direction), `ring`, `cone`, `box_shell`, `resample`, and `grow(...)`, which keys
a tube's growth, pulses and fade plus arrow heads that ride the tips and rest at the ends. `grow` gives every line its own
render window (t0 .. fade end): a faded line lying on another one would otherwise hide it (drawn black). Builders call
these from `after_episode(pk, spec)`; ep02's paths are in `episodes/ep02_hagia_sophia/build_hagia_sophia.py`.

ep01 keys `pk_ghost` on the brick skin while `build_pantheon._wall_diagram`
(spec `"wall_diagram"`: show window, ghost / ring / pier-pour keys, per-tier load-line start times and speed) shows the
drum's structure: 8 piers, dark voids, 3 tiers of voussoir arches, gold load lines with arrow heads (parts
`wall_diagram`, `load_flow`; own materials `DG_*` driven by object props `pk_glow`, `pk_len`, `pk_phase`, `pk_fade`).
Overlay: `place` also takes `x`, `y` (card top-left, clamped to the safe width); a label may set `size` (title px) when a
long title would not fit the safe width at 62 px.

## Final render settings (ep01, 1080x1920, chosen 2026-09-29) — the standard for every episode

**Quality bar = ep01 draft 2** (`out/ep01_real_draft2.mp4`: 540x960, 6 samples, shadow_res 0.3, ray tracing off,
upscaled 2x). A final must be at least as sharp and as clean as that. How it is measured (`kit/bench_render.py`,
results in `out/speed_study/`): render 3 representative frames per variant in one Blender process, then compare each
against a 64-sample render with the same settings; noise = high-frequency RMS of the difference (8-bit levels,
difference minus its Gaussian σ2 blur). Draft 2's own noise is measured the same way (540 s6 vs 540 s64, both
upscaled 2x). In-process setting switches are deterministic: the 540 s6 variant rendered after six other variants
matched the real draft 2 frames exactly (RMS 0.00).

Speed study (M2, 1080x1920, warm s/frame, machine load 5-8 so +-0.25 s):

| variant | t 1.0 exterior | t 24 wall diagram | t 13.5 scan interior | noise vs s64: portico / diagram / interior |
|---|---|---|---|---|
| draft 2 (540, s6, sh 0.3, RT off, upscaled) | 0.39 | 0.46 | 0.65 | 2.20 / 3.64 / 0.57 |
| A s16, sh 0.45, RT on (old final) | 1.46 | 1.73 | 2.68 | (RT shifts the look, see below) |
| B s16, RT off | 1.39 | 1.72 | 2.20 | 1.43 / 2.96 / 0.41 |
| **H s12, RT off** | **1.03** | **1.26** | **1.76** | **1.62 / 3.54 / 0.43** |
| C s8, RT off | 1.17 | 1.26 | 1.40 | 2.17 / 4.50 / 0.48 (diagram noisier than draft 2) |
| D s8, sh 0.30 | 0.90 | 1.47 | 1.43 | noisier than C |
| E s6, sh 0.30 (draft 2 settings at 1080) | 0.82 | 1.00 | 1.11 | noisier than D |
| F s8, volumetric tile 16 | 0.91 | 1.17 | 1.63 | changes the sunbeam (RMS 1.6), no gain |
| G s8 + OIDN denoise (compositor) | 1.70 | 1.55 | 2.23 | slower, softens brick/scan texture |
| reference s64, RT off | 3.83 | 4.92 | 6.99 | — |

Findings: (1) ray tracing (screen-space GI/reflections) changes only contact shading on the exterior (RMS 5-8, low
frequency, invisible at viewing size) and nothing in the scan interior (RMS 0.3-1.1, the scan is emission-lit) while
costing ~20 % there, so it is **off everywhere** (= the approved draft 2 look). (2) Samples are the main lever at
1080: 16 -> 12 saves ~25 %, still cleaner than draft 2 everywhere; 8 is noisier than draft 2 in the wall diagram.
(3) Lower shadow_res and bigger volume tiles save little and cost sharpness / change the beam. (4) OIDN is slower
than just rendering more samples. Draft 2 at 540 is 3-4x faster per frame but visibly soft.

**Standard final settings for every episode: 12 samples, 16 in diagram segments (ghosted skin + dark voids are the
noisiest pixels), ray tracing off, shadow_res 0.45** (episode `render_segments`, one segment per camera block; fast GI
on, volumetric tile 8 / 32 samples from the scan block, PNG). ep01:

| segment | t (s) | frames | samples | RT | s/frame, ep01 final (golden_hour, machine loaded by other sessions) |
|---|---|---|---|---|---|
| exterior | 0 – 10.6 | 1–254 | 12 | off | 6.46 |
| interior (scan + sunbeam volume) | 10.6 – 15.0 | 255–360 | 12 | off | 6.06 |
| portico | 15.0 – 20.45 | 361–491 | 12 | off | 5.86 |
| diagram (relieving arches) | 20.45 – 26.95 | 492–647 | 16 | off | 5.95 |
| cutaway + sphere + loop | 26.95 – 40.0 | 648–960 | 12 | off | 3.28 |

The s/frame column was measured with other sessions loading the machine (one Blender at a time through
`blender_locked.sh`, peak ~1.33 GB); on an idle machine the golden_hour hook frame renders in 1.5 s (all presets
1.4–2.9 s, see "Lighting presets"). Re-running after an interruption keeps finished frames (`--skip-existing`). Grade + labels + music +
share copy + contact sheet: 11.6 min under the same load. Outputs: film 42.4 MB, share copy 26.1 MB (< 30 MB),
no-music version 41.4 MB (the overlay's `silent.mp4`, silent AAC track, for Douyin in-app music); all 1080x1920,
24 fps, 960 frames, 40.000 s, AAC 48 kHz stereo, BT.709; music -13.2 LUFS, peak -1.3 dBFS.
At these settings the ep01 final is sharper than draft 2 everywhere and cleaner in the wall diagram (pier pour, voids).

**Workflow for every episode (final):**
```bash
# from the repo root
# 0. draft first (540x960, fast): as in "Making an exploded episode", user approves the draft
python3 kit/produce.py episodes/ep01_pantheon/episode.json draft
# 1. frames: one Blender per render segment, resumable (re-run = only missing frames), anchors from the first process
# 2. labels (overlay.py --preset slow) + music + share copy + contact sheet -> out/ep01_final.mp4, out/ep01_final_share.mp4
python3 kit/produce.py episodes/ep01_pantheon/episode.json final
#    the same steps by hand:
#    kit/render_final.sh EP.json out/ep01_final/frames out/ep01_final/anchors.json
#    python3 kit/overlay.py EP.json out/ep01_final/frames out/ep01_final/anchors.json out/ep01_final/silent.mp4 \
#        --contact out/ep01_final/contact.jpg --preset slow
#    python3 kit/finish.py EP.json out/ep01_final/silent.mp4 out/ep01_final.mp4 --share out/ep01_final_share.mp4
# 3. self-check: ffprobe (1080x1920, 24 fps, duration, audio), contact sheet, 6 consecutive frames at every cut /
#    diagram / loop point (ffmpeg select), crops vs the approved draft
```
New episode: copy `render_segments` (one segment per camera block; 12 samples, 16 in diagram segments, RT off,
shadow_res 0.45), then check with `kit/bench_render.py` (~3 min) if the building is very different or the preset adds
lights (`blue_hour` / `night_flood`: ~20 spot lights, +0.5–1.4 s per frame). Mux settings (finish.py, from the episode `music` block): music from `start`, fade in 0.3 s,
fade out over the last 2.7 s, two-pass loudnorm I=-14 / TP=-1.5 / LRA=11, AAC 192k 48 kHz; video x264 crf 18 preset slow, yuv420p, BT.709
matrix + tags; share copy 1080x1920 two-pass 5 Mb/s (< 30 MB for 40 s).

## Lighting presets (`kit/light_presets.py`): one per episode, chosen for the building

**Rule: one preset per episode, the same from the first frame to the last.** No preset switches and no time-of-day
changes inside an episode; the lighting varies across the series, episode by episode. Choose the preset that suits
the building (material, setting, character, the story of the episode), set `"real_look": {"preset": "<name>"}` in
the episode JSON, and override single keys only when the building needs it. `golden_hour` is not a default: it is
ep01's choice. Within the one preset, `sun_keys` can dim the key sun under a diagram segment so the diagram colours
read (ep01: 10 % for the relieving-arch diagram, back to 100 % on the hard cut out of it); sky, sun direction and
colour, and grade stay the same.

A preset carries its `look` (realkit LOOK keys), a `palette` (warm-stone ground, under the episode's `real_palette`)
and a `grade` (overlay.py, used only when the episode has no `grade`). Episodes without `preset` use the
`realkit.LOOK` defaults and none of the preset keys (checked pixel-identical at t 0 and 5.5).

| preset | 中文 | light | what it adds (keys) | s/frame |
|---|---|---|---|---|
| `golden_hour` | 黄昏 | low warm sun from the side (az 70, el 12, #FFB462), cool blue sky fill (#8DB0D4), warm rim, slate haze, clouds | = the ep01 final look: `cine_sky`, `rim_*`, warm-stone ground, `hue_fix` + `shadow_cool` grade | 1.5 |
| `blue_hour` | 蓝调时刻 | sun just set, deep blue flat sky light, afterglow on the horizon | `sky_flat`, warm grazing `floods` round the footprint + 3 distant floods, `interior` glow, lit `city_windows` | 2.9 |
| `overcast_drama` | 阴天压顶 | heavy low clouds to the horizon, dark desaturated world; one soft `shaft` from a cloud break lights the building and a pool round it | `sky_flat`, `shaft`, `cloud_low`, desaturated grade (0.82) | 1.4 |
| `night_flood` | 夜景泛光 | near-black navy sky, faint `stars`, faint moon; warm floods from the base (strong falloff) + distant / low front floods for the upper parts and the portico | `floods`, `interior`, `city_windows`, `setting_haze` 0.05 | 2.2 |
| `morning_mist` | 晨雾 | low soft sun from the side/back (az 122, el 7), warm glow in the sky, ground `mist` by distance and height, pastel | `mist*`, `ground_fade` 70-300 m, strong city haze | 1.4 |
| `noon_hard` | 正午硬光 | high sun (el 58), tiny sun angle = crisp shadows, saturated blue sky with small clouds, AgX High Contrast | shadows fall blue, graphic light/shadow sides | 1.7 |

s/frame: ep01 hook camera, t 0, 1080x1920, 12 samples, idle machine; ~6 s per Blender process incl. the build.

**Choosing (the building decides):**
- `golden_hour` - warm stone, brick, travertine; a classical or historic landmark in a city square.
  Pantheon (Rome), Colosseum, Florence Duomo.
- `blue_hour` - buildings with windows or a lit interior, glass, waterfronts, civic buildings; calm, elegant.
  Sydney Opera House, Hagia Sophia, Notre-Dame de Paris.
- `overcast_drama` - massive, heavy, fortified or tragic subjects; dark stone; a story about weight, war or
  survival. Mont-Saint-Michel, a Gothic cathedral like Cologne, Edinburgh Castle.
- `night_flood` - monuments that are famous floodlit at night, towers, arches; spectacle and scale.
  Arc de Triomphe, Eiffel Tower, Tower Bridge.
- `morning_mist` - gardens, temples, pagodas, buildings in landscape or on water; quiet, spiritual, timber.
  Kinkaku-ji, the Temple of Heaven, Angkor Wat.
- `noon_hard` - modern and modernist architecture: white concrete, clean planes, strong geometry, deserts.
  Villa Savoye, Salk Institute, Great Mosque of Djenné.

Write the choice and the reason in the episode's SCRIPT.md (section "模型与材质").

**Guard-rails (check the hook still before an episode renders):**
1. The building separates from the background: brighter or darker than what is behind it (value), and warm against
   cool (warm stone/floods vs blue sky/shadow). If the building sinks into the sky or the ground, fix the light
   (exposure, flood/shaft `e`, mist amount), not the grade.
2. Explained structures stay readable: whatever a label points at must be lit (night: add a low front flood group
   for porticoes/columns; overcast: aim the `shaft` at the facade the camera sees; mist: `mist_top` keeps the top clear).
3. No dirty or muddy colours: no pink-purple ground (red-orange sun + violet fill = magenta on grey stone; keep the
   sun yellow-orange and the fill blue, not violet, and keep the preset `palette` ground fix and `hue_fix`), no
   grey-brown haze over warm stone, night props must not glow (`setting_haze` low). Measure a ground patch: hue
   20-40 deg (warm) or 200-230 deg (blue), never 290-350.
4. Labels stay legible over the sky: captions/cards sit in the top sky band; keep that band calm (no bright sun
   glow or busy clouds behind the text), and check dark skies (night) and pale skies (mist) with the real caption.

**Look keys** (all off unless a preset/episode sets them; documented at the top of `light_presets.py`):
`cine_sky` (camera sky = haze -> `sky_mid_hex` -> `sky_zenith_hex` gradient + sun glow `sun_glow*` + planar clouds
`clouds`, `cloud_hex`/`cloud_lit_hex`), `sky_light_hex` (tints the sky that LIGHTS the scene: cool fill = blue
shadows), `sky_flat` (flat lighting sky), `rim_az/rim_el/rim_strength/rim_hex/rim_angle` (second sun = warm
rim/kicker), `floods` (ring groups: lamps found by ray casts round the footprint at 15 % height, placed on the
podium/steps under them, aimed up their bit of wall; distant groups: `az`/`dist`/`h`), `shaft` (soft spot from the
sun direction, `cover` x footprint radius), `interior` (point light inside; a list of them = several lamps on the axis, ep02: window ring + a low one), `mist*` (distance + height fog on every
realkit surface), `stars`, `cloud_low`, `setting_haze`, `city_windows`/`window_hex`/`windows_lit`, `sun_keys`,
`dof_fstop`/`dof_keys` (depth of field focused on the camera target; no effect on 170-190 m wide shots, for close
shots). Flood/shaft/interior strength `e` is irradiance at the aim point in sun-strength units
(power = e x 4 pi d^2). The building box ignores pieces lower than 2 m (ground boards, steps) and piece scale.

**Commands:**
```bash
# one hero still per preset + labelled sheet (default all six, t = 0 = hook camera; --draft for 540x960 look tests)
python3 kit/preset_stills.py episodes/ep01_pantheon/episode.json out/light_presets [--presets blue_hour night_flood] [--draft]
#   -> out/light_presets/<preset>.png (grade + captions at t), raw/<preset>.png, presets_sheet.jpg, render_times.json
# any run_episode command can try a preset without editing the JSON (replaces real_look, drops the episode grade)
kit/blender_locked.sh -b --factory-startup -P kit/run_episode.py -- episodes/ep01_pantheon/episode.json --look night_flood --draft --stills out/test --still-t 0
```
For a real episode put the preset into the JSON (so overlay.py picks up the preset grade), check the hook still
against the guard-rails, then render as usual.

## Grade (overlay.py: the episode `grade`, else the preset's)

Applied to every rendered frame before labels and captions: `vignette`, `bottom` [y0_frac, k] darkening, `contrast`
(S-curve), `saturation`, split tone `shadow_hex`/`shadow_k` and `high_hex`/`high_k`. `hue_fix` (one band or a list)
pulls a hue band on low/mid-saturation, not-dark pixels toward a target hue (`from` [lo, hi] deg, `to`, `k`, `soft`,
`sat`, `sat_min`, `v`; `desat` or `"to": null` desaturates the band instead); strongly saturated paint (diagram
arches) is left alone. `shadow_cool` adds a little blue to near-neutral shadows. Both take `off` time spans (ep01:
off in the scan interior 12.375-15.0 s, hard cuts at both ends, so the photo scan keeps its colours).
Keep hue_fix bands monotonic: wide `soft` edges (30-40 deg) and never a lilac->blue band butting against a
pink->orange band, or smooth sky/roof gradients fold into a magenta/green seam; check the into-sun shots (sun glow
in view) whenever the grade changes. Cost ~+0.1 s per frame in overlay.py.

## Optional: blueprint / x-ray graphics layer (off by default, not part of the standard)

Rendered only when the episode JSON has a `graphics` block; ep01 has none and standard episodes use the default
label cards.
**3D** (`kit/blueprint.py`, called by run_episode after apply_episode): `cut` (x-ray cutaway: the camera-side half of
a part dissolves into glowing ghost edges, the far half shows its section profile as a cyan outline + navy hatched
poche), `sphere_grid` (glowing cell grid drawn on cell by cell, e.g. coffers 5 x 28), `xray` (piece turns navy with
a cyan rim, keyed `pk_xray`; LOOK `xray_base_hex/xray_rim_hex/xray_emit/xray_keep`), `grid` (faint ground grid).
All emission, blended, no shadows, rendered only inside their windows. Keys documented at the top of blueprint.py.
**2D** (`overlay.py`): `graphics.dims` = dimension lines between two anchors (use `follow` anchors on pieces that stay
visible), drawn on from the middle with ticks + arrowheads, number pill in DIN (`ARCH_KIT_DIN`; the approx sign falls
back to Noto); `graphics.card_style {label id: "blueprint"}` = navy glass card, cyan hairline + corner ticks, glowing
leader; `grade.windows` [{t, fade, desat, cool, dark}] cools/desaturates the frame while the layer is on. Numbers
in dims must come from the verified labels / fact table.
Cost (1080x1920, 12 samples, machine load 13-22): 3.0-4.7 s/frame with the layer on ep01 0-12 s; the layer itself
adds little (~5.4k tube segments, 24 caps, 140 grid cells).
