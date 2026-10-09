"""overlay.py - 2D label layer + encode for a paper-architecture episode (plain python3, no Blender).

python3 overlay.py EPISODE.json FRAMES_DIR ANCHORS.json OUT.mp4 [--contact OUT.jpg] [--frames N] [--check DIR] [--workers 2]

Reads the episode's "overlay" block:
  "overlay": {
    "labels": "labels.json", "captions": "captions.json",     (paths relative to the episode JSON)
    "anchor_for": {"L1_arches": "arches", ...},                (label id -> anchor name in ANCHORS.json)
    "place": {"L1_arches": {"zone": "top"|"bottom", "side": "left"|"right", "x": px, "y": px}, ...}   (optional, else auto;
             x/y = card top-left in the 1080x1920 frame, clamped to the safe width)
  }
Frames from Blender (draft 540x960 or full 1080x1920) are scaled to 1080x1920, labels are drawn at full
resolution (crisp text), and the result is piped to ffmpeg (H.264 crf 18, BT.709 matrix + tags, + silent AAC track;
--preset slow for finals).
Speed: label state (visibility fade, last anchor) is precomputed from the anchors in one cheap pass, so frames are
composited independently by --workers processes (default 2; 8 GB machine) and piped in order to one ffmpeg.
Leader lines / dots are rasterised in small bbox-local masks, frames are read + upscaled with OpenCV.
Safe area for Douyin UI: nothing in the bottom 20 % (y > 1536) or the right 12 % (x > 950).
Graphics layer (episode "graphics", 2D half; blueprint.py does the 3D half):
  "dims": [{"id", "a": anchor, "b": anchor, "text": "43.3 m", "t": [t_in, t_out], "style": "inside"|"outside",
            "text_side": -1|1, "text_off": px, "text_dx"/"text_dy": px, "size": px}]   drawn on from the middle, ticks +
            arrowheads (outside = small dimension, arrows pointing in), number in DIN on a navy pill, cyan glow
  "card_style": {label id: "blueprint"}   navy glass card, cyan hairline + corner ticks, glowing cyan leader + ring
Grade (episode "grade", applied to the rendered frame before any label): {"vignette", "bottom": [y0_frac, k],
  "contrast", "saturation", "shadow_hex"/"shadow_k", "high_hex"/"high_k" (split tone),
  "windows": [{"t": [a, b], "fade", "desat", "cool", "dark"}] (blueprint mode shifts),
  "hue_fix": {...} or [{...}, ...]  {"from": [lo, hi] deg, "to": deg, "k", "soft", "sat": [full_below, none_above], "sat_min", "v": [v0, v1],
              "desat": 0..1, "off": [[t0, t1], ...]}   pull a hue band toward a target on low/mid-saturation pixels (pink
              paving -> stone); "desat" also desaturates the band, "to": null = desaturate only (put a desat band where
              two rotations meet, e.g. 335 deg between lilac->blue and pink->stone, or sky gradients show a magenta seam),
  "shadow_cool": {"rgb": [dr, dg, db], "k", "l": [full_below, none_above], "sat_max", "l_min", "off": [[t0, t1]]}
              additive cool shift on near-neutral shadows}
"""
import os, sys, json, math, argparse, subprocess
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1920
SAFE_L, SAFE_R, SAFE_T, SAFE_B = 64, 950, 250, 1536
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
FONT_DIR = config.FONT_DIR          # ARCH_KIT_FONTS overrides (~/Library/Fonts by default)
F_BOLD = os.path.join(FONT_DIR, "NotoSansSC-Bold.ttf")        # OFL
F_MED = os.path.join(FONT_DIR, "NotoSansSC-Medium.ttf")       # OFL
F_BLACK = os.path.join(FONT_DIR, "NotoSansSC-Black.ttf")      # OFL
INK, INK2 = (43, 38, 34), (96, 86, 76)
RED = (176, 58, 46)
PAPER = (248, 244, 236)
T_SIZE, S_SIZE = 62, 44            # label title / second line (px at 1080 wide)
F_DIN = config.DIN_FONT             # dimension numbers (ARCH_KIT_DIN; macOS DIN Alternate Bold by default)
NO_DIN = "\u2248"                                                      # drawn with Noto instead (DIN has no glyph)
BP_NAVY, BP_CYAN, BP_LINE, BP_TEXT, BP_SUB = (9, 26, 42), (92, 205, 255), (150, 232, 255), (246, 251, 255), (160, 222, 250)
C_SIZE, CS_SIZE = 76, 48           # top caption title / second line


