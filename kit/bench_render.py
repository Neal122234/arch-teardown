"""bench_render.py - time render-setting variants on a few frames, in ONE Blender process.

Runs after run_episode.py in the same process (run_episode builds the scene and applies the render setup):
  kit/blender_locked.sh -b --factory-startup -P kit/run_episode.py -P kit/bench_render.py -- \
      episodes/ep01_pantheon/episode.json   (no --draft: 1080x1920)
Environment:
  BENCH_OUT       output dir (PNG per variant/frame + bench.json)
  BENCH_FRAMES    "25,577,325"   frames to time (frame f-1 is rendered first, untimed, as warm-up)
  BENCH_VARIANTS  JSON list [{"name": "rt_on", "samples": 16, "shadow_res": 0.45, "raytracing": 1,
                  "fast_gi": 1, "vol_tile": 8, "vol_samples": 32, "denoise": 0, "pct": 100}, ...]
Keys missing from a variant keep the value of the previous variant (so order them from the baseline).
"""
import os, sys, json, time
import bpy

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
import paperkit as pk

out = os.path.abspath(os.environ["BENCH_OUT"])
os.makedirs(out, exist_ok=True)
frames = [int(x) for x in os.environ.get("BENCH_FRAMES", "25,577,325").split(",")]
variants = json.loads(os.environ["BENCH_VARIANTS"])
sc = bpy.context.scene
res = []
for v in variants:
    pk.apply_render_overrides(v)
    if "pct" in v:                       # resolution percentage (50 = draft 540x960)
        sc.render.resolution_percentage = int(v["pct"])
    row = {"variant": v["name"], "settings": pk.render_state(), "frames": {}}
    for f in frames:
        sc.frame_set(f - 1)
        sc.render.filepath = os.path.join(out, "_warm.png")
        bpy.ops.render.render(write_still=True)
        sc.frame_set(f)
        sc.render.filepath = os.path.join(out, "%s_f%05d.png" % (v["name"], f))
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        dt = time.time() - t0
        row["frames"][f] = round(dt, 2)
        print("[bench] %-14s frame %4d  %.2fs" % (v["name"], f, dt), flush=True)
    res.append(row)
    json.dump(res, open(os.path.join(out, "bench.json"), "w"), indent=1)
try:
    os.remove(os.path.join(out, "_warm.png"))
except OSError:
    pass
print("[bench] done -> %s" % out)
