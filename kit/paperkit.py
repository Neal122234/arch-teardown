"""paperkit.py - parametric PAPER-ARCHITECTURE kit for Blender 5.x (EEVEE), driven from Python.

Import inside Blender (run_episode.py does this for you):

    import sys; sys.path.insert(0, KIT_DIR); import paperkit as pk
    pk.new_scene(); pk.set_palette({...}); ... components ...; pk.rise(...); pk.render_stills(...)

Design rules (keep them, they are what makes episodes consistent):
  * ONE shader for every paper piece. Colour lives on the mesh (face attribute "paper_col"),
    darker edge lines live on the mesh (face attribute "paper_edge" = bevel chamfers / card rims),
    per-piece tint variation comes from Object Info > Random. So a new building = new palette
    entries + geometry, never new shaders.
  * Every visible element is a separate "paper piece" object whose ORIGIN is its base/hinge,
    so the animation presets only touch transforms (cheap: no modifier re-evaluation per frame).
  * Section cut = shader clip against the empty "PK_SectionPlane" (+ back faces drawn as flat
    poche colour), so cutting 600 pieces costs nothing.
  * Units = metres at real building scale.  Time in the API = seconds.
"""
import bpy, bmesh, math, json, os, time, random
from mathutils import Vector, Matrix, Quaternion

FPS = 24
RES = (1080, 1920)
PARTS = {}            # part name -> [objects]  (creation order)
_PAL_NAMES = []       # palette index -> name
_PAL = {}             # name -> linear RGB
_MAT = {}
POCHE = "#9C4A3E"     # section-cut fill colour (classic architectural red)
POCHE_BANDS = None    # optional [[z_m, "#hex"], ...]: section fill by world height (e.g. aggregate layers)
STYLE = "paper"       # "paper" (one paper shader) | "real" (realkit.py: procedural PBR per material recipe)
REAL_BEVEL = 0.6      # style real: bevel widths are scaled by this (crisper stone arrises)
REAL_GAP = 0.004      # style real: gap between revolve segments (paper: 3 cm visible card joints)


# ----------------------------------------------------------------------------- utils
def hex2lin(h):
    h = h.lstrip('#')
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


def set_palette(d):
    """d: {name: '#rrggbb'}  (paper colours by MATERIAL, e.g. brick, travertine, granite_grey)."""
    for k, v in d.items():
        if k not in _PAL:
            _PAL_NAMES.append(k)
        _PAL[k] = hex2lin(v)


def _pidx(name):
    if name not in _PAL:
        raise KeyError("colour '%s' not in palette (%s)" % (name, ", ".join(_PAL_NAMES)))
    return _PAL_NAMES.index(name)


def sec2f(t):
    """seconds -> frame (frame 1 == t 0)."""
    return int(round(t * FPS)) + 1


def _fcurves(ob):
    ad = ob.animation_data
    if not ad or not ad.action:
        return []
    try:
        from bpy_extras.anim_utils import action_get_channelbag_for_slot
        cb = action_get_channelbag_for_slot(ad.action, ad.action_slot)
        return list(cb.fcurves) if cb else []
    except Exception:
        return list(getattr(ad.action, "fcurves", []))


def _key(ob, path, frame, interp=None, easing='AUTO', back=1.7, index=-1):
    ob.keyframe_insert(path, frame=frame, index=index)
    if interp:
        for fc in _fcurves(ob):
            if fc.data_path != path:
                continue
            for kp in fc.keyframe_points:
                if abs(kp.co.x - frame) < 0.01:
                    kp.interpolation = interp
                    if interp == 'BACK':
                        kp.easing = 'EASE_OUT'
                        kp.back = back
                    elif interp in ('SINE', 'QUAD', 'CUBIC', 'EXPO', 'CIRC', 'QUART', 'QUINT'):
                        kp.easing = easing if easing != 'AUTO' else 'EASE_IN_OUT'


# ----------------------------------------------------------------------------- scene
def new_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    PARTS.clear(); _MAT.clear()
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.unit_settings.system = 'METRIC'
    # section plane: parked far away => nothing clipped
    e = bpy.data.objects.new("PK_SectionPlane", None)
    e.empty_display_type = 'PLAIN_AXES'
    e.location = (0, -1e4, 0)
    sc.collection.objects.link(e)
    return sc


def part_collection(part):
    name = "part:" + part
    c = bpy.data.collections.get(name)
    if not c:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


# ----------------------------------------------------------------------------- materials
def _sock(node, ident, out=False):
    for s in (node.outputs if out else node.inputs):
        if s.identifier == ident:
            return s
    raise KeyError(ident)


def paper_material(tint_var=0.07, hue_var=0.012, edge_dark=0.42, fibre=0.06, rough=0.88):
    """The single paper shader. Colour/edge from mesh attributes, clip from PK_SectionPlane."""
    if "paper" in _MAT:
        return _MAT["paper"]
    m = bpy.data.materials.new("PK_paper")
    m.use_nodes = True
    m.surface_render_method = 'DITHERED'
    m.use_transparent_shadow = True
    nt = m.node_tree; N = nt.nodes; L = nt.links
    N.clear()
    def node(t, x, y, **kw):
        n = N.new(t); n.location = (x, y)
        for k, v in kw.items():
            setattr(n, k, v)
        return n
    col = node('ShaderNodeAttribute', -1400, 300, attribute_name="paper_col", attribute_type='GEOMETRY')
    edg = node('ShaderNodeAttribute', -1400, 0, attribute_name="paper_edge", attribute_type='GEOMETRY')
    oi = node('ShaderNodeObjectInfo', -1400, -250)
    # per-piece tint:  hue +-hue_var, value +-tint_var
    hsv = node('ShaderNodeHueSaturation', -900, 300)
    mh = node('ShaderNodeMath', -1150, 150, operation='MULTIPLY_ADD')
    mh.inputs[1].default_value = 2 * hue_var; mh.inputs[2].default_value = 0.5 - hue_var
    mv = node('ShaderNodeMath', -1150, -50, operation='MULTIPLY_ADD')
    mv.inputs[1].default_value = 2 * tint_var; mv.inputs[2].default_value = 1.0 - tint_var
    L.new(oi.outputs['Random'], mh.inputs[0]); L.new(oi.outputs['Random'], mv.inputs[0])
    L.new(mh.outputs[0], hsv.inputs['Hue']); L.new(mv.outputs[0], hsv.inputs['Value'])
    L.new(col.outputs['Color'], hsv.inputs['Color'])
    # fibre mottling (large soft noise) + fine grain for bump
    tc = node('ShaderNodeTexCoord', -1400, -500)
    nz = node('ShaderNodeTexNoise', -1150, -450)
    nz.inputs['Scale'].default_value = 0.35; nz.inputs['Detail'].default_value = 6.0
    L.new(tc.outputs['Object'], nz.inputs['Vector'])
    mot = node('ShaderNodeMix', -650, 250, data_type='RGBA', blend_type='MULTIPLY')
    mr = node('ShaderNodeMapRange', -900, -400)
    mr.inputs['To Min'].default_value = 1.0 - fibre; mr.inputs['To Max'].default_value = 1.0 + fibre * 0.6
    L.new(nz.outputs['Fac'], mr.inputs['Value'])
    cmb = node('ShaderNodeCombineColor', -700, -400)
    for i in range(3):
        L.new(mr.outputs[0], cmb.inputs[i])
    mot.inputs['Factor'].default_value = 1.0
    L.new(hsv.outputs[0], _sock(mot, 'A_Color')); L.new(cmb.outputs[0], _sock(mot, 'B_Color'))
    # darker edge lines (bevel chamfers & card rims)
    dark = node('ShaderNodeMix', -400, 250, data_type='RGBA', blend_type='MULTIPLY')
    _sock(dark, 'B_Color').default_value = (edge_dark, edge_dark, edge_dark, 1)
    L.new(edg.outputs['Fac'], dark.inputs['Factor']); L.new(_sock(mot, 'Result_Color', out=True), _sock(dark, 'A_Color'))
    grain = node('ShaderNodeTexNoise', -900, -700)
    grain.inputs['Scale'].default_value = 9.0; grain.inputs['Detail'].default_value = 3.0
    L.new(tc.outputs['Object'], grain.inputs['Vector'])
    bump = node('ShaderNodeBump', -400, -500)
    bump.inputs['Strength'].default_value = 0.08; bump.inputs['Distance'].default_value = 0.02
    L.new(grain.outputs['Fac'], bump.inputs['Height'])
    bsdf = node('ShaderNodeBsdfPrincipled', -150, 250)
    bsdf.inputs['Roughness'].default_value = rough
    for nm in ('Specular IOR Level', 'Specular'):
        if nm in bsdf.inputs:
            bsdf.inputs[nm].default_value = 0.18
    if 'Sheen Weight' in bsdf.inputs:
        bsdf.inputs['Sheen Weight'].default_value = 0.25
        bsdf.inputs['Sheen Roughness'].default_value = 0.6
    L.new(_sock(dark, 'Result_Color', out=True), bsdf.inputs['Base Color'])
    L.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
    # back faces (only seen through the section cut) -> flat poche
    geo = node('ShaderNodeNewGeometry', -150, -150)
    em = node('ShaderNodeEmission', -150, -300)
    em.inputs['Color'].default_value = (*hex2lin(POCHE), 1); em.inputs['Strength'].default_value = 0.9
    if POCHE_BANDS:
        # banded section fill by world Z (constant colour ramp over 0..100 m)
        pz = node('ShaderNodeSeparateXYZ', -600, -750)
        L.new(geo.outputs['Position'], pz.inputs[0])
        sc_ = node('ShaderNodeMath', -450, -750, operation='MULTIPLY'); sc_.inputs[1].default_value = 0.01
        L.new(pz.outputs['Z'], sc_.inputs[0])
        rb = node('ShaderNodeValToRGB', -300, -750)
        rb.color_ramp.interpolation = 'CONSTANT'
        bands = sorted(POCHE_BANDS, key=lambda b: b[0])
        el_ = rb.color_ramp.elements
        el_[0].position = 0.0; el_[0].color = (*hex2lin(bands[0][1]), 1)
        el_[1].position = max(0.001, min(0.999, bands[1][0] * 0.01)) if len(bands) > 1 else 0.999
        el_[1].color = (*hex2lin(bands[1][1] if len(bands) > 1 else bands[0][1]), 1)
        for zb_, hx in bands[2:]:
            e_ = el_.new(max(0.001, min(0.999, zb_ * 0.01))); e_.color = (*hex2lin(hx), 1)
        L.new(sc_.outputs[0], rb.inputs[0]); L.new(rb.outputs[0], em.inputs['Color'])
    mixb = node('ShaderNodeMixShader', 250, 150)
    L.new(geo.outputs['Backfacing'], mixb.inputs[0]); L.new(bsdf.outputs[0], mixb.inputs[1]); L.new(em.outputs[0], mixb.inputs[2])
    # section clip: keep where local Y of PK_SectionPlane > 0
    sp = bpy.data.objects.get("PK_SectionPlane")
    tcs = node('ShaderNodeTexCoord', -150, -550)
    tcs.object = sp
    sep = node('ShaderNodeSeparateXYZ', 50, -550)
    gt = node('ShaderNodeMath', 250, -550, operation='GREATER_THAN')
    gt.inputs[1].default_value = 0.0
    L.new(tcs.outputs['Object'], sep.inputs[0]); L.new(sep.outputs['Y'], gt.inputs[0])
    tr = node('ShaderNodeBsdfTransparent', 250, -250)
    mixc = node('ShaderNodeMixShader', 500, 100)
    L.new(gt.outputs[0], mixc.inputs[0]); L.new(tr.outputs[0], mixc.inputs[1]); L.new(mixb.outputs[0], mixc.inputs[2])
    out = node('ShaderNodeOutputMaterial', 750, 100)
    L.new(mixc.outputs[0], out.inputs['Surface'])
    _MAT["paper"] = m
    return m