def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def ease_back(x, s=1.7):
    x = min(max(x, 0.0), 1.0) - 1
    return x * x * ((s + 1) * x + s) + 1


def text_w(font, s):
    return font.getlength(s)


def make_card(title, sub, t_size=T_SIZE):
    """Paper card: accent bar + title + sub line, soft shadow. Returns RGBA numpy (premultiplied later).
    t_size: title px (labels.json "size", for a long title that must fit the safe width)."""
    ft, fs = ImageFont.truetype(F_BOLD, t_size), ImageFont.truetype(F_MED, S_SIZE)
    pad_x, pad_y, bar, gap = 30, 20, 8, 10
    tw = max(text_w(ft, title), text_w(fs, sub) if sub else 0)
    cw = int(tw + 2 * pad_x + bar + 6)
    th = t_size + 14 + ((S_SIZE + gap) if sub else 0)
    ch = int(th + 2 * pad_y)
    m = 24                                  # shadow margin
    im = Image.new("RGBA", (cw + 2 * m, ch + 2 * m), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((m, m + 6, m + cw, m + ch + 6), 18, fill=(60, 40, 20, 60))
    sh = sh.filter(ImageFilter.GaussianBlur(10))
    im.alpha_composite(sh)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((m, m, m + cw, m + ch), 18, fill=PAPER + (238,))
    d.rounded_rectangle((m, m, m + bar + 10, m + ch), 18, fill=RED + (255,))
    d.rectangle((m + bar, m, m + bar + 12, m + ch), fill=PAPER + (238,))
    x = m + bar + pad_x - 4
    d.text((x, m + pad_y - 6), title, font=ft, fill=INK + (255,))
    if sub:
        d.text((x, m + pad_y + t_size + 10), sub, font=fs, fill=INK2 + (255,))
    return np.array(im), m, cw, ch


def make_card_bp(title, sub, t_size=T_SIZE):
    """Blueprint card (graphics.card_style): dark navy glass, cyan hairline frame with corner ticks, white title."""
    ft, fs = ImageFont.truetype(F_BOLD, t_size), ImageFont.truetype(F_MED, S_SIZE - 2)
    pad_x, pad_y, gap = 30, 20, 10
    tw = max(text_w(ft, title), text_w(fs, sub) if sub else 0)
    cw = int(tw + 2 * pad_x)
    ch = int(t_size + 14 + ((S_SIZE + gap) if sub else 0) + 2 * pad_y)
    m = 24
    im = Image.new("RGBA", (cw + 2 * m, ch + 2 * m), (0, 0, 0, 0))
    gl = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(gl).rectangle((m, m, m + cw, m + ch), outline=BP_CYAN + (150,), width=4)
    im.alpha_composite(gl.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(im)
    d.rectangle((m, m, m + cw, m + ch), fill=BP_NAVY + (212,))
    d.rectangle((m, m, m + cw, m + ch), outline=BP_CYAN + (170,), width=2)
    k = 18
    for (x, y, sx, sy) in ((m, m, 1, 1), (m + cw, m, -1, 1), (m, m + ch, 1, -1), (m + cw, m + ch, -1, -1)):
        d.line((x, y, x + sx * k, y), fill=BP_LINE + (255,), width=4)
        d.line((x, y, x, y + sy * k), fill=BP_LINE + (255,), width=4)
    x = m + pad_x
    d.text((x, m + pad_y - 6), title, font=ft, fill=BP_TEXT + (255,))
    if sub:
        d.line((x, m + pad_y + t_size + 4, x + 46, m + pad_y + t_size + 4), fill=BP_CYAN + (230,), width=2)
        d.text((x, m + pad_y + t_size + 10), sub, font=fs, fill=BP_SUB + (255,))
    return np.array(im), m, cw, ch


def make_dim_text(text, size=44):
    """dimension number: DIN on a small navy pill with a cyan hairline. RGBA numpy, centre-anchored by caller."""
    f = ImageFont.truetype(F_DIN if os.path.exists(F_DIN) else F_BOLD, size)
    fb = ImageFont.truetype(F_BOLD, int(size * 0.92))              # glyphs DIN lacks (e.g. the approx sign)
    runs = [(ch, fb if ch in NO_DIN else f) for ch in text]
    tw = int(sum(text_w(ff, ch) for ch, ff in runs)); px, py = 16, 8
    w_, h_ = tw + 2 * px, size + 2 * py
    m = 14
    im = Image.new("RGBA", (w_ + 2 * m, h_ + 2 * m), (0, 0, 0, 0))
    gl = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(gl).rectangle((m, m, m + w_, m + h_), fill=BP_CYAN + (90,))
    im.alpha_composite(gl.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(im)
    d.rectangle((m, m, m + w_, m + h_), fill=BP_NAVY + (225,), outline=BP_CYAN + (200,), width=2)
    x = m + px
    for ch, ff in runs:
        d.text((x, m + py - 2 - (int(size * 0.10) if ff is fb else 0)), ch, font=ff, fill=BP_TEXT + (255,))
        x += text_w(ff, ch)
    return np.array(im)


def blend_add_glow(out, segs, tris, alpha, pad=16):
    """cyan glow (blurred) + crisp light line for line segments [(x0,y0,x1,y1,width)] and filled triangles."""
    if alpha <= 0.003 or (not segs and not tris):
        return
    xs = [v for sg in segs for v in (sg[0], sg[2])] + [p[0] for t in tris for p in t]
    ys = [v for sg in segs for v in (sg[1], sg[3])] + [p[1] for t in tris for p in t]
    box = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)

    def draw(mk, ox, oy):
        for x0, y0, x1, y1, w in segs:
            cv2.line(mk, (int((x0 - ox) * 4), int((y0 - oy) * 4)), (int((x1 - ox) * 4), int((y1 - oy) * 4)), 255, w,
                     cv2.LINE_AA, shift=2)
        for t in tris:
            cv2.fillPoly(mk, [np.array([[int((x - ox) * 4), int((y - oy) * 4)] for x, y in t], np.int32)], 255,
                         cv2.LINE_AA, shift=2)

    def glow(mk, ox, oy):
        draw(mk, ox, oy)
        mk[:] = np.minimum(cv2.GaussianBlur(mk, (0, 0), 5) * 2.2, 255).astype(np.uint8)
    blend_mask_local(out, glow, BP_CYAN, alpha * 0.55, box)
    blend_mask_local(out, draw, BP_LINE, alpha, box)


def draw_dim(out, d, pa, pb, t):
    """engineering dimension from pa to pb (px): draws on from the middle, ticks + arrowheads, number pill."""
    ti, to = d["t"]
    pr = ease_out((t - ti) / 0.6)
    al = min(ease_out((t - ti) / 0.25), ease_out((to - t) / 0.35))
    if al <= 0.003:
        return
    ax, ay = pa; bx, by = pb
    vx, vy = bx - ax, by - ay
    L = math.hypot(vx, vy)
    if L < 2:
        return
    ux, uy = vx / L, vy / L
    nx, ny = -uy, ux                                   # perpendicular (screen)
    if nx < -1e-6 or (abs(nx) < 1e-6 and ny > 0):      # normal points right (or up when vertical)
        nx, ny = -nx, -ny
    mx, my = (ax + bx) / 2, (ay + by) / 2
    segs, tris = [], []
    ah, aw = 18, 7                                     # arrowhead length / half width
    tick = 20 * min(1.0, pr * 1.6)
    for (px_, py_) in (pa, pb):                        # extension ticks
        segs.append((px_ - nx * tick, py_ - ny * tick, px_ + nx * tick, py_ + ny * tick, 3))
    def arrow(tx, ty, dx, dy):                         # tip at (tx,ty) pointing along (dx,dy)
        return [(tx, ty), (tx - dx * ah + dy * aw, ty - dy * ah - dx * aw), (tx - dx * ah - dy * aw, ty - dy * ah + dx * aw)]
    if d.get("style", "inside") == "outside":          # small dimension: arrows outside pointing in
        ext = 46 * pr
        segs.append((ax - ux * ext, ay - uy * ext, ax, ay, 3))
        segs.append((bx + ux * ext, by + uy * ext, bx, by, 3))
        segs.append((ax, ay, bx, by, 2))
        if pr > 0.5:
            tris += [arrow(ax, ay, ux, uy), arrow(bx, by, -ux, -uy)]
    else:
        h = L / 2 * pr
        segs.append((mx - ux * h, my - uy * h, mx + ux * h, my + uy * h, 3))
        if pr > 0.8:
            tris += [arrow(ax, ay, -ux, -uy), arrow(bx, by, ux, uy)]
    blend_add_glow(out, segs, tris, al)
    img = d["img"]
    h_, w_ = img.shape[:2]
    side = d.get("text_side", -1)
    off = d.get("text_off", 34)
    if d.get("style") == "outside":
        cx_, cy_ = mx + nx * side * (off + w_ / 2 - 10), my + ny * side * (off + h_ / 2 - 10)
    else:
        cx_, cy_ = mx + nx * side * (off + h_ / 2 - 12), my + ny * side * (off + h_ / 2 - 12)
    cx_ += d.get("text_dx", 0); cy_ += d.get("text_dy", 0)
    blend_rgba(out, img, int(cx_ - w_ / 2), int(cy_ - h_ / 2), al * ease_out((t - ti - 0.3) / 0.35))


def grade_setup(gr):
    """precomputed grade (episode "grade"): vignette + bottom darkening masks, split-tone vectors."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    rx, ry = (xx - W / 2) / (W / 2), (yy - H * 0.46) / (H / 2)
    r = np.sqrt(rx * rx * 0.9 + ry * ry)
    v = 1.0 - gr.get("vignette", 0.0) * np.clip((r - 0.45) / 0.85, 0, 1) ** 1.6
    b0, b1 = gr.get("bottom", [0.72, 0.0])[:2] if isinstance(gr.get("bottom"), list) else (0.72, gr.get("bottom", 0.0))
    v *= 1.0 - b1 * np.clip((yy / H - b0) / (1 - b0), 0, 1) ** 1.3
    hx = lambda h: np.array([int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5)], np.float32)
    return dict(mask=v[..., None].astype(np.float32), sh=hx(gr.get("shadow_hex", "#808080")) - 0.5,
                hi=hx(gr.get("high_hex", "#808080")) - 0.5, k_sh=gr.get("shadow_k", 0.0), k_hi=gr.get("high_k", 0.0),
                contrast=gr.get("contrast", 0.0), sat=gr.get("saturation", 1.0), windows=gr.get("windows", []),
                hue_fix=gr.get("hue_fix"), shadow_cool=gr.get("shadow_cool"))


def _off(t, spans):
    return any(a <= t < b for a, b in (spans or []))


def _hue_fix(x, hf):
    """pull a hue band (e.g. pink/salmon 340..24 deg) toward a target hue (warm stone ~28), only on low/mid
    saturation pixels (sat window) that are not dark: strongly saturated paint (diagram arches) is left alone."""
    hsv = cv2.cvtColor(np.ascontiguousarray(x), cv2.COLOR_RGB2HSV)       # float32: H 0..360, S, V 0..1
    h, s_, v_ = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lo, hi = hf["from"]; tg = hf.get("to"); soft = hf.get("soft", 8.0)
    d_lo = (h - lo) % 360.0; width = (hi - lo) % 360.0                  # position inside the (wrapping) band
    band = np.clip(d_lo / soft, 0, 1) * np.clip((width - d_lo) / soft, 0, 1) * (d_lo <= width)
    s0, s1 = hf.get("sat", [0.35, 0.55])
    sw = np.clip((s1 - s_) / max(1e-3, s1 - s0), 0, 1) * np.clip(s_ / hf.get("sat_min", 0.06), 0, 1)
    vw = np.clip((v_ - hf.get("v", [0.15, 0.3])[0]) / max(1e-3, hf.get("v", [0.15, 0.3])[1] - hf.get("v", [0.15, 0.3])[0]), 0, 1)
    w = band * sw * vw
    if hf.get("desat"):                                                 # desaturate the band (no hue split -> no fringe)
        hsv[..., 1] = s_ * (1.0 - w * hf["desat"])
    if tg is not None:
        dh = ((tg - h + 180.0) % 360.0) - 180.0
        hsv[..., 0] = (h + w * hf.get("k", 1.0) * dh) % 360.0
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)


def _shadow_cool(x, Lm, sc):
    """cool the near-neutral shadows (sky-lit paving, shaded lead/concrete): additive blue, low saturation only."""
    mx, mn = x.max(axis=2, keepdims=True), x.min(axis=2, keepdims=True)
    s_ = (mx - mn) / np.maximum(mx, 1e-4)
    l0, l1 = sc.get("l", [0.3, 0.62])                                  # full below l0 .. none above l1
    w = np.clip((l1 - Lm) / max(1e-3, l1 - l0), 0, 1) * np.clip((sc.get("sat_max", 0.22) - s_) / sc.get("sat_max", 0.22), 0, 1)
    w = w * np.clip(Lm / sc.get("l_min", 0.12), 0, 1)                 # keep the darkest voids neutral-dark
    return x + w * sc.get("k", 1.0) * np.array(sc.get("rgb", [-0.02, 0.0, 0.03]), np.float32)


def apply_grade(im, G, t):
    x = im.astype(np.float32) / 255.0
    Lm = x[..., 0:1] * 0.2126 + x[..., 1:2] * 0.7152 + x[..., 2:3] * 0.0722
    sat, cool, dark = G["sat"], 0.0, 0.0
    for w in G["windows"]:                             # blueprint mode: cooler, less saturated, a bit darker
        a0, a1 = w["t"]; fd = w.get("fade", 0.5)
        k = min(ease_out((t - a0) / fd), ease_out((a1 - t) / fd)) if a0 <= t <= a1 else 0.0
        sat -= k * w.get("desat", 0.0); cool += k * w.get("cool", 0.0); dark += k * w.get("dark", 0.0)
    hfs = G.get("hue_fix") or []
    for hf in ([hfs] if isinstance(hfs, dict) else hfs):          # one band or a list of bands
        if not _off(t, hf.get("off")):
            x = _hue_fix(x, hf)
    if G.get("shadow_cool") and not _off(t, G["shadow_cool"].get("off")):
        x = _shadow_cool(x, Lm, G["shadow_cool"])
    if G["contrast"]:
        x = x + G["contrast"] * (x * x * (3 - 2 * x) - x)
    if G["k_sh"] or G["k_hi"]:
        x = x + (1 - Lm) ** 2 * G["k_sh"] * G["sh"] + Lm ** 2 * G["k_hi"] * G["hi"]
    if sat != 1.0:
        x = Lm + (x - Lm) * sat
    if cool:
        x = x + cool * np.array([-0.05, 0.0, 0.06], np.float32) * (1 - Lm)
    x = x * G["mask"] * (1.0 - dark)
    return np.clip(x * 255.0 + 0.5, 0, 255).astype(np.uint8)


def make_caption(title, sub):
    ft, fs = ImageFont.truetype(F_BLACK, C_SIZE), ImageFont.truetype(F_MED, CS_SIZE)
    im = Image.new("RGBA", (W, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = (SAFE_L + SAFE_R) / 2 + 20          # centred in the safe width
    tw = text_w(ft, title)
    d.text((cx - tw / 2, 30), title, font=ft, fill=INK + (255,), stroke_width=5, stroke_fill=PAPER + (230,))
    if sub:
        sw = text_w(fs, sub)
        d.text((cx - sw / 2, 30 + C_SIZE + 26), sub, font=fs, fill=RED + (255,), stroke_width=4, stroke_fill=PAPER + (230,))
    return np.array(im)


def blend_rgba(out, rgba, x, y, alpha):
    """out uint8 HxWx3; rgba uint8 hxwx4 placed at (x,y), multiplied by alpha."""
    if alpha <= 0.003:
        return
    h, w = rgba.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    src = rgba[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    a = src[..., 3:4] / 255.0 * alpha
    dst = out[y0:y1, x0:x1].astype(np.float32)
    out[y0:y1, x0:x1] = (dst * (1 - a) + src[..., :3] * a).astype(np.uint8)


def blend_mask(out, mask, color, alpha, box):
    x0, y0, x1, y1 = box
    x0, y0, x1, y1 = max(int(x0), 0), max(int(y0), 0), min(int(x1), W), min(int(y1), H)
    if x1 <= x0 or y1 <= y0 or alpha <= 0.003:
        return
    a = mask[y0:y1, x0:x1, None].astype(np.float32) / 255.0 * alpha
    dst = out[y0:y1, x0:x1].astype(np.float32)
    out[y0:y1, x0:x1] = (dst * (1 - a) + np.array(color, np.float32) * a).astype(np.uint8)


def blend_mask_local(out, draw, color, alpha, box):
    """rasterise with draw(mask, ox, oy) into a bbox-sized mask only, then blend."""
    x0, y0, x1, y1 = box
    x0, y0, x1, y1 = max(int(x0), 0), max(int(y0), 0), min(int(math.ceil(x1)), W), min(int(math.ceil(y1)), H)
    if x1 <= x0 or y1 <= y0 or alpha <= 0.003:
        return
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    draw(mask, x0, y0)
    a = mask[..., None].astype(np.float32) / 255.0 * alpha
    dst = out[y0:y1, x0:x1].astype(np.float32)
    out[y0:y1, x0:x1] = (dst * (1 - a) + np.array(color, np.float32) * a).astype(np.uint8)


_G = {}


def _init(g):
    _G.update(g)


def compose(fi):
    """one output frame (RGB uint8 bytes); stateless given the precomputed label states in _G."""
    g = _G
    fps = g["fps"]; t = fi / fps
    im = cv2.imread(os.path.join(g["frames"], g["files"][fi]), cv2.IMREAD_COLOR)
    im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
    if im.shape[1] != W or im.shape[0] != H:
        im = cv2.resize(im, (W, H), interpolation=cv2.INTER_CUBIC)
    if g.get("G"):
        im = apply_grade(im, g["G"], t)
    out = np.ascontiguousarray(im)
    for d in g.get("D", []):
        if d["t"][0] <= t <= d["t"][1]:
            pa, pb = d["pts"].get(fi, (None, None))
            if pa and pb:
                draw_dim(out, d, pa, pb, t)
    for c in g["C"]:
        ti, to = c["t_in"], c["t_out"]
        if ti <= t <= to:
            al = min(ease_out((t - ti) / 0.35), ease_out((to - t) / 0.35))
            blend_rgba(out, c["img"], 0, 190 - int((1 - al) * 12), al)
    lw = 4
    for l in g["L"]:
        ti, to = l["t_in"], l["t_out"]
        if not (ti <= t <= to):
            continue
        st = l["state"].get(fi)
        vis, p = (st if st else (0.0, None))
        al_out = ease_out((to - t) / 0.35)
        al_c = ease_out((t - ti - 0.18) / 0.35) * al_out
        dy = int((1 - ease_out((t - ti - 0.18) / 0.35)) * 16)
        m = l["m"]
        blend_rgba(out, l["card"], l["x"] - m, l["y"] - m + dy, al_c)
        if p and vis > 0.01:
            ax, ay = p
            cx0, cx1 = l["x"] + 40, l["x"] + l["cw"] - 40
            bx = min(max(ax, cx0), cx1)
            by = l["y"] + l["ch"] + dy if l["zone"] == "top" else l["y"] + dy
            pr = ease_out((t - ti) / 0.45)
            ex, ey = ax + (bx - ax) * pr, ay + (by - ay) * pr
            al_l = vis * al_out
            if l.get("style") == "blueprint":
                blend_add_glow(out, [(ax, ay, ex, ey, 3)], [], al_l)
                r = 12 * ease_back((t - ti) / 0.25)
                if r > 0.5:
                    bb = (ax - r - 10, ay - r - 10, ax + r + 10, ay + r + 10)
                    blend_mask_local(out, lambda mk, ox, oy: cv2.circle(mk, (int((ax - ox) * 4), int((ay - oy) * 4)),
                                     int(r * 4), 255, 3, cv2.LINE_AA, shift=2), BP_LINE, al_l, bb)
                    blend_mask_local(out, lambda mk, ox, oy: cv2.circle(mk, (int((ax - ox) * 4), int((ay - oy) * 4)),
                                     int(4.5 * 4), 255, -1, cv2.LINE_AA, shift=2), BP_TEXT, al_l, bb)
                continue
            blend_mask_local(out, lambda mk, ox, oy: cv2.line(mk, (int((ax - ox) * 4), int((ay - oy) * 4)),
                             (int((ex - ox) * 4), int((ey - oy) * 4)), 255, lw, cv2.LINE_AA, shift=2),
                             RED, al_l, (min(ax, ex) - 8, min(ay, ey) - 8, max(ax, ex) + 8, max(ay, ey) + 8))
            r = 11 * ease_back((t - ti) / 0.25)
            if r > 0.5:
                bb = (ax - r - 8, ay - r - 8, ax + r + 8, ay + r + 8)
                blend_mask_local(out, lambda mk, ox, oy: cv2.circle(mk, (int((ax - ox) * 4), int((ay - oy) * 4)),
                                 int((r + 4) * 4), 255, -1, cv2.LINE_AA, shift=2), PAPER, al_l, bb)
                blend_mask_local(out, lambda mk, ox, oy: cv2.circle(mk, (int((ax - ox) * 4), int((ay - oy) * 4)),
                                 int(r * 4), 255, -1, cv2.LINE_AA, shift=2), RED, al_l, bb)
    return fi, out.tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode"); ap.add_argument("frames"); ap.add_argument("anchors"); ap.add_argument("out")
    ap.add_argument("--contact"); ap.add_argument("--frames-n", type=int)
    ap.add_argument("--check", help="dir: also save composited PNGs of these seconds (--check-t)")
    ap.add_argument("--check-t", nargs="*", type=float, default=[])
    ap.add_argument("--only-check", action="store_true", help="layout test: render only the --check-t frames, no video")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--preset", default="fast")
    a = ap.parse_args()

    ep = json.load(open(a.episode)); edir = os.path.dirname(os.path.abspath(a.episode))
    ov = ep.get("overlay", {})
    labels = json.load(open(os.path.join(edir, ov.get("labels", "labels.json"))))
    caps = json.load(open(os.path.join(edir, ov.get("captions", "captions.json")))) if os.path.exists(
        os.path.join(edir, ov.get("captions", "captions.json"))) else []
    anc = json.load(open(a.anchors))
    fps = ep.get("fps", 24)
    files = sorted(f for f in os.listdir(a.frames) if f.endswith(".png"))
    n = a.frames_n or len(files)
    files = files[:n]

    def anchor_at(name, fi):
        arr = anc["anchors"].get(name)
        if not arr:
            return None
        i = (fi + 1 - anc["frame_start"]) // anc.get("step", 1)
        if i < 0 or i >= len(arr) or arr[i] is None:
            return None
        x, y, fl = arr[i]
        return (x, y) if fl & 1 else None

    gfx = ep.get("graphics", {})
    L = []
    for lb in labels:
        an = ov.get("anchor_for", {}).get(lb["id"], lb.get("anchor_part"))
        f0, f1 = int(round(lb["t_in"] * fps)), int(round(lb["t_out"] * fps))
        pts = [anchor_at(an, f) for f in range(f0, min(f1, n))]
        pts = [p for p in pts if p]
        my = np.median([p[1] for p in pts]) if pts else 1000
        mx = np.median([p[0] for p in pts]) if pts else 300
        pl = ov.get("place", {}).get(lb["id"], {})
        zone = pl.get("zone", "top" if my > 820 else "bottom")
        side = pl.get("side", "left" if mx < 560 else "right")
        style = gfx.get("card_style", {}).get(lb["id"], "paper")
        card, m, cw, ch = (make_card_bp if style == "blueprint" else make_card)(lb["text"], lb.get("sub", ""),
                                                                              lb.get("size", T_SIZE))
        cx0 = pl.get("x", SAFE_L if side == "left" else SAFE_R - cw)
        cx0 = min(max(cx0, SAFE_L), SAFE_R - cw)
        if cw > SAFE_R - SAFE_L:
            print("[overlay] WARNING %s card %d px wider than the safe width" % (lb["id"], cw))
        cy0 = pl.get("y", 300 if zone == "top" else 1180)
        # label state per frame (sequential smoothing done once here, so compositing is stateless)
        state, vis, last = {}, 0.0, None
        for f in range(f0, min(f1 + 1, n)):
            p = anchor_at(an, f)
            target = 1.0 if p else 0.0
            vis = target if f == f0 else vis + (target - vis) * 0.35
            if p:
                last = p
            state[f] = (vis, p or last)
        L.append(dict(t_in=lb["t_in"], t_out=lb["t_out"], card=card, m=m, cw=cw, ch=ch, x=cx0, y=cy0, zone=zone,
                      state=state, style=style))
        print("[overlay] %-12s anchor=%-12s zone=%-6s side=%-5s card=%dx%d at (%d,%d) median anchor (%.0f,%.0f) n=%d"
              % (lb["id"], an, zone, side, cw, ch, cx0, cy0, mx, my, len(pts)))
    C = [dict(t_in=c["t_in"], t_out=c["t_out"], img=make_caption(c["text"], c.get("sub", ""))) for c in caps]
    D = []
    for d in gfx.get("dims", []):          # dimension lines: endpoints = 3D anchors projected per frame (occlusion ignored)
        pts = {}
        for f in range(int(round(d["t"][0] * fps)), min(int(round(d["t"][1] * fps)) + 1, n)):
            pa, pb = anchor_at(d["a"], f), anchor_at(d["b"], f)
            if pa and pb:
                pts[f] = (pa, pb)
        D.append(dict(d, pts=pts, img=make_dim_text(d["text"], d.get("size", 44))))
        print("[overlay] dim %-6s %s -> %s  '%s'  frames with both ends: %d" % (d["id"], d["a"], d["b"], d["text"], len(pts)))
    import light_presets                # episode "grade", else the lighting preset's grade (real_look.preset)
    _grade = light_presets.grade_for(ep)
    g = dict(fps=fps, frames=a.frames, files=files, L=L, C=C, D=D,
             G=grade_setup(_grade) if _grade else None)

    ff = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
          "-r", str(fps), "-i", "-", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
          "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "libx264", "-preset", a.preset, "-crf", "18",
          # RGB -> BT.709 limited-range YUV (swscale defaults to the BT.601 matrix) + matching stream tags
          "-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p,"
                 "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", a.out]
    enc = None if a.only_check else subprocess.Popen(ff, stdin=subprocess.PIPE)
    checks = {int(round(t * fps)): t for t in a.check_t}
    ct_times = [i * 2.0 for i in range(20)] + [(n - 1) / fps]
    ct_frames = {int(round(t * fps)): t for t in ct_times}
    todo = sorted(checks) if a.only_check else list(range(n))
    contact = {}
    import time as _time
    t0 = _time.time()
    if a.workers > 1:
        import multiprocessing as mp
        pool = mp.get_context("spawn").Pool(a.workers, initializer=_init, initargs=(g,))
        it = pool.imap(compose, todo, chunksize=4)
    else:
        _init(g); pool = None
        it = (compose(fi) for fi in todo)
    for fi, buf in it:
        if enc:
            enc.stdin.write(buf)
        if fi in checks and a.check or fi in ct_frames:
            img = Image.frombytes("RGB", (W, H), buf)
            if fi in checks and a.check:
                os.makedirs(a.check, exist_ok=True)
                img.save(os.path.join(a.check, "t%05.2f.png" % checks[fi]))
            if fi in ct_frames:
                contact[ct_frames[fi]] = img.resize((216, 384), Image.LANCZOS)
        if fi % 120 == 0:
            print("[overlay] frame %d/%d  %.1fs" % (fi, n, _time.time() - t0), flush=True)
    if pool:
        pool.close(); pool.join()
    if enc:
        enc.stdin.close(); enc.wait()
    print("[overlay] composited %d frames in %.1fs" % (len(todo), _time.time() - t0))
    if a.contact and contact:
        cols, tw_, th_ = 7, 216, 384
        rows = math.ceil(len(contact) / cols)
        sheet = Image.new("RGB", (cols * tw_, rows * (th_ + 30)), (250, 248, 244))
        d = ImageDraw.Draw(sheet)
        fnt = ImageFont.truetype(F_MED, 20)
        for i, (tt, img) in enumerate(sorted(contact.items())):
            x, y = (i % cols) * tw_, (i // cols) * (th_ + 30)
            sheet.paste(img, (x, y + 30)); d.text((x + 6, y + 3), "%.2f s" % tt, font=fnt, fill=INK)
        sheet.save(a.contact, quality=90)
    print("[overlay] done ->", a.out)


if __name__ == "__main__":
    main()
