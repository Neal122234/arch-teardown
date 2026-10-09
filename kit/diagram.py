"""diagram.py - structural diagram pieces for the exploded-view episodes (Blender, style real).

"Show what it does, not just what it is" (STANDARD.md 3.4): gold load lines that flow down a structure, red-orange
thrust arrows that grow outward, rings that light up, pieces that fill with gold from the top down, ghost fades of
real pieces. Generalised from ep01's wall diagram (build_pantheon._wall_diagram, which keeps its own copy).

Two ways in:
  episode "ghost": [{"select": {selector}, "keys": [[t, value], ...]}]      pk_ghost keys (0 opaque .. 1 gone) on real
      pieces (every realkit material reads the object prop pk_ghost); applied by run_episode after apply_episode.
  builder hook after_episode(pk, spec): run_episode calls it (if the builder defines it) after apply_episode, i.e.
      after the lights were placed from the building's footprint, so diagram pieces never move a flood lamp. It
      builds the building-specific paths and calls the helpers below with timings from the episode JSON.

Helpers (all times in seconds, frame = round(t * fps) + 1; every piece is a part like any other, so anchors and
selectors see it; diagram pieces cast no shadows):
  flow_mat(name, hex)                 emissive line material: visible where s < pk_len (growing tip), bright pulses
                                      travelling with pk_phase, pk_fade fades it out (s = metres along the path)
  glow_mat(name, base, glow, k, hide_zero)   base colour + emission x object prop pk_glow; hide_zero = invisible
                                      while pk_glow is 0 (rings, arrow heads)
  ghost_mat(name, hex, alpha, rim)    translucent pale ghost (alpha-blended, rim-lit), fades with pk_ghost; set_mat
  pour_mat(name, hex, z_top, z_bot)   shell that fills from z_top down to z_bot as pk_glow goes 0 -> 1 (gold poured
                                      into a pier), transparent above the level ... below the level; pk_fade fades it
  tube(paths, name, part, mat, radius)  tubes along 3D polylines (rotation-minimising frames, any direction)
  ring(name, part, center, radius, z, mat, tube_r)   closed horizontal ring
  cone(name, part, mat, r, h)         arrow head (tip at the origin, +Z)
  box_shell(name, part, boxes, mat)   open-bottom box shells (pour)
  grow(ob, paths, t0, speed, fade, t_end, heads=mat, head=(r, h))  keys pk_len / pk_phase / pk_fade on a tube
                                      object, and arrow heads that ride the growing tips and rest at the path ends;
                                      both get their own render window (t0 .. fade end, prop dg_own_vis): a faded
                                      tube lying on another one would still hide it (drawn black in EEVEE dithered)
  keyprop(ob, prop, keys, interp), show(objs, windows), apply_ghost(spec_ghost)
"""
import math
import bpy
import bmesh
from mathutils import Vector

FPS = 24


def _f(t):
    return int(round(t * FPS)) + 1


def _fcurves(ob):
    import paperkit as pk
    return pk._fcurves(ob)


def keyprop(ob, prop, keys, interp='LINEAR'):
    """key a custom (object) property: keys [[t, value], ...]; constant before the first / after the last key."""
    for t, v in keys:
        ob[prop] = float(v)
        ob.keyframe_insert('["%s"]' % prop, frame=_f(t))
    for fc in _fcurves(ob):
        if fc.data_path == '["%s"]' % prop:
            for kp in fc.keyframe_points:
                kp.interpolation = interp


def show(objs, windows):
    """rendered only inside the windows [[t0, t1], ...] (hide_render keys, constant)."""
    for ob in objs:
        ob.hide_render = True
        ob.keyframe_insert("hide_render", frame=0)
        for t0, t1 in windows:
            ob.hide_render = False
            ob.keyframe_insert("hide_render", frame=_f(t0))
            ob.hide_render = True
            ob.keyframe_insert("hide_render", frame=_f(t1))
        for fc in _fcurves(ob):
            if fc.data_path == "hide_render":
                for kp in fc.keyframe_points:
                    kp.interpolation = 'CONSTANT'


