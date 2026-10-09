"""preset_stills.py - one hero still per lighting preset + a labelled contact sheet (plain python3).

python3 kit/preset_stills.py EPISODE.json OUT_DIR [--presets golden_hour blue_hour ...] [--t 0] [--draft]
                             [--no-render] [--no-caption]
For each preset: Blender (kit/blender_locked.sh, one at a time) renders the episode at time t with
run_episode.py --look PRESET (no scan), then the preset grade + the captions visible at t are applied as overlay.py
does -> OUT_DIR/<preset>.png (raw render in OUT_DIR/raw/<preset>.png), and OUT_DIR/presets_sheet.jpg (Chinese names).
"""
import os, sys, re, json, time, argparse, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
import light_presets as lp
import overlay as ov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode"); ap.add_argument("out")
    ap.add_argument("--presets", nargs="*", default=list(lp.PRESETS))
    ap.add_argument("--t", type=float, default=0.0)
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--no-caption", action="store_true")
    ap.add_argument("--sheet-only", action="store_true")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    raw = os.path.join(out, "raw")
    os.makedirs(raw, exist_ok=True)
    ep_path = os.path.abspath(a.episode)
    ep = json.load(open(ep_path))
    times = {}
    for p in a.presets:
        if a.no_render or a.sheet_only:
            break
        d = os.path.join(raw, "_" + p)
        cmd = [os.path.join(KIT, "blender_locked.sh"), "-b", "--factory-startup", "-P", os.path.join(KIT, "run_episode.py"),
               "--", ep_path, "--look", p, "--no-scan", "--stills", d, "--still-t", "%g" % a.t] + (["--draft"] if a.draft else [])
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        log = r.stdout + r.stderr
        open(os.path.join(raw, p + ".log"), "w").write(log)
        m = re.search(r"\[run\] still t=\s*[\d.]+s\s+render ([\d.]+)s", log)
        src = os.path.join(d, "t%05.2f.png" % a.t)
        if r.returncode or not os.path.exists(src):
            print("[presets] %s FAILED (see %s)" % (p, os.path.join(raw, p + ".log")))
            print("\n".join(log.splitlines()[-25:]))
            continue
        os.replace(src, os.path.join(raw, p + ".png")); os.rmdir(d)
        times[p] = (float(m.group(1)) if m else -1, time.time() - t0)
        lights = re.search(r"\[realkit\] preset lights: (\d+)", log)
        print("[presets] %-15s render %.1fs, process %.1fs%s" % (p, times[p][0], times[p][1],
              ", %s preset lights" % lights.group(1) if lights else ""), flush=True)
    edir = os.path.dirname(ep_path)
    caps = []
    cp = os.path.join(edir, ep.get("overlay", {}).get("captions", "captions.json"))
    if os.path.exists(cp) and not a.no_caption:
        caps = [c for c in json.load(open(cp)) if c["t_in"] <= a.t <= c["t_out"]]
    for p in a.presets:
        if a.sheet_only:
            break
        rp = os.path.join(raw, p + ".png")
        if not os.path.exists(rp):
            continue
        im = np.array(Image.open(rp).convert("RGB"))
        if im.shape[1] != ov.W:
            im = np.array(Image.fromarray(im).resize((ov.W, ov.H), Image.BICUBIC))
        spec = dict(ep, real_look={"preset": p}); spec.pop("grade", None)
        g = lp.grade_for(spec)
        if g:
            im = ov.apply_grade(im, ov.grade_setup(g), a.t)
        o = np.ascontiguousarray(im)
        for c in caps:
            ov.blend_rgba(o, ov.make_caption(c["text"], c.get("sub", "")), 0, 190, 1.0)
        Image.fromarray(o).save(os.path.join(out, p + ".png"))
    # contact sheet: 3 x 2, Chinese names
    cells = [(p, os.path.join(out, p + ".png")) for p in a.presets if os.path.exists(os.path.join(out, p + ".png"))]
    if cells:
        cw, ch, lab, gap = 480, 853, 64, 12
        cols = 3; rows = (len(cells) + cols - 1) // cols
        sh = Image.new("RGB", (cols * cw + (cols + 1) * gap, rows * (ch + lab) + (rows + 1) * gap), (24, 24, 26))
        d = ImageDraw.Draw(sh)
        f1 = ImageFont.truetype(ov.F_BOLD, 38); f2 = ImageFont.truetype(ov.F_MED, 22)
        for i, (p, fp) in enumerate(cells):
            x = gap + (i % cols) * (cw + gap); y = gap + (i // cols) * (ch + lab + gap)
            sh.paste(Image.open(fp).convert("RGB").resize((cw, ch), Image.LANCZOS), (x, y + lab))
            d.text((x + 4, y + 6), lp.ZH[p], font=f1, fill=(245, 240, 232))
            d.text((x + 8 + ov.text_w(f1, lp.ZH[p]) + 10, y + 22), p, font=f2, fill=(150, 146, 140))
        sh.save(os.path.join(out, "presets_sheet.jpg"), quality=92)
        print("[presets] sheet ->", os.path.join(out, "presets_sheet.jpg"))
    if times:
        tp = os.path.join(out, "render_times.json")
        allt = json.load(open(tp)) if os.path.exists(tp) else {}
        allt.update(times)
        json.dump(allt, open(tp, "w"), indent=1)


if __name__ == "__main__":
    main()