def glass_material(name, hexcol, alpha=0.12, rim=0.9, emission=1.0):
    """Translucent, outlined look for diagrams (e.g. the inscribed sphere). Not clipped."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.surface_render_method = 'BLENDED'
    m.use_transparent_shadow = True
    try:
        m.use_backface_culling = False
        m.show_transparent_back = True
    except Exception:
        pass
    nt = m.node_tree; N = nt.nodes; L = nt.links; N.clear()
    c = (*hex2lin(hexcol), 1)
    lw = N.new('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = 0.35
    em = N.new('ShaderNodeEmission'); em.inputs['Color'].default_value = c; em.inputs['Strength'].default_value = emission
    tr = N.new('ShaderNodeBsdfTransparent')
    ma = N.new('ShaderNodeMath'); ma.operation = 'MULTIPLY_ADD'
    ma.inputs[1].default_value = rim; ma.inputs[2].default_value = alpha
    L.new(lw.outputs['Facing'], ma.inputs[0])
    mix = N.new('ShaderNodeMixShader')
    L.new(ma.outputs[0], mix.inputs[0]); L.new(tr.outputs[0], mix.inputs[1]); L.new(em.outputs[0], mix.inputs[2])
    out = N.new('ShaderNodeOutputMaterial'); L.new(mix.outputs[0], out.inputs['Surface'])
    return m


def line_material(name, hexcol, strength=1.2):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; N = nt.nodes; L = nt.links; N.clear()
    em = N.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*hex2lin(hexcol), 1)
    em.inputs['Strength'].default_value = strength
    out = N.new('ShaderNodeOutputMaterial'); L.new(em.outputs[0], out.inputs['Surface'])
    return m


# ----------------------------------------------------------------------------- mesh builder
class MB:
    """Accumulates faces (by coordinates; coincident vertices are shared within an 'island')."""
    def __init__(self):
        self.bm = bmesh.new()
        self.el = self.bm.faces.layers.int.new("pk_edge")
        self.nb = self.bm.faces.layers.int.new("pk_nobevel")   # 1 = edges of this face are never bevelled
        self.vmap = {}
        self.nobevel = False

    def island(self):
        self.vmap = {}

    def v(self, p):
        k = (round(p[0], 4), round(p[1], 4), round(p[2], 4))
        vv = self.vmap.get(k)
        if vv is None:
            vv = self.bm.verts.new((p[0], p[1], p[2]))
            self.vmap[k] = vv
        return vv

    def face(self, pts, col, edge=False):
        vs = []
        for p in pts:
            vv = self.v(p)
            if not vs or vs[-1] is not vv:
                vs.append(vv)
        while len(vs) > 1 and vs[0] is vs[-1]:
            vs.pop()
        if len(vs) < 3 or len(set(vs)) != len(vs):
            return None
        try:
            f = self.bm.faces.new(vs)
        except ValueError:
            return None
        f.material_index = _pidx(col)
        f[self.el] = 1 if edge else 0
        f[self.nb] = 1 if self.nobevel else 0
        return f

    # --- primitives -----------------------------------------------------------
    def prism(self, poly, vec, col, side_col=None, side_edge=False, top_col=None):
        """Extrude planar polygon `poly` (list of 3D pts) by vector `vec` -> closed solid."""
        self.island()
        vec = Vector(vec)
        top = [Vector(p) + vec for p in poly]
        self.face(list(reversed(poly)), col)
        self.face(top, top_col or col)
        n = len(poly)
        for i in range(n):
            a, b = Vector(poly[i]), Vector(poly[(i + 1) % n])
            self.face([a, b, b + vec, a + vec], side_col or col, edge=side_edge)

    def box(self, x0, x1, y0, y1, z0, z1, col, top_col=None, side_col=None):
        self.prism([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], (0, 0, z1 - z0),
                   col, side_col=side_col, top_col=top_col)

    def cylinder(self, cx, cy, z0, z1, r0, r1=None, col='x', n=24, cap_col=None):
        self.island()
        r1 = r0 if r1 is None else r1
        a = [2 * math.pi * k / n for k in range(n)]
        bot = [(cx + r0 * math.cos(t), cy + r0 * math.sin(t), z0) for t in a]
        top = [(cx + r1 * math.cos(t), cy + r1 * math.sin(t), z1) for t in a]
        self.face(list(reversed(bot)), cap_col or col)
        self.face(top, cap_col or col)
        for i in range(n):
            j = (i + 1) % n
            self.face([bot[i], bot[j], top[j], top[i]], col)

    def revolve(self, profile, az0, az1, steps, center=(0, 0, 0), cols=None, col='x', cap_col=None, full=False):
        """Sweep closed (r,z) polygon around the Z axis through `center` from az0..az1 (radians)."""
        self.island()
        cx, cy, cz = center
        n = len(profile)
        angs = [az0 + (az1 - az0) * k / steps for k in range(steps + 1)]
        def P(r, z, a):
            return (cx + r * math.cos(a), cy + r * math.sin(a), cz + z)
        for i in range(n):
            (r1, z1), (r2, z2) = profile[i], profile[(i + 1) % n]
            c = cols[i] if cols else col
            for k in range(steps):
                a, b = angs[k], angs[k + 1]
                self.face([P(r1, z1, a), P(r1, z1, b), P(r2, z2, b), P(r2, z2, a)], c)
        if not full:
            self.nobevel = STYLE == "real"        # real: segment end caps meet flush, no V-groove joints
            self.face([P(r, z, az0) for r, z in profile], cap_col or (cols[0] if cols else col))
            self.face([P(r, z, az1) for r, z in reversed(profile)], cap_col or (cols[0] if cols else col))
            self.nobevel = False


def _fix_islands(bm):
    """recalc_face_normals can turn a closed island inside out (seen on revolved shafts with axis fans).
    Flip any connected island whose signed volume is negative."""
    bm.faces.index_update()
    seen = set()
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        isl, stack = [], [f0]
        seen.add(f0.index)
        while stack:
            f = stack.pop(); isl.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index); stack.append(g)
        vol = 0.0
        for f in isl:
            vs = [v.co for v in f.verts]
            for i in range(1, len(vs) - 1):
                vol += vs[0].dot(vs[i].cross(vs[i + 1]))
        if vol < 0:
            bmesh.ops.reverse_faces(bm, faces=isl)


def finish(mb, name, part, pivot=(0, 0, 0), bevel=0.12, bevel_angle=35.0, meta=None, smooth_angle=33.0):
    """Turn a builder into one paper-piece object (origin = pivot, attributes baked)."""
    bm = mb.bm
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if STYLE == "real":
        bevel *= REAL_BEVEL
        _fix_islands(bm)
    if bevel > 0:
        lim = math.radians(bevel_angle)
        edges = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0) > lim
                 and not any(f[mb.nb] for f in e.link_faces)]
        if edges:
            res = bmesh.ops.bevel(bm, geom=edges, offset=bevel, offset_type='OFFSET', segments=1,
                                  profile=0.5, affect='EDGES', clamp_overlap=True, material=-1)
            for f in res['faces']:
                f[mb.el] = 1
    sl = math.radians(smooth_angle)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        if len(e.link_faces) != 2 or e.calc_face_angle(0) > sl:
            e.smooth = False
    pv = Vector(pivot)
    for v in bm.verts:
        v.co -= pv
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    npoly = len(me.polygons)
    mi = [0] * npoly
    me.polygons.foreach_get("material_index", mi)
    ed = [0] * npoly
    me.attributes["pk_edge"].data.foreach_get("value", ed)
    cols = []
    for i in mi:
        c = _PAL[_PAL_NAMES[i]]
        cols += [c[0], c[1], c[2], 1.0]
    a = me.attributes.new("paper_col", 'FLOAT_COLOR', 'FACE'); a.data.foreach_set("color", cols)
    b = me.attributes.new("paper_edge", 'FLOAT', 'FACE'); b.data.foreach_set("value", [float(x) for x in ed])
    me.attributes.remove(me.attributes["pk_edge"])
    if "pk_nobevel" in me.attributes:
        me.attributes.remove(me.attributes["pk_nobevel"])
    if STYLE == "real":
        import realkit
        realkit.assign_materials(me, mi, override=(meta or {}).get("recipe"))
    else:
        me.polygons.foreach_set("material_index", [0] * npoly)
        me.materials.append(paper_material())
    ob = bpy.data.objects.new(name, me)
    ob.location = pv
    part_collection(part).objects.link(ob)
    ob["pk_part"] = part
    ob["pk_rest"] = (pv.x, pv.y, pv.z)     # rest position: real materials map textures in rest world space
    for k, v in (meta or {}).items():
        ob[k] = v
    PARTS.setdefault(part, []).append(ob)
    return ob


def _pname(part):
    return "%s.%03d" % (part, len(PARTS.get(part, [])))


# ----------------------------------------------------------------------------- components
def box_piece(part, x0, x1, y0, y1, z0, z1, col, top_col=None, side_col=None, bevel=0.1, meta=None):
    mb = MB(); mb.box(x0, x1, y0, y1, z0, z1, col, top_col=top_col, side_col=side_col)
    return finish(mb, _pname(part), part, pivot=((x0 + x1) / 2, (y0 + y1) / 2, z0), bevel=bevel, meta=meta)


def sheet(part, poly, thickness, col, normal=(0, 0, 1), meta=None, pivot=None):
    """Flat card: polygon + visible card thickness with dark rim (the 'solidify' look)."""
    mb = MB(); nv = Vector(normal).normalized() * thickness
    mb.prism(poly, nv, col, side_col=col, side_edge=True)
    if pivot is None:
        zs = min(p[2] for p in poly)
        pivot = (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly), zs)
    return finish(mb, _pname(part), part, pivot=pivot, bevel=0, meta=meta)


def _hinge_meta(profile, az, center):
    zmin = min(z for r, z in profile)
    rr = max(r for r, z in profile if abs(z - zmin) < 1e-6)
    cx, cy, cz = center
    piv = (cx + rr * math.cos(az), cy + rr * math.sin(az), cz + zmin)
    axis = (-math.sin(az), math.cos(az), 0.0)          # tangent: +angle tilts top outward
    return piv, axis


def revolve_pieces(part, profile, n_seg, center=(0, 0, 0), cols=None, col='x', az0=0.0, az1=360.0,
                   gap=0.03, ring=0, bevel=0.12, deg_per_step=5.0, skip=None, cap_col=None, profiles=None):
    """Solid of revolution cut into n_seg paper pieces (each a closed sector).
    profile: closed [(r,z),...]; cols: colour per profile edge.  az in degrees (0 = +X, CCW).
    skip: list of segment indices to omit. profiles: optional {seg_index: other_profile} (e.g. door lintel)."""
    out = []
    if STYLE == "real":
        gap = min(gap, REAL_GAP)
    span = math.radians(az1 - az0) / n_seg
    rmax = max(r for r, z in profile)
    g = gap / max(rmax, 1e-3) / 2
    for s in range(n_seg):
        if skip and s in skip:
            continue
        prof = (profiles or {}).get(s, profile)
        a0 = math.radians(az0) + s * span + g
        a1 = math.radians(az0) + (s + 1) * span - g
        steps = max(1, int(math.ceil(math.degrees(a1 - a0) / deg_per_step)))
        mb = MB(); mb.revolve(prof, a0, a1, steps, center=center, cols=cols, col=col, cap_col=cap_col)
        am = (a0 + a1) / 2
        piv, axis = _hinge_meta(prof, am, center)
        out.append(finish(mb, _pname(part), part, pivot=piv, bevel=bevel,
                          meta={"az": math.degrees(am) % 360, "ring": ring, "seg": s, "hinge": axis}))
    return out


def cylinder_wall(part, r_in, r_out, z0, z1, n_seg=16, center=(0, 0, 0), cols=None, **kw):
    """Thick cylindrical wall. cols = [bottom, outer, top, inner]."""
    prof = [(r_in, z0), (r_out, z0), (r_out, z1), (r_in, z1)]
    return revolve_pieces(part, prof, n_seg, center=center, cols=cols or ['x'] * 4, **kw)


def ring_band(part, r_in, r_out, z0, z1, col, n_seg=16, center=(0, 0, 0), ring=0, **kw):
    """Cornice / step ring."""
    return revolve_pieces(part, [(r_in, z0), (r_out, z0), (r_out, z1), (r_in, z1)], n_seg,
                          center=center, col=col, ring=ring, **kw)


def column(part, x, y, z, height, diam, shaft='x', base='x', capital='x', n=20, taper=0.87, meta=None):
    """Simplified classical column: plinth + torus + tapered shaft + flared capital + abacus."""
    d = diam; r = d / 2
    hb, ht, hc, ha = 0.035 * height, 0.03 * height, 0.085 * height, 0.03 * height
    mb = MB()
    mb.box(x - 0.68 * d, x + 0.68 * d, y - 0.68 * d, y + 0.68 * d, z, z + hb, base)
    mb.cylinder(x, y, z + hb, z + hb + ht, 0.64 * d, 0.58 * d, col=base, n=n)
    zs0 = z + hb + ht; zs1 = z + height - hc - ha
    mb.cylinder(x, y, zs0, zs1, r, r * taper, col=shaft, n=n)
    mb.cylinder(x, y, zs1, zs1 + hc, r * taper * 1.02, r * 1.32, col=capital, n=n)
    mb.box(x - 0.74 * d, x + 0.74 * d, y - 0.74 * d, y + 0.74 * d, zs1 + hc, z + height, capital)
    m = {"x": x, "y": y}; m.update(meta or {})
    return finish(mb, _pname(part), part, pivot=(x, y, z), bevel=0.06, meta=m)


def columns_at(part, points, height, diam, **kw):
    return [column(part, p[0], p[1], p[2] if len(p) > 2 else 0.0, height, diam, **kw) for p in points]


def column_ring(part, radius, count, height, diam, center=(0, 0, 0), az0=0.0, **kw):
    cx, cy, cz = center
    pts = [(cx + radius * math.cos(math.radians(az0 + 360 * i / count)),
            cy + radius * math.sin(math.radians(az0 + 360 * i / count)), cz) for i in range(count)]
    return columns_at(part, pts, height, diam, **kw)


def gable(part, x0, x1, y_front, y_back, z_base, rise, col='x', tymp_col=None, roof_col=None,
          cornice_col=None, entab_h=0.0, entab_col=None, overhang=0.8, roof_t=0.45, cornice_t=0.7):
    """Classical pediment facing -Y: [entablature beam], triangular gable body, raking cornice
    frame, two roof slabs. Returns pieces in build order."""
    out = []
    xm = (x0 + x1) / 2; hw = (x1 - x0) / 2
    zb = z_base
    if entab_h > 0:
        out.append(box_piece(part, x0, x1, y_front, y_back, zb, zb + entab_h, entab_col or col, bevel=0.1))
        zb += entab_h
    # gable body (tympanum set back 0.35)
    tri = [(x0, y_front + 0.35, zb), (x1, y_front + 0.35, zb), (xm, y_front + 0.35, zb + rise)]
    mb = MB(); mb.prism(tri, (0, y_back - y_front - 0.35, 0), tymp_col or col, side_col=col)
    out.append(finish(mb, _pname(part), part, pivot=(xm, y_front, zb), bevel=0.1))
    # raking + horizontal cornice frame (front)
    mb = MB()
    s = math.atan2(rise, hw)
    ct = cornice_t
    for sign in (-1, 1):
        ex, ez = xm + sign * (hw + overhang * 0.6), zb - 0.1
        ax_, az_ = xm, zb + rise + 0.25
        dx, dz = ax_ - ex, az_ - ez
        L = math.hypot(dx, dz)
        nx, nz = -dz / L * ct, dx / L * ct
        if nz < 0:
            nx, nz = -nx, -nz
        poly = [(ex, y_front - 0.25, ez), (ax_, y_front - 0.25, az_), (ax_ + nx, y_front - 0.25, az_ + nz), (ex + nx, y_front - 0.25, ez + nz)]
        mb.prism(poly, (0, 1.2, 0), cornice_col or col)
    mb.box(x0 - overhang * 0.6, x1 + overhang * 0.6, y_front - 0.25, y_front + 0.95, zb - 0.1, zb + ct * 0.8, cornice_col or col)
    out.append(finish(mb, _pname(part), part, pivot=(xm, y_front, zb), bevel=0.06))
    # roof slabs
    for sign in (-1, 1):
        e0 = (xm + sign * (hw + overhang), zb - overhang * math.tan(s))
        e1 = (xm, zb + rise)
        p = [(e0[0], y_front - 0.3, e0[1] + ct), (e1[0], y_front - 0.3, e1[1] + ct),
             (e1[0], y_back, e1[1] + ct), (e0[0], y_back, e0[1] + ct)]
        if sign < 0:
            p = [p[1], p[0], p[3], p[2]]
        mb = MB(); mb.prism(p, (0, 0, roof_t), roof_col or col, side_col=roof_col or col, side_edge=True)
        out.append(finish(mb, _pname(part), part, pivot=(xm + sign * hw / 2, (y_front + y_back) / 2, zb), bevel=0))
    return out


def dome_shell(part, center, r_in, el0, el1, n_rings, n_seg, outer, col_out='x', col_in='x',
               col_edge=None, ring0=0, bevel=0.1, seg_offset=0.0, az0=None, az1=None, meta=None):
    """Dome made of rings (each ring = n_seg paper pieces). Inner surface = sphere r_in from
    elevation el0..el1 (deg). outer: callable u->(r,z) along the outer profile, u in [0,1]
    (z relative to center), or a float = constant thickness. Returns pieces with meta ring/seg.
    az0/az1 (deg): only this plan sector (half domes, exedrae: n_seg pieces over az0..az1); default the full
    circle from seg_offset. meta: extra properties set on every piece (e.g. pk_dome_center for lead seams)."""
    a_lo = seg_offset if az0 is None else az0
    a_hi = (a_lo + 360.0) if az1 is None else az1
    out = []
    cz = center[2]
    if not callable(outer):
        th = float(outer)
        outer = lambda u, th=th: ((r_in + th) * math.cos(math.radians(el0 + (el1 - el0) * u)),
                                  (r_in + th) * math.sin(math.radians(el0 + (el1 - el0) * u)))
    for k in range(n_rings):
        u0, u1 = k / n_rings, (k + 1) / n_rings
        m = max(2, int(math.ceil((el1 - el0) / n_rings / 4.0)))
        inner = []
        for j in range(m + 1):
            e = math.radians(el0 + (el1 - el0) * (u0 + (u1 - u0) * j / m))
            inner.append((r_in * math.cos(e), r_in * math.sin(e)))
        outer_pts = [outer(u0 + (u1 - u0) * j / m) for j in range(m + 1)]
        prof = inner + list(reversed(outer_pts))
        # edge colours: inner arc edges, then top edge, outer arc, bottom edge
        cols = [col_in] * m + [col_edge or col_out] + [col_out] * m + [col_edge or col_out]
        out += revolve_pieces(part, prof, n_seg, center=center, cols=cols, ring=ring0 + k, bevel=bevel,
                              az0=a_lo, az1=a_hi)
    for o in out:
        for k_, v_ in (meta or {}).items():
            o[k_] = v_
    return out


def coffers(part, center, r, rows, cols_n, el0, el1, depth, rib='x', recess='x', back=None,
            az0=0.0, ring0=0, rib_frac=0.16):
    """Grid of stepped, recessed coffers on the inside of a sphere (radius r = rib surface)."""
    cx, cy, cz = center
    out = []
    def S(a, e, rad):
        return (cx + rad * math.cos(e) * math.cos(a), cy + rad * math.cos(e) * math.sin(a), cz + rad * math.sin(e))
    for i in range(rows):
        e0 = math.radians(el0 + (el1 - el0) * i / rows); e1 = math.radians(el0 + (el1 - el0) * (i + 1) / rows)
        for j in range(cols_n):
            a0 = math.radians(az0 + 360.0 * j / cols_n); a1 = math.radians(az0 + 360.0 * (j + 1) / cols_n)
            def quad(fr, rad):
                da = (a1 - a0) * fr; de = (e1 - e0) * fr
                return [S(a0 + da, e0 + de, rad), S(a1 - da, e0 + de, rad), S(a1 - da, e1 - de, rad), S(a0 + da, e1 - de, rad)]
            O = quad(0.0, r); I1 = quad(rib_frac, r); I1b = quad(rib_frac, r + depth * 0.45)
            I2 = quad(rib_frac + 0.08, r + depth * 0.45); B = quad(rib_frac + 0.16, r + depth)
            O0 = Vector(O[0]); O2 = Vector(O[2])
            sag = ((O0 - O2).length / 2) ** 2 / (2 * r)      # flat back cover must clear the curved recess
            Ob = quad(0.0, r + depth + 0.08 + sag)
            mb = MB()
            for q in range(4):
                n = (q + 1) % 4
                mb.face([O[q], O[n], I1[n], I1[q]], rib)            # rib frame
                mb.face([I1[q], I1[n], I1b[n], I1b[q]], recess)     # step wall
                mb.face([I1b[q], I1b[n], I2[n], I2[q]], recess)     # step ledge
                mb.face([I2[q], I2[n], B[n], B[q]], recess)         # sloped wall
                mb.face([O[n], O[q], Ob[q], Ob[n]], rib)            # hidden sides
            mb.face(B, back or recess)
            mb.face(list(reversed(Ob)), rib)
            am, em = (a0 + a1) / 2, (e0 + e1) / 2
            out.append(finish(mb, _pname(part), part, pivot=S(am, em, r), bevel=0.05,
                              meta={"az": math.degrees(am) % 360, "ring": ring0 + i, "seg": j}))
    return out


def arches(part, center, r_wall, z_spring, az_list, span, band=0.9, protrude=0.25, col='x', n=14, ring=0):
    """Relieving-arch strips (semicircular bands) lying on a cylindrical wall of radius r_wall."""
    cx, cy, cz = center
    out = []
    Ra = span / 2
    for s, azd in enumerate(az_list):
        az = math.radians(azd)
        def P(u, v, d):
            a = az + u / r_wall; rr = r_wall + d
            return (cx + rr * math.cos(a), cy + rr * math.sin(a), cz + z_spring + v)
        ins = [(Ra * math.cos(math.pi * k / n), Ra * math.sin(math.pi * k / n)) for k in range(n + 1)]
        outs = [((Ra + band) * math.cos(math.pi * k / n), (Ra + band) * math.sin(math.pi * k / n)) for k in range(n + 1)]
        mb = MB()
        for k in range(n):
            mb.face([P(*ins[k], protrude), P(*outs[k], protrude), P(*outs[k + 1], protrude), P(*ins[k + 1], protrude)], col)
            mb.face([P(*ins[k + 1], -0.1), P(*outs[k + 1], -0.1), P(*outs[k], -0.1), P(*ins[k], -0.1)], col)
            mb.face([P(*outs[k], protrude), P(*outs[k], -0.1), P(*outs[k + 1], -0.1), P(*outs[k + 1], protrude)], col)
            mb.face([P(*ins[k + 1], protrude), P(*ins[k + 1], -0.1), P(*ins[k], -0.1), P(*ins[k], protrude)], col)
        for k in (0, n):
            mb.face([P(*ins[k], protrude), P(*ins[k], -0.1), P(*outs[k], -0.1), P(*outs[k], protrude)], col)
        out.append(finish(mb, _pname(part), part, pivot=P(0, 0, 0), bevel=0.05,
                          meta={"az": azd % 360, "ring": ring, "seg": s}))
    return out


# ----------------------------------------------------------------------------- walls with real openings, domes on
# pendentives (ep02 Hagia Sophia; generic: any arched window, drum, pendentive dome, barrel arch, buttress)
def P_cyl(center, r_ref, az0_deg):
    """(u, v, w) -> 3D on a cylinder: u = arc length at radius r_ref from plan azimuth az0, v = z, w = radius."""
    cx, cy = center[0], center[1]
    a0 = math.radians(az0_deg)
    def P(u, v, w):
        a = a0 + u / r_ref
        return (cx + w * math.cos(a), cy + w * math.sin(a), v)
    return P


def P_plane(origin, u_dir, w_dir):
    """(u, v, w) -> 3D on a vertical plane: origin + u * u_dir + v * Z + w * w_dir (u_dir, w_dir horizontal)."""
    ox, oy, oz = origin
    def P(u, v, w):
        return (ox + u * u_dir[0] + w * w_dir[0], oy + u * u_dir[1] + w * w_dir[1], oz + v)
    return P


def _bisect0(g, a, b, it=26):
    ga = g(a)
    for _ in range(it):
        m = (a + b) / 2
        if (g(m) > 0) == (ga > 0):
            a, ga = m, g(m)
        else:
            b = m
    return (a + b) / 2


def uv_runs(us, vb, vt, eps=0.01):
    """split the u samples into runs where vt(u) - vb(u) > eps (crossings refined by bisection)."""
    g = lambda u: vt(u) - vb(u) - eps
    runs, cur = [], []
    for i, u in enumerate(us):
        if g(u) > 0:
            if not cur and i > 0:
                cur.append(_bisect0(g, us[i - 1], u))
            cur.append(u)
        elif cur:
            cur.append(_bisect0(g, us[i - 1], u))
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    out = []
    for r in runs:
        rr = [r[0]]
        for u in r[1:]:
            if u - rr[-1] > 1e-4:
                rr.append(u)
        if len(rr) >= 2:
            out.append(rr)
    return out


def uv_strip(mb, P, us, vb, vt, w0, w1, cols):
    """Closed solid over the u samples `us` between bottom vb(u) and top vt(u) (callables), depth w0..w1 (w1 =
    front), mapped to 3D by P(u, v, w). cols: a colour name or {front, back, top, bottom, end, all}. End faces
    are never bevelled, so neighbouring strips of one wall meet flush."""
    if isinstance(cols, dict):
        c = lambda k: cols.get(k, cols.get("all", "x"))
    else:
        c = lambda k: cols
    mb.island()
    B = [(u, vb(u)) for u in us]
    T = [(u, vt(u)) for u in us]
    q = lambda uv, w: P(uv[0], uv[1], w)
    n = len(us)
    for i in range(n - 1):
        mb.face([q(B[i], w1), q(B[i + 1], w1), q(T[i + 1], w1), q(T[i], w1)], c("front"))
        mb.face([q(T[i], w0), q(T[i + 1], w0), q(B[i + 1], w0), q(B[i], w0)], c("back"))
        mb.face([q(B[i], w0), q(B[i + 1], w0), q(B[i + 1], w1), q(B[i], w1)], c("bottom"))
        mb.face([q(T[i], w1), q(T[i + 1], w1), q(T[i + 1], w0), q(T[i], w0)], c("top"))
    mb.nobevel = True
    for i, sgn in ((0, 1), (n - 1, -1)):
        pts = [q(B[i], w0), q(B[i], w1), q(T[i], w1), q(T[i], w0)]
        mb.face(pts if sgn > 0 else list(reversed(pts)), c("end"))
    mb.nobevel = False


def _arch_top(win):
    uc, w, zs, zp = win[:4]
    r = w / 2.0
    return lambda u: zp + math.sqrt(max(r * r - (u - uc) ** 2, 0.0))


def _u_samples(a, b, cover, du=0.3, n_arc=12):
    """u samples in [a, b]: uniform (du) plus angle-uniform samples of every covering window's arch."""
    us = {a, b}
    n = max(1, int(math.ceil((b - a) / du)))
    us.update(a + (b - a) * k / n for k in range(n + 1))
    for wd in cover:
        uc, w = wd[0], wd[1]
        r = w / 2.0
        p0 = math.acos(max(-1.0, min(1.0, (a - uc) / r)))
        p1 = math.acos(max(-1.0, min(1.0, (b - uc) / r)))
        m = max(2, int(n_arc * abs(p0 - p1) / math.pi) + 2)
        us.update(uc + r * math.cos(p0 + (p1 - p0) * k / m) for k in range(m + 1))
    return sorted(u for u in us if a - 1e-9 <= u <= b + 1e-9)