def apply_ghost(entries):
    """episode "ghost": [{"select": {...}, "keys": [[t, v], ...], "interp": "LINEAR"|"BEZIER"}]. A piece matched by
    several entries gets all their keys (keep their time ranges apart)."""
    import paperkit as pk
    out = []
    for g in entries or []:
        objs = pk.select(g["select"])
        if not objs:
            print("[diagram] WARNING: ghost selector matched nothing:", g["select"])
        for o in objs:
            keyprop(o, "pk_ghost", g["keys"], g.get("interp", 'LINEAR'))
        out.append(len(objs))
    return out


# ============================================================================= materials
def _lin(h):
    import paperkit as pk
    return pk.hex2lin(h)


class _N:
    """tiny node helper"""
    def __init__(self, m):
        self.nt = m.node_tree
        self.N, self.L = self.nt.nodes, self.nt.links

    def new(self, t, **kw):
        n = self.N.new(t)
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    def attr(self, name, typ='OBJECT'):
        a = self.new('ShaderNodeAttribute', attribute_type=typ, attribute_name=name)
        return a.outputs['Fac']

    def op(self, o, a, b=None, c=None):
        n = self.new('ShaderNodeMath', operation=o)
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                self.L.new(v, n.inputs[i])
        return n.outputs[0]


def _new_mat(name):
    m = bpy.data.materials.get(name)
    if m:
        return m, None
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.surface_render_method = 'DITHERED'
    m.node_tree.nodes.clear()
    return m, _N(m)


def flow_mat(name, hexcol="#FFA41C", base=1.3, pulse=1.4, head=2.2, pulse_len=3.2, pulse_w=3.2, head_len=2.5):
    """growing emissive line: visible where s < pk_len; strength = (base + pulses travelling with pk_phase + a bright
    head at the growing tip) x pk_fade."""
    m, n = _new_mat(name)
    if n is None:
        return m
    s, ln, ph, fd = n.attr("s", 'GEOMETRY'), n.attr("pk_len"), n.attr("pk_phase"), n.attr("pk_fade")
    vis = n.op('LESS_THAN', s, ln)
    hd = n.op('SUBTRACT', 1.0, n.op('MINIMUM', n.op('DIVIDE', n.op('SUBTRACT', ln, s), head_len), 1.0))
    fr = n.op('FRACT', n.op('DIVIDE', n.op('SUBTRACT', s, ph), pulse_len))
    pu = n.op('MAXIMUM', n.op('SUBTRACT', 1.0, n.op('MULTIPLY', n.op('ABSOLUTE', n.op('SUBTRACT', fr, 0.5)), pulse_w)), 0.0)
    st = n.op('MULTIPLY', n.op('ADD', n.op('ADD', base, n.op('MULTIPLY', pu, pulse)), n.op('MULTIPLY', hd, head)), fd)
    em = n.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*_lin(hexcol), 1)
    n.L.new(st, em.inputs['Strength'])
    tr = n.new('ShaderNodeBsdfTransparent')
    mx = n.new('ShaderNodeMixShader')
    n.L.new(n.op('MULTIPLY', vis, n.op('GREATER_THAN', fd, 0.001)), mx.inputs[0])
    n.L.new(tr.outputs[0], mx.inputs[1]); n.L.new(em.outputs[0], mx.inputs[2])
    out = n.new('ShaderNodeOutputMaterial'); n.L.new(mx.outputs[0], out.inputs['Surface'])
    return m


def glow_mat(name, base_hex="#E0901C", glow_hex="#FFA41C", glow_k=2.6, rough=0.5, hide_zero=True):
    """diffuse base + emission glow_k x pk_glow; hide_zero: transparent while pk_glow == 0 (fades in with it)."""
    m, n = _new_mat(name)
    if n is None:
        return m
    bs = n.new('ShaderNodeBsdfPrincipled')
    bs.inputs['Base Color'].default_value = (*_lin(base_hex), 1)
    bs.inputs['Roughness'].default_value = rough
    g = n.attr("pk_glow")
    em = n.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*_lin(glow_hex), 1)
    n.L.new(n.op('MULTIPLY', g, glow_k), em.inputs['Strength'])
    ad = n.new('ShaderNodeAddShader')
    n.L.new(bs.outputs[0], ad.inputs[0]); n.L.new(em.outputs[0], ad.inputs[1])
    sh = ad.outputs[0]
    if hide_zero:
        tr = n.new('ShaderNodeBsdfTransparent')
        mx = n.new('ShaderNodeMixShader')
        n.L.new(n.op('MINIMUM', n.op('MULTIPLY', g, 1.0), 1.0), mx.inputs[0])
        n.L.new(tr.outputs[0], mx.inputs[1]); n.L.new(sh, mx.inputs[2])
        sh = mx.outputs[0]
    out = n.new('ShaderNodeOutputMaterial'); n.L.new(sh, out.inputs['Surface'])
    return m


