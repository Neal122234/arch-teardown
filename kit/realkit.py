"""realkit.py - the "real" style for paperkit (Blender 5.2, EEVEE): realistic architecture instead of paper.

Switch: paperkit.STYLE = "real" before building (run_episode.py --style real, or "style": "real" in the
episode JSON). Nothing else in a builder has to change: every face still names a palette colour; in real
style the palette name picks a procedural PBR *recipe* (RECIPE below) and the palette colour (overridden
by REAL_COLOURS / the episode's "real_palette") becomes that recipe's base tint. So grey and pink granite
share one material, and a new building = palette names + geometry, never new shaders.

Also here (style-agnostic geometry, built with paperkit.MB/finish, so they animate like any piece):
  column_real      Attic base + entasis shaft + Corinthian capital (bell, 2 leaf rows, volutes, abacus)
  entablature_real architrave (3 fascias) + frieze (+ inscription) + dentilled cornice, swept round a plan path
  pediment_real    tympanum + dentilled raking cornices (mitred) + roof slabs
  cornice_ring     moulded ring cornice for drums (revolve pieces)
  step_rings       dome step rings with nosing
  sweep / tube     low-level: profile swept along a mitred polyline, round tube along a path

Textures are mapped in REST world space (object coords + the piece's build-time pivot "pk_rest"), so they
are continuous across pieces and stick to a piece while it flies apart in an exploded view.
No image textures, no downloads.
"""
import bpy, math, os
from mathutils import Vector
import paperkit as pk

GROUND_Z = -0.23          # top of the endless piazza (paperkit.backdrop in real style)

# realistic base colours (sRGB) - override the paper palette entries of the same name in real style
REAL_COLOURS = {
    "piazza": "#A8A7A2", "table": "#A8A7A2", "paving": "#B4B0A8", "paving_light": "#CFC8BA",
    "brick": "#907364", "brick_dark": "#8C6E5F",
    "travertine": "#CEC5B2", "travertine_dark": "#C0B59E", "tympanum": "#C9C2B4",
    "marble_white": "#DDD7CB", "granite_grey": "#6F706F", "granite_pink": "#98776D",
    "roof_lead": "#7C8285", "lead": "#8C9194", "lead_light": "#C4C1B8", "step_ring": "#C4C1B8",
    "bronze": "#4A3925", "bronze_dark": "#30271C", "ceiling": "#8F8A80",
}
# palette name -> recipe (unknown names: prefix match, else "stucco")
RECIPE = {
    "piazza": "ground", "table": "ground", "paving": "paving", "paving_light": "paving",
    "brick": "brick", "brick_dark": "brick_arch",
    "travertine": "travertine", "travertine_dark": "travertine",
    "marble_white": "marble", "tympanum": "marble", "attic": "marble", "marble_int": "marble", "niche": "marble",
    "granite_grey": "granite", "granite_pink": "granite",
    "roof_lead": "lead_roof", "lead": "lead_dome", "lead_light": "stucco", "step_ring": "stucco",
    "giallo": "polished", "porphyry": "polished",
    "bronze": "bronze", "bronze_dark": "bronze", "ceiling": "stucco",
    # ep02 (Hagia Sophia)
    "window_glass": "window_glow", "window_ring": "window_glow_dim", "window_sky": "window_sky",
    "gold_mosaic": "gold_mosaic",
    "brick_byz": "brick_byz", "bronze_gold": "bronze", "marble_floor": "marble", "render_inner": "plaster",
    "render_ochre": "render", "render_red": "render",
    # ep02 fidelity pass: salmon render over brick with worn bands, grilled windows, grey ashlar (Ottoman setting)
    "render_salmon": "render_byz", "render_rose": "render_byz", "window_grille": "window_grille",
    "ashlar_grey": "travertine", "ashlar_light": "travertine",
}
_PREFIX = (("brick", "brick"), ("granite", "granite"), ("marble", "marble"), ("travertine", "travertine"),
           ("bronze", "bronze"), ("lead", "lead_dome"), ("roof", "lead_roof"), ("paving", "paving"))

# lighting / look defaults (episode JSON "real_look" overrides any key)
LOOK = dict(sun_az=-65.0, sun_el=21.0, sun_angle=1.6, sun_strength=6.5, sun_hex="#FFC994",
            sky_strength=0.14, sky_cam_strength=0.32, sky_air=1.0, sky_aerosol=1.6, sky_ozone=1.0,
            haze_hex="#DDD8D0", haze_strength=0.9, sky_cam_mix=0.85, haze_band=0.28,
            exposure=-0.2, look="AgX - Medium High Contrast", bloom=0.10, bloom_threshold=1.2, bloom_size=6,
            dome_center=(0.0, 0.0, 21.65), ground_fade=(95.0, 420.0), ao_distance=1.2)

# named looks: episode "real_look": {"preset": "golden_hour", ...overrides}. Keys not in LOOK above:
#   cine_sky          camera sky = graded gradient (haze -> mid -> zenith) + sun glow + a planar cloud layer
#   sky_mid_hex/sky_zenith_hex, sky_mid_z/sky_zenith_z (direction z where each colour is reached)
#   sun_glow_hex, sun_glow (strength), sun_glow_width (1 - cos of the glow radius)
#   clouds (0..1 cover), cloud_scale, cloud_hex (shadow side), cloud_lit_hex (sun side), cloud_cov (threshold)
#   sky_light_hex     tint of the physical sky that LIGHTS the scene (cool -> blue shadows vs warm sun)
#   rim_az/rim_el/rim_strength/rim_hex   second sun (kicker/rim light), shadows on
#   dof_fstop, dof_keys [[t, fstop], ...]  camera depth of field, focused on the camera target (PK_CamPivot)
#   xray_base_hex/xray_rim_hex/xray_emit/xray_keep  look of pieces with object prop pk_xray (blueprint.py)
#   sky_flat, floods, shaft, interior, mist*, stars, city_windows/window_hex/windows_lit: see light_presets.py
import light_presets as _lp                 # the preset library (plain python, shared with overlay.py)
LOOK_PRESETS = _lp.LOOK_PRESETS


def set_look(d):
    """LOOK <- preset (d["preset"]) <- the other keys of d."""
    d = dict(d or {})
    pre = d.pop("preset", None)
    if pre:
        LOOK.update(LOOK_PRESETS[pre])
    LOOK.update(d)
    return LOOK


_MATS = {}


def recipe_for(name):
    if name in RECIPE:
        return RECIPE[name]
    for p, r in _PREFIX:
        if name.startswith(p):
            return r
    return "stucco"


def real_palette(pal, extra=None):
    """Paper palette + REAL_COLOURS + episode 'real_palette' (later wins)."""
    out = dict(pal)
    out.update(REAL_COLOURS)
    out.update(extra or {})
    return out


def assign_materials(me, mi, override=None):
    """Called by paperkit.finish in real style: face palette index -> recipe material slot."""
    slots, idx = [], []
    for i in mi:
        r = override or recipe_for(pk._PAL_NAMES[i])
        if r not in slots:
            slots.append(r)
        idx.append(slots.index(r))
    me.materials.clear()
    for r in slots:
        me.materials.append(material(r))
    me.polygons.foreach_set("material_index", idx)


# ============================================================================= node helper
class NB:
    def __init__(s, nt):
        s.nt = nt; s.N = nt.nodes; s.L = nt.links
        s.N.clear()

    def node(s, t, **kw):
        n = s.N.new(t)
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    def put(s, sock, v):
        if v is None:
            return
        if isinstance(v, bpy.types.NodeSocket):
            s.L.new(v, sock)
        else:
            if isinstance(v, (tuple, list)) and len(v) == 3 and sock.type == 'RGBA':
                v = (*v, 1.0)
            sock.default_value = v

    def math(s, op, a, b=None, c=None, clamp=False):
        n = s.node('ShaderNodeMath', operation=op, use_clamp=clamp)
        s.put(n.inputs[0], a); s.put(n.inputs[1], b); s.put(n.inputs[2], c)
        return n.outputs[0]

    def vmath(s, op, a, b=None, scale=None):
        n = s.node('ShaderNodeVectorMath', operation=op)
        s.put(n.inputs[0], a); s.put(n.inputs[1], b)
        if scale is not None:
            s.put(n.inputs['Scale'], scale)
        return n.outputs['Value'] if op in ('LENGTH', 'DOT_PRODUCT', 'DISTANCE') else n.outputs['Vector']

    def sep(s, v):
        n = s.node('ShaderNodeSeparateXYZ'); s.put(n.inputs[0], v); return n.outputs

    def comb(s, x, y, z=0.0):
        n = s.node('ShaderNodeCombineXYZ')
        s.put(n.inputs[0], x); s.put(n.inputs[1], y); s.put(n.inputs[2], z)
        return n.outputs[0]

    def noise(s, v, scale, detail=2.0, rough=0.5, dist=0.0, col=False):
        n = s.node('ShaderNodeTexNoise')
        s.put(n.inputs['Vector'], v); s.put(n.inputs['Scale'], scale); s.put(n.inputs['Detail'], detail)
        s.put(n.inputs['Roughness'], rough); s.put(n.inputs['Distortion'], dist)
        return n.outputs['Color'] if col else n.outputs['Fac']

    def voronoi(s, v, scale, rnd=1.0):
        n = s.node('ShaderNodeTexVoronoi', feature='F1', distance='EUCLIDEAN')
        s.put(n.inputs['Vector'], v); s.put(n.inputs['Scale'], scale); s.put(n.inputs['Randomness'], rnd)
        return n.outputs['Distance']

    def white(s, v):
        n = s.node('ShaderNodeTexWhiteNoise', noise_dimensions='1D')
        s.put(n.inputs['W'], v)
        return n.outputs['Value']

    def mr(s, v, a, b, c=0.0, d=1.0, smooth=True):
        n = s.node('ShaderNodeMapRange', interpolation_type='SMOOTHSTEP' if smooth else 'LINEAR', clamp=True)
        s.put(n.inputs['Value'], v); s.put(n.inputs['From Min'], a); s.put(n.inputs['From Max'], b)
        s.put(n.inputs['To Min'], c); s.put(n.inputs['To Max'], d)
        return n.outputs['Result']

    def mixc(s, a, b, fac, blend='MIX'):
        n = s.node('ShaderNodeMix', data_type='RGBA', blend_type=blend)
        s.put(pk._sock(n, 'Factor_Float'), fac); s.put(pk._sock(n, 'A_Color'), a); s.put(pk._sock(n, 'B_Color'), b)
        return pk._sock(n, 'Result_Color', out=True)

    def mixf(s, a, b, fac):
        n = s.node('ShaderNodeMix', data_type='FLOAT')
        s.put(pk._sock(n, 'Factor_Float'), fac); s.put(pk._sock(n, 'A_Float'), a); s.put(pk._sock(n, 'B_Float'), b)
        return pk._sock(n, 'Result_Float', out=True)

    def scale_col(s, c, k):
        """colour * scalar k (socket or float; a vector socket so k > 1 is not clamped)."""
        return s.mixc(c, s.comb(k, k, k), 1.0, 'MULTIPLY')

    def smin(s, a, b):
        return s.math('MINIMUM', a, b)


def _lin(hexs):
    return pk.hex2lin(hexs)


def _ctx(nb, ao_dist):
    c = {}
    c["col"] = nb.node('ShaderNodeAttribute', attribute_name="paper_col", attribute_type='GEOMETRY').outputs['Color']
    c["rnd"] = nb.node('ShaderNodeObjectInfo').outputs['Random']
    tc = nb.node('ShaderNodeTexCoord')
    c["obj"] = tc.outputs['Object']
    rest = nb.node('ShaderNodeAttribute', attribute_name="pk_rest", attribute_type='OBJECT').outputs['Vector']
    c["P"] = nb.vmath('ADD', c["obj"], rest)
    geo = nb.node('ShaderNodeNewGeometry')
    c["N"] = geo.outputs['Normal']
    ao = nb.node('ShaderNodeAmbientOcclusion', samples=8, only_local=False)
    ao.inputs['Distance'].default_value = ao_dist
    c["ao"] = ao.outputs['AO']
    c["cavity"] = nb.mr(ao.outputs['AO'], 0.35, 0.95, 1.0, 0.0)     # 1 = deep crevice
    return c


def _grime(nb, c, base, dirt_hex="#3E3A33", ao_k=0.75, streak_k=0.45, top_k=0.25, streak_scale=(1.6, 1.6, 0.11)):
    """Weathering: AO-driven crevice dirt + vertical rain streaks + dust on up-facing ledges.
    Returns (colour, grime factor 0..1)."""
    st = nb.noise(nb.vmath('MULTIPLY', c["P"], streak_scale), 1.0, 4.0, 0.55)
    streak = nb.mr(st, 0.52, 0.78, 0.0, 1.0)
    nz = nb.sep(c["N"])[2]
    top = nb.mr(nz, 0.55, 0.95, 0.0, 1.0)
    g = nb.math('ADD', nb.math('MULTIPLY', c["cavity"], ao_k), nb.math('MULTIPLY', streak, streak_k))
    g = nb.math('ADD', g, nb.math('MULTIPLY', top, top_k), clamp=True)
    dirt = nb.mixc(base, _lin(dirt_hex), 1.0, 'MULTIPLY')
    return nb.mixc(base, dirt, nb.math('MULTIPLY', g, 0.85)), g


def _bsdf(nb, base, rough, height=None, bump=0.25, bump_dist=0.01, metallic=0.0, spec=0.5, coat=0.0):
    b = nb.node('ShaderNodeBsdfPrincipled')
    nb.put(b.inputs['Base Color'], base); nb.put(b.inputs['Roughness'], rough)
    nb.put(b.inputs['Metallic'], metallic); nb.put(b.inputs['Specular IOR Level'], spec)
    if coat:
        nb.put(b.inputs['Coat Weight'], coat)
    if height is not None:
        bp = nb.node('ShaderNodeBump')
        bp.inputs['Strength'].default_value = bump; bp.inputs['Distance'].default_value = bump_dist
        nb.put(bp.inputs['Height'], height)
        nb.L.new(bp.outputs['Normal'], b.inputs['Normal'])
    return b.outputs[0]