def windowed_wall(mb, P, ua, ub, z_lo, top, windows, w0, w1, cols, glass_mb=None, glass=None, du=0.3, n_arc=12,
                  inset=0.025):
    """Solid wall over u in [ua, ub] (P(u, v, w) mapping, depth w0..w1, w1 = front), from v = z_lo up to `top`
    (a float or u -> v), with arched openings cut right through it: windows [(uc, w, z_sill, z_spring[, glazed])] = rectangle
    z_sill..z_spring + semicircle of radius w/2 on top (z_spring may lie below z_sill: a big arch whose springing is
    below the wall's foot). Built as column strips between the openings (no booleans, no coplanar faces).
    glass = (gw0, gw1, col_out, col_in): a pane slab per opening (inset from the jambs) into glass_mb; the pane's
    front face (outside) gets col_out, its back face (inside) col_in."""
    topf = top if callable(top) else (lambda u, t=float(top): t)
    cuts = {ua, ub}
    for wd in windows:
        uc, w = wd[0], wd[1]
        for e in (uc - w / 2, uc + w / 2):
            if ua < e < ub:
                cuts.add(e)
    cuts = sorted(cuts)
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 1e-4:
            continue
        m = (a + b) / 2
        cover = sorted([wd for wd in windows if wd[0] - wd[1] / 2 <= m <= wd[0] + wd[1] / 2], key=lambda wd: wd[2])
        us = _u_samples(a, b, cover, du, n_arc)
        prev = lambda u, z=float(z_lo): z
        for wd in cover:
            vt_ = (lambda u, zs=wd[2], t=topf: min(zs, t(u)))
            for run in uv_runs(us, prev, vt_):
                uv_strip(mb, P, run, prev, vt_, w0, w1, cols)
            prev = (lambda u, f=_arch_top(wd), z=float(z_lo): max(f(u), z))
        vt_ = topf
        for run in uv_runs(us, prev, vt_):
            uv_strip(mb, P, run, prev, vt_, w0, w1, cols)
    if glass_mb is not None and glass:
        gw0, gw1, gc_out, gc_in = glass
        gc = {"front": gc_out, "back": gc_in, "all": gc_out}
        for wd in windows:
            uc, w, zs, zp = wd[:4]
            if len(wd) > 4 and not wd[4]:
                continue                          # an unglazed opening (arch into an exedra, doorway)
            e0, e1 = uc - w / 2 + inset, uc + w / 2 - inset
            a, b = max(ua, e0), min(ub, e1)
            if b - a < 1e-3:
                continue
            us = _u_samples(a, b, [(uc, w - 2 * inset, zs, zp)], du, n_arc)
            at = _arch_top((uc, w - 2 * inset, zs, zp - inset))
            vb_ = (lambda u, z=zs + inset: z)
            vt_ = (lambda u, at=at, t=topf: min(at(u), t(u) - inset))
            for run in uv_runs(us, vb_, vt_):
                uv_strip(glass_mb, P, run, vb_, vt_, gw0, gw1, gc)


