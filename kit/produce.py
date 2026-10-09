"""produce.py - one command from episode JSON to a finished, music-mixed video (plain python3; drives Blender).

python3 kit/produce.py episodes/ep01_pantheon/episode.json draft     # 540x960 low-quality 3D, full overlay + music
python3 kit/produce.py episodes/ep01_pantheon/episode.json final     # 1080x1920, per-segment render settings
  --from render|overlay|finish    start at this step (earlier outputs must exist)
  --only-render                   stop after frames + anchors
  --frames A:B                    render only this frame range (tests); no overlay/finish unless the range is complete
  --dry-run                       print the commands, run nothing

Outputs (under ARCH_KIT_OUT, default <repo>/out):  <episode>_<stage>/frames/*.png, anchors.json, silent.mp4,
contact.jpg, render.log  and  <episode>_<stage>.mp4 (1080x1920 + music) + <episode>_<stage>_share.mp4
(1080x1920, two-pass 5 Mb/s, < 30 MB for 40 s).

Rendering resumes: run_episode --skip-existing keeps frames already on disk, so an interrupted run can simply be rerun.
Blender always runs through kit/blender_locked.sh (one Blender at a time on the machine).

Render settings come from the episode JSON:
  "render_segments": [{"name", "t": [t0, t1], "samples", "shadow_res", "raytracing", "vol_tile", "denoise", ...}]
                    per-time-range quality on top of "real_render"/"render". final: one Blender process per segment
                    (same as kit/render_final.sh). No segments -> one process for the whole film.
  "draft_render":   {"samples": 6, "set": {"shadow_res": 0.3, "raytracing": 0}}   (default shown; passed as --samples /
                    --set, which win over the segments; draft runs as one process at 540x960)
  "music":          {"file": "music/x.mp3", "start": 4.2, "fade_in": 0.3, "fade_out": 2.7, "lufs": -14}
"""
import os, sys, json, argparse, subprocess, shlex, time

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
import config  # noqa: E402

DRAFT_DEFAULT = {"samples": 6, "set": {"shadow_res": 0.3, "raytracing": 0}}


def run(cmd, dry, log=None):
    print("$ " + " ".join(shlex.quote(str(c)) for c in cmd), flush=True)
    if dry:
        return
    if log:
        with open(log, "a") as fh:
            fh.write("\n$ %s\n" % " ".join(map(str, cmd)))
            fh.flush()
            r = subprocess.run(list(map(str, cmd)), stdout=fh, stderr=subprocess.STDOUT)
    else:
        r = subprocess.run(list(map(str, cmd)))
    if r.returncode:
        sys.exit("command failed (%d)%s" % (r.returncode, " - see " + log if log else ""))


def blender_cmd(episode, extra):
    return [os.path.join(KIT, "blender_locked.sh"), "-b", "--factory-startup", "-P",
            os.path.join(KIT, "run_episode.py"), "--", episode] + extra


def quality_args(q):
    a = []
    if q.get("samples"):
        a += ["--samples", str(q["samples"])]
    if q.get("set"):
        a += ["--set"] + ["%s=%s" % (k, (int(v) if isinstance(v, bool) else v)) for k, v in q["set"].items()]
    return a


def missing_ranges(frames_dir, f0, f1):
    """Contiguous runs of frames in [f0, f1] with no (or an empty) PNG yet."""
    out, start = [], None
    for f in range(f0, f1 + 1):
        p = os.path.join(frames_dir, "%05d.png" % f)
        have = os.path.exists(p) and os.path.getsize(p) > 0
        if not have and start is None:
            start = f
        if have and start is not None:
            out.append((start, f - 1)); start = None
    if start is not None:
        out.append((start, f1))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode")
    ap.add_argument("stage", choices=["draft", "final"])
    ap.add_argument("--from", dest="start", choices=["render", "overlay", "finish"], default="render")
    ap.add_argument("--only-render", action="store_true")
    ap.add_argument("--frames")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    ep = config.find_config(a.episode)
    spec = json.load(open(ep))
    fps, dur = spec.get("fps", 24), spec.get("duration", 40)
    n_frames = int(round(dur * fps))
    name = "%s_%s" % (spec.get("episode", os.path.basename(os.path.dirname(ep))), a.stage)
    od = os.path.join(config.OUT_DIR, name)
    frames, anchors = os.path.join(od, "frames"), os.path.join(od, "anchors.json")
    silent, log = os.path.join(od, "silent.mp4"), os.path.join(od, "render.log")
    final_mp4 = os.path.join(config.OUT_DIR, name + ".mp4")
    share_mp4 = os.path.join(config.OUT_DIR, name + "_share.mp4")
    os.makedirs(frames, exist_ok=True)
    t0 = time.time()

    if a.start == "render":
        g0, g1 = map(int, (a.frames or "1:%d" % n_frames).split(":"))
        sec2f = lambda t: int(round(t * fps)) + 1              # same as paperkit.sec2f
        if a.stage == "draft":
            q = dict(DRAFT_DEFAULT, **spec.get("draft_render", {}))
            runs = [(["--draft"] + quality_args(q), g0, g1)]
        else:                                                  # one Blender per render segment (as render_final.sh)
            runs = [(["--segment", sg["name"]], max(g0, sec2f(sg["t"][0])), min(g1, sec2f(sg["t"][1]) - 1))
                    for sg in spec.get("render_segments", [])] or [([], g0, g1)]
        want_anchors = not os.path.exists(anchors) and not a.frames
        for extra, f0, f1 in runs:
            if f0 > f1 or not missing_ranges(frames, f0, f1):
                continue                                       # nothing left to render in this segment
            anch = ["--anchors", anchors] if want_anchors else []
            want_anchors = False
            print("[produce] %s %s frames %d-%d" % (a.stage, " ".join(extra) or "(whole film)", f0, f1), flush=True)
            run(blender_cmd(ep, extra + ["--anim", frames, "--frames", "%d:%d" % (g0, g1), "--skip-existing"] + anch),
                a.dry_run, log)
        if want_anchors:                                       # frames were already there: anchors only
            run(blender_cmd(ep, (["--draft"] if a.stage == "draft" else []) + ["--anchors", anchors]), a.dry_run, log)
        left = missing_ranges(frames, 1, n_frames)
        if a.only_render or (left and not a.dry_run):
            if left:
                print("[produce] frames still missing: %s - stopping before overlay" % left)
            print("[produce] done in %.0f s" % (time.time() - t0))
            return

    if a.start in ("render", "overlay"):
        run([sys.executable, os.path.join(KIT, "overlay.py"), ep, frames, anchors, silent,
             "--contact", os.path.join(od, "contact.jpg")] + (["--preset", "slow"] if a.stage == "final" else []), a.dry_run)

    run([sys.executable, os.path.join(KIT, "finish.py"), ep, silent, final_mp4, "--share", share_mp4], a.dry_run)
    print("[produce] %s -> %s (%.0f s)" % (a.stage, final_mp4, time.time() - t0))


if __name__ == "__main__":
    main()