def _mist(nb, shader):
    """preset mist (LOOK mist > 0): fade the lit surface to mist_hex by camera distance, thinner with height."""
    L = LOOK
    d = nb.node('ShaderNodeCameraData').outputs['View Distance']
    f = nb.math('MULTIPLY', nb.math('MAXIMUM', nb.math('SUBTRACT', d, L.get("mist_start", 40.0)), 0.0),
                -L.get("mist_density", 0.006))
    f = nb.math('SUBTRACT', 1.0, nb.math('EXPONENT', f))
    z = nb.sep(nb.node('ShaderNodeNewGeometry').outputs['Position'])[2]
    z0, z1 = L.get("mist_z", (10.0, 45.0))
    f = nb.math('MULTIPLY', f, nb.mr(z, GROUND_Z + z0, GROUND_Z + z1, 1.0, L.get("mist_top", 0.5)))
    f = nb.math('MULTIPLY', f, L["mist"])
    em = nb.node('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*_lin(L.get("mist_hex", L["haze_hex"])), 1)
    em.inputs['Strength'].default_value = L.get("mist_strength", 1.0)
    m = nb.node('ShaderNodeMixShader')
    nb.L.new(f, m.inputs[0]); nb.L.new(shader, m.inputs[1]); nb.L.new(em.outputs[0], m.inputs[2])
    return m.outputs[0]


def _finish(nb, shader):
    """back faces -> flat poche, section clip against PK_SectionPlane (same contract as the paper shader)."""
    if LOOK.get("mist", 0) > 0:
        shader = _mist(nb, shader)
    geo = nb.node('ShaderNodeNewGeometry')
    em = nb.node('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*pk.hex2lin(pk.POCHE), 1); em.inputs['Strength'].default_value = 0.9
    mixb = nb.node('ShaderNodeMixShader')
    nb.L.new(geo.outputs['Backfacing'], mixb.inputs[0]); nb.L.new(shader, mixb.inputs[1]); nb.L.new(em.outputs[0], mixb.inputs[2])
    tcs = nb.node('ShaderNodeTexCoord'); tcs.object = bpy.data.objects.get("PK_SectionPlane")
    gt = nb.math('GREATER_THAN', nb.sep(tcs.outputs['Object'])[1], 0.0)
    tr = nb.node('ShaderNodeBsdfTransparent')
    mixc = nb.node('ShaderNodeMixShader')
    nb.L.new(gt, mixc.inputs[0]); nb.L.new(tr.outputs[0], mixc.inputs[1]); nb.L.new(mixb.outputs[0], mixc.inputs[2])
    # x-ray: object prop "pk_xray" 0..1 turns the piece into a blueprint drawing (dark navy body, glowing cyan rim)
    xr = nb.node('ShaderNodeAttribute', attribute_name="pk_xray", attribute_type='OBJECT').outputs['Fac']
    lw = nb.node('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = 0.35
    rim = nb.math('POWER', lw.outputs['Facing'], 1.7)
    xcol = nb.mixc(_lin(LOOK.get("xray_base_hex", "#0B2233")), _lin(LOOK.get("xray_rim_hex", "#58CFFF")), rim)
    xem = nb.node('ShaderNodeEmission'); nb.put(xem.inputs['Color'], xcol)
    xem.inputs['Strength'].default_value = LOOK.get("xray_emit", 1.0)
    xk = nb.node('ShaderNodeMixShader'); xk.inputs[0].default_value = 1.0 - LOOK.get("xray_keep", 0.18)
    nb.L.new(mixc.outputs[0], xk.inputs[1]); nb.L.new(xem.outputs[0], xk.inputs[2])
    mixx = nb.node('ShaderNodeMixShader')
    nb.L.new(xr, mixx.inputs[0]); nb.L.new(mixc.outputs[0], mixx.inputs[1]); nb.L.new(xk.outputs[0], mixx.inputs[2])
    # ghost: object custom prop "pk_ghost" 0..1 fades the piece to transparent (missing prop = 0 = opaque)
    gh = nb.node('ShaderNodeAttribute', attribute_name="pk_ghost", attribute_type='OBJECT').outputs['Fac']
    trg = nb.node('ShaderNodeBsdfTransparent')
    mixg = nb.node('ShaderNodeMixShader')
    nb.L.new(gh, mixg.inputs[0]); nb.L.new(mixx.outputs[0], mixg.inputs[1]); nb.L.new(trg.outputs[0], mixg.inputs[2])
    out = nb.node('ShaderNodeOutputMaterial')
    nb.L.new(mixg.outputs[0], out.inputs['Surface'])


# ============================================================================= recipes
def _r_granite(nb, c):
    base = nb.scale_col(c["col"], nb.mr(c["rnd"], 0.0, 1.0, 0.9, 1.08, smooth=False))
    grains = nb.voronoi(c["P"], 22.0)
    dark = nb.mr(grains, 0.10, 0.22, 1.0, 0.0)                         # biotite / hornblende
    flk = nb.mr(nb.noise(c["P"], 70.0, 0.0), 0.58, 0.68, 0.0, 1.0)     # feldspar / quartz
    base = nb.mixc(base, nb.scale_col(base, 0.35), nb.math('MULTIPLY', dark, 0.75))
    base = nb.mixc(base, nb.scale_col(base, 1.55), nb.math('MULTIPLY', flk, 0.5))
    mot = nb.noise(c["P"], 0.9, 3.0)
    base = nb.scale_col(base, nb.mr(mot, 0.3, 0.7, 0.9, 1.1))
    base, g = _grime(nb, c, base, "#4A4640", ao_k=0.6, streak_k=0.35, top_k=0.15)
    rough = nb.math('ADD', 0.26, nb.math('MULTIPLY', g, 0.4))
    h = nb.math('ADD', nb.math('MULTIPLY', dark, -0.3), nb.math('MULTIPLY', flk, 0.2))
    return _bsdf(nb, base, rough, h, bump=0.15, bump_dist=0.004, spec=0.6)


def _veins(nb, c, scale=0.35):
    n1 = nb.noise(c["P"], scale, 5.0, 0.62, 2.8)
    return nb.mr(nb.math('ABSOLUTE', nb.math('SUBTRACT', n1, 0.5)), 0.0, 0.035, 1.0, 0.0)


def _r_marble(nb, c, rough0=0.42, dirty=1.0):
    base = c["col"]
    vein = _veins(nb, c)
    base = nb.mixc(base, nb.scale_col(base, 0.78), nb.math('MULTIPLY', vein, 0.25))
    base = nb.scale_col(base, nb.mr(nb.noise(c["P"], 1.3, 3.0), 0.3, 0.7, 0.93, 1.05))
    base, g = _grime(nb, c, base, "#5A554C", ao_k=0.85 * dirty, streak_k=0.55 * dirty, top_k=0.3 * dirty)
    rough = nb.math('ADD', rough0, nb.math('MULTIPLY', g, 0.35))
    return _bsdf(nb, base, rough, vein, bump=0.05, bump_dist=0.003, spec=0.5)


def _r_polished(nb, c):
    base = c["col"]
    vein = _veins(nb, c, 0.6)
    base = nb.mixc(base, nb.scale_col(base, 0.6), nb.math('MULTIPLY', vein, 0.5))
    return _bsdf(nb, base, 0.12, None, spec=0.6)


def _r_travertine(nb, c):
    base = c["col"]
    bands = nb.noise(nb.vmath('MULTIPLY', c["P"], (0.45, 0.45, 5.0)), 1.0, 3.0)
    base = nb.scale_col(base, nb.mr(bands, 0.3, 0.7, 0.88, 1.07))
    pores = nb.voronoi(nb.vmath('MULTIPLY', c["P"], (3.0, 3.0, 9.0)), 5.0)
    pore = nb.mr(pores, 0.03, 0.12, 1.0, 0.0)
    base = nb.mixc(base, nb.scale_col(base, 0.55), nb.math('MULTIPLY', pore, 0.6))
    base, g = _grime(nb, c, base, "#554E43", ao_k=0.8, streak_k=0.5, top_k=0.3)
    rough = nb.math('ADD', 0.68, nb.math('MULTIPLY', g, 0.2))
    return _bsdf(nb, base, rough, nb.math('MULTIPLY', pore, -1.0), bump=0.3, bump_dist=0.01)


def _r_stucco(nb, c):
    base = nb.scale_col(c["col"], nb.mr(nb.noise(c["P"], 0.6, 4.0), 0.3, 0.7, 0.86, 1.06))
    base, g = _grime(nb, c, base, "#4F4A42", ao_k=0.8, streak_k=0.6, top_k=0.35)
    fine = nb.noise(c["P"], 9.0, 3.0)
    return _bsdf(nb, base, 0.86, fine, bump=0.12, bump_dist=0.01)


def _r_render(nb, c):
    """Exterior lime render on masonry (ep02 walls): broad blotchy discolouration, light rain streaks only (the
    'stucco' streaks read as wood planks on big flat walls), fine trowel bump."""
    base = nb.scale_col(c["col"], nb.mr(nb.noise(c["P"], 0.18, 4.0, 0.6), 0.3, 0.7, 0.86, 1.08))
    base = nb.scale_col(base, nb.mr(nb.noise(nb.vmath('ADD', c["P"], (17.0, 3.0, 9.0)), 0.9, 3.0), 0.35, 0.65, 0.94, 1.04))
    base, g = _grime(nb, c, base, "#4F4A42", ao_k=0.8, streak_k=0.22, top_k=0.3, streak_scale=(0.7, 0.7, 0.06))
    fine = nb.noise(c["P"], 9.0, 3.0)
    return _bsdf(nb, base, 0.88, fine, bump=0.1, bump_dist=0.01)


def _r_plaster(nb, c):
    """Interior plaster: soft mottling, crevice AO, no rain streaks or ledge dust."""
    base = nb.scale_col(c["col"], nb.mr(nb.noise(c["P"], 0.3, 3.0), 0.3, 0.7, 0.9, 1.05))
    base, g = _grime(nb, c, base, "#5A5246", ao_k=0.7, streak_k=0.0, top_k=0.0)
    return _bsdf(nb, base, 0.82, nb.noise(c["P"], 7.0, 2.0), bump=0.06, bump_dist=0.01)


def _soot(nb, c, base, k=1.0):
    """big weathering patches on brick: dark soot + light remains of lime render."""
    w1 = nb.noise(nb.vmath('MULTIPLY', c["P"], (0.6, 0.6, 2.2)), 0.16, 6.0, 0.68)
    soot = nb.mr(w1, 0.45, 0.72, 0.0, 0.55 * k)
    base = nb.mixc(base, _lin("#2A221D"), soot)
    w2 = nb.noise(nb.vmath('ADD', c["P"], (37.0, 11.0, 5.0)), 0.07, 3.0)
    lime = nb.mr(w2, 0.6, 0.72, 0.0, 0.3 * k)
    return nb.mixc(base, _lin("#A39C8E"), lime)


def _r_brick(nb, c):
    x, y, z = nb.sep(c["P"])
    ang = nb.math('ARCTAN2', x, nb.math('MULTIPLY', y, -1.0))       # seam at +Y (back of the building)
    r = nb.vmath('LENGTH', nb.comb(x, y, 0.0))
    u = nb.math('MULTIPLY', ang, r)
    bt = nb.node('ShaderNodeTexBrick', offset=0.5, offset_frequency=2, squash=1.0, squash_frequency=2)
    nb.put(bt.inputs['Vector'], nb.comb(u, z, 0.0))
    nb.put(bt.inputs['Color1'], nb.scale_col(c["col"], 0.8)); nb.put(bt.inputs['Color2'], nb.scale_col(c["col"], 1.12))
    nb.put(bt.inputs['Mortar'], (*_lin("#9B9384"), 1.0))
    for k, v in (('Scale', 1.0), ('Mortar Size', 0.016), ('Mortar Smooth', 0.2), ('Bias', 0.0),
                 ('Brick Width', 0.40), ('Row Height', 0.082)):
        bt.inputs[k].default_value = v
    base = bt.outputs['Color']
    lace = nb.mr(nb.math('FRACT', nb.math('DIVIDE', z, 1.19)), 0.0, 0.06, 1.0, 0.0)   # bipedales bonding course
    base = nb.mixc(base, nb.scale_col(c["col"], 0.72), nb.math('MULTIPLY', lace, 0.55))
    base = _soot(nb, c, base)
    base, g = _grime(nb, c, base, "#3A2E27", ao_k=0.8, streak_k=0.35, top_k=0.2)
    h = nb.math('SUBTRACT', 1.0, bt.outputs['Fac'])
    return _bsdf(nb, base, nb.math('ADD', 0.84, nb.math('MULTIPLY', g, 0.1)), h, bump=0.55, bump_dist=0.012, spec=0.35)


def _r_brick_arch(nb, c):
    """Relieving arch: radial voussoirs around the arch centre (= piece origin); tangent from 'az'."""
    ox, oy, oz = nb.sep(c["obj"])
    azr = nb.math('RADIANS', nb.node('ShaderNodeAttribute', attribute_name="az", attribute_type='OBJECT').outputs['Fac'])
    uu = nb.math('ADD', nb.math('MULTIPLY', ox, nb.math('MULTIPLY', nb.math('SINE', azr), -1.0)),
                 nb.math('MULTIPLY', oy, nb.math('COSINE', azr)))
    a = nb.math('ARCTAN2', oz, uu)
    nv = 38.0
    t = nb.math('MULTIPLY', a, nv / math.pi)
    ft = nb.math('FRACT', t)
    joint = nb.mr(nb.smin(ft, nb.math('SUBTRACT', 1.0, ft)), 0.0, 0.1, 1.0, 0.0)
    wn = nb.white(nb.math('FLOOR', t))
    base = nb.scale_col(c["col"], nb.mr(wn, 0.0, 1.0, 0.82, 1.12, smooth=False))
    base = nb.mixc(base, _lin("#9B9384"), nb.math('MULTIPLY', joint, 0.85))
    base = _soot(nb, c, base, 0.8)
    base, g = _grime(nb, c, base, "#3A2E27", ao_k=0.8, streak_k=0.3, top_k=0.2)
    return _bsdf(nb, base, 0.86, nb.math('SUBTRACT', 1.0, joint), bump=0.5, bump_dist=0.012, spec=0.35)


def _lead(nb, c, u, v, seam_w=0.06, lap=1.9):
    """lead sheeting in (u = across sheets, in sheet widths; v = down-slope metres)."""
    fu = nb.math('FRACT', u)
    seam = nb.mr(nb.smin(fu, nb.math('SUBTRACT', 1.0, fu)), 0.0, seam_w, 1.0, 0.0)
    fv = nb.math('FRACT', nb.math('DIVIDE', v, lap))
    lapl = nb.mr(fv, 0.0, 0.025, 1.0, 0.0)
    sheet = nb.white(nb.math('ADD', nb.math('FLOOR', u), nb.math('MULTIPLY', nb.math('FLOOR', nb.math('DIVIDE', v, lap)), 7.31)))
    base = nb.scale_col(c["col"], nb.mr(sheet, 0.0, 1.0, 0.9, 1.08, smooth=False))
    ox = nb.noise(nb.comb(nb.math('MULTIPLY', u, 0.6), nb.math('MULTIPLY', v, 0.12), 0.0), 1.0, 4.0, 0.6)
    base = nb.mixc(base, _lin("#C9CCC8"), nb.mr(ox, 0.55, 0.78, 0.0, 0.45))       # white lead-carbonate bloom
    dk = nb.noise(nb.comb(nb.math('MULTIPLY', u, 2.0), nb.math('MULTIPLY', v, 0.08), 3.0), 1.0, 3.0)
    base = nb.mixc(base, _lin("#3C4042"), nb.mr(dk, 0.55, 0.75, 0.0, 0.35))         # dark run-off streaks
    base = nb.mixc(base, nb.scale_col(base, 0.55), nb.math('MULTIPLY', seam, 0.5))
    base, g = _grime(nb, c, base, "#3C3D3B", ao_k=0.7, streak_k=0.2, top_k=0.0)
    h = nb.math('ADD', nb.math('MULTIPLY', seam, 1.0), nb.math('MULTIPLY', fv, 0.25))
    h = nb.math('SUBTRACT', h, nb.math('MULTIPLY', lapl, 0.2))
    rough = nb.math('ADD', 0.5, nb.math('MULTIPLY', nb.mr(ox, 0.4, 0.8, 0.0, 1.0), 0.25))
    return _bsdf(nb, base, rough, h, bump=0.6, bump_dist=0.02, metallic=0.25, spec=0.45)


def _r_lead_dome(nb, c):
    """Sheets radiate from a dome centre: the piece's own (object props pk_dome_on = 1, pk_dome_center (rest world
    xyz), pk_dome_sheets = sheets round a full circle, pk_dome_r = radius in metres: half domes, exedrae, minaret
    cones) or LOOK dome_center with 128 sheets / 23 m (ep01, any piece without the props)."""
    cx, cy, cz = LOOK["dome_center"]
    attr = lambda nm, out: nb.node('ShaderNodeAttribute', attribute_name=nm, attribute_type='OBJECT').outputs[out]
    on = attr("pk_dome_on", 'Fac')
    dc = nb.vmath('SUBTRACT', attr("pk_dome_center", 'Vector'), (cx, cy, cz))
    cen = nb.vmath('ADD', nb.vmath('SCALE', dc, scale=on), (cx, cy, cz))
    q = nb.vmath('SUBTRACT', c["P"], cen)
    x, y, z = nb.sep(q)
    az = nb.math('ARCTAN2', x, nb.math('MULTIPLY', y, -1.0))
    rxy = nb.vmath('LENGTH', nb.comb(x, y, 0.0))
    el = nb.math('ARCTAN2', z, rxy)
    sheets = nb.mixf(128.0, attr("pk_dome_sheets", 'Fac'), on)
    rad = nb.mixf(23.0, attr("pk_dome_r", 'Fac'), on)
    u = nb.math('MULTIPLY', az, nb.math('DIVIDE', sheets, 2 * math.pi))     # sheets round the dome
    v = nb.math('MULTIPLY', el, nb.math('MULTIPLY', rad, -1.0))            # metres down the meridian
    return _lead(nb, c, u, v)


def dome_props(ob, center, radius, sheets=None):
    """mark a lead_dome piece with its own dome centre (lead seams radiate from it)."""
    ob["pk_dome_on"] = 1.0
    ob["pk_dome_center"] = tuple(float(v) for v in center)
    ob["pk_dome_r"] = float(radius)
    ob["pk_dome_sheets"] = float(sheets or max(12, round(2 * math.pi * radius / 0.95)))
    return ob


def _r_lead_roof(nb, c):
    x, y, z = nb.sep(c["P"])
    return _lead(nb, c, nb.math('DIVIDE', y, 0.95), nb.math('MULTIPLY', nb.math('ABSOLUTE', x), -1.0), seam_w=0.05, lap=2.3)


def _r_bronze(nb, c):
    base = nb.scale_col(c["col"], nb.mr(nb.noise(c["P"], 2.0, 4.0), 0.3, 0.7, 0.8, 1.2))
    pat = nb.math('ADD', nb.mr(nb.noise(c["P"], 0.9, 5.0, 0.6), 0.52, 0.72, 0.0, 0.55),
                  nb.math('MULTIPLY', c["cavity"], 0.6), clamp=True)
    base = nb.mixc(base, _lin("#3E5446"), nb.math('MULTIPLY', pat, 0.55))
    metal = nb.math('SUBTRACT', 0.9, nb.math('MULTIPLY', pat, 0.6))
    rough = nb.math('ADD', 0.34, nb.math('MULTIPLY', pat, 0.35))
    return _bsdf(nb, base, rough, None, metallic=metal)


def _paving(nb, c, bw, rh):
    x, y, z = nb.sep(c["P"])
    bt = nb.node('ShaderNodeTexBrick', offset=0.5, offset_frequency=2, squash=1.0, squash_frequency=2)
    nb.put(bt.inputs['Vector'], nb.comb(x, y, 0.0))
    nb.put(bt.inputs['Color1'], nb.scale_col(c["col"], 0.95)); nb.put(bt.inputs['Color2'], nb.scale_col(c["col"], 1.04))
    nb.put(bt.inputs['Mortar'], nb.scale_col(c["col"], 0.8))
    for k, v in (('Scale', 1.0), ('Mortar Size', 0.012), ('Mortar Smooth', 0.3), ('Bias', 0.0),
                 ('Brick Width', bw), ('Row Height', rh)):
        bt.inputs[k].default_value = v
    base = nb.scale_col(bt.outputs['Color'], nb.mr(nb.noise(c["P"], 0.25, 4.0), 0.3, 0.7, 0.92, 1.05))
    base, g = _grime(nb, c, base, "#6A6358", ao_k=0.9, streak_k=0.0, top_k=0.0)
    return base, bt.outputs['Fac']


def _r_paving(nb, c):
    base, fac = _paving(nb, c, 1.3, 0.65)
    return _bsdf(nb, base, 0.7, nb.math('SUBTRACT', 1.0, fac), bump=0.3, bump_dist=0.01)


def _r_ground(nb, c):
    base, fac = _paving(nb, c, 1.6, 0.8)
    gv = LOOK.get("ground_var", 0.0)
    if gv > 0:     # setting: large worn / washed patches + a faint second scale (sampietrini variation)
        x_, y_, z_ = nb.sep(c["P"])
        p2 = nb.comb(x_, y_, 0.0)
        big = nb.noise(p2, 0.035, 3.0, 0.55)
        mid = nb.noise(nb.vmath('ADD', p2, (13.0, 7.0, 0.0)), 0.16, 2.0)
        k = nb.math('ADD', nb.mr(big, 0.3, 0.7, 1.0 - gv, 1.0 + gv * 0.6), nb.mr(mid, 0.35, 0.65, -gv * 0.35, gv * 0.35))
        base = nb.scale_col(base, k)
        warm = nb.mr(nb.noise(nb.vmath('ADD', p2, (-31.0, 5.0, 0.0)), 0.05, 2.0), 0.5, 0.75, 0.0, gv * 1.6)
        base = nb.mixc(base, nb.mixc(base, _lin("#C9B28F"), 1.0, 'MULTIPLY'), warm)
    b = _bsdf(nb, base, 0.72, nb.math('SUBTRACT', 1.0, fac), bump=0.3, bump_dist=0.01)
    x, y, z = nb.sep(c["P"])
    r = nb.vmath('LENGTH', nb.comb(x, y, 0.0))
    f0, f1 = LOOK["ground_fade"]
    fade = nb.mr(r, f0, f1, 0.0, 1.0)
    em = nb.node('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*_lin(LOOK["haze_hex"]), 1); em.inputs['Strength'].default_value = LOOK["haze_strength"]
    m = nb.node('ShaderNodeMixShader')
    nb.L.new(fade, m.inputs[0]); nb.L.new(b, m.inputs[1]); nb.L.new(em.outputs[0], m.inputs[2])
    return m.outputs[0]


def _haze_mix(nb, shader, near=None, far=None, k0=None, k1=None):
    """blend a shader into the flat haze colour by camera distance (distant setting pieces stay calm)."""
    L = LOOK
    cam = nb.node('ShaderNodeCameraData')
    d = cam.outputs['View Distance']
    fac = nb.mr(d, near or L.get("city_near", 150.0), far or L.get("city_far", 420.0),
                L.get("city_haze0", 0.45) if k0 is None else k0, L.get("city_haze1", 0.9) if k1 is None else k1)
    em = nb.node('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*_lin(L["haze_hex"]), 1); em.inputs['Strength'].default_value = L["haze_strength"]
    m = nb.node('ShaderNodeMixShader')
    nb.L.new(fac, m.inputs[0]); nb.L.new(shader, m.inputs[1]); nb.L.new(em.outputs[0], m.inputs[2])
    return m.outputs[0]


def _r_facade(nb, c):
    """Distant Roman palazzi: tinted render, window grid (object space), roof/ground darker; hazed by distance."""
    ox, oy, oz = nb.sep(c["obj"])
    base = nb.scale_col(c["col"], nb.mr(c["rnd"], 0.0, 1.0, 0.86, 1.1, smooth=False))
    u = nb.math('ADD', ox, oy)
    fu = nb.math('FRACT', nb.math('DIVIDE', u, 3.3))
    fz = nb.math('FRACT', nb.math('DIVIDE', nb.math('SUBTRACT', oz, 1.2), 3.5))
    win = nb.math('MULTIPLY', nb.mr(nb.math('ABSOLUTE', nb.math('SUBTRACT', fu, 0.5)), 0.17, 0.22, 1.0, 0.0),
                  nb.mr(nb.math('ABSOLUTE', nb.math('SUBTRACT', fz, 0.5)), 0.22, 0.27, 1.0, 0.0))
    nz = nb.sep(c["N"])[2]
    side = nb.mr(nb.math('ABSOLUTE', nz), 0.3, 0.6, 1.0, 0.0)
    win = nb.math('MULTIPLY', win, side)
    win = nb.math('MULTIPLY', win, nb.mr(oz, 2.5, 3.5, 0.0, 1.0))
    base = nb.mixc(base, _lin("#3B3431"), nb.math('MULTIPLY', win, 0.8))
    base, g = _grime(nb, c, base, "#5A4D40", ao_k=0.5, streak_k=0.35, top_k=0.1)
    sh = _haze_mix(nb, _bsdf(nb, base, 0.85, None))
    if LOOK.get("city_windows", 0) > 0:      # preset (blue hour / night): some windows lit, warm
        cid = nb.math('ADD', nb.math('FLOOR', nb.math('DIVIDE', u, 3.3)),
                      nb.math('MULTIPLY', nb.math('FLOOR', nb.math('DIVIDE', nb.math('SUBTRACT', oz, 1.2), 3.5)), 57.0))
        cid = nb.math('ADD', cid, nb.math('MULTIPLY', c["rnd"], 911.0))
        rn = nb.white(cid)
        lit = nb.math('MULTIPLY', win, nb.mr(rn, 1.0 - LOOK.get("windows_lit", 0.4), 1.0 - LOOK.get("windows_lit", 0.4) + 0.01))
        k = nb.math('MULTIPLY', lit, nb.mr(nb.white(nb.math('ADD', cid, 0.37)), 0.0, 1.0, 0.45, 1.0))
        em = nb.node('ShaderNodeEmission')
        nb.put(em.inputs['Color'], nb.mixc(_lin(LOOK.get("window_hex", "#FFB765")), _lin("#FFE0B0"),
                                           nb.white(nb.math('ADD', cid, 0.71))))
        nb.L.new(nb.math('MULTIPLY', k, LOOK["city_windows"]), em.inputs['Strength'])
        ad = nb.node('ShaderNodeAddShader')
        nb.L.new(sh, ad.inputs[0]); nb.L.new(em.outputs[0], ad.inputs[1])
        sh = ad.outputs[0]
    return sh


def _r_setting(nb, c):
    """near setting props (bollards, fountain, obelisk): travertine-like stone, lightly hazed."""
    return _haze_mix(nb, _r_travertine(nb, c), 60.0, 400.0, 0.0, LOOK.get("setting_haze", 0.7))


def _r_window_glow(nb, c, scale=1.0):
    """Window glass seen from OUTSIDE (the pane's outer face): dark glass reflecting the sky; when the interior is
    lit (LOOK interior, or window_glow > 0) it also glows warm, a little unevenly from window to window. Keys:
    window_glow (emission strength, default 4 with a lit interior, else 0), window_glow_hex (default interior hex)."""
    it = LOOK.get("interior") or {}
    if isinstance(it, (list, tuple)):
        it = it[0] if it else {}
    k = LOOK.get("window_glow", 4.0 if it else 0.0) * scale
    sh = _bsdf(nb, (0.016, 0.02, 0.026), 0.06, None, spec=0.6)
    if k <= 0:
        return sh
    var = nb.mr(nb.noise(c["P"], 0.45, 2.0), 0.3, 0.7, 0.72, 1.18)
    em = nb.node('ShaderNodeEmission')
    nb.put(em.inputs['Color'], _lin(LOOK.get("window_glow_hex", it.get("hex", "#FFB56A"))))
    nb.L.new(nb.math('MULTIPLY', var, k), em.inputs['Strength'])
    ad = nb.node('ShaderNodeAddShader')
    nb.L.new(sh, ad.inputs[0]); nb.L.new(em.outputs[0], ad.inputs[1])
    return ad.outputs[0]


def _r_window_glow_dim(nb, c):
    """window_glow at window_glow_dim x the strength (default 0.35): panes the camera flies right up to (ep02: the
    dome's window ring in the dive), so the arch and the sky reflection read instead of a white blob."""
    return _r_window_glow(nb, c, LOOK.get("window_glow_dim", 0.35))


def _r_window_sky(nb, c):
    """Window glass seen from INSIDE (the pane's inner face): the sky outside as flat emission in the camera sky's
    colours (haze/mid mix), strength window_sky (default 1) x haze_strength; window_sky_hex overrides the colour."""
    L = LOOK
    if L.get("window_sky_hex"):
        col = _lin(L["window_sky_hex"])
    else:
        a, b = _lin(L["haze_hex"]), _lin(L.get("sky_mid_hex", L["haze_hex"]))
        col = tuple(0.45 * x + 0.55 * y for x, y in zip(a, b))
    em = nb.node('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*col, 1)
    em.inputs['Strength'].default_value = L.get("window_sky", 1.0) * L.get("haze_strength", 1.0)
    return em.outputs[0]


def _r_brick_byz(nb, c):
    """Byzantine brickwork (cut faces, the dome's brick shell): thin bricks in mortar beds almost as thick as the
    bricks (pinkish lime mortar with crushed brick), no Roman bonding courses; mapped round the Z axis like brick."""
    x, y, z = nb.sep(c["P"])
    ang = nb.math('ARCTAN2', x, nb.math('MULTIPLY', y, -1.0))
    r = nb.vmath('LENGTH', nb.comb(x, y, 0.0))
    u = nb.math('MULTIPLY', ang, r)
    bt = nb.node('ShaderNodeTexBrick', offset=0.5, offset_frequency=2, squash=1.0, squash_frequency=2)
    nb.put(bt.inputs['Vector'], nb.comb(u, z, 0.0))
    nb.put(bt.inputs['Color1'], nb.scale_col(c["col"], 0.86)); nb.put(bt.inputs['Color2'], nb.scale_col(c["col"], 1.08))
    nb.put(bt.inputs['Mortar'], (*_lin("#B4A190"), 1.0))
    for k, v in (('Scale', 1.0), ('Mortar Size', 0.034), ('Mortar Smooth', 0.35), ('Bias', 0.0),
                 ('Brick Width', 0.37), ('Row Height', 0.10)):
        bt.inputs[k].default_value = v
    base = _soot(nb, c, bt.outputs['Color'], 0.45)
    base, g = _grime(nb, c, base, "#3A2E27", ao_k=0.7, streak_k=0.25, top_k=0.15)
    h = nb.math('SUBTRACT', 1.0, bt.outputs['Fac'])
    return _bsdf(nb, base, 0.88, h, bump=0.4, bump_dist=0.01, spec=0.3)


def _r_gold_mosaic(nb, c):
    """Gold glass tesserae (irregular ~11 cm cells): gilded tiles, each tilted and smoother / rougher at random,
    thin dark grout. Mostly diffuse gold (metallic 0.22, low specular): with screen-space effects off, specular
    light is not occluded indoors, so a metallic interior would mirror the outdoor sky (half domes turned blue)."""
    v = nb.vmath('MULTIPLY', c["P"], (9.0, 9.0, 9.0))
    vo = nb.node('ShaderNodeTexVoronoi', feature='F1', distance='EUCLIDEAN')
    nb.put(vo.inputs['Vector'], v); vo.inputs['Randomness'].default_value = 0.85
    cr = nb.sep(vo.outputs['Color'])
    ve = nb.node('ShaderNodeTexVoronoi', feature='DISTANCE_TO_EDGE', distance='EUCLIDEAN')
    nb.put(ve.inputs['Vector'], v); ve.inputs['Randomness'].default_value = 0.85
    grout = nb.mr(ve.outputs['Distance'], 0.0, 0.07, 1.0, 0.0)
    base = nb.scale_col(c["col"], nb.mr(cr[0], 0.0, 1.0, 0.78, 1.14, smooth=False))
    base = nb.scale_col(base, nb.mr(nb.noise(c["P"], 0.25, 3.0), 0.3, 0.7, 0.85, 1.08))
    base = nb.mixc(base, _lin("#3E321F"), nb.math('MULTIPLY', grout, 0.75))
    base, g = _grime(nb, c, base, "#4A3C24", ao_k=0.6, streak_k=0.0, top_k=0.0)
    rough = nb.math('ADD', nb.math('ADD', 0.38, nb.math('MULTIPLY', cr[1], 0.3)), nb.math('MULTIPLY', grout, 0.3))
    metal = nb.math('MULTIPLY', 0.22, nb.math('SUBTRACT', 1.0, grout))
    h = nb.math('ADD', nb.math('MULTIPLY', cr[2], 0.35), nb.math('MULTIPLY', grout, -0.6))
    return _bsdf(nb, base, rough, h, bump=0.22, bump_dist=0.01, metallic=metal, spec=0.3)


def _r_render_byz(nb, c):
    """Byzantine exterior walls (ep02 fidelity pass): weathered salmon lime render over brick: blotchy
    discolouration, faint coursing read through the thin render, worn horizontal bands every ~2.6 m and patches
    where the render is gone and the thin bricks show (mapped round the Z axis like brick_byz), light rain streaks."""
    x, y, z = nb.sep(c["P"])
    ang = nb.math('ARCTAN2', x, nb.math('MULTIPLY', y, -1.0))
    r = nb.vmath('LENGTH', nb.comb(x, y, 0.0))
    u = nb.math('MULTIPLY', ang, r)
    bt = nb.node('ShaderNodeTexBrick', offset=0.5, offset_frequency=2, squash=1.0, squash_frequency=2)
    nb.put(bt.inputs['Vector'], nb.comb(u, z, 0.0))
    bc = _lin("#9A5C47")
    nb.put(bt.inputs['Color1'], (*[v * 0.82 for v in bc], 1.0)); nb.put(bt.inputs['Color2'], (*[v * 1.1 for v in bc], 1.0))
    nb.put(bt.inputs['Mortar'], (*_lin("#C4AC98"), 1.0))
    for k, v in (('Scale', 1.0), ('Mortar Size', 0.034), ('Mortar Smooth', 0.35), ('Bias', 0.0),
                 ('Brick Width', 0.37), ('Row Height', 0.10)):
        bt.inputs[k].default_value = v
    base = nb.scale_col(c["col"], nb.mr(nb.noise(c["P"], 0.16, 4.0, 0.6), 0.3, 0.7, 0.82, 1.08))
    base = nb.scale_col(base, nb.mr(nb.noise(nb.vmath('ADD', c["P"], (17.0, 3.0, 9.0)), 0.9, 3.0), 0.35, 0.65, 0.93, 1.05))
    base = nb.scale_col(base, nb.mr(bt.outputs['Fac'], 0.0, 1.0, 0.97, 1.03))          # coursing through the render
    f = nb.math('FRACT', nb.math('DIVIDE', z, 2.6))
    band = nb.math('MULTIPLY', nb.mr(f, 0.0, 0.025), nb.mr(f, 0.10, 0.125, 1.0, 0.0))
    band = nb.math('MULTIPLY', band, nb.mr(nb.noise(c["P"], 0.35, 3.0), 0.36, 0.56, 0.2, 0.9))
    pat = nb.mr(nb.noise(nb.vmath('ADD', c["P"], (5.0, 9.0, 2.0)), 0.11, 5.0, 0.62), 0.565, 0.625, 0.0, 1.0)
    bare = nb.math('MAXIMUM', band, pat)
    base = nb.mixc(base, bt.outputs['Color'], bare)
    base, g = _grime(nb, c, base, "#4F4A42", ao_k=0.8, streak_k=0.3, top_k=0.3, streak_scale=(0.7, 0.7, 0.06))
    h = nb.mixf(nb.noise(c["P"], 9.0, 3.0), nb.math('SUBTRACT', 1.0, bt.outputs['Fac']), bare)
    return _bsdf(nb, base, 0.88, h, bump=0.18, bump_dist=0.01, spec=0.35)


def _r_window_grille(nb, c):
    """Grilled window seen from outside (ep02 fidelity pass): the window_glow pane (dark glass, warm interior glow)
    behind a dark iron diamond lattice (~0.34 m mesh) drawn in the pane's own plane (u along the wall from the face
    normal, v = z), so the lit windows read as grilles instead of flat glowing slabs."""
    glow = _r_window_glow(nb, c)
    nx, ny, nz = nb.sep(c["N"])
    t = nb.vmath('NORMALIZE', nb.comb(nb.math('MULTIPLY', ny, -1.0), nx, 0.0))
    u = nb.vmath('DOT_PRODUCT', c["P"], t)
    z = nb.sep(c["P"])[2]
    bars = []
    for op in ('ADD', 'SUBTRACT'):
        fa = nb.math('FRACT', nb.math('MULTIPLY', nb.math(op, u, z), 1.0 / 0.34))
        da = nb.smin(fa, nb.math('SUBTRACT', 1.0, fa))
        bars.append(nb.mr(da, 0.05, 0.09, 1.0, 0.0))
    bar = nb.math('MAXIMUM', bars[0], bars[1])
    iron = _bsdf(nb, _lin("#1E1C1A"), 0.55, None, metallic=0.35, spec=0.4)
    mx = nb.node('ShaderNodeMixShader')
    nb.L.new(bar, mx.inputs[0]); nb.L.new(glow, mx.inputs[1]); nb.L.new(iron, mx.inputs[2])
    return mx.outputs[0]


RECIPES = {"facade": _r_facade, "setting": _r_setting, "granite": _r_granite, "marble": _r_marble, "polished": _r_polished, "travertine": _r_travertine,
           "stucco": _r_stucco, "brick": _r_brick, "brick_arch": _r_brick_arch, "lead_dome": _r_lead_dome,
           "lead_roof": _r_lead_roof, "bronze": _r_bronze, "paving": _r_paving, "ground": _r_ground,
           "window_glow": _r_window_glow, "window_glow_dim": _r_window_glow_dim, "window_sky": _r_window_sky, "brick_byz": _r_brick_byz,
           "gold_mosaic": _r_gold_mosaic, "render": _r_render, "plaster": _r_plaster,
           "render_byz": _r_render_byz, "window_grille": _r_window_grille}


def material(recipe):
    if recipe in _MATS and _MATS[recipe].name in bpy.data.materials:
        return _MATS[recipe]
    m = bpy.data.materials.new("RK_" + recipe)
    m.use_nodes = True
    m.surface_render_method = 'DITHERED'
    m.use_transparent_shadow = True
    nb = NB(m.node_tree)
    c = _ctx(nb, LOOK["ao_distance"])
    _finish(nb, RECIPES[recipe](nb, c))
    _MATS[recipe] = m
    return m


# ============================================================================= lighting / render
def _dirv(az, el):
    a, e = math.radians(az), math.radians(el)
    return Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))


def lighting(look=None):
    """Warm low sun (soft shadows) + physical sky (single-scattering = Nishita) for lighting; the camera sees
    a softened sky that fades into a haze band at the horizon (same colour as the far piazza)."""
    set_look(look)
    L = LOOK
    sc = bpy.context.scene
    ld = bpy.data.lights.new("PK_key", 'SUN')
    ld.energy = L["sun_strength"]; ld.angle = math.radians(L["sun_angle"]); ld.color = pk.hex2lin(L["sun_hex"])
    ob = bpy.data.objects.new("PK_key", ld); sc.collection.objects.link(ob)
    ob.rotation_euler = _dirv(L["sun_az"], L["sun_el"]).to_track_quat('Z', 'Y').to_euler()
    if L.get("sun_keys"):            # [[t, mult], ...] key-sun strength over time (ep01: dimmed under the wall diagram)
        for t_, m_ in L["sun_keys"]:
            ld.energy = L["sun_strength"] * m_
            ld.keyframe_insert("energy", frame=int(round(t_ * pk.FPS)) + 1)    # auto-clamped bezier = eased, flat holds
    w = bpy.data.worlds.new("PK_world"); sc.world = w
    w.use_nodes = True
    nb = NB(w.node_tree)
    sky = nb.node('ShaderNodeTexSky', sky_type='SINGLE_SCATTERING')
    sky.sun_disc = False
    sky.sun_elevation = math.radians(L["sun_el"])
    sky.sun_rotation = math.radians(L["sun_az"]) + math.pi
    sky.air_density = L["sky_air"]; sky.aerosol_density = L["sky_aerosol"]; sky.ozone_density = L["sky_ozone"]
    bgl = nb.node('ShaderNodeBackground'); bgl.inputs['Strength'].default_value = L["sky_strength"]
    skl = sky.outputs['Color']
    if L.get("sky_flat"):            # flat lighting sky (blue hour / night / overcast): colour x sky_strength
        skl = (*_lin(L.get("sky_light_hex", "#FFFFFF")),)
    elif L.get("sky_light_hex"):     # tint the lighting sky (cool fill -> blue shadows against the warm sun)
        skl = nb.mixc(skl, _lin(L["sky_light_hex"]), 1.0, 'MULTIPLY')
        skl = nb.scale_col(skl, 1.0 / max(1e-3, sum(_lin(L["sky_light_hex"])) / 3.0))
    nb.put(bgl.inputs['Color'], skl)
    if L.get("rim_strength", 0) > 0:
        rd = bpy.data.lights.new("PK_rim", 'SUN')
        rd.energy = L["rim_strength"]; rd.angle = math.radians(L.get("rim_angle", 2.0)); rd.color = pk.hex2lin(L["rim_hex"])
        ro = bpy.data.objects.new("PK_rim", rd); sc.collection.objects.link(ro)
        ro.rotation_euler = _dirv(L["rim_az"], L["rim_el"]).to_track_quat('Z', 'Y').to_euler()
    if L.get("floods") or L.get("shaft") or L.get("interior"):
        _preset_lights(L)
    # camera: haze near the horizon -> softened sky above
    tc = nb.node('ShaderNodeTexCoord')
    dz = nb.sep(tc.outputs['Generated'])[2]
    if L.get("cine_sky"):
        camc = _cine_sky(nb, tc.outputs['Generated'], dz, L)
    else:
        f = nb.mr(dz, 0.0, L["haze_band"], 0.0, L["sky_cam_mix"])
        skyc = nb.scale_col(sky.outputs['Color'], L["sky_cam_strength"])
        camc = nb.mixc((*_lin(L["haze_hex"]),), skyc, f)
    camc = nb.scale_col(camc, L["haze_strength"])
    bgc = nb.node('ShaderNodeBackground'); bgc.inputs['Strength'].default_value = 1.0
    nb.L.new(camc, bgc.inputs['Color'])
    lp = nb.node('ShaderNodeLightPath')
    mix = nb.node('ShaderNodeMixShader')
    nb.L.new(lp.outputs['Is Camera Ray'], mix.inputs[0]); nb.L.new(bgl.outputs[0], mix.inputs[1]); nb.L.new(bgc.outputs[0], mix.inputs[2])
    out = nb.node('ShaderNodeOutputWorld'); nb.L.new(mix.outputs[0], out.inputs['Surface'])


def _building_box():
    """world bbox of the built parts at rest, for lights placed from the building: pieces that rise more than 2 m
    above the ground (podium plates / steps / ground boards do not count), scale ignored (pop-in pieces sit at 0)."""
    from mathutils import Matrix
    mn, mx = [1e9] * 3, [-1e9] * 3
    for name, obs in pk.PARTS.items():
        if name.startswith("_"):
            continue
        for o in obs:
            if o.type != 'MESH':
                continue
            M = Matrix.LocRotScale(o.location, o.rotation_euler, (1.0, 1.0, 1.0))
            if o.parent:
                M = o.parent.matrix_world @ M
            ws = [M @ Vector(c) for c in o.bound_box]
            if max(w.z for w in ws) < GROUND_Z + 2.0:
                continue
            for w in ws:
                for i in range(3):
                    mn[i] = min(mn[i], w[i]); mx[i] = max(mx[i], w[i])
    return Vector(mn), Vector(mx)


def _lamp(name, kind, pos, target, power, hexcol, size, spread=None, blend=0.5):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = power; ld.color = pk.hex2lin(hexcol); ld.shadow_soft_size = size
    if kind == 'SPOT':
        ld.spot_size = math.radians(spread); ld.spot_blend = blend
    ob = bpy.data.objects.new(name, ld); bpy.context.scene.collection.objects.link(ob)
    ob.location = pos
    if target is not None:
        ob.rotation_euler = (Vector(pos) - Vector(target)).normalized().to_track_quat('Z', 'Y').to_euler()
    return ob


# power = e x 4 pi d^2 x FLOOD_K gives about e (sun-strength units) of irradiance at the aim point
FLOOD_K = 1.0


def _preset_lights(L):
    """floods (ring round the footprint + distant), cloud-break shaft, interior glow; see light_presets.py."""
    mn, mx = _building_box()
    if mn.x > mx.x:
        return
    ctr = (mn + mx) * 0.5
    H = mx.z - GROUND_Z
    R = max(mx.x - mn.x, mx.y - mn.y) * 0.5
    dg = bpy.context.evaluated_depsgraph_get()
    sc = bpy.context.scene
    n_l = 0
    for gi, f in enumerate(L.get("floods") or []):
        aimz = GROUND_Z + f.get("aim", 0.5) * H
        if f.get("ring"):
            n = int(f["ring"])
            zr = GROUND_Z + 0.15 * H
            for k in range(n):
                a = 2 * math.pi * (k + 0.5) / n
                d = Vector((math.cos(a), math.sin(a), 0.0))
                o = Vector((ctr.x, ctr.y, zr)) + d * (R * 2.0 + 20.0)
                hit = None
                for _ in range(24):          # march inward, skipping setting pieces / ground
                    ok, loc, nrm, idx, ob, _m = sc.ray_cast(dg, o, -d, distance=R * 2.0 + 30.0)
                    if not ok:
                        break
                    if ob.get("pk_part") and not str(ob.get("pk_part")).startswith("_"):
                        hit = loc; break
                    o = loc - d * 0.05
                if hit is None:
                    continue
                pos = Vector((hit.x, hit.y, 0.0)) + d * f.get("margin", 2.5)
                ok, loc, *_r = sc.ray_cast(dg, Vector((pos.x, pos.y, GROUND_Z + H + 5.0)), Vector((0, 0, -1)))
                pos.z = max(loc.z if ok else GROUND_Z, GROUND_Z) + f.get("h", 0.4)     # on the podium / steps
                tgt = Vector((hit.x, hit.y, aimz)) - d * 0.5
                dist = (tgt - pos).length
                _lamp("PK_flood%d_%d" % (gi, k), 'SPOT', pos, tgt, f["e"] * 4 * math.pi * dist * dist * FLOOD_K,
                      f.get("hex", "#FFC27A"), f.get("size", 0.25), f.get("spread", 70), f.get("blend", 0.8))
                n_l += 1
        for k, az in enumerate(f.get("az", [])):
            d = _dirv(az, 0.0)
            pos = Vector((ctr.x, ctr.y, GROUND_Z + f.get("h", 12.0))) + d * f.get("dist", 90.0)
            tgt = Vector((ctr.x, ctr.y, aimz))
            dist = (tgt - pos).length
            _lamp("PK_floodfar%d_%d" % (gi, k), 'SPOT', pos, tgt, f["e"] * 4 * math.pi * dist * dist * FLOOD_K,
                  f.get("hex", "#FFD29A"), f.get("size", 1.0), f.get("spread", 32), f.get("blend", 0.7))
            n_l += 1
    s = L.get("shaft")
    if s:
        tgt = Vector((ctr.x, ctr.y, GROUND_Z + s.get("aim", 0.4) * H))
        D = s.get("dist", 900.0)
        pos = tgt + _dirv(L["sun_az"], L["sun_el"]) * D
        spread = math.degrees(2 * math.atan(R * s.get("cover", 1.3) / D))
        _lamp("PK_shaft", 'SPOT', pos, tgt, s["e"] * 4 * math.pi * D * D * FLOOD_K, s.get("hex", "#FFF0DA"),
              s.get("size", 15.0), spread, s.get("blend", 0.45))
        n_l += 1
    it = L.get("interior")
    for k, it_ in enumerate(it if isinstance(it, (list, tuple)) else ([it] if it else [])):
        pos = Vector((ctr.x, ctr.y, GROUND_Z + it_.get("z", 0.25) * H))
        _lamp("PK_interior" + ("" if k == 0 else str(k)), 'POINT', pos, None,
              it_["e"] * 4 * math.pi * R * R * 0.25 * FLOOD_K, it_.get("hex", "#FFB56A"), it_.get("size", 2.0))
        n_l += 1
    print("[realkit] preset lights: %d (building box %s .. %s, H %.1f, R %.1f)"
          % (n_l, tuple(round(v, 1) for v in mn), tuple(round(v, 1) for v in mx), H, R))


def _cine_sky(nb, D, dz, L):
    """camera-ray sky: haze at the horizon -> mid -> zenith, warm glow around the sun, planar cloud layer."""
    c = nb.mixc(_lin(L["haze_hex"]), _lin(L["sky_mid_hex"]), nb.mr(dz, 0.0, L["sky_mid_z"]))
    c = nb.mixc(c, _lin(L["sky_zenith_hex"]), nb.mr(dz, L["sky_mid_z"], L["sky_zenith_z"]))
    S = _dirv(L["sun_az"], L["sun_el"])
    cs = nb.vmath('DOT_PRODUCT', D, tuple(S))
    w = L.get("sun_glow_width", 0.5)
    glow = nb.math('POWER', nb.mr(cs, 1.0 - w, 1.0, 0.0, 1.0, smooth=False), 2.2)
    glow = nb.math('MULTIPLY', glow, nb.mr(dz, -0.03, 0.02))
    wide = nb.mr(cs, -0.2, 1.0, 0.0, 1.0)                                    # sun side of the sky
    if L.get("clouds", 0) > 0:
        zc = nb.math('MAXIMUM', dz, 0.02)
        x, y, _z = nb.sep(D)
        uv = nb.comb(nb.math('DIVIDE', x, zc), nb.math('MULTIPLY', nb.math('DIVIDE', y, zc), 2.2), 0.0)
        n1 = nb.noise(nb.vmath('MULTIPLY', uv, (L["cloud_scale"], L["cloud_scale"] * 0.45, 1.0)), 1.0, 6.0, 0.62, 0.3)
        cov = L.get("cloud_cov", 0.52)
        dens = nb.mr(n1, cov, cov + 0.16)
        cl0, cl1 = L.get("cloud_low", (0.03, 0.15))      # clouds fade in above the horizon between these dz
        dens = nb.math("MULTIPLY", dens, nb.mr(dz, cl0, cl1))
        dens = nb.math('MULTIPLY', dens, L["clouds"])
        ccol = nb.mixc(_lin(L["cloud_hex"]), _lin(L["cloud_lit_hex"]), nb.math('POWER', wide, 2.0))
        c = nb.mixc(c, ccol, dens)
        glow = nb.math('MULTIPLY', glow, nb.math('SUBTRACT', 1.0, nb.math('MULTIPLY', dens, 0.5)))
    gcol = nb.scale_col(_lin(L.get("sun_glow_hex", "#FFFFFF")), glow)
    c = nb.mixc(c, nb.scale_col(gcol, L.get("sun_glow", 1.0)), 1.0, 'ADD')
    if L.get("stars", 0) > 0:        # faint stars: sparse voronoi cells on the view direction, fade near the horizon
        vo = nb.node('ShaderNodeTexVoronoi', feature='F1', distance='EUCLIDEAN')
        nb.put(vo.inputs['Vector'], D); vo.inputs['Scale'].default_value = 420.0
        cell = nb.sep(vo.outputs['Color'])[0]
        st = nb.math('MULTIPLY', nb.mr(vo.outputs['Distance'], 0.05, 0.16, 1.0, 0.0), nb.mr(cell, 0.8, 0.98, 0.0, 1.0))
        st = nb.math('MULTIPLY', st, nb.mr(dz, 0.12, 0.35))
        st = nb.math('MULTIPLY', st, L["stars"] * 0.35)
        c = nb.mixc(c, nb.scale_col(_lin("#DCE6FF"), st), 1.0, 'ADD')
    return c


def camera_dof(look=None):
    """depth of field from LOOK dof_fstop / dof_keys, focused on the camera target (PK_CamPivot)."""
    L = LOOK if look is None else look
    if not (L.get("dof_fstop") or L.get("dof_keys")):
        return
    cam = bpy.data.objects.get("PK_Cam")
    if not cam:
        return
    d = cam.data.dof
    d.use_dof = True
    d.focus_object = bpy.data.objects.get("PK_CamPivot")
    d.aperture_fstop = L.get("dof_fstop", 2.8)
    for t, fs in L.get("dof_keys", []):
        d.aperture_fstop = fs
        cam.data.keyframe_insert('dof.aperture_fstop', frame=pk.sec2f(t))


def post_render_setup(q=None):
    """View transform + mild bloom (compositor Glare/Bloom). Called by paperkit.render_setup in real style."""
    sc = bpy.context.scene
    try:
        sc.view_settings.view_transform = 'AgX'
        sc.view_settings.look = LOOK["look"]
        sc.view_settings.exposure = LOOK["exposure"]
    except Exception as ex:
        print("[realkit] view", ex)
    if LOOK.get("bloom", 0) <= 0:
        return
    try:
        ct = bpy.data.node_groups.new("PK_comp", "CompositorNodeTree")
        ct.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
        rl = ct.nodes.new("CompositorNodeRLayers")
        gl = ct.nodes.new("CompositorNodeGlare")
        for v in ("Bloom", "BLOOM"):
            try:
                gl.inputs['Type'].default_value = v; break
            except Exception:
                pass
        gl.inputs['Threshold'].default_value = LOOK["bloom_threshold"]
        gl.inputs['Strength'].default_value = LOOK["bloom"]
        try:
            gl.inputs['Size'].default_value = LOOK["bloom_size"] / 9.0 if gl.inputs['Size'].type == 'VALUE' else LOOK["bloom_size"]
        except Exception as ex:
            print("[realkit] bloom size", ex)
        out = ct.nodes.new("NodeGroupOutput")
        ct.links.new(rl.outputs['Image'], gl.inputs['Image'])
        ct.links.new(gl.outputs['Image'], out.inputs[0])
        sc.compositing_node_group = ct
        sc.render.use_compositing = True
        try:
            sc.render.compositor_device = 'GPU'
        except Exception:
            pass
    except Exception as ex:
        print("[realkit] bloom disabled:", ex)


# ============================================================================= geometry helpers
def mitre_frames(pts, axis):
    """Per-vertex offset vectors (right-hand normals d x axis, mitre-scaled) for a polyline."""
    pts = [Vector(p) for p in pts]
    axis = Vector(axis)
    ns = [(pts[i + 1] - pts[i]).normalized().cross(axis).normalized() for i in range(len(pts) - 1)]
    out = []
    for i in range(len(pts)):
        if i == 0:
            out.append(ns[0])
        elif i == len(pts) - 1:
            out.append(ns[-1])
        else:
            n1, n2 = ns[i - 1], ns[i]
            out.append((n1 + n2) / (1.0 + n1.dot(n2)))
    return out


def sweep(mb, pts, axis, profile, cols, caps=True):
    """Closed profile [(a, b)] swept along polyline pts: point = P + n*a + axis*b (n = mitred normal)."""
    mb.island()
    pts = [Vector(p) for p in pts]
    ns = mitre_frames(pts, axis)
    ax = Vector(axis)
    rings = [[p + n * a + ax * b for (a, b) in profile] for p, n in zip(pts, ns)]
    k = len(profile)
    for i in range(len(pts) - 1):
        r0, r1 = rings[i], rings[i + 1]
        for j in range(k):
            j2 = (j + 1) % k
            mb.face([r0[j], r1[j], r1[j2], r0[j2]], cols[j] if isinstance(cols, (list, tuple)) else cols)
    if caps:
        c0 = cols[0] if isinstance(cols, (list, tuple)) else cols
        mb.face(list(reversed(rings[0])), c0)
        mb.face(rings[-1], c0)
    return rings


def dentils(mb, pts, axis, a0, a1, b0, b1, col, width=0.17, pitch=0.29, skip_ends=0.3):
    """Row of dentil blocks along the polyline (profile coords a0..a1 outward, b0..b1 along axis)."""
    pts = [Vector(p) for p in pts]
    ax = Vector(axis)
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        d = (q - p); L = d.length; d.normalize()
        n = d.cross(ax).normalized()
        s = skip_ends + pitch / 2
        while s < L - skip_ends:
            o = p + d * (s - width / 2)
            poly = [o + n * a0 + ax * b0, o + n * a1 + ax * b0, o + n * a1 + ax * b1, o + n * a0 + ax * b1]
            mb.prism(poly, d * width, col)
            s += pitch


def tube(mb, pts, radii, binormal, col, sides=6):
    """Round tube along pts lying in the plane normal to `binormal` (volutes, stalks)."""
    mb.island()
    pts = [Vector(p) for p in pts]
    B = Vector(binormal).normalized()
    rings = []
    for i, p in enumerate(pts):
        T = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        N2 = T.cross(B).normalized()
        rings.append([p + (B * math.cos(2 * math.pi * k / sides) + N2 * math.sin(2 * math.pi * k / sides)) * radii[i]
                      for k in range(sides)])
    for i in range(len(rings) - 1):
        for k in range(sides):
            k2 = (k + 1) % sides
            mb.face([rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]], col)
    mb.face(list(reversed(rings[0])), col)
    mb.face(rings[-1], col)


def _arc(cr, cz, rad, t0, t1, n):
    return [(cr + rad * math.cos(math.radians(t0 + (t1 - t0) * k / n)), cz + rad * math.sin(math.radians(t0 + (t1 - t0) * k / n)))
            for k in range(n + 1)]


# ============================================================================= classical components
def column_real(part, x, y, z, height, diam, shaft='x', base='x', capital='x', n=32, meta=None):
    """Corinthian column in three pieces (base / shaft / capital), each with its own bottom pivot.
    Attic base (plinth, torus, scotia, torus), entasis shaft (straight lower third, tapers to 0.88),
    capital: astragal, bell, 2 rows x 8 acanthus leaves (lobed, tips curling), 4 corner volutes on
    stalks, concave abacus with a fleuron on each face. Returns [base, shaft, capital]."""
    D = diam; r = D / 2
    hb, hc = 0.5 * D, 1.27 * D
    hs = height - hb - hc
    m0 = {"x": x, "y": y}; m0.update(meta or {})
    out = []
    # ---- base
    mb = MB()
    mb.box(x - 0.7 * D, x + 0.7 * D, y - 0.7 * D, y + 0.7 * D, z, z + 0.16 * D, base)
    prof = [(0.0, 0.16)] + [(p[0], p[1]) for p in _arc(0.60, 0.235, 0.075, -90, 90, 6)]
    prof += [(0.575, 0.315), (0.555, 0.33)] + _arc(0.585, 0.36, 0.035, 250, 110, 4)[1:-1] + [(0.555, 0.39), (0.575, 0.40)]
    prof += _arc(0.545, 0.44, 0.042, -90, 90, 5) + [(0.52, 0.485), (0.5, 0.5), (0.0, 0.5)]
    prof = [(a * D, z + b * D) for a, b in prof]
    mb.revolve(prof, 0, 2 * math.pi, n, center=(x, y, 0), col=base, full=True)
    out.append(pk.finish(mb, pk._pname(part), part, pivot=(x, y, z), bevel=0.02, meta=dict(m0, sub="base")))
    # ---- shaft (entasis)
    z0 = z + hb
    prof = [(0.0, 0.0), (r * 1.06, 0.0), (r * 1.06, 0.03)]
    for k in range(1, 15):
        t = k / 14
        rr = r * (1 - 0.12 * max(0.0, (t - 0.33) / 0.67) ** 1.3)
        if k == 1:
            rr = r * 1.015
        prof.append((rr, t * hs))
    prof += [(r * 0.88 * 1.04, hs), (0.0, hs)]
    mb = MB()
    mb.revolve([(a, z0 + b) for a, b in prof], 0, 2 * math.pi, n, center=(x, y, 0), col=shaft, full=True)
    out.append(pk.finish(mb, pk._pname(part), part, pivot=(x, y, z0), bevel=0.0, meta=dict(m0, sub="shaft")))
    # ---- capital
    zc = z0 + hs
    rt = r * 0.88
    mb = MB()
    bell = [(0.0, 0.0), (rt * 1.02, 0.0)] + [(a, b) for a, b in _arc(rt * 1.02, 0.05 * D, 0.05 * D, -90, 90, 5)]
    bell += [(rt, 0.11 * D), (rt * 1.01, 0.4 * D), (rt * 1.07, 0.75 * D), (rt * 1.16, 0.98 * D), (rt * 1.24, 1.03 * D),
             (rt * 1.24, 1.08 * D), (0.0, 1.08 * D)]
    mb.revolve([(a, zc + b) for a, b in bell], 0, 2 * math.pi, n, center=(x, y, 0), col=capital, full=True)

    def rbell(zz):          # bell radius at height zz (relative to zc)
        pts = [(0.11 * D, rt), (0.4 * D, rt * 1.01), (0.75 * D, rt * 1.07), (0.98 * D, rt * 1.16)]
        if zz <= pts[0][0]:
            return pts[0][1]
        for (za, ra), (zb, rb) in zip(pts, pts[1:]):
            if zz <= zb:
                return ra + (rb - ra) * (zz - za) / (zb - za)
        return pts[-1][1]

    def leaf(azc, zb, h, wdeg, lean, curl):
        mb.island()
        nu, nv = 6, 9
        F, Bk = [], []
        for j in range(nv + 1):
            v = j / nv
            w = math.radians(wdeg) * (0.35 + 0.65 * math.sin(math.pi * min(0.15 + v * 0.95, 1.0))) * (1 + 0.16 * math.sin(v * math.pi * 7))
            if j == nv:
                w *= 0.25
            rowf, rowb = [], []
            for i in range(nu + 1):
                u = -1 + 2 * i / nu
                zz = zb + v * h - curl * 0.5 * max(0.0, (v - 0.78) / 0.22) ** 2 * h
                off = 0.02 * D + lean * v ** 2 + curl * max(0.0, (v - 0.7) / 0.3) ** 2 - 0.05 * D * u * u + 0.02 * D * (1 - abs(u)) ** 4
                a = azc + u * w
                rb = rbell(zz)
                rowf.append((x + (rb + off) * math.cos(a), y + (rb + off) * math.sin(a), zc + zz))
                rowb.append((x + (rb - 0.02) * math.cos(a), y + (rb - 0.02) * math.sin(a), zc + zz))
            F.append(rowf); Bk.append(rowb)
        for j in range(nv):
            for i in range(nu):
                mb.face([F[j][i], F[j][i + 1], F[j + 1][i + 1], F[j + 1][i]], capital)
                mb.face([Bk[j][i], Bk[j + 1][i], Bk[j + 1][i + 1], Bk[j][i + 1]], capital)
        for j in range(nv):
            mb.face([F[j][0], F[j + 1][0], Bk[j + 1][0], Bk[j][0]], capital)
            mb.face([F[j][nu], Bk[j][nu], Bk[j + 1][nu], F[j + 1][nu]], capital)
        for i in range(nu):
            mb.face([F[nv][i], F[nv][i + 1], Bk[nv][i + 1], Bk[nv][i]], capital)
            mb.face([F[0][i], Bk[0][i], Bk[0][i + 1], F[0][i + 1]], capital)

    for k in range(8):                      # lower row: on the faces and diagonals
        leaf(math.radians(45 * k), 0.1 * D, 0.42 * D, 21, 0.11 * D, 0.07 * D)
    for k in range(8):                      # upper row: in between, taller
        leaf(math.radians(22.5 + 45 * k), 0.14 * D, 0.72 * D, 19, 0.15 * D, 0.1 * D)
    # corner volutes on stalks (in the diagonal vertical plane)
    for k in range(4):
        a = math.radians(45 + 90 * k)
        er = Vector((math.cos(a), math.sin(a), 0)); et = Vector((-math.sin(a), math.cos(a), 0))
        cs, cz_ = 0.78 * D, 0.90 * D
        pts2 = [(rbell(0.6 * D) + 0.03 * D, 0.6 * D), (0.60 * D, 0.82 * D), (0.72 * D, 0.97 * D), (0.84 * D, 1.02 * D)]
        R0 = math.hypot(0.84 * D - cs, 1.02 * D - cz_)
        t0 = math.atan2(1.02 * D - cz_, 0.84 * D - cs)
        for j in range(1, 19):
            t = t0 - j * (2.3 * math.pi / 18)
            rr = R0 * (1 - 0.72 * j / 18)
            pts2.append((cs + rr * math.cos(t), cz_ + rr * math.sin(t)))
        P3 = [Vector((x, y, zc)) + er * s_ + Vector((0, 0, zz)) for s_, zz in pts2]
        radii = [0.045 * D * (1 - 0.55 * j / (len(P3) - 1)) for j in range(len(P3))]
        tube(mb, P3, radii, et, capital, sides=6)
    # abacus: concave sides, chamfered corners, fleuron in the middle of each face
    poly = []
    for k in range(4):
        a = math.radians(-90 + 90 * k)
        nrm = Vector((math.cos(a), math.sin(a), 0)); tg = Vector((-math.sin(a), math.cos(a), 0))
        for j in range(7):
            s_ = -1 + 2 * j / 6
            dd = 0.76 * D - 0.12 * D * (1 - s_ * s_)
            p = nrm * dd + tg * s_ * 0.62 * D
            poly.append((x + p.x, y + p.y, zc + 1.08 * D))
    mb.prism(poly, (0, 0, 0.19 * D), capital)
    for k in range(4):
        a = math.radians(-90 + 90 * k)
        cx_, cy_ = x + 0.66 * D * math.cos(a), y + 0.66 * D * math.sin(a)
        mb.island()
        mb.cylinder(cx_, cy_, zc + 1.1 * D, zc + 1.25 * D, 0.07 * D, 0.05 * D, col=capital, n=10)
    out.append(pk.finish(mb, pk._pname(part), part, pivot=(x, y, zc), bevel=0.012, meta=dict(m0, sub="capital")))
    return out


def columns_real(part, points, height, diam, **kw):
    out = []
    for i, p in enumerate(points):
        out += column_real(part, p[0], p[1], p[2] if len(p) > 2 else 0.0, height, diam, meta={"col_i": i}, **kw)
    return out


# entablature profiles: (a = outward from the face line, b = height above the course's base), metres
ARCHITRAVE = [(0.0, 0.0), (0.0, 0.32), (0.05, 0.34), (0.05, 0.68), (0.10, 0.70), (0.10, 1.02), (0.17, 1.08), (0.17, 1.15)]
FRIEZE_H = 0.95
CORNICE = [(0.0, 0.0), (0.07, 0.06), (0.13, 0.12), (0.13, 0.40), (0.38, 0.42), (0.44, 0.48), (0.96, 0.50), (0.96, 0.64),
           (1.02, 0.68), (1.08, 0.76), (1.10, 0.80)]
CORNICE_H = 0.80


def _closed(front, depth, h):
    """front profile (a,b) from b=0 to b=h -> closed polygon with the back at a=-depth."""
    return [(-depth, 0.0)] + list(front) + [(-depth, h)]


def entablature_real(part, path, z, col='x', frieze_col=None, cornice_col=None, depth=1.4, ceiling=None,
                     inscription=None, font=None, text_col='bronze', text_size=1.0):
    """Classical entablature swept along a plan polyline `path` [(x,y),...] (outward = right-hand side,
    e.g. back-left -> front-left -> front-right -> back-right for a portico facing -Y).
    Pieces: architrave (3 fascias), frieze, cornice (+ dentils), optional ceiling slab, optional inscription
    (raised letters centred on the frieze of the longest segment). Returns pieces; z = underside."""
    out = []
    pts = [Vector((p[0], p[1], 0.0)) for p in path]
    up = (0, 0, 1)
    ha = ARCHITRAVE[-1][1]
    for prof, z0, h, cc, sub in ((ARCHITRAVE, z, ha, col, "architrave"),
                                 ([(0.0, 0.0), (0.0, FRIEZE_H)], z + ha, FRIEZE_H, frieze_col or col, "frieze"),
                                 (CORNICE, z + ha + FRIEZE_H, CORNICE_H, cornice_col or col, "cornice")):
        mb = MB()
        sweep(mb, [p + Vector((0, 0, z0)) for p in pts], up, _closed(prof, depth, h), cc)
        if sub == "cornice":
            dentils(mb, [p + Vector((0, 0, z0)) for p in pts], up, 0.13, 0.31, 0.14, 0.38, cc)
        c = (pts[0] + pts[-1]) / 2
        out.append(pk.finish(mb, pk._pname(part), part, pivot=(c.x, c.y, z0), bevel=0.02, meta={"sub": sub}))
    if ceiling:
        x0, x1, y0, y1 = ceiling
        out.append(pk.box_piece(part, x0, x1, y0, y1, z + 0.5, z + ha + FRIEZE_H, "ceiling", bevel=0.0,
                                meta={"sub": "ceiling"}))
    if inscription:
        segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        p, q = max(segs, key=lambda s: (s[1] - s[0]).length)
        d = (q - p).normalized(); n = d.cross(Vector(up))
        mid = (p + q) / 2 + n * 0.04 + Vector((0, 0, z + ha + FRIEZE_H * 0.5))
        out += pk.text_piece(part, inscription, tuple(mid), text_size, text_col, facing="-y", depth=0.07,
                             font=font, meta={"sub": "inscription"})
    return out


def pediment_real(part, x0, x1, y_face, y_back, z, rise, col='x', tymp_col=None, cornice_col=None, roof_col=None,
                  roof_t=0.35, roof_front=1.0):
    """Pediment facing -Y on top of an entablature (z = top of its cornice): tympanum flush with the frieze
    plane y_face, mitred raking cornices with dentils, two roof slabs back to y_back."""
    out = []
    xm = (x0 + x1) / 2
    tri = [(x0, y_face, z), (x1, y_face, z), (xm, y_face, z + rise)]
    mb = MB(); mb.prism(tri, (0, y_back - y_face, 0), tymp_col or col, side_col=col)
    out.append(pk.finish(mb, pk._pname(part), part, pivot=(xm, y_face, z), bevel=0.03, meta={"sub": "tympanum"}))
    # raking cornice: path along the sloped top edges in the facade plane; profile (a = up the slope normal,
    # b = along +Y) -> projection toward the viewer is negative b.
    ext = 0.25
    s = math.atan2(rise, (x1 - x0) / 2)
    path = [Vector((x0 - ext * math.cos(s), y_face, z - ext * math.sin(s))), Vector((xm, y_face, z + rise)),
            Vector((x1 + ext * math.cos(s), y_face, z - ext * math.sin(s)))]
    prof = [(b, -a) for a, b in CORNICE]
    closed = [(0.0, 1.2)] + prof + [(CORNICE_H, 1.2)]
    mb = MB()
    sweep(mb, path, (0, 1, 0), closed, cornice_col or col)
    dentils(mb, path, (0, 1, 0), 0.14, 0.38, -0.13, -0.31, cornice_col or col, skip_ends=0.6)
    out.append(pk.finish(mb, pk._pname(part), part, pivot=(xm, y_face, z), bevel=0.02, meta={"sub": "raking_cornice"}))
    # roof slabs on the top of the raking cornice
    ns = mitre_frames(path, (0, 1, 0))
    top = [p + n * CORNICE_H for p, n in zip(path, ns)]
    yf = y_face - roof_front
    for i in (0, 1):
        a, b = top[i], top[i + 1]
        poly = [Vector((a.x, yf, a.z)), Vector((b.x, yf, b.z)), Vector((b.x, y_back, b.z)), Vector((a.x, y_back, a.z))]
        nrm = ns[0] if i == 0 else ns[2]
        mb = MB(); mb.prism(poly, nrm.normalized() * roof_t, roof_col or col)
        c = (a + b) / 2
        out.append(pk.finish(mb, pk._pname(part), part, pivot=(c.x, (yf + y_back) / 2, z), bevel=0.0, meta={"sub": "roof"}))
    return out


def cornice_ring(part, r_face, z0, h, proj, col, n_seg=16, r_back=None, ring=0, **kw):
    """Moulded ring cornice on a drum of radius r_face (bed moulding + corona + sima), n_seg pieces."""
    rb = r_back if r_back is not None else r_face - 0.4
    k = h / 0.9
    prof = [(rb, z0), (r_face + 0.06 * k, z0), (r_face + 0.06 * k, z0 + 0.2 * k), (r_face + 0.25 * k, z0 + 0.38 * k),
            (r_face + proj, z0 + 0.52 * k), (r_face + proj, z0 + h - 0.12 * k), (r_face + proj - 0.08 * k, z0 + h), (rb, z0 + h)]
    return pk.revolve_pieces(part, prof, n_seg, col=col, ring=ring, **kw)


def step_rings(part, z0, n, step_h, r0, step_in, sph_r, col, n_seg=16, ring0=1, cut_cols=None, inner_col=None):
    """Stepped rings at the foot of a dome: riser + tread with a small nosing. sph_r(z) = inner radius.
    cut_cols: optional colour per ring for the ring's bottom face and the inner part of its top face (what an
    exploded band shows: the aggregate); inner_col: colour of the inner (dome-facing) surface."""
    out = []
    for k in range(n):
        za, zb = z0 + k * step_h, z0 + (k + 1) * step_h
        ro = r0 - step_in * k
        prof = [(sph_r(za), za), (ro, za), (ro, zb - 0.14), (ro + 0.08, zb - 0.1), (ro + 0.08, zb), (sph_r(zb), zb)]
        if cut_cols:
            cc = cut_cols[k]
            # tread of the NEXT step covers the inner part of this top face: split it so the visible tread stays stucco
            rn = r0 - step_in * (k + 1) - 0.02
            prof = [(sph_r(za), za), (ro, za), (ro, zb - 0.14), (ro + 0.08, zb - 0.1), (ro + 0.08, zb), (rn, zb), (sph_r(zb), zb)]
            cols = [cc, col, col, col, col, cc, inner_col or col]
            out += pk.revolve_pieces(part, prof, n_seg, cols=cols, ring=ring0 + k, bevel=0.06)
        else:
            out += pk.revolve_pieces(part, prof, n_seg, col=col, ring=ring0 + k, bevel=0.06)
    return out


MB = pk.MB


def minaret_real(part, x, y, z, h, d, balconies=(0.6,), col="marble_white", top_col=None, cap_col="lead",
                 alem_col="bronze_gold", base_w=None, base_h=None, n_shaft=16, cap_h=None, alem_az=0.0, meta=None,
                 base_style="square", flare=0.2, base_col=None, balcony_col=None, drum_col=None):
    """Ottoman minaret, foot of the pedestal at z, cone tip at z + h (the gilded finial rises ~2 m above): square
    pedestal, polygonal transition, n_shaft-sided shaft tapering slightly, one serefe (balcony) per entry of
    `balconies` (fractions of h: corbelled stepped rings, floor, parapet), upper drum, tall lead cone (lead seams
    radiate from its own axis) and an alem (rod, two bulbs, crescent facing alem_az). col = shaft stone/brick,
    top_col = the part above the first balcony (default col). Pieces (meta sub): base, shaft (seg k), balcony
    (seg k), top, cap, alem; each pivots at its own bottom centre. Returns the pieces.
    Styles (defaults = the plain minaret above): base_style "pyramid" = low square plinth + a tall tapering
    many-sided flare (flare x h) from the plinth width to the shaft (Sinan's thick minarets, ep02 west); base_col
    (pedestal + transition), balcony_col (serefe), drum_col (upper drum) override col / top_col (ep02 SE: stone
    pedestal, brick shaft, white balcony and drum)."""
    r = d / 2.0
    bw = base_w or d * 1.4
    bh = base_h or 0.1 * h
    cap_h = cap_h or 0.15 * h
    top_col = top_col or col
    m0 = {"x": x, "y": y}
    m0.update(meta or {})
    out = []
    poly_rev = lambda mb, prof, cc, steps=n_shaft: mb.revolve(prof, math.radians(11.25), math.radians(11.25) + 2 * math.pi,
                                                            steps, center=(x, y, 0), col=cc, full=True)
    bcol = base_col or col
    # pedestal + transition (square -> polygon)
    mb = MB()
    mb.box(x - bw / 2, x + bw / 2, y - bw / 2, y + bw / 2, z, z + bh, bcol)
    mb.island()
    if base_style == "pyramid":
        fh = flare * h
        poly_rev(mb, [(0.0, z + bh), (bw / 2 * 0.97, z + bh), (r * 1.12, z + bh + fh), (r * 1.12, z + bh + fh + 0.45),
                      (0.0, z + bh + fh + 0.45)], bcol, n_shaft)
        zc = z + bh + fh + 0.45
    else:
        poly_rev(mb, [(0.0, z + bh), (bw / 2 * 1.05, z + bh), (r * 1.15, z + bh + 0.05 * h), (r * 1.15, z + bh + 0.065 * h),
                      (0.0, z + bh + 0.065 * h)], bcol, 8)
        zc = z + bh + 0.065 * h
    out.append(pk.finish(mb, pk._pname(part), part, pivot=(x, y, z), bevel=0.04, meta=dict(m0, sub="base")))
    rc = r
    z_cone = z + h - cap_h
    for k, f in enumerate(list(balconies) + [None]):
        zb = (z + f * h) if f is not None else z_cone - 0.07 * h
        r1 = rc * (0.96 if f is not None else 0.97)
        cc = col if k == 0 else top_col
        mb = MB()
        poly_rev(mb, [(0.0, zc), (rc, zc), (r1, zb), (0.0, zb)], cc)
        out.append(pk.finish(mb, pk._pname(part), part, pivot=(x, y, zc), bevel=0.0, meta=dict(m0, sub="shaft", seg=k)))
        if f is None:
            zc, rc = zb, r1
            break
        # serefe: 4 corbel steps out to the floor, floor slab, parapet
        mb = MB()
        rb = r1 + 0.95
        prof = [(0.0, zb)]
        for j in range(4):
            rr = r1 + (rb - r1) * (j + 1) / 4
            prof += [(r1 + (rb - r1) * j / 4 + 0.02, zb + 0.3 * j), (rr, zb + 0.3 * j + 0.22)]
        prof += [(rb, zb + 1.25), (0.0, zb + 1.25)]
        poly_rev(mb, prof, balcony_col or top_col)
        mb.island()
        poly_rev(mb, [(rb - 0.12, zb + 1.25), (rb, zb + 1.25), (rb, zb + 2.2), (rb - 0.12, zb + 2.2)], balcony_col or top_col,
                 n_shaft * 2)
        out.append(pk.finish(mb, pk._pname(part), part, pivot=(x, y, zb), bevel=0.02, meta=dict(m0, sub="balcony", seg=k)))
        zc, rc = zb + 1.25, r1 * 0.93
    # top drum + cornice, cone, alem
    mb = MB()
    poly_rev(mb, [(0.0, zc), (rc, zc), (rc, z_cone - 0.35), (rc * 1.12, z_cone - 0.2), (rc * 1.12, z_cone), (0.0, z_cone)],
             drum_col or top_col)
    out.append(pk.finish(mb, pk._pname(part), part, pivot=(x, y, zc), bevel=0.02, meta=dict(m0, sub="top")))
    mb = MB()
    rcap = rc * 1.08
    mb.revolve([(0.0, z_cone), (rcap, z_cone), (rcap * 0.93, z_cone + 0.12 * cap_h), (0.0, z + h)], 0, 2 * math.pi, 32,
               center=(x, y, 0), col=cap_col, full=True)
    ob = pk.finish(mb, pk._pname(part), part, pivot=(x, y, z_cone), bevel=0.0, meta=dict(m0, sub="cap"))
    dome_props(ob, (x, y, z_cone), cap_h, sheets=18)
    out.append(ob)
    mb = MB()
    za = z + h - 0.4
    mb.cylinder(x, y, za, za + 2.3, 0.07, 0.05, col=alem_col, n=8)
    for zz, rr in ((za + 0.55, 0.26), (za + 1.15, 0.2)):
        mb.island()
        mb.revolve([(0.0, zz - rr)] + [(rr * math.sin(math.pi * j / 6), zz - rr * math.cos(math.pi * j / 6)) for j in range(1, 6)]
                   + [(0.0, zz + rr)], 0, 2 * math.pi, 12, center=(x, y, 0), col=alem_col, full=True)
    a = math.radians(alem_az)
    t = Vector((math.cos(a), math.sin(a), 0.0))                  # the crescent's plane faces alem_az
    nrm = Vector((-math.sin(a), math.cos(a), 0.0))
    cc_ = Vector((x, y, za + 1.95))
    pts = [cc_ + nrm * (0.42 * math.cos(math.radians(th))) + Vector((0, 0, 0.42 * math.sin(math.radians(th))))
           for th in range(-150, 151, 15)]
    rad = [0.035 + 0.075 * math.cos(math.radians(th) / 2.2) for th in range(-150, 151, 15)]
    tube(mb, pts, rad, t, alem_col, sides=6)
    out.append(pk.finish(mb, pk._pname(part), part, pivot=(x, y, za), bevel=0.0, meta=dict(m0, sub="alem")))
    return out


def turret_real(part, x, y, z, h, r, col="render_rose", dome_col="lead", n=16, slits=2, slit_col="window_grille",
                meta=None):
    """Small round stair turret with a lead dome (ep02 east / west ends): n-sided drum r, z..z+h, a moulded cornice,
    `slits` small arched-top window slits facing out (4 cm proud, slit_col) and a hemispherical lead dome (own
    seam centre) with a short finial. One piece (pivot = foot centre). Returns [piece]."""
    mb = MB()
    mb.revolve([(0.0, z), (r, z), (r, z + h - 0.5), (r + 0.22, z + h - 0.3), (r + 0.22, z + h), (0.0, z + h)],
               0.0, 2 * math.pi, n, center=(x, y, 0), col=col, full=True)
    out_a = math.atan2(y, x)
    for k in range(slits):
        a = out_a + (k - (slits - 1) / 2.0) * (2 * math.pi / 5.0)
        ca, sa = math.cos(a), math.sin(a)
        zs = z + h * 0.35 + (h * 0.3 if slits > 2 and k % 2 else 0.0)
        hw, ht = 0.28, min(1.5, h * 0.28)
        p = lambda t, zz, o: (x + ca * (r + o) - sa * t, y + sa * (r + o) + ca * t, zz)
        mb.island()
        fr = [p(-hw, zs, 0.04), p(hw, zs, 0.04), p(hw, zs + ht, 0.04), p(-hw, zs + ht, 0.04)]
        bk = [p(-hw, zs, -0.1), p(hw, zs, -0.1), p(hw, zs + ht, -0.1), p(-hw, zs + ht, -0.1)]
        mb.face(fr, slit_col); mb.face(list(reversed(bk)), slit_col)
        for i in range(4):
            j = (i + 1) % 4
            mb.face([fr[i], bk[i], bk[j], fr[j]], col)
    zd = z + h
    rd = r + 0.05
    prof = [(0.0, zd)] + [(rd * math.cos(math.radians(e)), zd + rd * math.sin(math.radians(e))) for e in range(0, 91, 10)]
    mb.island()
    mb.revolve(prof, 0.0, 2 * math.pi, 24, center=(x, y, 0), col=dome_col, full=True)
    mb.island()
    mb.cylinder(x, y, zd + rd - 0.1, zd + rd + 0.9, 0.06, 0.04, col="bronze_gold", n=6)
    ob = pk.finish(mb, pk._pname(part), part, pivot=(x, y, z), bevel=0.03, meta=dict(meta or {}, sub="turret"))
    dome_props(ob, (x, y, zd), rd, sheets=16)
    return [ob]


def _octagon(cx, cy, w, z, rot=22.5):
    """8 corners of a regular octagon, `w` across the flats, at height z (flat faces on the axes for rot 22.5)."""
    R = w / 2.0 / math.cos(math.radians(22.5))
    return [(cx + R * math.cos(math.radians(rot + 45 * k)), cy + R * math.sin(math.radians(rot + 45 * k)), z)
            for k in range(8)]


def turbe(part, x, y, z, w, h, dome_d, drum_h=2.2, col="ashlar_grey", trim_col="ashlar_light", roof_col="roof_lead",
          dome_col="lead", win_col="bronze_dark", eave=0.0, rows=2, meta=None):
    """Ottoman octagonal domed mausoleum (türbe, ep02 setting): octagonal ashlar body (`w` across the flats, z..z+h)
    with `rows` rows of two grilled windows per face (dark panels 4 cm proud with light frames), a projecting cornice,
    an octagonal drum (drum_h) and a lead dome dome_d across, finial on top; optional `eave` metres of a lean-to
    lead portico roof round the body at 0.45 h (the larger türbes). Pieces: body, dome (meta sub). Returns pieces."""
    out = []
    m0 = dict(meta or {})
    mb = MB()
    mb.island()
    bot, top = _octagon(x, y, w, z), _octagon(x, y, w, z + h)
    mb.face(list(reversed(bot)), col); mb.face(top, roof_col)
    for i in range(8):
        j = (i + 1) % 8
        mb.face([bot[i], bot[j], top[j], top[i]], col)
    # cornice
    mb.island()
    c0, c1 = _octagon(x, y, w + 0.7, z + h - 0.7), _octagon(x, y, w + 0.7, z + h + 0.05)
    mb.face(list(reversed(c0)), trim_col); mb.face(c1, roof_col)
    for i in range(8):
        j = (i + 1) % 8
        mb.face([c0[i], c0[j], c1[j], c1[i]], trim_col)
    # windows: per face, `rows` x 2 grilled panels with frames
    side = 2 * (w / 2.0) * math.tan(math.radians(22.5))
    for i in range(8):
        a = math.radians(45 * i)
        nx, ny = math.cos(a), math.sin(a)
        tx, ty = -ny, nx
        for rr in range(rows):
            zs = z + h * (0.16 + 0.42 * rr)
            ht = h * 0.24
            for t in (-side * 0.22, side * 0.22):
                hw = min(side * 0.13, 0.75)
                for (o, e, cc) in ((0.05, 0.22, trim_col), (0.09, 0.0, win_col)):
                    p = lambda u, zz: (x + nx * (w / 2.0 + o) + tx * (t + u), y + ny * (w / 2.0 + o) + ty * (t + u), zz)
                    mb.island()
                    q = [p(-hw - e, zs - e), p(hw + e, zs - e), p(hw + e, zs + ht + e), p(-hw - e, zs + ht + e)]
                    qb = [(q[k][0] - nx * (o + 0.03), q[k][1] - ny * (o + 0.03), q[k][2]) for k in range(4)]
                    mb.face(q, cc); mb.face(list(reversed(qb)), cc)
                    for k in range(4):
                        l = (k + 1) % 4
                        mb.face([q[k], qb[k], qb[l], q[l]], cc)
    if eave > 0:
        ze = z + h * 0.45
        mb.island()
        i0, o0 = _octagon(x, y, w + 0.06, ze), _octagon(x, y, w + 2 * eave, ze - 1.1)
        i1, o1 = _octagon(x, y, w + 0.06, ze + 0.25), _octagon(x, y, w + 2 * eave, ze - 0.85)
        for i in range(8):
            j = (i + 1) % 8
            mb.face([i1[i], i1[j], o1[j], o1[i]], roof_col)
            mb.face([i0[j], i0[i], o0[i], o0[j]], trim_col)
            mb.face([o0[i], o0[j], o1[j], o1[i]], trim_col)
    out.append(pk.finish(mb, pk._pname(part), part, pivot=(x, y, z), bevel=0.03, meta=dict(m0, sub="body")))
    # drum + dome
    mb = MB()
    zd = z + h + 0.05
    wd = dome_d * 1.04
    mb.island()
    b2, t2 = _octagon(x, y, wd, zd), _octagon(x, y, wd, zd + drum_h)
    mb.face(list(reversed(b2)), col); mb.face(t2, roof_col)
    for i in range(8):
        j = (i + 1) % 8
        mb.face([b2[i], b2[j], t2[j], t2[i]], col)
    rd = dome_d / 2.0
    z0 = zd + drum_h + 0.02
    prof = [(0.0, z0)] + [(rd * math.cos(math.radians(e)), z0 + rd * 0.92 * math.sin(math.radians(e))) for e in range(0, 91, 6)]
    mb.island()
    mb.revolve(prof, 0.0, 2 * math.pi, 32, center=(x, y, 0), col=dome_col, full=True)
    mb.island()
    mb.cylinder(x, y, z0 + rd * 0.92 - 0.1, z0 + rd * 0.92 + 1.6, 0.09, 0.05, col="bronze_gold", n=8)
    ob = pk.finish(mb, pk._pname(part), part, pivot=(x, y, zd), bevel=0.03, meta=dict(m0, sub="dome"))
    dome_props(ob, (x, y, z0), rd, sheets=max(16, round(2 * math.pi * rd / 0.95)))
    out.append(ob)
    return out


def sadirvan(part, x, y, z, w=9.0, h=7.5, col="ashlar_light", roof_col="roof_lead", dome_col="lead",
             grille_col="bronze_dark", meta=None):
    """Ottoman octagonal ablution fountain (şadırvan, ep02 setting): octagonal marble basin with a grilled screen,
    8 slender columns, a wide octagonal lead eave roof (`w` across its flats) and a small lead cupola. One piece."""
    mb = MB()
    wb = w * 0.55
    mb.island()
    b, t = _octagon(x, y, wb, z), _octagon(x, y, wb, z + 1.0)
    mb.face(list(reversed(b)), col); mb.face(t, col)
    for i in range(8):
        j = (i + 1) % 8
        mb.face([b[i], b[j], t[j], t[i]], col)
    mb.island()                                   # grilled screen (dark) above the basin
    b, t = _octagon(x, y, wb * 0.92, z + 1.0), _octagon(x, y, wb * 0.92, z + 2.6)
    mb.face(list(reversed(b)), grille_col); mb.face(t, col)
    for i in range(8):
        j = (i + 1) % 8
        mb.face([b[i], b[j], t[j], t[i]], grille_col)
    zc = z + h * 0.62
    R = w * 0.38 / math.cos(math.radians(22.5))
    for k in range(8):
        a = math.radians(22.5 + 45 * k)
        mb.cylinder(x + R * math.cos(a), y + R * math.sin(a), z, zc, 0.22, 0.2, col=col, n=8)
    mb.island()                                   # eave roof: sloped octagonal ring + soffit
    i1, o1 = _octagon(x, y, w * 0.34, z + h * 0.82), _octagon(x, y, w, zc + 0.3)
    o0, i0 = _octagon(x, y, w, zc), _octagon(x, y, w * 0.34, zc + 0.6)
    for i in range(8):
        j = (i + 1) % 8
        mb.face([o1[i], o1[j], i1[j], i1[i]], roof_col)
        mb.face([o0[j], o0[i], i0[i], i0[j]], col)
        mb.face([o0[i], o0[j], o1[j], o1[i]], col)
        mb.face([i0[j], i0[i], i1[i], i1[j]], col)
    rd = w * 0.17
    z0 = z + h * 0.82
    prof = [(0.0, z0)] + [(rd * math.cos(math.radians(e)), z0 + rd * math.sin(math.radians(e))) for e in range(0, 91, 10)]
    mb.island()
    mb.revolve(prof, 0.0, 2 * math.pi, 24, center=(x, y, 0), col=dome_col, full=True)
    ob = pk.finish(mb, pk._pname(part), part, pivot=(x, y, z), bevel=0.02, meta=dict(meta or {}, sub="sadirvan"))
    dome_props(ob, (x, y, z0), rd, sheets=16)
    return [ob]


# ============================================================================= setting (per-episode "setting" block)
def _box_obj(name, w, d, h, col, recipe, loc, rot_z=0.0, top_col=None):
    """axis-aligned box in its own object space (base centre = origin), then placed + rotated."""
    mb = pk.MB()
    mb.box(-w / 2, w / 2, -d / 2, d / 2, 0.0, h, col, top_col=top_col)
    ob = pk.finish(mb, name, "_setting", pivot=(0, 0, 0), bevel=0.0, meta={"recipe": recipe})
    ob.location = loc; ob.rotation_euler = (0, 0, rot_z)
    ob["pk_rest"] = tuple(loc)
    return ob


def build_setting(cfg):
    """Calm surroundings so the model does not stand in a void. cfg (episode JSON "setting"):
      ground:   {"variation": 0.12}                          large-scale paving variation (0 = plain)
      props:    [{"type": "bollards", "path": [[x,y],...], "spacing": 4.2, "h": 0.95, "d": 0.34},
                 {"type": "fountain_obelisk", "pos": [x,y], "obelisk_h": 6.3, "basin_r": 5.2}]
      backdrop: {"type": "city_ring", "r0": 165, "r1": 240, "count": 64, "h": [13, 26], "w": [14, 34],
                 "seed": 7, "colors": ["#hex", ...], "roof": "#hex", "gaps": [[az0, az1], ...]}
    Everything lands in collection part:_setting (not a part: never animated/selected/anchored).
    Distant pieces blend into the haze colour by camera distance (LOOK city_near/city_far/city_haze0/1)."""
    import random as _r
    n = 0
    g = cfg.get("ground", {})
    if g.get("variation"):
        LOOK["ground_var"] = g["variation"]
    extra = {}
    for nm, hx in (("facade_ochre", "#C89A63"), ("facade_terra", "#B7694B"), ("facade_yellow", "#D2B071"),
                   ("facade_pale", "#D8C6A6"), ("facade_rose", "#C58B72"), ("roof_tile", "#8E5642"),
                   ("setting_stone", "#CFC6B3"), ("setting_water", "#7E8C8C")):
        extra[nm] = hx
    for nm, hx in (cfg.get("colors_extra") or {}).items():
        extra[nm] = hx
    pk.set_palette({k: v for k, v in extra.items() if k not in pk._PAL})
    Z = GROUND_Z
    for pr in cfg.get("props", []):
        if pr["type"] == "bollards":
            sp, h, d = pr.get("spacing", 4.2), pr.get("h", 0.95), pr.get("d", 0.34)
            pts = pr["path"]
            for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
                L = math.hypot(xb - xa, yb - ya); m = max(1, int(L // sp))
                for i in range(m + 1):
                    x, y = xa + (xb - xa) * i / m, ya + (yb - ya) * i / m
                    mb = pk.MB()
                    mb.cylinder(x, y, Z, Z + h, d / 2, d / 2 * 0.8, col="setting_stone", n=10)
                    pk.finish(mb, "_bollard.%03d" % n, "_setting", pivot=(x, y, Z), bevel=0.0, meta={"recipe": "setting"})
                    n += 1
        elif pr["type"] == "fountain_obelisk":
            x, y = pr["pos"]; br = pr.get("basin_r", 5.2); oh = pr.get("obelisk_h", 6.3)
            mb = pk.MB()
            mb.cylinder(x, y, Z, Z + 0.45, br + 0.9, br + 0.9, col="setting_stone", n=32)          # low step
            mb.island(); mb.cylinder(x, y, Z + 0.45, Z + 1.35, br, br, col="setting_stone", n=32)  # basin rim
            mb.island(); mb.cylinder(x, y, Z + 1.36, Z + 1.2 + 0.2, br - 0.35, br - 0.35, col="setting_water", n=32)
            mb.island(); mb.cylinder(x, y, Z + 1.35, Z + 3.4, 1.5, 1.1, col="setting_stone", n=16)  # pedestal
            mb.island(); mb.box(x - 1.3, x + 1.3, y - 1.3, y + 1.3, Z + 3.4, Z + 5.6, "setting_stone")
            z0 = Z + 5.6
            w0, w1 = 0.72, 0.52
            mb.island()
            q0 = [(x - w0, y - w0, z0), (x + w0, y - w0, z0), (x + w0, y + w0, z0), (x - w0, y + w0, z0)]
            q1 = [(x - w1, y - w1, z0 + oh), (x + w1, y - w1, z0 + oh), (x + w1, y + w1, z0 + oh), (x - w1, y + w1, z0 + oh)]
            for i in range(4):
                j = (i + 1) % 4
                mb.face([q0[i], q0[j], q1[j], q1[i]], "setting_stone")
            mb.face(list(reversed(q0)), "setting_stone")
            apex = (x, y, z0 + oh + 1.0)
            for i in range(4):
                j = (i + 1) % 4
                mb.face([q1[i], q1[j], apex], "setting_stone")
            pk.finish(mb, "_fountain", "_setting", pivot=(x, y, Z), bevel=0.0, meta={"recipe": "setting"})
            n += 1
        elif pr["type"] == "fountain":     # round basin with a two-tier centre bowl, no obelisk
            x, y = pr["pos"]; br = pr.get("basin_r", 6.0)
            mb = pk.MB()
            mb.cylinder(x, y, Z, Z + 0.3, br + 1.2, br + 1.2, col="setting_stone", n=40)
            mb.island(); mb.cylinder(x, y, Z + 0.3, Z + 1.0, br, br, col="setting_stone", n=40)
            mb.island(); mb.cylinder(x, y, Z + 1.01, Z + 0.85, br - 0.3, br - 0.3, col="setting_water", n=40)
            mb.island(); mb.cylinder(x, y, Z + 0.85, Z + 2.2, 0.7, 0.55, col="setting_stone", n=16)
            mb.island(); mb.cylinder(x, y, Z + 2.2, Z + 2.6, 2.2, 2.4, col="setting_stone", n=24)
            mb.island(); mb.cylinder(x, y, Z + 2.6, Z + 3.5, 0.35, 0.3, col="setting_stone", n=12)
            mb.island(); mb.cylinder(x, y, Z + 3.5, Z + 3.8, 1.1, 1.2, col="setting_stone", n=16)
            pk.finish(mb, "_fountain.%03d" % n, "_setting", pivot=(x, y, Z), bevel=0.0, meta={"recipe": "setting"})
            n += 1
    bd = cfg.get("backdrop") or {}
    if bd.get("type") == "city_ring":
        rnd = _r.Random(bd.get("seed", 7))
        r0, r1 = bd.get("r0", 165.0), bd.get("r1", 240.0)
        h0, h1 = bd.get("h", [13.0, 26.0]); w0, w1 = bd.get("w", [14.0, 34.0])
        cols = bd.get("colors", ["facade_ochre", "facade_terra", "facade_yellow", "facade_pale", "facade_rose"])
        cnt = bd.get("count", 64)
        gaps = bd.get("gaps", [])
        for i in range(cnt):
            az = 360.0 * (i + rnd.uniform(-0.3, 0.3)) / cnt
            if any(a0 <= az % 360 <= a1 for a0, a1 in gaps):
                continue
            for row in range(bd.get("rows", 2)):
                r = r0 + (r1 - r0) * (row + rnd.uniform(0.0, 0.6)) / max(bd.get("rows", 2), 1)
                a = math.radians(az + rnd.uniform(-2.0, 2.0))
                w, d, h = rnd.uniform(w0, w1), rnd.uniform(12, 20), rnd.uniform(h0, h1) * (1.0 + 0.25 * row)
                loc = (r * math.cos(a), r * math.sin(a), Z)
                rot = a + math.pi / 2
                col = cols[rnd.randrange(len(cols))]
                _box_obj("_bld.%03d" % n, w, d, h, col, "facade", loc, rot)
                roof = pk.MB()   # low hipped roof (terracotta)
                hr = rnd.uniform(1.6, 3.0)
                c4 = [(-w / 2 - 0.4, -d / 2 - 0.4, h), (w / 2 + 0.4, -d / 2 - 0.4, h), (w / 2 + 0.4, d / 2 + 0.4, h), (-w / 2 - 0.4, d / 2 + 0.4, h)]
                rg = [(-w / 2 + d / 2, 0, h + hr), (w / 2 - d / 2, 0, h + hr)] if w > d else [(0, 0, h + hr), (0, 0, h + hr)]
                roof.face([c4[0], c4[1], rg[1], rg[0]], "roof_tile"); roof.face([c4[1], c4[2], rg[1]], "roof_tile")
                roof.face([c4[2], c4[3], rg[0], rg[1]], "roof_tile"); roof.face([c4[3], c4[0], rg[0]], "roof_tile")
                roof.face(list(reversed(c4)), "roof_tile")
                ob = pk.finish(roof, "_roof.%03d" % n, "_setting", pivot=(0, 0, 0), bevel=0.0, meta={"recipe": "facade"})
                ob.location = loc; ob.rotation_euler = (0, 0, rot)
                if rnd.random() < bd.get("tower_p", 0.06):      # an occasional bell tower / dome for skyline rhythm
                    tw = rnd.uniform(5, 7)
                    _box_obj("_tower.%03d" % n, tw, tw, h + rnd.uniform(10, 16), col, "facade", loc, rot)
                n += 1
    for o in pk.PARTS.pop("_setting", []):
        o.visible_shadow = cfg.get("shadows", True) and not o.name.startswith(("_bld", "_roof", "_tower"))
    print("[realkit] setting: %d props/buildings" % n)
    return n


# ============================================================================= photogrammetry scan (per-episode "scan" block)
def _agx_inverse_lut(n=32):
    """[(t, x)]: display value t (sRGB-encoded, what 'Standard' would show) -> scene-linear x such that the scene's
    view transform (AgX + look + exposure) displays x as t. Neutral axis, computed with Blender's own OCIO config."""
    sc = bpy.context.scene
    try:
        import PyOpenColorIO as OCIO
        cfg = OCIO.GetCurrentConfig()
        # the film's transform = what post_render_setup will set (LOOK), not the factory scene at load time
        dvt = OCIO.DisplayViewTransform(src=OCIO.ROLE_SCENE_LINEAR, display=cfg.getDefaultDisplay(), view="AgX")
        pipe = OCIO.LegacyViewingPipeline(); pipe.setDisplayViewTransform(dvt)
        look = LOOK.get("look", "None")
        if look and look != "None":
            pipe.setLooksOverrideEnabled(True); pipe.setLooksOverride(look)
        proc = pipe.getProcessor(cfg).getDefaultCPUProcessor()
        ex = 2.0 ** LOOK.get("exposure", 0.0)
        xs = [1e-4 * (2.0 ** (k / 8.0)) for k in range(0, 8 * 21)]           # 1e-4 .. ~200
        ys = [proc.applyRGB([x * ex] * 3)[1] for x in xs]
    except Exception as e:
        print("[realkit] OCIO LUT failed (%s): gamma fallback" % e)
        return [(k / (n - 1), (k / (n - 1)) ** 2.2 * 1.8) for k in range(n)]
    lut = []
    for k in range(n):
        t = k / (n - 1)
        t = min(max(t, ys[0]), ys[-1])
        j = next((i for i in range(1, len(ys)) if ys[i] >= t), len(ys) - 1)
        y0, y1 = ys[j - 1], ys[j]
        f = (t - y0) / max(y1 - y0, 1e-9)
        lut.append((k / (n - 1), xs[j - 1] + (xs[j] - xs[j - 1]) * f))
    return lut


def _scan_material(mat, emission=0.78, principled=0.22, roughness=0.8, lut=None, sat=1.08, back_hex="#A79C8A"):
    """Photographic scan texture under the film's view transform: the texture is read as raw display values
    (Non-Color) and pushed through the inverse-AgX LUT, so AgX shows it as 'Standard' would (one film, one
    transform). Back faces (outside of a scan shell) render as plain lime concrete lit by our sun."""
    nt = mat.node_tree
    img = next((n.image for n in nt.nodes if n.type == "TEX_IMAGE" and n.image), None)
    nt.nodes.clear()
    nb = NB(nt)
    tex = nb.node('ShaderNodeTexImage'); tex.image = img; tex.interpolation = 'Linear'
    if img is not None:
        img.colorspace_settings.name = 'Non-Color'
    sepn = nb.node('ShaderNodeSeparateColor'); nb.L.new(tex.outputs['Color'], sepn.inputs[0])
    chans = []
    for i in range(3):
        cr = nb.node('ShaderNodeValToRGB')
        el = cr.color_ramp.elements
        el[0].position = lut[0][0]; el[0].color = (lut[0][1],) * 3 + (1,)
        el[1].position = lut[-1][0]; el[1].color = (lut[-1][1],) * 3 + (1,)
        for t, x in lut[1:-1]:
            e = el.new(t); e.color = (x, x, x, 1)
        cr.color_ramp.interpolation = 'LINEAR'
        nb.L.new(sepn.outputs[i], cr.inputs['Fac'])
        chans.append(cr.outputs['Color'])
    comb = nb.node('ShaderNodeCombineColor')
    for i in range(3):
        sp = nb.node('ShaderNodeSeparateColor'); nb.L.new(chans[i], sp.inputs[0])
        nb.L.new(sp.outputs[0], comb.inputs[i])
    col = comb.outputs[0]
    if abs(sat - 1.0) > 1e-3:
        hs = nb.node('ShaderNodeHueSaturation'); hs.inputs['Saturation'].default_value = sat
        nb.L.new(col, hs.inputs['Color']); col = hs.outputs[0]
    em = nb.node('ShaderNodeEmission'); nb.L.new(col, em.inputs['Color']); em.inputs['Strength'].default_value = 1.0
    gam = nb.node('ShaderNodeGamma'); nb.L.new(tex.outputs['Color'], gam.inputs['Color']); gam.inputs['Gamma'].default_value = 2.2
    pb = nb.node('ShaderNodeBsdfPrincipled'); pb.inputs['Roughness'].default_value = roughness
    nb.L.new(gam.outputs[0], pb.inputs['Base Color'])
    mix = nb.node('ShaderNodeMixShader'); mix.inputs[0].default_value = principled / max(emission + principled, 1e-6)
    nb.L.new(em.outputs[0], mix.inputs[1]); nb.L.new(pb.outputs[0], mix.inputs[2])
    back = nb.node('ShaderNodeBsdfPrincipled'); back.inputs['Roughness'].default_value = 0.9
    back.inputs['Base Color'].default_value = (*_lin(back_hex), 1)
    geo = nb.node('ShaderNodeNewGeometry')
    mb_ = nb.node('ShaderNodeMixShader')
    nb.L.new(geo.outputs['Backfacing'], mb_.inputs[0]); nb.L.new(mix.outputs[0], mb_.inputs[1]); nb.L.new(back.outputs[0], mb_.inputs[2])
    out = nb.node('ShaderNodeOutputMaterial'); nb.L.new(mb_.outputs[0], out.inputs['Surface'])
    mat.use_backface_culling = False
    return mat


def _split_mesh(o, cls, names, coll):
    """split object o by per-face class ids (numpy array) into new objects names[c] (empty classes skipped)."""
    import bmesh, numpy as np
    out = {}
    for c, nm in enumerate(names):
        keep = np.nonzero(cls == c)[0]
        if len(keep) == 0:
            continue
        me = o.data.copy()
        bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
        dead_idx = np.nonzero(cls != c)[0]
        dead = [bm.faces[i] for i in dead_idx.tolist()]
        if dead:
            bmesh.ops.delete(bm, geom=dead, context='FACES')
        bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new(nm, me); ob.matrix_world = o.matrix_world.copy()
        coll.objects.link(ob)
        out[nm] = ob
    return out


def load_scan(cfg):
    """episode "scan": {"blend", "collection", "tex": 2048, "z_split": 21.9, "split_x": true, "floor_z": 0.6,
    "shading": {emission, principled, roughness}, "sat": 1.08, "back_hex": "#A79C8A",
    "sun_link": true, "volumetric": {samples, tile, end}}
    Appends the prepped scan (import_scan.py prep), converts its textures for the film's view transform, splits it
    into parts the kit can animate: scan_dome (above z_split), scan_wall, scan_floor, each with meta side R/L
    (x sign) so exploded-view selectors / groups treat it like any built part."""
    import numpy as np
    import config
    blend = config.resolve(cfg["blend"], base=os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists(blend):
        raise FileNotFoundError("scan blend not found: %s (set ARCH_KIT_MODELS or run import_scan.py prep; "
                                "see the episode's assets.md)" % blend)
    cname = cfg.get("collection", "pantheon_interior_scan")
    bpy.ops.wm.append(directory=blend + "/Collection/", filename=cname)
    coll = bpy.data.collections[cname]
    tex = int(cfg.get("tex", 2048))
    for img in bpy.data.images:
        if img.size[0] > tex:
            img.scale(tex, tex)
    lut = _agx_inverse_lut()
    print("[realkit] scan LUT (display->linear) %s" % ", ".join("%.2f:%.3f" % tx for tx in lut[::6]))
    sh = cfg.get("shading", {})
    done = set()
    src = [o for o in coll.objects if o.type == 'MESH' and o.name.startswith(cfg.get("prefix", "scan_interior"))]
    for o in src:
        for m in o.data.materials:
            if m and m.name not in done:
                _scan_material(m, sh.get("emission", 0.78), sh.get("principled", 0.22), sh.get("roughness", 0.8),
                               lut, cfg.get("sat", 1.08), cfg.get("back_hex", "#A79C8A"))
                done.add(m.name)
    zs, fz, rmax = cfg.get("z_split", 21.9), cfg.get("floor_z", 0.6), cfg.get("floor_r", 21.0)
    split_x = cfg.get("split_x", True)
    kinds = ["scan_dome", "scan_wall", "scan_floor"]
    for o in src:
        me = o.data; n = len(me.polygons)
        cen = np.empty(n * 3, np.float32); me.polygons.foreach_get("center", cen); cen = cen.reshape(-1, 3)
        M = np.array(o.matrix_world)
        w = cen @ M[:3, :3].T + M[:3, 3]
        kind = np.where(w[:, 2] > zs, 0, np.where((w[:, 2] < fz) & (np.hypot(w[:, 0], w[:, 1]) < rmax), 2, 1))
        side = (w[:, 0] < 0).astype(np.int32) if split_x else np.zeros(n, np.int32)
        cls = kind * 2 + side
        names = ["%s_%s_%s" % (o.name, k, s_) for k in kinds for s_ in ("R", "L")]
        parts = _split_mesh(o, cls, names, coll)
        for nm, ob in parts.items():
            k = next(k for k in kinds if "_" + k + "_" in nm)
            ob["pk_part"] = k; ob["side"] = nm[-1]; ob["pk_rest"] = (0.0, 0.0, 0.0); ob["role"] = k
            pk.PARTS.setdefault(k, []).append(ob)
        me_old = o.data
        bpy.data.objects.remove(o); bpy.data.meshes.remove(me_old)
    sun = bpy.data.objects.get("scan_sun")
    if sun and cfg.get("sun_link", True):
        try:
            sun.light_linking.receiver_collection = coll
            sun.light_linking.blocker_collection = coll
        except Exception as ex:
            print("[realkit] light linking:", ex)
    vol = bpy.data.objects.get("scan_volume")
    if vol:
        pk.PARTS.setdefault("scan_volume", []).append(vol); vol["pk_part"] = "scan_volume"
    ee = bpy.context.scene.eevee
    for k, v in dict(volumetric_tile_size=str(cfg.get("volumetric", {}).get("tile", 8)),
                     volumetric_samples=cfg.get("volumetric", {}).get("samples", 32),
                     use_volumetric_shadows=True, volumetric_shadow_samples=12,
                     volumetric_end=cfg.get("volumetric", {}).get("end", 300.0)).items():
        try:
            setattr(ee, k, v)
        except Exception as ex:
            print("[realkit] eevee", k, ex)
    st = {k: len(pk.PARTS.get(k, [])) for k in kinds}
    print("[realkit] scan loaded: %s faces %d" % (st, sum(len(o.data.polygons) for k in kinds for o in pk.PARTS.get(k, []))))
    return st


def kill_inner_faces(objs, pred):
    """delete faces of objs where pred(world_centre, world_normal) (e.g. our drum's inner skin where the scan's
    walls/niches sit behind it)."""
    import bmesh
    n = 0
    for o in objs:
        me = o.data
        if me.users > 1:
            o.data = me = me.copy()
        bm = bmesh.new(); bm.from_mesh(me)
        M = o.matrix_world; N = M.to_3x3().inverted().transposed()
        dead = [f for f in bm.faces if pred(M @ f.calc_center_median(), (N @ f.normal).normalized())]
        if dead:
            bmesh.ops.delete(bm, geom=dead, context='FACES'); n += len(dead)
        bm.to_mesh(me); bm.free()
    return n