def profile_faces(mb, poly, P3, width, col, top_col=None, side_col=None, top_k=0.25):
    """Prism from a closed profile poly [(o, z)] in a vertical plane, extruded `width` (centred) along the plane's
    normal. P3(o, z, s) -> 3D (s = across). Perimeter faces whose outward normal points up (nz > top_k) get top_col
    (weathering / lead on sloped tops). Adds one island to mb."""
    mb.island()
    area = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly)))
    if area < 0:
        poly = list(reversed(poly))
    h = width / 2.0
    F = [P3(o, z, -h) for o, z in poly]
    Bk = [P3(o, z, h) for o, z in poly]
    mb.face(F, side_col or col); mb.face(list(reversed(Bk)), side_col or col)
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        do, dz = poly[j][0] - poly[i][0], poly[j][1] - poly[i][1]
        L = math.hypot(do, dz) or 1.0
        nz = -do / L                                 # CCW polygon: outward normal = (dz, -do)
        mb.face([F[i], F[j], Bk[j], Bk[i]], (top_col or col) if nz > top_k else col)


def profile_prism(part, poly, origin, out_dir, width, col='x', top_col=None, side_col=None, bevel=0.06, meta=None,
                  pivot=None):
    """Buttress / fin / sloped wall: profile poly [(o, z)] (o = metres along the horizontal out_dir from origin,
    z absolute), extruded `width` metres across (centred on origin). Sloped and horizontal tops get top_col."""
    ox, oy = origin[0], origin[1]
    d = Vector((out_dir[0], out_dir[1], 0.0)).normalized()
    s = Vector((-d.y, d.x, 0.0))
    P3 = lambda o, z, w: (ox + d.x * o + s.x * w, oy + d.y * o + s.y * w, z)
    mb = MB()
    profile_faces(mb, poly, P3, width, col, top_col, side_col)
    zmin = min(z for o, z in poly)
    return finish(mb, _pname(part), part, pivot=pivot or (ox, oy, zmin), bevel=bevel, meta=meta)


def battered_prism(part, poly, origin, out_dir, w_bot, w_top=None, col='x', top_col=None, side_col=None, bevel=0.06,
                   meta=None, pivot=None, top_k=0.25):
    """Battered (sloping) buttress / fin: like profile_prism (side profile poly [(o, z)], o = metres along the
    horizontal out_dir from origin, z absolute) but the width across tapers linearly with height, from w_bot at the
    profile's lowest z to w_top at its highest z, so the two side faces lean in as well (side faces stay planar).
    Perimeter faces whose outward normal points up (nz > top_k) get top_col (lead on the sloped cap)."""
    ox, oy = origin[0], origin[1]
    d = Vector((out_dir[0], out_dir[1], 0.0)).normalized()
    s = Vector((-d.y, d.x, 0.0))
    w_top = w_bot if w_top is None else w_top
    z0, z1 = min(z for o, z in poly), max(z for o, z in poly)
    hw = lambda z: 0.5 * (w_bot + (w_top - w_bot) * (z - z0) / max(z1 - z0, 1e-6))
    P3 = lambda o, z, w: (ox + d.x * o + s.x * w, oy + d.y * o + s.y * w, z)
    area = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly)))
    if area < 0:
        poly = list(reversed(poly))
    mb = MB()
    mb.island()
    F = [P3(o, z, -hw(z)) for o, z in poly]
    Bk = [P3(o, z, hw(z)) for o, z in poly]
    mb.face(F, side_col or col); mb.face(list(reversed(Bk)), side_col or col)
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        do, dz = poly[j][0] - poly[i][0], poly[j][1] - poly[i][1]
        L = math.hypot(do, dz) or 1.0
        mb.face([F[i], F[j], Bk[j], Bk[i]], (top_col or col) if -do / L > top_k else col)
    return finish(mb, _pname(part), part, pivot=pivot or (ox, oy, z0), bevel=bevel, meta=meta)


def poly_prism(mb, poly, z0, z1, edge_cols, top_col, bottom_col=None):
    """Vertical prism over a plan polygon [(x, y)] (any simple polygon, concave allowed), z0..z1; edge_cols: one
    colour per polygon edge (i -> i+1) or a single name. One island."""
    mb.island()                       # winding does not matter: finish() recalculates the normals
    cols = edge_cols if isinstance(edge_cols, (list, tuple)) else [edge_cols] * len(poly)
    bot = [(x, y, z0) for x, y in poly]
    top = [(x, y, z1) for x, y in poly]
    mb.face(list(reversed(bot)), bottom_col or top_col)
    mb.face(top, top_col)
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        mb.face([bot[i], bot[j], top[j], top[i]], cols[i % len(cols)])


def window_crown(part, center, r_in, r_out, z0, h, n, az0=0.0, az1=360.0, win_w=1.5, sill=0.5, rect_h=2.2,
                 seg_az=None, fin=(1.4, 0.5, 1.4, 1.5), fin_r_in=None, cols=None, glass=("window_glass", "window_sky"),
                 ring=0, meta=None, extra_openings=None, bevel=0.05):
    """Drum / window ring: n arched windows cut right through a cylindrical band r_in..r_out, z0..z0+h (plan arc
    az0..az1, deg). Full ring (az1 - az0 == 360): windows centred at az0 + k*360/n and one piece per window-to-window
    sector (seams through the window centres, so a seam plane through az0 crosses glass, not masonry); arc: windows
    centred in n equal sub-arcs, pieces split at seg_az (default: at the windows' outer edges' midpoints).
    Each pier between two windows carries an outside buttress fin: fin = (depth out, thickness, rise above the band
    top at the wall, height at the outer face), its top sloping outward-down (top_col), its inner edge running in to
    fin_r_in above the band (against the dome). extra_openings: [(az_c, w, z_sill, z_spring)] more arched openings
    (e.g. big arches into exedrae under a half-dome's window band). Pieces: masonry (role 'band', meta sub 'band',
    seg, az, side) + one glass piece per sector (role 'glass', sub 'glass': outer face col_out = warm window glow,
    inner face col_in = sky seen from inside). Returns (band_pieces, glass_pieces)."""
    cols = cols or {"front": "x", "back": "x", "all": "x"}
    full = abs((az1 - az0) - 360.0) < 1e-6
    span = math.radians(az1 - az0)
    U = r_in * span
    if full:
        wu = [r_in * math.radians(360.0 * k / n) for k in range(n + 1)]
    else:
        wu = [U * (k + 0.5) / n for k in range(n)]
    wins = [(u, win_w, z0 + sill, z0 + sill + rect_h) for u in wu]
    for az_c, w, zs, zp in (extra_openings or []):
        wins.append((r_in * math.radians(az_c - az0), w, zs, zp, False))      # open arches: no glass
    if seg_az is None:
        bounds = wu if full else [0.0] + [(wu[k] + wu[k + 1]) / 2 for k in range(n - 1)] + [U]
    else:
        bounds = sorted(r_in * math.radians(a - az0) for a in seg_az)
    piers = [(wu[k] + wu[k + 1]) / 2 for k in range(len(wu) - 1)] if full else \
            [(wu[k] + wu[k + 1]) / 2 for k in range(n - 1)]
    P = P_cyl(center, r_in, az0)
    fd, ft, fup, fout = fin if fin else (0, 0, 0, 0)
    fr_in = fin_r_in if fin_r_in is not None else r_out - 0.3
    zt = z0 + h
    band, glass_out = [], []
    for s in range(len(bounds) - 1):
        ua, ub = bounds[s], bounds[s + 1]
        mb, gmb = MB(), MB()
        windowed_wall(mb, P, ua, ub, z0, zt, wins, r_in, r_out, cols,
                      glass_mb=gmb, glass=((r_in + r_out) / 2 - 0.03, (r_in + r_out) / 2 + 0.03) + tuple(glass))
        if fin:
            for up in piers:
                if ua + ft / 2 <= up <= ub - ft / 2:
                    poly = [(r_out, z0), (r_out + fd, z0), (r_out + fd, z0 + fout), (r_out + 0.3, zt + fup),
                            (fr_in, zt + fup), (fr_in, zt), (r_out, zt)]
                    a = math.radians(az0) + up / r_in
                    d = (math.cos(a), math.sin(a)); tng = (-math.sin(a), math.cos(a))
                    cx, cy = center[0], center[1]
                    P3 = lambda o, z, w, d=d, tng=tng: (cx + d[0] * o + tng[0] * w, cy + d[1] * o + tng[1] * w, z)
                    profile_faces(mb, poly, P3, ft, cols.get("front", "x"), cols.get("top", None))
        am = az0 + math.degrees((ua + ub) / 2 / r_in)
        m = {"az": am % 360, "seg": s, "ring": ring, "sub": "band", "role": "band",
             "side": "R" if center[0] + r_in * math.cos(math.radians(am)) > 1e-6 else "L"}
        m.update(meta or {})
        a_m = math.radians(am)
        piv = (center[0] + r_in * math.cos(a_m), center[1] + r_in * math.sin(a_m), z0)
        band.append(finish(mb, _pname(part), part, pivot=piv, bevel=bevel, meta=m))
        if gmb.bm.faces:
            mg = dict(m, sub="glass", role="glass")
            glass_out.append(finish(gmb, _pname(part), part, pivot=piv, bevel=0.0, meta=mg))
        else:
            gmb.bm.free()
    return band, glass_out


def pendentive(part, center, side, z_spring, z_top=None, inset=0.04, rings=1, col_in='x', col_back='x',
               col_top='x', nz=16, nt=16, meta=None):
    """The 4 pendentives of a square bay of side `side` (plan centre `center`, arches springing at z_spring): the
    spherical triangles of the sphere through the bay's corners (radius side/sqrt2, centre at springing height) left
    between the four arch planes. Each is a solid from that sphere back to the arch planes (inset `inset` from
    them: no coplanar faces with the arches' faces), from its tip at the corner up to the ring z_spring + side/2
    where the four top edges join into the circle that carries the dome; z_top > ring adds a vertical collar
    (inner face = the ring's cylinder) up to the arches' extrados. rings > 1 cuts each into horizontal bands (meta
    ring). Pieces carry meta corner (sx, sy), sub 'pendentive', ring. Returns pieces (4 x rings)."""
    cx, cy = center[0], center[1]
    A = side / 2.0
    Ai = A - inset
    RP = A * math.sqrt(2.0)
    z_ring = z_spring + A
    z_top = z_ring if z_top is None else max(z_top, z_ring)
    z_tip = z_spring + math.sqrt(max(RP * RP - 2 * Ai * Ai, 0.0))
    nt += nt % 2
    zs_sph = [z_tip + (z_ring - z_tip) * k / nz for k in range(nz + 1)]
    zs_col = [z_ring + (z_top - z_ring) * k / 2 for k in (1, 2)] if z_top > z_ring + 1e-3 else []
    rows = zs_sph + zs_col
    out = []
    for sx in (1, -1):
        for sy in (1, -1):
            def ring_pts(z):
                if z <= z_ring + 1e-9:
                    r = math.sqrt(max(RP * RP - (z - z_spring) ** 2, 0.0))
                else:
                    r = A
                lo = math.acos(max(-1.0, min(1.0, Ai / max(r, 1e-6))))
                hi = math.pi / 2 - lo
                inner, back = [], []
                for j in range(nt + 1):
                    a = lo + (hi - lo) * j / nt
                    px, py = r * math.cos(a), r * math.sin(a)
                    if j in (0, nt):
                        bx, by = px, py
                    else:
                        k = Ai / max(px, py)
                        bx, by = px * k, py * k
                        if j == nt // 2:
                            bx, by = Ai, Ai
                    inner.append((cx + sx * px, cy + sy * py, z)); back.append((cx + sx * bx, cy + sy * by, z))
                return inner, back
            bands = [rows] if rings <= 1 else []
            if rings > 1:
                zb = [z_tip + (z_top - z_tip) * k / rings for k in range(rings + 1)]
                for k in range(rings):
                    rr = [zb[k]] + [z for z in rows if zb[k] < z < zb[k + 1]] + [zb[k + 1]]
                    bands.append(rr)
            for bi, rr in enumerate(bands):
                mb = MB(); mb.island()
                R = [ring_pts(z) for z in rr]
                for k in range(len(rr) - 1):
                    (i0, b0), (i1, b1) = R[k], R[k + 1]
                    for j in range(nt):
                        mb.face([i0[j], i0[j + 1], i1[j + 1], i1[j]], col_in)
                        mb.face([b0[j], b1[j], b1[j + 1], b0[j + 1]], col_back)
                it, bt = R[-1]
                mb.face(it + list(reversed(bt)), col_top)
                if rr[0] > z_tip + 1e-6:          # a band above the tip: close its bottom
                    ib, bb = R[0]
                    mb.face(ib + list(reversed(bb)), col_top)
                m = {"corner": (sx, sy), "sub": "pendentive", "ring": bi,
                     "side": "R" if sx * 1 > 0 else "L"}
                m.update(meta or {})
                out.append(finish(mb, _pname(part), part, pivot=(cx + sx * Ai, cy + sy * Ai, rr[0]), bevel=0.0, meta=m))
    return out