def ghost_mat(name, hexcol="#EEF1F4", alpha=0.26, rim=0.6, emit=0.85, rim_power=1.6):
    """translucent "ghost" of a piece that no longer exists (alpha-blended: no dither speckle, no shadows): pale
    emission, more opaque toward the silhouette (rim), x (1 - pk_ghost) so the JSON ghost keys fade it."""
    m, n = _new_mat(name)
    if n is None:
        return m
    m.surface_render_method = 'BLENDED'
    m.use_backface_culling = True
    lw = n.new('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = 0.5
    rimf = n.op('POWER', lw.outputs['Facing'], rim_power)
    a = n.op('MULTIPLY', n.op('ADD', alpha, n.op('MULTIPLY', rimf, rim)), n.op('SUBTRACT', 1.0, n.attr("pk_ghost")))
    em = n.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*_lin(hexcol), 1)
    em.inputs['Strength'].default_value = emit
    tr = n.new('ShaderNodeBsdfTransparent')
    mx = n.new('ShaderNodeMixShader')
    n.L.new(n.op('MINIMUM', a, 1.0), mx.inputs[0])
    n.L.new(tr.outputs[0], mx.inputs[1]); n.L.new(em.outputs[0], mx.inputs[2])
    out = n.new('ShaderNodeOutputMaterial'); n.L.new(mx.outputs[0], out.inputs['Surface'])
    return m


def set_mat(objs, mat):
    """replace every material of these pieces (e.g. a real piece turned into a ghost); no shadows."""
    for ob in objs:
        me = ob.data
        me.materials.clear(); me.materials.append(mat)
        me.polygons.foreach_set("material_index", [0] * len(me.polygons))
        ob.visible_shadow = False


def pour_mat(name, hexcol="#E8A23A", glow_hex="#FFA41C", z_top=42.0, z_bot=0.0, glow_k=0.9, soft=0.6):
    """gold fills a shell from z_top down to z_bot while pk_glow goes 0 -> 1 (world Z of the shading point), a soft
    bright band at the level; transparent where not (yet) filled; x pk_fade (missing = 1)."""
    m, n = _new_mat(name)
    if n is None:
        return m
    geo = n.new('ShaderNodeNewGeometry')
    sep = n.new('ShaderNodeSeparateXYZ'); n.L.new(geo.outputs['Position'], sep.inputs[0])
    g = n.attr("pk_glow")
    fd = n.attr("pk_fade")
    level = n.op('MULTIPLY_ADD', g, -(z_top - z_bot), z_top)              # z_top -> z_bot
    d = n.op('SUBTRACT', sep.outputs['Z'], level)                         # > 0 = filled
    filled = n.op('GREATER_THAN', d, 0.0)
    filled = n.op('MULTIPLY', filled, n.op('GREATER_THAN', g, 0.001))
    band = n.op('MAXIMUM', n.op('SUBTRACT', 1.0, n.op('DIVIDE', n.op('ABSOLUTE', d), soft)), 0.0)
    bs = n.new('ShaderNodeBsdfPrincipled')
    bs.inputs['Base Color'].default_value = (*_lin(hexcol), 1)
    bs.inputs['Roughness'].default_value = 0.55
    em = n.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*_lin(glow_hex), 1)
    n.L.new(n.op('MULTIPLY', n.op('ADD', glow_k, n.op('MULTIPLY', band, 2.5)), fd), em.inputs['Strength'])
    ad = n.new('ShaderNodeAddShader')
    n.L.new(bs.outputs[0], ad.inputs[0]); n.L.new(em.outputs[0], ad.inputs[1])
    tr = n.new('ShaderNodeBsdfTransparent')
    mx = n.new('ShaderNodeMixShader')
    # pk_fade missing -> attribute 0: treat "no fade keys" as 1 by keying pk_fade wherever pour_mat is used
    n.L.new(n.op('MULTIPLY', filled, n.op('MINIMUM', n.op('MULTIPLY', fd, 1.5), 1.0)), mx.inputs[0])
    n.L.new(tr.outputs[0], mx.inputs[1]); n.L.new(ad.outputs[0], mx.inputs[2])
    out = n.new('ShaderNodeOutputMaterial'); n.L.new(mx.outputs[0], out.inputs['Surface'])
    return m


