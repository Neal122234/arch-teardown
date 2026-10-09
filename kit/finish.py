"""finish.py - mix the music under the silent overlay video, loudness-normalised, plus a small share copy.

python3 kit/finish.py EPISODE.json SILENT.mp4 OUT.mp4 [--share OUT_share.mp4] [--music FILE] [--start S] [--lufs -14]
(--share: 1080x1920 two-pass x264 5 Mb/s, BT.709, < 30 MB for 40 s - same as the ep01 final share copy)

Music settings come from the episode JSON "music" block (command-line flags override):
  {"file": "music/bach_air_usaf.mp3", "start": 4.2, "fade_in": 0.3, "fade_out": 2.7, "lufs": -14, "tp": -1.5, "lra": 11}
"file" is resolved like every kit path (music/... -> ARCH_KIT_MUSIC). The video stream is copied, not re-encoded.
The fade-out ends on the last frame so the loop point is quiet; loudness is measured afterwards and printed.
"""
import os, sys, json, re, argparse, subprocess

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
import config  # noqa: E402


def measure_lufs(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a", "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(m[-1]) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode"); ap.add_argument("silent"); ap.add_argument("out")
    ap.add_argument("--share"); ap.add_argument("--music"); ap.add_argument("--start", type=float)
    ap.add_argument("--lufs", type=float)
    a = ap.parse_args()

    ep = config.find_config(a.episode)
    spec = json.load(open(ep))
    m = dict(spec.get("music", {}))
    if a.music:
        m["file"] = a.music
    if a.start is not None:
        m["start"] = a.start
    if a.lufs is not None:
        m["lufs"] = a.lufs
    if not m.get("file"):
        sys.exit("no music: add a \"music\" block to the episode JSON or pass --music")
    music = config.resolve(m["file"], os.path.dirname(ep))
    if not os.path.exists(music):
        sys.exit("music file not found: %s (see the episode's assets.md for the download link)" % music)
    dur = float(spec.get("duration", 40))
    fi, fo = m.get("fade_in", 0.3), m.get("fade_out", 2.7)
    fades = "afade=t=in:st=0:d={fi},afade=t=out:st={st}:d={fo}".format(fi=fi, st=dur - fo, fo=fo)
    ln = "loudnorm=I={i}:TP={tp}:LRA={lra}".format(i=m.get("lufs", -14), tp=m.get("tp", -1.5), lra=m.get("lra", 11))
    # two-pass loudnorm: measure the faded excerpt, then normalise linearly (one pass lands ~1 LU off on 40 s)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(m.get("start", 0)), "-t", str(dur), "-i", music,
                        "-af", fades + "," + ln + ":print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    js = r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1]
    try:
        mm = json.loads(js)
        ln += (":measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:measured_thresh={input_thresh}"
               ":offset={target_offset}:linear=true").format(**mm)
    except (ValueError, KeyError):
        print("[finish] loudness measurement failed, falling back to one-pass loudnorm")
    af = "[1:a]" + fades + "," + ln + "[a]"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", a.silent, "-ss", str(m.get("start", 0)),
           "-t", str(dur), "-i", music, "-filter_complex", af, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", a.out]
    print("$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    print("[finish] %s  integrated loudness %s LUFS (target %s)" % (a.out, measure_lufs(a.out), m.get("lufs", -14)))
    if a.share:
        # share copy < 30 MB: full 1080x1920, two-pass x264 at 5 Mb/s (40 s -> ~26 MB), BT.709 tags, audio copied
        v = ["-c:v", "libx264", "-preset", "slow", "-b:v", "5000k", "-maxrate", "7500k", "-bufsize", "10000k",
             "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
             "-color_range", "tv"]
        plog = os.path.join(os.path.dirname(os.path.abspath(a.share)), ".x264pass_%d" % os.getpid())
        base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", a.out] + v + ["-passlogfile", plog]
        try:
            subprocess.run(base + ["-pass", "1", "-an", "-f", "mp4", os.devnull], check=True)
            subprocess.run(base + ["-pass", "2", "-c:a", "copy", "-movflags", "+faststart", a.share], check=True)
        finally:
            for f in os.listdir(os.path.dirname(plog)):
                if f.startswith(os.path.basename(plog)):
                    os.remove(os.path.join(os.path.dirname(plog), f))
        print("[finish] share copy %s (%.1f MB)" % (a.share, os.path.getsize(a.share) / 1e6))


if __name__ == "__main__":
    main()