def arch_barrel(part, center, span, thick, depth, axis='x', z_spring=0.0, n_vous=8, leg=0.0, col_soffit='x',
                col_face='x', col_ext='x', col_joint=None, ring=0, steps=4, meta=None, bevel=0.04):
    """Semicircular barrel arch with real depth, cut into n_vous voussoir pieces (even n puts a joint at the
    crown, i.e. on a centre seam plane). center = (x, y) of the arch's mid-depth at the span centre; intrados radius
    span/2 at z_spring, ring thickness `thick`, `depth` along `axis` ('x': deep along x, the arch spans along y;
    'y': deep along y, spans along x). col_face: one name, or (face at -depth/2, face at +depth/2) when one face is
    inside and the other outside. leg: the end voussoirs run straight down `leg` metres below the springing
    (seat them inside the piers). Meta: seg (voussoir index), ring, sub 'voussoir', side by the voussoir's centre."""
    cx, cy = center[0], center[1]
    R, Ro = span / 2.0, span / 2.0 + thick
    hd = depth / 2.0
    def P(s, z, d):
        return (cx + d, cy + s, z) if axis == 'x' else (cx + s, cy + d, z)
    out = []
    g = REAL_GAP / 2 / R if STYLE == "real" else 0.0
    for k in range(n_vous):
        t0 = math.pi * k / n_vous + (g if k > 0 else 0.0)
        t1 = math.pi * (k + 1) / n_vous - (g if k < n_vous - 1 else 0.0)
        ts = [t0 + (t1 - t0) * i / steps for i in range(steps + 1)]
        inner = [(R * math.cos(t), z_spring + R * math.sin(t)) for t in ts]
        outer = [(Ro * math.cos(t), z_spring + Ro * math.sin(t)) for t in reversed(ts)]
        poly, ecol = [], []
        if k == 0 and leg > 0:
            poly += [(Ro, z_spring - leg), (R, z_spring - leg)]; ecol += [col_ext, col_soffit]
        for i, p in enumerate(inner):
            poly.append(p); ecol.append(col_soffit if i < len(inner) - 1 else (col_joint or col_ext))
        if k == n_vous - 1 and leg > 0:
            ecol[-1] = col_soffit
            poly += [(-R, z_spring - leg), (-Ro, z_spring - leg)]; ecol += [col_ext, col_ext]
        for i, p in enumerate(outer):
            poly.append(p); ecol.append(col_ext if i < len(outer) - 1 else (col_joint or col_ext))
        if k == 0 and leg > 0:
            ecol[-1] = col_ext
        mb = MB(); mb.island()
        F = [P(s, z, -hd) for s, z in poly]
        Bk = [P(s, z, hd) for s, z in poly]
        cf0, cf1 = col_face if isinstance(col_face, (tuple, list)) else (col_face, col_face)
        mb.face(F, cf0); mb.face(list(reversed(Bk)), cf1)
        for i in range(len(poly)):
            j = (i + 1) % len(poly)
            mb.face([F[i], F[j], Bk[j], Bk[i]], ecol[i])
        tm = (t0 + t1) / 2
        sm = (R + thick / 2) * math.cos(tm)
        c3 = P(sm, z_spring + (R + thick / 2) * math.sin(tm), 0.0)
        m = {"seg": k, "ring": ring, "sub": "voussoir", "side": "R" if c3[0] > 1e-6 else "L"}
        m.update(meta or {})
        out.append(finish(mb, _pname(part), part, pivot=c3, bevel=bevel, meta=m))
    return out


def ribbed_dome(part, center, r_in, thick, el0, el_c, n, az0=0.0, rib_w=0.9, rib_out=0.3, rib_in=0.3,
                col_out='x', col_in='x', col_edge='x', col_rib_in=None, ring=0, steps_el=12, crown=True,
                crown_pieces=2, meta=None, bevel=0.03):
    """Ribbed spherical shell (sphere r_in .. r_in + thick around `center`) cut into n gores, each with a rib on its
    centre line outside (rib_out proud) and inside (rib_in proud, the ribs seen from the floor), from elevation el0
    to el_c (deg), plus a crown medallion (el_c .. 90) in crown_pieces sectors. Gore k spans az0 + k*360/n ..
    (k+1)*360/n, so with az0 on a seam plane the seams stay on it. Ribs keep a constant angular width (rib_w metres
    at el0), so they converge on the medallion. Meta: seg, ring, az (rib azimuth), sub 'gore' / 'crown'."""
    cx, cy, cz = center
    ro0 = r_in + thick
    hw = (rib_w / 2) / (r_in * math.cos(math.radians(el0)))
    out = []
    S = lambda a, e, r: (cx + r * math.cos(e) * math.cos(a), cy + r * math.cos(e) * math.sin(a), cz + r * math.sin(e))
    es = [math.radians(el0 + (el_c - el0) * i / steps_el) for i in range(steps_el + 1)]
    for k in range(n):
        a0 = math.radians(az0 + 360.0 * k / n)
        a1 = math.radians(az0 + 360.0 * (k + 1) / n)
        ac = (a0 + a1) / 2
        g = REAL_GAP / 2 / ro0 if STYLE == "real" else 0.0
        az = [a0 + g, ac - hw, ac - 0.55 * hw, ac + 0.55 * hw, ac + hw, a1 - g]
        bump = [0, 0, 1, 1, 0, 0]
        ro = [ro0 + rib_out * b for b in bump]
        ri = [r_in - rib_in * b for b in bump]
        mb = MB(); mb.island()
        O = [[S(a, e, r) for a, r in zip(az, ro)] for e in es]
        I = [[S(a, e, r) for a, r in zip(az, ri)] for e in es]
        m6 = len(az)
        for i in range(len(es) - 1):
            for j in range(m6 - 1):
                mb.face([O[i][j], O[i][j + 1], O[i + 1][j + 1], O[i + 1][j]], col_out)
                cin = col_rib_in if (col_rib_in and bump[j] + bump[j + 1] > 0) else col_in
                mb.face([I[i][j], I[i + 1][j], I[i + 1][j + 1], I[i][j + 1]], cin)
        for j in range(m6 - 1):
            mb.face([I[0][j], I[0][j + 1], O[0][j + 1], O[0][j]], col_edge)
            mb.face([O[-1][j], O[-1][j + 1], I[-1][j + 1], I[-1][j]], col_edge)
        mb.nobevel = True
        for i in range(len(es) - 1):
            mb.face([I[i][0], O[i][0], O[i + 1][0], I[i + 1][0]], col_edge)
            mb.face([O[i][-1], I[i][-1], I[i + 1][-1], O[i + 1][-1]], col_edge)
        mb.nobevel = False
        m = {"seg": k, "ring": ring, "az": math.degrees(ac) % 360, "sub": "gore",
             "side": "R" if math.cos(ac) > 1e-6 else "L"}
        m.update(meta or {})
        out.append(finish(mb, _pname(part), part, pivot=S(ac, es[0], r_in), bevel=bevel, meta=m))
    if crown:
        ri_c, ro_c = r_in - rib_in, ro0 + rib_out
        e_c = math.radians(el_c)
        m_ = 6
        prof = [(ri_c * math.cos(e_c + (math.pi / 2 - e_c) * j / m_), ri_c * math.sin(e_c + (math.pi / 2 - e_c) * j / m_))
                for j in range(m_ + 1)]
        prof += [(ro_c * math.cos(e_c + (math.pi / 2 - e_c) * j / m_), ro_c * math.sin(e_c + (math.pi / 2 - e_c) * j / m_))
                 for j in range(m_, -1, -1)]
        prof = [(max(r_, 0.0), z_) for r_, z_ in prof]
        cols_c = [col_rib_in or col_in] * m_ + [col_edge] + [col_out] * m_ + [col_edge]
        for o in revolve_pieces(part, prof, crown_pieces, center=center, cols=cols_c, az0=az0, az1=az0 + 360.0,
                                ring=ring + 1, bevel=bevel):
            o["sub"] = "crown"; o["side"] = "R" if math.cos(math.radians(o["az"])) > 1e-6 else "L"
            for k_, v_ in (meta or {}).items():
                o[k_] = v_
            out.append(o)
    return out


def stairs(part, x0, x1, y_front, z0, n, tread, rise, col='x', direction=1):
    """n steps climbing toward +Y*direction starting at y_front. Each step = one piece."""
    out = []
    for k in range(n):
        ya = y_front + direction * k * tread
        yb = y_front + direction * (n * tread + 0.5)
        y0, y1 = min(ya, yb), max(ya, yb)
        out.append(box_piece(part, x0, x1, y0, y1, z0 + k * rise, z0 + (k + 1) * rise, col, bevel=0.05))
    return out


def door(part, x, y, z, width, height, leaf='x', frame='x', facing=-1, leaves=2, frame_w=0.7, depth=0.6):
    """Double door on a wall plane y (front face), facing -Y (facing=-1) or +Y."""
    out = []
    f = facing
    x0, x1 = x - width / 2, x + width / 2
    yb, yf = y, y + f * depth
    y0, y1 = min(yb, yf), max(yb, yf)
    mb = MB()
    mb.box(x0 - frame_w, x0, y0, y1, z, z + height + frame_w, frame)
    mb.box(x1, x1 + frame_w, y0, y1, z, z + height + frame_w, frame)
    mb.box(x0, x1, y0, y1, z + height, z + height + frame_w, frame)
    out.append(finish(mb, _pname(part), part, pivot=(x, y, z), bevel=0.05))
    lw = width / leaves
    for i in range(leaves):
        a, b = x0 + i * lw + 0.04, x0 + (i + 1) * lw - 0.04
        ly0, ly1 = min(y + f * 0.1, y + f * 0.35), max(y + f * 0.1, y + f * 0.35)
        mb = MB()
        mb.box(a, b, ly0, ly1, z, z + height - 0.04, leaf)
        # raised panels (2 per leaf)
        pa, pb = a + 0.28 * lw * 0.9, b - 0.28 * lw * 0.9
        pa, pb = a + 0.18 * lw, b - 0.18 * lw
        for (h0, h1) in ((0.1, 0.45), (0.55, 0.92)):
            py0, py1 = (ly0 - 0.12, ly0) if f < 0 else (ly1, ly1 + 0.12)
            mb.box(pa, pb, py0, py1, z + h0 * height, z + h1 * height, leaf)
        out.append(finish(mb, _pname(part), part, pivot=((a + b) / 2, y, z), bevel=0.04))
    return out


def floor_disc(part, center, radius, thick, base_col, tile=3.6, tile_cols=('x', 'y'), circle_col=None,
               tile_thick=0.12, n_seg=8):
    """Circular floor: base disc (n_seg sectors) + square tiles (every other with an inset circle)."""
    cx, cy, cz = center
    out = revolve_pieces(part, [(0.0, 0.0), (radius, 0.0), (radius, thick), (0.0, thick)], n_seg,
                         center=center, col=base_col, bevel=0.05, gap=0.02)
    n = int(radius // tile) + 1
    k = 0
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x, y = cx + i * tile, cy + j * tile
            hs = tile * 0.43
            if all(math.hypot(x + sx * hs - cx, y + sy * hs - cy) < radius - 0.4 for sx in (-1, 1) for sy in (-1, 1)):
                c = tile_cols[(i + j) % 2]
                mb = MB()
                mb.box(x - hs, x + hs, y - hs, y + hs, cz + thick, cz + thick + tile_thick, c)
                if circle_col and (i + j) % 2 == 0:
                    mb.cylinder(x, y, cz + thick + tile_thick, cz + thick + tile_thick * 1.8, hs * 0.72, col=circle_col, n=20)
                out.append(finish(mb, _pname(part), part, pivot=(x, y, cz + thick), bevel=0.04,
                                  meta={"r": math.hypot(x - cx, y - cy), "seg": k}))
                k += 1
    return out


def uv_sphere_globe(part, center, radius, line_hex, fill_hex, lines=(24, 12), wire=0.09, fill_alpha=0.035, fill_rim=0.3):
    """Outlined translucent sphere (diagram element): wire globe + faint fill. Two pieces."""
    out = []
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=lines[0], v_segments=lines[1], radius=radius)
    bmesh.ops.wireframe(bm, faces=bm.faces[:], thickness=wire, use_replace=True, use_even_offset=True)
    me = bpy.data.meshes.new(part + "_wire"); bm.to_mesh(me); bm.free()
    me.materials.append(line_material("PK_line_" + part, line_hex))
    ob = bpy.data.objects.new(part + ".wire", me); ob.location = center
    part_collection(part).objects.link(ob); PARTS.setdefault(part, []).append(ob)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=radius * 0.995)
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new(part + "_fill"); bm.to_mesh(me); bm.free()
    me.materials.append(glass_material("PK_glass_" + part, fill_hex, alpha=fill_alpha, rim=fill_rim))
    ob2 = bpy.data.objects.new(part + ".fill", me); ob2.location = center
    part_collection(part).objects.link(ob2); PARTS.setdefault(part, []).append(ob2)
    for o in (ob, ob2):
        o.visible_shadow = False
    return [ob, ob2]


def backdrop(radius=600.0, col='x', z=-0.02):
    """Endless paper table (not a part; never animated). Style real: piazza paving that fades into haze."""
    if STYLE == "real":
        import realkit
        col = "piazza" if "piazza" in _PAL else col
        z = realkit.GROUND_Z
    mb = MB()
    n = 64
    pts = [(radius * math.cos(2 * math.pi * k / n), radius * math.sin(2 * math.pi * k / n), z - 0.2) for k in range(n)]
    mb.prism(pts, (0, 0, 0.2), col)
    ob = finish(mb, "PK_backdrop", "_env", pivot=(0, 0, z), bevel=0,
                meta={"recipe": "ground"} if STYLE == "real" else None)
    PARTS.pop("_env", None)
    return ob


