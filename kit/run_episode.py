"""run_episode.py - one command per episode.

blender --background --python kit/run_episode.py -- episodes/ep01_pantheon/episode.json [options]
  (the episode path may be given relative to the cwd, the repo root or kit/; run Blender via kit/blender_locked.sh)
  --draft                 540x960 (else 1080x1920)
  --stills DIR            render the config's "stills" (named, at time t) into DIR
  --only NAME ...         restrict --stills to these names
  --anim DIR              render PNG sequence into DIR (frame range = --frames a:b or whole episode)
  --frames A:B            frame range for --anim (frame 1 == t 0)
  --anchors FILE.json     export per-frame 2D anchor positions for label leader lines
  --save-blend FILE       save the built scene (for manual inspection)
  --samples N             override EEVEE samples
  --style paper|real      look (default: the JSON "style", else paper). real = realkit.py PBR materials + sky
  --shots DIR             render the JSON "shots" (fixed cameras, whole building at rest, no schedule) into DIR
                          shots: [{name, az, el, dist, target, lens}]  (+ --only NAME ...)
  --segment NAME ...      --anim only the frames of these named "render_segments" (one process per segment)
  --skip-existing         --anim: keep frames that already exist (resume an interrupted run)
Per-time-range render settings: episode "render_segments": [{"name", "t": [t0, t1], <override>...}], override keys
as paperkit.apply_render_overrides (samples, shadow_res, raytracing, fast_gi, vol_tile, vol_samples, denoise ...).
They apply to --anim / --stills / --still-t frames (base = "render"/"real_render", then the segment, then --samples /
--set, which always win). vol_tile is given for 1080x1920 and halved in --draft.
"""
import sys, os, json, time, math, argparse, importlib.util
import bpy

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
import paperkit as pk
import config

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("config")
ap.add_argument("--draft", action="store_true")
ap.add_argument("--stills")
ap.add_argument("--only", nargs="*")
ap.add_argument("--anim")
ap.add_argument("--frames")
ap.add_argument("--anchors")
ap.add_argument("--save-blend")
ap.add_argument("--samples", type=int)
ap.add_argument("--style")
ap.add_argument("--shots")
ap.add_argument("--no-scan", action="store_true")
ap.add_argument("--still-t", nargs="*", type=float, default=[], help="extra stills at these seconds (named tXX.XX)")
ap.add_argument("--set", nargs="*", default=[], help="override render quality: key=value (raytracing=0 ...)")
ap.add_argument("--segment", nargs="*")
ap.add_argument("--skip-existing", action="store_true")
ap.add_argument("--look", help="lighting preset test: real_look = {preset: NAME} (+ the episode's dome_center / "
                "ao_distance), episode grade dropped so the preset grade applies (light_presets.py)")
a = ap.parse_args(argv)

cfg_path = config.find_config(a.config)
spec = json.load(open(cfg_path))
cfg_dir = os.path.dirname(cfg_path)
if a.look:
    import light_presets
    if a.look not in light_presets.PRESETS:
        sys.exit("[run] unknown look %s; have %s" % (a.look, list(light_presets.PRESETS)))
    keep = {k: v for k, v in (spec.get("real_look") or {}).items() if k in ("dome_center", "ao_distance")}
    spec["real_look"] = dict(keep, preset=a.look)
    spec.pop("grade", None)
    print("[run] look preset %s (episode real_look / grade replaced)" % a.look)
pk.FPS = spec.get("fps", 24)

t0 = time.time()
pk.STYLE = a.style or spec.get("style", "paper")
pk.new_scene()
if pk.STYLE == "real":
    import realkit
    realkit.set_look(spec.get("real_look", {}))
    import light_presets             # preset palette (ground fix ...) under the episode's real_palette
    pk.set_palette(realkit.real_palette(spec["palette"], light_presets.palette_for(spec)))
else:
    pk.set_palette(spec["palette"])
if spec.get("poche_bands"):
    pk.POCHE_BANDS = spec["poche_bands"]
pk.backdrop(col=spec.get("backdrop", "table"))
mod = None
if spec.get("builder"):
    bp = spec["builder"]
    for d in (cfg_dir, KIT):
        if os.path.exists(os.path.join(d, bp)):
            bp = os.path.join(d, bp); break
    sp = importlib.util.spec_from_file_location("builder", bp)
    mod = importlib.util.module_from_spec(sp); sp.loader.exec_module(mod)
    st = mod.build(pk, spec)