# ============================================================================= geometry
def _link(pk, ob, part, mat):
    ob.data.materials.append(mat)
    pk.part_collection(part).objects.link(ob)
    ob["pk_part"] = part
    ob["pk_rest"] = (0.0, 0.0, 0.0)
    ob.visible_shadow = False
    pk.PARTS.setdefault(part, []).append(ob)
    return ob


def _frames(pts):
    """rotation-minimising frames (double reflection) along a polyline: [(T, N, B)]"""
    T = []
    for i in range(len(pts)):
        a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
        t = (b - a)
        T.append(t.normalized() if t.length > 1e-9 else Vector((0, 0, 1)))
    ref = Vector((0, 0, 1)) if abs(T[0].z) < 0.9 else Vector((1, 0, 0))
    N = [(ref - T[0] * ref.dot(T[0])).normalized()]
    for i in range(len(pts) - 1):
        v1 = pts[i + 1] - pts[i]
        c1 = v1.dot(v1)
        if c1 < 1e-12:
            N.append(N[-1].copy()); continue
        rL = N[i] - v1 * (2.0 / c1 * v1.dot(N[i]))
        tL = T[i] - v1 * (2.0 / c1 * v1.dot(T[i]))
        v2 = T[i + 1] - tL
        c2 = v2.dot(v2)
        n_ = rL - v2 * (2.0 / c2 * v2.dot(rL)) if c2 > 1e-12 else rL
        N.append(n_.normalized())
    return [(T[i], N[i], T[i].cross(N[i])) for i in range(len(pts))]


def tube(pk, paths, name, part, mat, radius=0.2, sides=8, closed=False):
    """one mesh of tubes along 3D polylines; point attribute s = metres along each path (from its first point)."""
    bm = bmesh.new()
    lay = bm.verts.layers.float.new("s")
    for pts in paths:
        pts = [Vector(p) for p in pts]
        if closed:
            pts = pts + [pts[0]]
        acc = [0.0]
        for i in range(1, len(pts)):
            acc.append(acc[-1] + (pts[i] - pts[i - 1]).length)
        fr = _frames(pts)
        rings = []
        for i, p in enumerate(pts):
            _, Nn, Bn = fr[i]
            ring = []
            for j in range(sides):
                a = 2 * math.pi * j / sides
                v = bm.verts.new(p + (Nn * math.cos(a) + Bn * math.sin(a)) * radius)
                v[lay] = acc[i]
                ring.append(v)
            rings.append(ring)
        for i in range(len(rings) - 1):
            for j in range(sides):
                jj = (j + 1) % sides
                bm.faces.new((rings[i][j], rings[i][jj], rings[i + 1][jj], rings[i + 1][j]))
        if not closed:
            bm.faces.new(list(reversed(rings[0])))
            bm.faces.new(rings[-1])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    for f in me.polygons:
        f.use_smooth = True
    return _link(pk, bpy.data.objects.new(name, me), part, mat)


def ring(pk, name, part, center, radius, z, mat, tube_r=0.3, n=96):
    pts = [(center[0] + radius * math.cos(2 * math.pi * i / n), center[1] + radius * math.sin(2 * math.pi * i / n), z)
           for i in range(n)]
    return tube(pk, [pts], name, part, mat, radius=tube_r, sides=10, closed=True)