# ----------------------------------------------------------------------------- lighting / world
def studio(sun_az=-40.0, sun_el=50.0, sun_angle=9.0, sun_strength=3.2, sun_hex="#FFF4E2",
           fill_strength=0.6, fill_az=150.0, fill_el=35.0, fill_size=80.0, fill_dist=160.0,
           sky_top="#C9DCEA", sky_horizon="#F1ECE2", sky_light="#DCE6EE", sky_strength=0.9,
           bg_strength=1.0, target=(0, 0, 15)):
    """Soft studio light for paper models: soft-shadow sun (key) + big area softbox (fill) + sky."""
    sc = bpy.context.scene
    def dirv(az, el):
        a, e = math.radians(az), math.radians(el)
        return Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    ld = bpy.data.lights.new("PK_key", 'SUN')
    ld.energy = sun_strength; ld.angle = math.radians(sun_angle); ld.color = hex2lin(sun_hex)
    ob = bpy.data.objects.new("PK_key", ld); sc.collection.objects.link(ob)
    ob.rotation_euler = dirv(sun_az, sun_el).to_track_quat('Z', 'Y').to_euler()
    if fill_strength > 0:
        la = bpy.data.lights.new("PK_fill", 'AREA')
        la.shape = 'SQUARE'; la.size = fill_size
        la.energy = fill_strength * math.pi * fill_dist ** 2
        la.use_shadow = False
        ob2 = bpy.data.objects.new("PK_fill", la); sc.collection.objects.link(ob2)
        d = dirv(fill_az, fill_el)
        ob2.location = Vector(target) + d * fill_dist
        ob2.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
    w = bpy.data.worlds.new("PK_world"); sc.world = w
    w.use_nodes = True
    nt = w.node_tree; N = nt.nodes; L = nt.links; N.clear()
    tc = N.new('ShaderNodeTexCoord')
    sep = N.new('ShaderNodeSeparateXYZ'); L.new(tc.outputs['Generated'], sep.inputs[0])
    ramp = N.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.0; ramp.color_ramp.elements[0].color = (*hex2lin(sky_horizon), 1)
    ramp.color_ramp.elements[1].position = 0.55; ramp.color_ramp.elements[1].color = (*hex2lin(sky_top), 1)
    L.new(sep.outputs['Z'], ramp.inputs[0])
    bgc = N.new('ShaderNodeBackground'); bgc.inputs['Strength'].default_value = bg_strength
    L.new(ramp.outputs[0], bgc.inputs['Color'])
    bgl = N.new('ShaderNodeBackground'); bgl.inputs['Strength'].default_value = sky_strength
    bgl.inputs['Color'].default_value = (*hex2lin(sky_light), 1)
    lp = N.new('ShaderNodeLightPath')
    mix = N.new('ShaderNodeMixShader')
    L.new(lp.outputs['Is Camera Ray'], mix.inputs[0]); L.new(bgl.outputs[0], mix.inputs[1]); L.new(bgc.outputs[0], mix.inputs[2])
    out = N.new('ShaderNodeOutputWorld'); L.new(mix.outputs[0], out.inputs['Surface'])


# ----------------------------------------------------------------------------- animation presets
def _order(objs, order, seed=0, az0=0.0):
    objs = list(objs)
    if order == 'index':
        return objs
    if order == 'reverse':
        return objs[::-1]
    if order == 'random':
        r = random.Random(seed); r.shuffle(objs); return objs
    keyf = {
        'az': lambda o: (o.get("az", 0.0) - az0) % 360,
        'az_from_front': lambda o: min((o.get("az", 0.0) - 270) % 360, (270 - o.get("az", 0.0)) % 360),
        'x': lambda o: o.location.x, '-x': lambda o: -o.location.x,
        'y': lambda o: o.location.y, '-y': lambda o: -o.location.y,
        'z': lambda o: o.location.z,
        'radial': lambda o: math.hypot(o.location.x, o.location.y),
        'ring': lambda o: (o.get("ring", 0), o.get("seg", 0)),
    }[order]
    return sorted(objs, key=keyf)


def rise(objs, start, stagger=0.05, duration=0.6, mode='grow', order='index', overshoot=1.6,
         fold_angle=88.0, ring_step=None, seed=0, az0=0.0):
    """Paper pieces appear FROM THE GROUND (their own base) with a small overshoot.
    mode: 'grow' (extrude up from base), 'fold' (pop-up: hinge at base, folds up from lying
    outward), 'pop' (scale up from its pivot, for tiles/coffers/small parts).
    order: index|reverse|random|az|az_from_front|x|-x|y|-y|z|radial|ring.
    ring_step: seconds between rings when order == 'ring' (seg * stagger within a ring).
    Returns end time (s)."""
    objs = _order(objs, order, seed, az0)
    t_end = start
    for i, ob in enumerate(objs):
        if order == 'ring' and ring_step is not None:
            rings = sorted({o.get("ring", 0) for o in objs})
            ri = rings.index(ob.get("ring", 0))
            segs_in_ring = [o for o in objs if o.get("ring", 0) == ob.get("ring", 0)]
            t = start + ri * ring_step + segs_in_ring.index(ob) * stagger
        else:
            t = start + i * stagger
        f0, f1 = sec2f(t), max(sec2f(t + duration), sec2f(t) + 2)
        t_end = max(t_end, t + duration)
        ob.scale = (0, 0, 0); _key(ob, "scale", f0 - 1, 'CONSTANT')
        if mode == 'grow':
            ob.scale = (1, 1, 0.001); _key(ob, "scale", f0, 'BACK', back=overshoot)
            ob.scale = (1, 1, 1); _key(ob, "scale", f1)
        elif mode == 'pop':
            ob.scale = (0.001, 0.001, 0.001); _key(ob, "scale", f0, 'BACK', back=overshoot)
            ob.scale = (1, 1, 1); _key(ob, "scale", f1)
        elif mode == 'fold':
            ob.scale = (1, 1, 1); _key(ob, "scale", f0, 'CONSTANT')
            ax = ob.get("hinge", (1.0, 0.0, 0.0))
            ob.rotation_mode = 'AXIS_ANGLE'
            ob.rotation_axis_angle = (math.radians(fold_angle), ax[0], ax[1], ax[2])
            _key(ob, "rotation_axis_angle", f0, 'BACK', back=overshoot)
            ob.rotation_axis_angle = (0.0, ax[0], ax[1], ax[2])
            _key(ob, "rotation_axis_angle", f1)
        else:
            raise ValueError(mode)
    return t_end


def sink(objs, t, stagger=0.0, duration=0.3, order='index', az0=0.0):
    """Reverse of the rise (loop endings: 'rise from the ground,
    return to the ground').
    Pieces translate straight down below the paper board (which hides them), then switch off."""
    t_end = t
    for i, ob in enumerate(_order(objs, order, 0, az0)):
        ti = t + i * stagger
        f0, f1 = sec2f(ti), max(sec2f(ti + duration), sec2f(ti) + 2)
        top = ob.location.z + max(v[2] for v in ob.bound_box) * max(ob.scale.z, 1.0)
        loc = ob.location.copy()
        _key(ob, "location", f0, 'SINE', easing='EASE_IN')
        ob.location = (loc.x, loc.y, loc.z - top - 1.5); _key(ob, "location", f1, 'CONSTANT')
        ob.location = loc
        ob.scale = (1, 1, 1); _key(ob, "scale", f1, 'CONSTANT')
        ob.scale = (0, 0, 0); _key(ob, "scale", f1 + 1, 'CONSTANT')
        ob.scale = (1, 1, 1)
        t_end = max(t_end, ti + duration)
    return t_end


def spot_light(name, pos, target, radius_at_target=4.5, power=3.0e6, hexcol="#FFE9B0", blend=0.2, soft=0.3):
    """Narrow spot (e.g. sunlight through an oculus, a light pool on the ground)."""
    ld = bpy.data.lights.new(name, 'SPOT')
    d = Vector(target) - Vector(pos)
    ld.spot_size = 2 * math.atan(radius_at_target / d.length)
    ld.spot_blend = blend; ld.energy = power; ld.color = hex2lin(hexcol)
    ld.shadow_soft_size = soft
    ob = bpy.data.objects.new(name, ld); bpy.context.scene.collection.objects.link(ob)
    ob.location = pos
    ob.rotation_euler = (-d).normalized().to_track_quat('Z', 'Y').to_euler()
    return ob


def text_piece(part, text, pos, size, col, facing="-y", depth=0.08, font=None, meta=None):
    """Raised lettering as a paper piece (inscriptions, plaques). Origin = text centre.
    facing: '-y' (on a front facade), '+z' (lying on the ground)."""
    cu = bpy.data.curves.new(_pname(part) + "_txt", 'FONT')
    cu.body = text; cu.size = size; cu.align_x = 'CENTER'; cu.align_y = 'CENTER'
    cu.extrude = depth / 2; cu.resolution_u = 4
    if font and os.path.exists(os.path.expanduser(font)):
        cu.font = bpy.data.fonts.load(os.path.expanduser(font), check_existing=True)
    tmp = bpy.data.objects.new("_pk_tmp_txt", cu); bpy.context.scene.collection.objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp); bpy.data.curves.remove(cu)
    if facing == "-y":
        me.transform(Matrix.Rotation(math.radians(90), 4, 'X'))
    npoly = len(me.polygons)
    c = _PAL[col]
    a = me.attributes.new("paper_col", 'FLOAT_COLOR', 'FACE'); a.data.foreach_set("color", [c[0], c[1], c[2], 1.0] * npoly)
    b = me.attributes.new("paper_edge", 'FLOAT', 'FACE'); b.data.foreach_set("value", [0.0] * npoly)
    me.materials.clear()
    if STYLE == "real":
        import realkit
        realkit.assign_materials(me, [_pidx(col)] * npoly)
    else:
        me.materials.append(paper_material())
        me.polygons.foreach_set("material_index", [0] * npoly)
    ob = bpy.data.objects.new(_pname(part), me)
    ob.location = Vector(pos)
    ob["pk_rest"] = tuple(pos)
    part_collection(part).objects.link(ob)
    ob["pk_part"] = part
    for k, v in (meta or {}).items():
        ob[k] = v
    PARTS.setdefault(part, []).append(ob)
    return [ob]


def vanish(objs, t, duration=0.5):
    """Shrink pieces away (e.g. hide a diagram before the next shot)."""
    for ob in objs:
        ob.scale = (1, 1, 1); _key(ob, "scale", sec2f(t), 'SINE', easing='EASE_IN')
        ob.scale = (0, 0, 0); _key(ob, "scale", sec2f(t + duration), 'CONSTANT')
    return t + duration


def section_cut(t_start, duration, az=90.0, center=(0, 0, 0), from_dist=60.0):
    """Sweep the clipping plane from the camera side (camera azimuth `az`) to `center`,
    cutting the model in half; back faces show as flat poche."""
    e = bpy.data.objects["PK_SectionPlane"]
    e.rotation_euler = (0, 0, math.radians(az))
    a = math.radians(az)
    d = Vector((math.sin(a), -math.cos(a), 0))
    c = Vector(center)
    e.location = c + d * 1e4; _key(e, "location", 0, 'CONSTANT'); _key(e, "rotation_euler", 0, 'CONSTANT')
    e.location = c + d * from_dist; _key(e, "location", sec2f(t_start), 'SINE', easing='EASE_IN_OUT')
    e.location = c - d * 0.08; _key(e, "location", sec2f(t_start + duration))


def section_restore(t_start, duration, az=90.0, center=(0, 0, 0), to_dist=80.0):
    e = bpy.data.objects["PK_SectionPlane"]
    a = math.radians(az)
    d = Vector((math.sin(a), -math.cos(a), 0))
    e.location = Vector(center) - d * 0.08; _key(e, "location", sec2f(t_start), 'SINE', easing='EASE_IN_OUT')
    e.location = Vector(center) + d * to_dist; _key(e, "location", sec2f(t_start + duration), 'CONSTANT')
    e.location = Vector(center) + d * 1e4; _key(e, "location", sec2f(t_start + duration) + 1, 'CONSTANT')


# ----------------------------------------------------------------------------- camera
def camera_rig(lens=38.0, clip_end=3000.0):
    sc = bpy.context.scene
    piv = bpy.data.objects.new("PK_CamPivot", None); sc.collection.objects.link(piv)
    cd = bpy.data.cameras.new("PK_Cam"); cd.lens = lens; cd.clip_start = 0.2; cd.clip_end = clip_end
    cd.sensor_fit = 'AUTO'
    cam = bpy.data.objects.new("PK_Cam", cd); sc.collection.objects.link(cam)
    cam.parent = piv
    cam.rotation_euler = (math.radians(90), 0, 0)
    cam.location = (0, -100, 0)
    sc.camera = cam
    return piv, cam