else:
    st = pk.build_parts(spec["parts"])
if spec.get("extra_parts"):          # parts added on top of a builder (inscriptions, props...)
    st = pk.build_parts(spec["extra_parts"])
if pk.STYLE == "real" and spec.get("setting"):      # calm surroundings: paving variation, props, city backdrop
    realkit.build_setting(spec["setting"])
if pk.STYLE == "real" and spec.get("scan") and not a.no_scan:   # photogrammetry interior as animatable parts
    t2 = time.time()
    realkit.load_scan(spec["scan"])
    print("[run] scan %.1fs" % (time.time() - t2))
for kl in spec.get("kill_inner", []):   # our inner skins where the scan's walls sit behind them
    rmax, zmax = kl.get("r_max", 1e9), kl.get("z_max", 1e9)
    n = realkit.kill_inner_faces(pk.select(kl["select"]), lambda c, nrm: math.hypot(c.x, c.y) < rmax and c.z < zmax and
                                 (nrm.x * c.x + nrm.y * c.y) / max(math.hypot(c.x, c.y), 1e-6) < -0.5)
    print("[run] kill_inner %s: %d faces" % (kl["select"], n))
if spec.get("hide"):
    print("[run] hidden pieces:", pk.hide_parts(spec["hide"]))
if a.shots:                          # stills of the finished building: no schedule, no section, no camera path
    spec = dict(spec, schedule=[], section=[], camera=[], explode=[], visibility=[], groups=[])
pk.apply_episode(spec)
if not a.shots:                      # after the lights (placed from the footprint): ghost keys + diagram pieces
    import diagram
    diagram.FPS = pk.FPS
    if spec.get("ghost"):
        print("[run] ghost keys on %s pieces" % diagram.apply_ghost(spec["ghost"]))
    if mod is not None and hasattr(mod, "after_episode"):
        t3 = time.time()
        print("[run] builder after_episode: %s (%.1fs)" % (json.dumps(mod.after_episode(pk, spec)), time.time() - t3))
if pk.STYLE == "real":
    realkit.camera_dof()
if spec.get("graphics") and not a.shots:     # blueprint / x-ray layer (3D part; the 2D dimension lines are overlay.py)
    import blueprint
    print("[run] graphics:", json.dumps(blueprint.apply(spec["graphics"])))
q = dict(spec.get("render", {}))
if pk.STYLE == "real":
    q.update(spec.get("real_render", {}))
cli = {}
for kv in a.set:
    k, v = kv.split("=")
    cli[k] = (v not in ("0", "false", "False")) if k in ("raytracing", "fast_gi", "shadows", "denoise") else (float(v) if k == "shadow_res" else (int(v) if v.isdigit() and (k.startswith("shadow_") or k.startswith("vol_")) else v))
q.update(cli)
if a.samples:
    cli["samples"] = a.samples
samples = a.samples or q.pop("samples", None)
pk.render_setup(draft=a.draft, samples=samples, duration=spec.get("duration", 40), quality=q)
print("[run] built in %.1fs  %s" % (time.time() - t0, json.dumps(st)))

# per-time-range render settings ("render_segments"): full setting dict per segment, switched in-process
SEG_KEYS = ("samples", "shadow_res", "raytracing", "fast_gi", "shadow_rays", "shadow_steps", "vol_tile", "vol_samples",
            "denoise")