def cone(pk, name, part, mat, r=0.7, h=1.7, n=12):
    """arrow head: tip at the origin, pointing along +Z."""
    bm = bmesh.new()
    tip = bm.verts.new((0, 0, 0))
    base = [bm.verts.new((r * math.cos(2 * math.pi * j / n), r * math.sin(2 * math.pi * j / n), -h)) for j in range(n)]
    for j in range(n):
        bm.faces.new((tip, base[j], base[(j + 1) % n]))
    bm.faces.new(list(reversed(base)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    return _link(pk, bpy.data.objects.new(name, me), part, mat)


def box_shell(pk, name, part, boxes, mat):
    """closed boxes [(x0, x1, y0, y1, z0, z1)] without bottoms (one object)."""
    bm = bmesh.new()
    for x0, x1, y0, y1, z0, z1 in boxes:
        v = [bm.verts.new(c) for c in ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                                       (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
        for q in ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7)):
            bm.faces.new([v[i] for i in q])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    return _link(pk, bpy.data.objects.new(name, me), part, mat)


def path_len(pts):
    return sum((Vector(pts[i]) - Vector(pts[i - 1])).length for i in range(1, len(pts)))


def resample(pts, step=0.5):
    """polyline -> points every ~step metres (keeps the corners)."""
    out = [Vector(pts[0])]
    for i in range(1, len(pts)):
        a, b = Vector(pts[i - 1]), Vector(pts[i])
        n = max(1, int(math.ceil((b - a).length / step)))
        for k in range(1, n + 1):
            out.append(a.lerp(b, k / n))
    return [tuple(p) for p in out]


# ============================================================================= animation
def grow(pk, ob, paths, t0, speed, fade, t_end=None, heads=None, head=(0.7, 1.7), stagger=None, part=None,
         pulse=True):
    """key a flow_mat tube: the lines grow from their first point at `speed` m/s from t0 (stagger[i] = extra delay
    of path i is not possible on one object: use one tube per delay group), pulses travel until t_end, everything
    fades over fade = [t_a, t_b]. heads = glow material: one cone per path rides the growing tip and rests at the
    end pointing along the last segment (scales in over 0.2 s, fades with the line). Returns the head objects."""
    lens = [path_len(p) for p in paths]
    Lm = max(lens)
    t_end = t_end if t_end is not None else fade[1]
    keyprop(ob, "pk_len", [(t0 - 0.05, 0.0), (t0, 0.0), (t0 + Lm / speed, Lm + 0.5)])
    if pulse:
        keyprop(ob, "pk_phase", [(t0, 0.0), (t_end, speed * (t_end - t0))])
    else:
        keyprop(ob, "pk_phase", [(t0, -1e4)])
    keyprop(ob, "pk_fade", [(t0 - 0.05, 0.0), (t0, 1.0), (fade[0], 1.0), (fade[1], 0.0)])
    # own render window: a faded tube that coincides with another one still occludes it (EEVEE dithered draws it
    # black), so a line is only rendered while it is growing / shown
    show([ob], [[t0 - 0.05, fade[1] + 0.05]])
    ob["dg_own_vis"] = 1
    out = []
    if not heads:
        return out
    part = part or ob["pk_part"]
    for i, (p3, L_) in enumerate(zip(paths, lens)):
        h = cone(pk, "%s_head%02d" % (ob.name, i), part, heads, r=head[0], h=head[1])
        h["role"] = "head"
        h.rotation_mode = 'QUATERNION'
        P3 = [Vector(p) for p in p3]
        acc = [0.0]
        for j in range(1, len(P3)):
            acc.append(acc[-1] + (P3[j] - P3[j - 1]).length)

        def at(sv, P3=P3, acc=acc):
            sv = min(max(sv, 0.0), acc[-1])
            j = 1
            while j < len(acc) - 1 and acc[j] < sv:
                j += 1
            f = (sv - acc[j - 1]) / max(acc[j] - acc[j - 1], 1e-6)
            tan = (P3[j] - P3[j - 1])
            return P3[j - 1].lerp(P3[j], f), tan.normalized()
        f0, f1 = _f(t0), _f(t0 + L_ / speed) + 1
        for fr in range(f0 - 1, f1 + 1):
            tt = (fr - 1) / FPS
            pos, tan = at(speed * (tt - t0))
            h.location = pos + tan * head[1] * 0.35
            h.rotation_quaternion = tan.to_track_quat('Z', 'Y')
            sc = min(max((tt - t0) / 0.2, 0.0), 1.0)
            h.scale = (sc, sc, sc)
            h.keyframe_insert("location", frame=fr); h.keyframe_insert("rotation_quaternion", frame=fr)
            h.keyframe_insert("scale", frame=fr)
        keyprop(h, "pk_glow", [(fade[0], 1.0), (fade[1], 0.0)])
        show([h], [[t0 - 0.05, fade[1] + 0.05]])
        h["dg_own_vis"] = 1
        out.append(h)
    return out