def camera_keys(keys):
    """keys: [{t, az, el, dist, target:[x,y,z], lens, interp:'EASE'|'LINEAR'|'HOLD'}]
    az: 0 = camera on -Y looking +Y (front), 90 = camera on +X. el may be negative (look up).
    Alternatively {t, loc:[..], target:[..]} is converted to az/el/dist."""
    piv = bpy.data.objects.get("PK_CamPivot") or camera_rig()[0]
    cam = bpy.data.objects["PK_Cam"]
    for k in keys:
        if "loc" in k:
            d = Vector(k["loc"]) - Vector(k["target"])
            dist = d.length
            el = math.degrees(math.asin(d.z / dist))
            az = math.degrees(math.atan2(d.x, -d.y))
            k = dict(k, az=az, el=el, dist=dist)
        f = sec2f(k["t"])
        it = {'EASE': 'BEZIER', 'LINEAR': 'LINEAR', 'HOLD': 'CONSTANT'}[k.get("interp", "EASE")]
        piv.location = k["target"]
        piv.rotation_euler = (-math.radians(k["el"]), 0, math.radians(k["az"]))
        cam.location = (0, -k["dist"], 0)
        cam.data.lens = k.get("lens", cam.data.lens)
        _key(piv, "location", f, it); _key(piv, "rotation_euler", f, it)
        _key(cam, "location", f, it); _key(cam.data, "lens", f, it)
    cuts = [sec2f(k["t"]) for k in keys if k.get("interp") == "HOLD"]
    if cuts:     # a HOLD key is a cut: approach it linearly, leave the next key linearly (no bezier bulge)
        for ob in (piv, cam, cam.data):
            for fc in _fcurves(ob):
                pts = list(fc.keyframe_points)
                for j, kp in enumerate(pts):
                    if int(round(kp.co.x)) in cuts:
                        kp.handle_left_type = 'VECTOR'
                        if j + 1 < len(pts):
                            pts[j + 1].handle_right_type = 'VECTOR'
                fc.update()


def cam_orbit(t0, t1, az0, az1, el, dist, target, lens=38.0):
    return [dict(t=t0, az=az0, el=el, dist=dist, target=target, lens=lens, interp='LINEAR'),
            dict(t=t1, az=az1, el=el, dist=dist, target=target, lens=lens)]


def cam_push_in(t0, t1, az, el, dist0, dist1, target, lens=38.0):
    return [dict(t=t0, az=az, el=el, dist=dist0, target=target, lens=lens),
            dict(t=t1, az=az, el=el, dist=dist1, target=target, lens=lens)]


def cam_top(t, dist, target, az=0.0, lens=38.0):
    return [dict(t=t, az=az, el=89.5, dist=dist, target=target, lens=lens)]


# ----------------------------------------------------------------------------- anchors (label leader lines)
def _part_bbox(part):
    mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
    for ob in PARTS.get(part, []):
        if ob.scale.length < 1e-4:
            continue
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            mn = Vector(map(min, mn, w)); mx = Vector(map(max, mx, w))
    return mn, mx


_FOLLOW = {}


def _follow_obj(a):
    f = a["follow"]
    key = a["name"]
    if key not in _FOLLOW:
        objs = select(f)
        if "az" in f:
            objs = sorted(objs, key=lambda o: min((o.get("az", 0.0) - f["az"]) % 360, (f["az"] - o.get("az", 0.0)) % 360))
        elif "near" in f:
            objs = sorted(objs, key=lambda o: (Vector(o.get("pk_rest", (0, 0, 0))) - Vector(f["near"])).length)
        ob = objs[0] if objs else None
        _FOLLOW[key] = (ob, ob.matrix_world.inverted().copy() if ob else None)      # captured at rest (frame 1)
    return _FOLLOW[key]


def anchor_world(a):
    if "follow" in a:
        ob, inv = _follow_obj(a)
        if ob is None:
            return Vector(a["pos"])
        if ob.hide_render and a.get("hide_follows", True):
            return None
        return ob.matrix_world @ (inv @ Vector(a["pos"]))
    if "pos" in a:
        return Vector(a["pos"])
    mn, mx = _part_bbox(a["part"])
    if mn.x > mx.x:
        return None
    c = (mn + mx) / 2
    wh = a.get("where", "top")
    if wh == "top":
        return Vector((c.x, c.y, mx.z))
    if wh == "front":
        return Vector((c.x, mn.y, c.z))
    return c


def export_anchors(anchors, path, t0=0.0, t1=None, step=1):
    """Per-frame screen positions (pixels of the FULL 1080x1920 frame, origin top-left) of named
    anchors -> JSON. Each sample: [x, y, flags] with flags: 1 = in front of camera & in frame,
    2 = occluded by paper geometry (ray cast; ignores the shader section clip)."""
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    W, H = RES
    f0 = sec2f(t0); f1 = sc.frame_end if t1 is None else sec2f(t1)
    out = {"fps": FPS, "width": W, "height": H, "frame_start": f0, "frame_end": f1, "t0": t0,
           "note": "frame 1 == t 0.0 s; sample i -> frame frame_start + i*step", "step": step, "anchors": {}}
    for a in anchors:
        out["anchors"][a["name"]] = []
    sc.frame_set(1)
    _FOLLOW.clear()
    for a in anchors:            # capture rest matrices of followed pieces at frame 1
        if "follow" in a:
            _follow_obj(a)
    for f in range(f0, f1 + 1, step):
        sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        cam = sc.camera
        cpos = cam.matrix_world.translation
        for a in anchors:
            w = anchor_world(a)
            if w is None:
                out["anchors"][a["name"]].append(None); continue
            co = world_to_camera_view(sc, cam, w)
            flags = 1 if (co.z > 0 and 0 <= co.x <= 1 and 0 <= co.y <= 1) else 0
            d = w - cpos
            dist = d.length
            hit, loc, *_ = sc.ray_cast(dg, cpos, d.normalized(), distance=max(dist - 1.0, 0.01))
            if hit:
                flags |= 2
            out["anchors"][a["name"]].append([round(co.x * W, 1), round((1 - co.y) * H, 1), flags])
    with open(path, "w") as fh:
        json.dump(out, fh)
    return out


# ----------------------------------------------------------------------------- render
def render_setup(draft=False, samples=None, duration=None, video=False, out_dir=None, quality=None):
    """quality: {"raytracing": bool, "fast_gi": bool, "shadow_rays": int, "shadow_steps": int,
    "gi_resolution": "2"|"4"...}  (episode JSON "render" block)."""
    q = dict(raytracing=True, fast_gi=True, shadow_rays=1, shadow_steps=6, rt_resolution='2', gi_resolution='2',
             shadow_res=1.0, shadows=True)
    q.update(quality or {})
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x, sc.render.resolution_y = RES
    sc.render.resolution_percentage = 50 if draft else 100
    sc.render.fps = FPS
    ee = sc.eevee
    ee.taa_render_samples = samples or (16 if draft else 24)
    ee.use_shadows = bool(q["shadows"])
    ee.shadow_resolution_scale = float(q["shadow_res"])
    ee.shadow_ray_count = q["shadow_rays"]
    ee.shadow_step_count = q["shadow_steps"]
    ee.use_raytracing = q["raytracing"]
    ee.ray_tracing_method = 'SCREEN'
    ee.use_fast_gi = q["fast_gi"]
    ee.fast_gi_method = 'GLOBAL_ILLUMINATION'
    ee.fast_gi_distance = 12.0
    for attr, key in (("ray_tracing_options.resolution_scale", "rt_resolution"), ("fast_gi_resolution", "gi_resolution")):
        try:
            tgt = ee.ray_tracing_options if attr.startswith("ray") else ee
            setattr(tgt, attr.split(".")[-1], q[key])
        except Exception as ex:
            print("[paperkit] render opt", attr, ex)
    try:
        sc.view_settings.view_transform = 'AgX'
        sc.view_settings.look = 'AgX - Medium High Contrast'
    except Exception:
        pass
    if STYLE == "real":
        import realkit
        realkit.post_render_setup(q)
    sc.render.film_transparent = False
    sc.render.use_persistent_data = True
    if duration:
        sc.frame_start = 1; sc.frame_end = sec2f(duration)
    im = sc.render.image_settings
    if video:
        im.file_format = 'FFMPEG'
        sc.render.ffmpeg.format = 'MPEG4'; sc.render.ffmpeg.codec = 'H264'
        sc.render.ffmpeg.constant_rate_factor = 'HIGH'
    else:
        im.file_format = 'PNG'; im.color_mode = 'RGB'; im.compression = 15
    if out_dir:
        sc.render.filepath = os.path.join(out_dir, "")


def render_state():
    """Current render-quality settings (for logs / bench tables)."""
    sc = bpy.context.scene
    ee = sc.eevee
    ct = getattr(sc, "compositing_node_group", None)
    return dict(res="%dx%d@%d" % (sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage),
                samples=ee.taa_render_samples, shadow_res=round(ee.shadow_resolution_scale, 3),
                raytracing=ee.use_raytracing, fast_gi=ee.use_fast_gi, shadow_rays=ee.shadow_ray_count,
                shadow_steps=ee.shadow_step_count, vol_tile=ee.volumetric_tile_size,
                vol_samples=ee.volumetric_samples,
                denoise=bool(ct and any(n.bl_idname == "CompositorNodeDenoise" and not n.mute for n in ct.nodes)))


def _set_denoise(on):
    """Insert/enable (or mute) an OIDN Denoise node between Render Layers and the first node it feeds."""
    sc = bpy.context.scene
    ct = getattr(sc, "compositing_node_group", None)
    if ct is None:
        if not on:
            return
        ct = bpy.data.node_groups.new("PK_comp", "CompositorNodeTree")
        ct.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
        rl = ct.nodes.new("CompositorNodeRLayers"); o = ct.nodes.new("NodeGroupOutput")
        ct.links.new(rl.outputs['Image'], o.inputs[0])
        sc.compositing_node_group = ct; sc.render.use_compositing = True
    dn = next((n for n in ct.nodes if n.bl_idname == "CompositorNodeDenoise"), None)
    if dn is None:
        if not on:
            return
        vl = bpy.context.view_layer
        vl.use_pass_normal = True; vl.use_pass_diffuse_color = True
        rl = next(n for n in ct.nodes if n.bl_idname == "CompositorNodeRLayers")
        lk = next(l for l in ct.links if l.from_node == rl and l.from_socket.name == "Image")
        dst = lk.to_socket
        dn = ct.nodes.new("CompositorNodeDenoise")
        ct.links.remove(lk)
        ct.links.new(rl.outputs['Image'], dn.inputs['Image'])
        for sock, name in (("Normal", "Normal"), ("DiffCol", "Albedo")):
            if sock in rl.outputs and name in dn.inputs:
                ct.links.new(rl.outputs[sock], dn.inputs[name])
        ct.links.new(dn.outputs['Image'], dst)
        for attr, val in (("prefilter", 'ACCURATE'), ("quality", 'HIGH'), ("use_hdr", True)):
            try:
                setattr(dn, attr, val)
            except Exception:
                pass
    dn.mute = not on


def apply_render_overrides(q):
    """Change render quality in a running scene (persistent data stays on). Keys: samples, shadow_res, raytracing,
    fast_gi, shadow_rays, shadow_steps, vol_tile (px: 2/4/8/16), vol_samples, denoise (compositor OIDN).
    Used by run_episode --anim for the episode's per-time-range "render_segments" and by bench_render.py."""
    ee = bpy.context.scene.eevee
    b = lambda v: v not in (0, "0", False, "false", "False", None)
    if "samples" in q: ee.taa_render_samples = int(q["samples"])
    if "shadow_res" in q: ee.shadow_resolution_scale = float(q["shadow_res"])
    if "raytracing" in q: ee.use_raytracing = b(q["raytracing"])
    if "fast_gi" in q: ee.use_fast_gi = b(q["fast_gi"])
    if "shadow_rays" in q: ee.shadow_ray_count = int(q["shadow_rays"])
    if "shadow_steps" in q: ee.shadow_step_count = int(q["shadow_steps"])
    if "vol_tile" in q: ee.volumetric_tile_size = str(int(q["vol_tile"]))
    if "vol_samples" in q: ee.volumetric_samples = int(q["vol_samples"])
    if "denoise" in q: _set_denoise(b(q["denoise"]))


def render_still(t, path):
    sc = bpy.context.scene
    sc.frame_set(sec2f(t))
    sc.render.filepath = path
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    return time.time() - t0


# ----------------------------------------------------------------------------- exploded views
EASE = {"EASE": ("BEZIER", "AUTO"), "LINEAR": ("LINEAR", "AUTO"), "BACK": ("BACK", "EASE_OUT"),
        "SINE": ("SINE", "EASE_IN_OUT"), "QUAD": ("QUAD", "EASE_IN_OUT"), "CUBIC": ("CUBIC", "EASE_IN_OUT"),
        "EXPO": ("EXPO", "EASE_IN_OUT"), "IN": ("SINE", "EASE_IN"), "OUT": ("SINE", "EASE_OUT")}
GROUPS = {}          # name -> pivot empty (objects parented to it rotate/translate together)
_OFF = {}            # object/empty name -> current offset (Vector) relative to rest
_ROT = {}            # empty name -> current rotation (deg, per axis index)


def select(sel):
    """Selector shared by explode/groups/visibility: {part | parts:[..], role (str|list), rings:[..],
    only:[names], match:{meta_key: value | [values]}, side: 'R'|'L' (by rest x sign), objects:[names]}."""
    if sel.get("objects"):
        return [bpy.data.objects[n] for n in sel["objects"] if n in bpy.data.objects]
    parts = sel.get("parts") or ([sel["part"]] if "part" in sel else [p for p in PARTS if not p.startswith("_")])
    objs = [o for p in parts for o in PARTS.get(p, [])]
    if "role" in sel:
        roles = sel["role"] if isinstance(sel["role"], list) else [sel["role"]]
        objs = [o for o in objs if o.get("role") in roles]
    if "rings" in sel:
        objs = [o for o in objs if o.get("ring", 0) in sel["rings"]]
    if "only" in sel:
        objs = [o for o in objs if o.name in sel["only"]]
    if "side" in sel:
        objs = [o for o in objs if side_of(o) == sel["side"]]
    for k, v in sel.get("match", {}).items():
        vs = v if isinstance(v, list) else [v]
        objs = [o for o in objs if o.get(k) in vs]
    if "not" in sel:
        drop = set(o.name for o in select(sel["not"]))
        objs = [o for o in objs if o.name not in drop]
    return objs


def side_of(o):
    """'R' (x > 0) / 'L': meta 'side', else from the piece's plan azimuth 'az', else its rest position."""
    if o.get("side") in ("R", "L"):
        return o["side"]
    if "az" in o:
        return "R" if math.cos(math.radians(o["az"])) > 1e-6 else "L"
    return "R" if o.get("pk_rest", (0, 0, 0))[0] > 0 else "L"