pk.apply_render_overrides({k: v for k, v in cli.items() if k in ("vol_tile", "vol_samples", "denoise")})
base_q = {k: v for k, v in pk.render_state().items() if k in SEG_KEYS}
segs = []
for sg in spec.get("render_segments", []):
    ov = {k: v for k, v in sg.items() if k in SEG_KEYS}
    if a.draft and "vol_tile" in ov:
        ov["vol_tile"] = max(2, int(ov["vol_tile"]) // 2)
    full = dict(base_q, **ov)
    full.update({k: v for k, v in cli.items() if k in SEG_KEYS})
    segs.append(dict(name=sg["name"], t=sg["t"], q=full, f0=pk.sec2f(sg["t"][0]), f1=pk.sec2f(sg["t"][1]) - 1))
_cur_seg = [None]


def seg_for(f):
    return next((s for s in segs if s["f0"] <= f <= s["f1"]), None)


def use_segment(f):
    s = seg_for(f)
    name = s["name"] if s else None
    if segs and name != _cur_seg[0]:
        pk.apply_render_overrides(s["q"] if s else base_q)
        _cur_seg[0] = name
        print("[run] render segment %s from frame %d: %s" % (name, f, json.dumps(pk.render_state())), flush=True)
    return name


if segs:
    for s in segs:
        print("[run] segment %-10s frames %4d-%4d  %s" % (s["name"], s["f0"], s["f1"], json.dumps(s["q"])))

if a.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save_blend))

if a.anchors:
    t1 = time.time()
    pk.export_anchors(spec.get("anchors", []), a.anchors, step=spec.get("anchor_step", 1))
    print("[run] anchors -> %s (%.1fs)" % (a.anchors, time.time() - t1))

times = []
if a.stills and not a.still_t:
    os.makedirs(a.stills, exist_ok=True)
    for s in spec.get("stills", []):
        if a.only and s["name"] not in a.only:
            continue
        use_segment(pk.sec2f(s["t"]))
        dt = pk.render_still(s["t"], os.path.join(os.path.abspath(a.stills), s["name"] + ".png"))
        times.append(dt)
        print("[run] still %-28s t=%5.2fs  render %.2fs" % (s["name"], s["t"], dt))

if a.still_t:
    d_ = os.path.abspath(a.stills or ".")
    os.makedirs(d_, exist_ok=True)
    for tt in a.still_t:
        use_segment(pk.sec2f(tt))
        dt = pk.render_still(tt, os.path.join(d_, "t%05.2f.png" % tt))
        times.append(dt)
        print("[run] still t=%5.2fs  render %.2fs" % (tt, dt))

if a.shots:
    os.makedirs(a.shots, exist_ok=True)
    piv, cam = bpy.data.objects["PK_CamPivot"], bpy.data.objects["PK_Cam"]
    for s in spec.get("shots", []):
        if a.only and s["name"] not in a.only:
            continue
        for o in (piv, cam, cam.data):
            o.animation_data_clear()
        pk.camera_keys([dict(s, t=0.0)])
        dt = pk.render_still(0.0, os.path.join(os.path.abspath(a.shots), s["name"] + ".png"))
        times.append(dt)
        print("[run] shot %-24s render %.2fs" % (s["name"], dt))

if a.anim:
    os.makedirs(a.anim, exist_ok=True)
    sc = bpy.context.scene
    f0, f1 = (int(x) for x in a.frames.split(":")) if a.frames else (sc.frame_start, sc.frame_end)
    todo = list(range(f0, f1 + 1))
    if a.segment:
        known = [s["name"] for s in segs]
        bad = [n for n in a.segment if n not in known]
        if bad:
            sys.exit("[run] unknown segment(s) %s; episode has %s" % (bad, known))
        todo = [f for f in todo if (seg_for(f) or {}).get("name") in a.segment]
    seg_times = {}
    for f in todo:
        path = os.path.join(os.path.abspath(a.anim), "%05d.png" % f)
        if a.skip_existing and os.path.exists(path) and os.path.getsize(path) > 0:
            continue
        sname = use_segment(f)
        sc.frame_set(f)
        sc.render.filepath = path
        t1 = time.time(); bpy.ops.render.render(write_still=True); times.append(time.time() - t1)
        seg_times.setdefault(sname, []).append(times[-1])
        print("[run] frame %d  %.2fs" % (f, times[-1]), flush=True)
    for n, ts in seg_times.items():
        print("[run] segment %-10s %4d frames  total %6.1fs  avg %.2f s/frame (first %.2f, max %.2f)"
              % (n, len(ts), sum(ts), sum(ts) / len(ts), ts[0], max(ts)))
try:
    import resource
    print("[run] peak RSS %.0f MB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576))
except Exception:
    pass
if times:
    warm = times[1:] if len(times) > 1 else times
    print("[run] render times: first %.2fs (includes shader compile), warm avg %.2fs, max %.2fs"
          % (times[0], sum(warm) / len(warm), max(warm)))