def make_group(name, objs, pivot, parent=None):
    """Pivot empty at `pivot`; objs are parented to it keeping their rest transform (local location == rest
    world location while the empty is unrotated), so a group rotation swings them like a door on a hinge.
    parent: another group name (nested hinges: the child group's angle adds to the parent's)."""
    sc = bpy.context.scene
    e = bpy.data.objects.new("GRP_" + name, None)
    e.empty_display_type = 'ARROWS'
    sc.collection.objects.link(e)
    e.location = Vector(pivot)
    if parent:
        pe = GROUPS[parent]
        bpy.context.view_layer.update()
        e.parent = pe
        e.matrix_parent_inverse = pe.matrix_world.inverted()
    bpy.context.view_layer.update()
    for o in objs:
        mw = o.matrix_world.copy()
        o.parent = e
        o.matrix_parent_inverse = e.matrix_world.inverted()
        o.matrix_world = mw
    GROUPS[name] = e
    return e


def _k_move(ob, path, idx_vals, f0, f1, easing, overshoot):
    """key current value at f0 (segment f0->f1 uses `easing`), then the new values at f1."""
    it, ea = EASE.get(easing, EASE["EASE"])
    cur, new = idx_vals
    setattr(ob, path, cur); _key(ob, path, f0, it if it != 'BEZIER' else None, easing=ea, back=overshoot)
    if it == 'BACK':
        for fc in _fcurves(ob):
            if fc.data_path == path:
                for kp in fc.keyframe_points:
                    if abs(kp.co.x - f0) < 0.01:
                        kp.interpolation = 'BACK'; kp.easing = 'EASE_OUT'; kp.back = overshoot
    setattr(ob, path, new); _key(ob, path, f1)


def explode(objs, t, dur=1.0, offset=(0, 0, 0), step=None, step_by="ring", radial=0.0, center=(0, 0, 0),
            stagger=0.0, order="index", easing="EASE", overshoot=1.3, ring_step=None, to_rest=False, az0=0.0):
    """Exploded-view move (translation) of pieces, relative to where they are now (moves stack in time order).
    offset: world vector for every piece; step + step_by ('ring' | 'index'): extra offset = rank * step
    (vertical spread of rings/bands); radial: metres outward from `center` in plan; to_rest: back to the
    built position (reassemble). stagger/order/ring_step as in rise(). easing: EASE LINEAR BACK SINE QUAD
    CUBIC EXPO IN OUT; overshoot = BACK strength. Returns end time."""
    objs = _order(objs, order, 0, az0)
    ranks = {}
    if step is not None:
        keys = sorted({(o.get("ring", 0) if step_by == "ring" else i) for i, o in enumerate(objs)})
        ranks = {k: j for j, k in enumerate(keys)}
    rings = sorted({o.get("ring", 0) for o in objs})
    t_end = t
    for i, ob in enumerate(objs):
        if order == "ring" and ring_step is not None:
            same = [o for o in objs if o.get("ring", 0) == ob.get("ring", 0)]
            ti = t + rings.index(ob.get("ring", 0)) * ring_step + same.index(ob) * stagger
        else:
            ti = t + i * stagger
        f0, f1 = sec2f(ti), max(sec2f(ti + dur), sec2f(ti) + 2)
        rest = Vector(ob.get("pk_rest_loc", ob.location[:]))
        if "pk_rest_loc" not in ob:
            ob["pk_rest_loc"] = tuple(ob.location)
        cur = _OFF.get(ob.name, Vector((0, 0, 0)))
        if to_rest:
            new = Vector((0, 0, 0))
        else:
            new = cur + Vector(offset)
            if step is not None:
                new = new + Vector(step) * ranks[ob.get("ring", 0) if step_by == "ring" else i]
            if radial:
                d = Vector((rest.x - center[0], rest.y - center[1], 0))
                if d.length > 1e-6:
                    new = new + d.normalized() * radial
        _k_move(ob, "location", (rest + cur, rest + new), f0, f1, easing, overshoot)
        _OFF[ob.name] = new
        t_end = max(t_end, ti + dur)
    return t_end


def reassemble(objs, t, dur=0.8, stagger=0.02, order="index", overshoot=1.3, easing="BACK", ring_step=None):
    """Everything back to its built position with a small overshoot (loop endings)."""
    moved = [o for o in objs if o.name in _OFF and _OFF[o.name].length > 1e-6]
    return explode(moved, t, dur, stagger=stagger, order=order, easing=easing, overshoot=overshoot,
                   ring_step=ring_step, to_rest=True)


def group_move(name, t, dur=1.0, rotate=None, offset=None, to_rest=False, easing="EASE", overshoot=1.3):
    """Animate a pivot group: rotate {axis:'X'|'Y'|'Z', angle: deg (added to the current angle)} and/or
    offset [x,y,z] (added). to_rest returns the group to angle 0 / offset 0."""
    e = GROUPS[name]
    f0, f1 = sec2f(t), max(sec2f(t + dur), sec2f(t) + 2)
    if rotate or to_rest:
        e.rotation_mode = 'XYZ'
        cur = list(_ROT.get(name, [0.0, 0.0, 0.0]))
        new = [0.0, 0.0, 0.0] if to_rest else list(cur)
        if rotate:
            new["XYZ".index(rotate.get("axis", "Z"))] += rotate["angle"]
        _k_move(e, "rotation_euler", (tuple(math.radians(a) for a in cur), tuple(math.radians(a) for a in new)),
                f0, f1, easing, overshoot)
        _ROT[name] = new
    if offset or to_rest:
        rest = Vector(e.get("pk_rest_loc", e.location[:]))
        if "pk_rest_loc" not in e:
            e["pk_rest_loc"] = tuple(e.location)
        cur = _OFF.get(e.name, Vector((0, 0, 0)))
        new = Vector((0, 0, 0)) if to_rest else cur + Vector(offset or (0, 0, 0))
        if (new - cur).length > 1e-6 or not to_rest:
            _k_move(e, "location", (rest + cur, rest + new), f0, f1, easing, overshoot)
        _OFF[e.name] = new
    return t + dur


def apply_groups(groups):
    """episode "groups": [{name, pivot:[x,y,z], parent: group|null, select: {...} | members: [{...}, ...]}]
    Built in list order (a parent group must come first)."""
    taken = set()
    for g in groups:
        objs = []
        for sel in g.get("members", [g.get("select", {})]):
            objs += [o for o in select(sel) if o.name not in taken]
        taken.update(o.name for o in objs)
        make_group(g["name"], objs, g.get("pivot", (0, 0, 0)), g.get("parent"))
        print("[paperkit] group %-10s %4d pieces  pivot %s" % (g["name"], len(objs), g.get("pivot")))


def apply_explode(moves):
    """episode "explode": list of moves, applied in time order:
      {t, dur, select:{...}, offset, step, step_by, radial, center, stagger, order, ring_step, easing, overshoot}
      {t, dur, group:"name", rotate:{axis, angle}, offset, easing, overshoot}
      {t, dur, reassemble:true, select:{...} (default: everything moved), groups:[names]|"all", stagger, order}"""
    for m in sorted(moves, key=lambda m: m["t"]):
        kw = {k: m[k] for k in ("stagger", "order", "easing", "overshoot", "ring_step") if k in m}
        if m.get("reassemble"):
            if "select" in m:        # "select": null -> groups only
                objs = select(m["select"]) if m["select"] else []
            else:
                objs = [bpy.data.objects[n] for n in _OFF if n in bpy.data.objects and not n.startswith("GRP_")]
            if objs:
                kw.setdefault("stagger", 0.0)       # JSON: whole rings/bands move together unless stagger is given
                reassemble(objs, m["t"], m.get("dur", 0.8), **kw)
            gs = list(GROUPS) if m.get("groups") == "all" else m.get("groups", [])
            for j, g in enumerate(gs):
                group_move(g, m["t"] + j * m.get("group_stagger", 0.0), m.get("dur", 0.8), to_rest=True,
                           easing=m.get("easing", "BACK"), overshoot=m.get("overshoot", 1.3))
        elif m.get("group"):
            group_move(m["group"], m["t"], m.get("dur", 1.0), rotate=m.get("rotate"), offset=m.get("offset"),
                       easing=m.get("easing", "EASE"), overshoot=m.get("overshoot", 1.3))
        else:
            objs = select(m.get("select", {}))
            if not objs:
                print("[paperkit] WARNING: explode selector matched nothing:", m.get("select")); continue
            explode(objs, m["t"], m.get("dur", 1.0), offset=m.get("offset", (0, 0, 0)), step=m.get("step"),
                    step_by=m.get("step_by", "ring"), radial=m.get("radial", 0.0), center=m.get("center", (0, 0, 0)),
                    az0=m.get("az0", 0.0), **kw)


def apply_visibility(vis):
    """episode "visibility": [{select:{...}, show:[[t0, t1], ...]}]: rendered only inside the windows."""
    for v in vis:
        for ob in select(v["select"]):
            ob.hide_render = True; ob.keyframe_insert("hide_render", frame=0)
            for t0, t1 in v["show"]:
                ob.hide_render = False; ob.keyframe_insert("hide_render", frame=sec2f(t0))
                ob.hide_render = True; ob.keyframe_insert("hide_render", frame=sec2f(t1))
            for fc in _fcurves(ob):
                if fc.data_path == "hide_render":
                    for kp in fc.keyframe_points:
                        kp.interpolation = 'CONSTANT'


def hide_parts(sels):
    """episode "hide": [{selector}] -> not rendered, not in anchor ray casts (e.g. parts a scan replaces)."""
    n = 0
    for sel in sels:
        for ob in select(sel):
            ob.hide_render = True; ob.hide_viewport = True; n += 1
    return n


# ----------------------------------------------------------------------------- episode driver
def apply_schedule(schedule):
    """schedule: [{part, t, dur, stagger, mode, order, overshoot, fold_angle, ring_step, only:[names]}]"""
    ends = {}
    for s in schedule:
        objs = PARTS.get(s["part"], [])
        if "only" in s:
            objs = [o for o in objs if o.name in s["only"]]
        if "rings" in s:
            objs = [o for o in objs if o.get("ring", 0) in s["rings"]]
        if "role" in s:
            objs = [o for o in objs if o.get("role") == s["role"]]
        if s.get("mode") == "vanish":
            ends[s["part"]] = vanish(objs, s["t"], s.get("dur", 0.5)); continue
        if s.get("mode") == "sink":
            ends[s["part"]] = sink(objs, s["t"], stagger=s.get("stagger", 0.0), duration=s.get("dur", 0.3),
                                   order=s.get("order", "index"), az0=s.get("az0", 0.0)); continue
        if not objs:
            print("[paperkit] WARNING: schedule part '%s' has no pieces" % s["part"]); continue
        ends[s["part"]] = rise(objs, s["t"], stagger=s.get("stagger", 0.04), duration=s.get("dur", 0.6),
                               mode=s.get("mode", "grow"), order=s.get("order", "index"),
                               overshoot=s.get("overshoot", 1.6), fold_angle=s.get("fold_angle", 88.0),
                               ring_step=s.get("ring_step"), seed=s.get("seed", 0), az0=s.get("az0", 0.0))
    return ends


def apply_episode(spec):
    """Everything after geometry: palette already set, parts built. Applies look, schedule,
    section, camera, render settings."""
    if STYLE == "real":
        import realkit
        realkit.lighting(spec.get("real_look", {}))
    else:
        studio(**spec.get("look", {}))
    for sp_ in spec.get("spots", []):
        spot_light(sp_.get("name", "PK_spot"), sp_["pos"], sp_["target"], sp_.get("radius", 4.5),
                   sp_.get("power", 3.0e6), sp_.get("color", "#FFE9B0"), sp_.get("blend", 0.2), sp_.get("soft", 0.3))
    if spec.get("groups"):
        apply_groups(spec["groups"])
    apply_schedule(spec.get("schedule", []))
    apply_explode(spec.get("explode", []))
    apply_visibility(spec.get("visibility", []))
    for sec in spec.get("section", []):
        if sec.get("restore"):
            section_restore(sec["t"], sec["dur"], az=sec.get("az", 90), center=sec.get("center", (0, 0, 0)))
        else:
            section_cut(sec["t"], sec["dur"], az=sec.get("az", 90), center=sec.get("center", (0, 0, 0)),
                        from_dist=sec.get("from", 60))
    camera_rig(lens=spec.get("lens", 38))
    camera_keys(spec.get("camera", []))
    sc = bpy.context.scene
    sc.frame_start = 1; sc.frame_end = sec2f(spec.get("duration", 40))


def stats():
    n = sum(len(v) for v in PARTS.values())
    tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for v in PARTS.values() for o in v)
    return {"pieces": n, "tris": tris, "parts": {k: len(v) for k, v in PARTS.items()}}


# ----------------------------------------------------------------------------- JSON-only buildings
COMPONENTS = ("box_piece", "sheet", "revolve_pieces", "cylinder_wall", "ring_band", "column", "columns_at",
              "column_ring", "gable", "dome_shell", "coffers", "arches", "stairs", "door", "floor_disc",
              "uv_sphere_globe", "text_piece", "window_crown", "pendentive", "arch_barrel", "ribbed_dome",
              "profile_prism")


def build_parts(parts):
    """Episode JSON "parts": [{"part": "ring_wall", "component": "cylinder_wall", "role": "drum",
    "args": {...}}, ...]  -> builds every piece in order (order = default build order)."""
    for p in parts:
        if p["component"] not in COMPONENTS:
            raise ValueError("unknown component %s (have %s)" % (p["component"], COMPONENTS))
        before = len(PARTS.get(p["part"], []))
        globals()[p["component"]](p["part"], **p.get("args", {}))
        for o in PARTS.get(p["part"], [])[before:]:
            if p.get("role"):
                o["role"] = p["role"]
            if p.get("hidden"):
                o.scale = (0, 0, 0)
    return stats()
