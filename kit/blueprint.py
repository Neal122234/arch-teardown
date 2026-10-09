"""blueprint.py - the 3D half of the episode "graphics" layer: blueprint / x-ray language for explained parts.

Called by run_episode.py after apply_episode when the episode JSON has a "graphics" block:
  "graphics": {
    "xray":  [{"select": {selector}, "t": [t_on, t_off], "fade": 0.5, "peak": 1.0,
               "lines": {"angle": 30, "mode": "all"|"circ", "center": [x, y], "radius": 0.09}}],
             pieces get object prop pk_xray keyed 0 -> peak (fade in from t_on) -> 0 (fade out ending at t_off);
             every realkit material reads it (realkit._finish): dark navy body + glowing cyan rim (LOOK xray_*).
             "lines": glowing feature-edge tubes built from each piece's own mesh (face angle > angle deg;
             mode "circ" keeps only edges running round `center`, i.e. drops radial / vertical seams), riding on
             the piece (Copy Transforms), rendered only inside the window.
    "cut":   [{"select": {selector}, "t": [t_on, t_off], "fade": 0.4, "stagger": 0.05 (per ring),
               "normal": [0, -1, 0] (points to the camera), "origin": [0, 0, 0], "eps": 0.06,
               "ghost_lines": {"angle", "mode": "circ", "radius", "strength"},   glowing edges left by the dissolved half
               "section_lines": {"radius", "strength"},                         outline of the far half's faces ON the plane
               "fill": {"hex", "hatch_hex", "alpha", "spacing", "width"}}]      navy poche with 45 deg hatch in the section
             x-ray cutaway: camera-side pieces dissolve (pk_ghost, then hide_render = no shadow), the far half shows its
             section profile. Needs piece seams on the plane (ep01 dome: seams at plan az 0/180).
    "sphere_grid": [{"follow": {selector}, "center", "r", "el": [e0, e1], "rows", "cols", "az0", "t": [t_on, t_off],
               "row_dt", "cell_dt", "fade", "radius", "strength"}]
             glowing cell grid on a sphere (ep01: coffer layout 5 x 28), drawn on ring by ring, cell by cell.
    "line_hex": "#8BE6FF", "line_strength": 5.0,
    "grid":  {"t": [t_on, t_off], "fade": 0.6, "z": -0.19, "center": [0, 0], "radius": [r_full, r_zero],
              "minor": 5.0, "major": 25.0, "hex": "#63CFFF", "strength": 1.4, "alpha": 0.6}
             faint engineering grid on the ground (blended emission disc, fades with distance from center).
    "dims", "card_style", "grade": 2D keys, read by overlay.py (dimension lines drawn on from 3D anchors)
  }
Cost: lines/grid are emission-only BLENDED surfaces without shadows; outside their window they are not rendered.
"""
import math
import bpy
import bmesh
from mathutils import Vector
import paperkit as pk

_MAT = {}


def _key_prop(ob, name, pts):
    for t, v in pts:
        ob[name] = float(v)
        ob.keyframe_insert('["%s"]' % name, frame=pk.sec2f(t))


def _window(ob, t0, t1):
    """rendered only for t0 <= t <= t1 (keyed hide_render, constant)."""
    for f, h in ((1, True), (pk.sec2f(t0), False), (pk.sec2f(t1) + 1, True)):
        ob.hide_render = h
        ob.keyframe_insert("hide_render", frame=f)


def _env(t, fade, peak=1.0):
    t0, t1 = t
    return [(t0, 0.0), (t0 + fade, peak), (t1 - fade, peak), (t1, 0.0)]


def _coll():
    c = bpy.data.collections.get("BP_graphics")
    if not c:
        c = bpy.data.collections.new("BP_graphics")
        bpy.context.scene.collection.children.link(c)
    return c


def _emit_mat(name, hexcol, strength, grid=None):
    """emission x object prop pk_xray, blended (noise-free fades, no depth write, no shadows)."""
    key = (name, hexcol, strength)
    if key in _MAT:
        return _MAT[key]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.surface_render_method = 'BLENDED'
    try:
        m.use_transparency_overlap = False
    except Exception:
        pass
    nt = m.node_tree; N, Lk = nt.nodes, nt.links
    N.clear()
    at = N.new('ShaderNodeAttribute'); at.attribute_type = 'OBJECT'; at.attribute_name = 'pk_xray'
    fac = at.outputs['Fac']
    em = N.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*pk.hex2lin(hexcol), 1.0); em.inputs['Strength'].default_value = strength
    if grid:
        fac = _grid_alpha(nt, fac, grid)
    tr = N.new('ShaderNodeBsdfTransparent')
    mx = N.new('ShaderNodeMixShader')
    Lk.new(fac, mx.inputs[0]); Lk.new(tr.outputs[0], mx.inputs[1]); Lk.new(em.outputs[0], mx.inputs[2])
    out = N.new('ShaderNodeOutputMaterial'); Lk.new(mx.outputs[0], out.inputs['Surface'])
    _MAT[key] = m
    return m


def _grid_alpha(nt, fac, g):
    N, Lk = nt.nodes, nt.links

    def math_(op, a, b=None, c=None):
        n = N.new('ShaderNodeMath'); n.operation = op
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                Lk.new(v, n.inputs[i])
            else:
                n.inputs[i].default_value = v
        return n.outputs[0]

    def mr(v, a, b, c=0.0, d=1.0):
        n = N.new('ShaderNodeMapRange'); n.interpolation_type = 'SMOOTHSTEP'; n.clamp = True
        Lk.new(v, n.inputs['Value'])
        n.inputs['From Min'].default_value = a; n.inputs['From Max'].default_value = b
        n.inputs['To Min'].default_value = c; n.inputs['To Max'].default_value = d
        return n.outputs['Result']

    geo = N.new('ShaderNodeNewGeometry')
    sp = N.new('ShaderNodeSeparateXYZ'); Lk.new(geo.outputs['Position'], sp.inputs[0])
    cx, cy = g.get("center", (0.0, 0.0))
    x = math_('SUBTRACT', sp.outputs[0], cx); y = math_('SUBTRACT', sp.outputs[1], cy)

    def lines(spacing, w, soft):
        acc = None
        for v in (x, y):
            d = math_('MULTIPLY', math_('ABSOLUTE', math_('SUBTRACT', math_('FRACT', math_('ADD', math_('DIVIDE', v, spacing), 0.5)), 0.5)), spacing)
            ln = mr(d, w, w + soft, 1.0, 0.0)
            acc = ln if acc is None else math_('MAXIMUM', acc, ln)
        return acc

    a = math_('MAXIMUM', math_('MULTIPLY', lines(g.get("minor", 5.0), 0.05, 0.2), 0.45),
              lines(g.get("major", 25.0), 0.1, 0.3))
    r = math_('SQRT', math_('ADD', math_('MULTIPLY', x, x), math_('MULTIPLY', y, y)))
    r0, r1 = g.get("radius", (35.0, 120.0))
    a = math_('MULTIPLY', a, mr(r, r0, r1, 1.0, 0.0))
    a = math_('MULTIPLY', a, g.get("alpha", 0.6))
    return math_('MULTIPLY', a, fac)


def _edge_segments(ob, angle, mode, center):
    bm = bmesh.new(); bm.from_mesh(ob.data)
    M = ob.matrix_world.copy()
    thr = math.radians(angle)
    cx, cy = center
    segs = []
    for e in bm.edges:
        nf = len(e.link_faces)
        if nf == 2:
            if e.calc_face_angle(0.0) < thr:
                continue
        elif nf != 1:
            continue
        v0, v1 = e.verts[0].co.copy(), e.verts[1].co.copy()
        if mode == "circ":
            w0, w1 = M @ v0, M @ v1
            d = w1 - w0
            if d.length < 1e-6:
                continue
            d.normalize()
            mid = (w0 + w1) / 2
            rad = Vector((mid.x - cx, mid.y - cy, 0.0))
            if abs(d.z) > 0.55 or (rad.length > 1e-3 and abs(d.dot(rad.normalized())) > 0.4):
                continue
        segs.append((v0, v1))
    bm.free()
    return segs


def _tubes(name, segs, r):
    verts, faces = [], []
    for v0, v1 in segs:
        d = v1 - v0
        L = d.length
        if L < 1e-5:
            continue
        u = d / L
        a = u.cross(Vector((0, 0, 1)))
        if a.length < 0.1:
            a = u.cross(Vector((1, 0, 0)))
        a.normalize(); b = u.cross(a)
        k = len(verts)
        for p in (v0, v1):
            for s_, t_ in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                verts.append(p + a * (s_ * r) + b * (t_ * r))
        for i in range(4):
            j = (i + 1) % 4
            faces.append((k + i, k + j, k + 4 + j, k + 4 + i))
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    return me


def _line_obj(name, ob, segs, rad, mat, env, t, coll):
    sx = max(ob.matrix_world.to_scale()) or 1.0
    lo = bpy.data.objects.new(name, _tubes(name, segs, rad / sx))
    coll.objects.link(lo)
    lo.data.materials.append(mat)
    lo.visible_shadow = False
    c = lo.constraints.new('COPY_TRANSFORMS'); c.target = ob
    _key_prop(lo, "pk_xray", env)
    _window(lo, t[0], t[1])
    return lo


def _cap_obj(name, ob, segs, shift, mat, coll):
    """filled section face (poche) from the outline edges lying on the cut plane (local coords), nudged by shift."""
    bm = bmesh.new()
    vid = {}

    def V(co):
        k = (round(co.x, 4), round(co.y, 4), round(co.z, 4))
        if k not in vid:
            vid[k] = bm.verts.new(co + shift)
        return vid[k]
    for a, b in segs:
        va, vb = V(a), V(b)
        if va is not vb and bm.edges.get((va, vb)) is None:
            bm.edges.new((va, vb))
    res = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=list(bm.edges))
    if not bm.faces:
        bm.free()
        return None
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    fo = bpy.data.objects.new(name, me)
    coll.objects.link(fo); me.materials.append(mat); fo.visible_shadow = False
    c = fo.constraints.new('COPY_TRANSFORMS'); c.target = ob
    return fo


def _fill_mat(f):
    """blueprint poche: dark navy, 45 deg cyan hatch (object space), alpha x pk_xray; blended, double sided."""
    key = ("BP_fill", f.get("hex"), f.get("hatch_hex"))
    if key in _MAT:
        return _MAT[key]
    m = bpy.data.materials.new("BP_fill")
    m.use_nodes = True
    m.surface_render_method = 'BLENDED'
    nt = m.node_tree; N, Lk = nt.nodes, nt.links
    N.clear()
    at = N.new('ShaderNodeAttribute'); at.attribute_type = 'OBJECT'; at.attribute_name = 'pk_xray'
    tc = N.new('ShaderNodeTexCoord')
    sp = N.new('ShaderNodeSeparateXYZ'); Lk.new(tc.outputs['Object'], sp.inputs[0])

    def M_(op, a, b=None):
        n = N.new('ShaderNodeMath'); n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                Lk.new(v, n.inputs[i])
            else:
                n.inputs[i].default_value = v
        return n.outputs[0]
    sp_ = f.get("spacing", 0.9)
    u = M_('DIVIDE', M_('ADD', M_('ADD', sp.outputs[0], sp.outputs[1]), sp.outputs[2]), sp_)
    d = M_('ABSOLUTE', M_('SUBTRACT', M_('FRACT', u), 0.5))           # 0 at the middle of a stripe .. 0.5
    hatch = M_('GREATER_THAN', d, 0.5 - f.get("width", 0.09))
    mix = N.new('ShaderNodeMix'); mix.data_type = 'RGBA'
    Lk.new(hatch, mix.inputs['Factor'])
    mix.inputs['A'].default_value = (*pk.hex2lin(f.get("hex", "#0A2238")), 1.0)
    mix.inputs['B'].default_value = (*pk.hex2lin(f.get("hatch_hex", "#4FC3F0")), 1.0)
    em = N.new('ShaderNodeEmission'); Lk.new(mix.outputs['Result'], em.inputs['Color'])
    em.inputs['Strength'].default_value = f.get("strength", 1.0)
    tr = N.new('ShaderNodeBsdfTransparent')
    mx = N.new('ShaderNodeMixShader')
    Lk.new(M_('MULTIPLY', at.outputs['Fac'], f.get("alpha", 0.85)), mx.inputs[0])
    Lk.new(tr.outputs[0], mx.inputs[1]); Lk.new(em.outputs[0], mx.inputs[2])
    out = N.new('ShaderNodeOutputMaterial'); Lk.new(mx.outputs[0], out.inputs['Surface'])
    _MAT[key] = m
    return m


def _cut(cut, g, coll, st):
    """x-ray cutaway: pieces on the camera side of a plane through `origin` (normal points to the camera) dissolve
    (pk_ghost 0->1, then hidden: no shadow) and leave glowing ghost edges; the remaining half gets glowing outlines
    of its faces lying ON the plane (the section profile). Ring-staggered: bottom ring first, back in reverse."""
    objs = pk.select(cut["select"])
    t0, t1 = cut["t"]
    fade, stg = cut.get("fade", 0.35), cut.get("stagger", 0.05)
    n = Vector(cut.get("normal", (0, -1, 0))).normalized()
    o = Vector(cut.get("origin", (0, 0, 0)))
    eps = cut.get("eps", 0.05)
    gl, sl = cut.get("ghost_lines", {}), cut.get("section_lines", {})
    gmat = _emit_mat("BP_ghostline", gl.get("hex", g.get("line_hex", "#8BE6FF")), gl.get("strength", 1.5))
    smat = _emit_mat("BP_secline", sl.get("hex", g.get("line_hex", "#8BE6FF")), sl.get("strength", 5.0))
    rings = sorted(set(ob.get("ring", 0) for ob in objs))
    front = back = 0
    probe = {}
    for ob in objs:
        if ob.type != 'MESH':
            continue
        M = ob.matrix_world
        cen = sum((M @ Vector(c) for c in ob.bound_box), Vector()) / 8.0
        ri = rings.index(ob.get("ring", 0))
        a_on, a_off = t0 + ri * stg, t1 - (len(rings) - 1 - ri) * stg * 0.5
        if (cen - o).dot(n) > 0:                       # camera side: dissolve
            front += 1
            _key_prop(ob, "pk_ghost", [(a_on, 0.0), (a_on + fade, 1.0), (a_off - fade, 1.0), (a_off, 0.0)])
            f_on, f_off = pk.sec2f(a_on + fade) + 1, pk.sec2f(a_off - fade) - 1
            if f_off > f_on:
                for f, h in ((1, False), (f_on, True), (f_off, False)):
                    ob.hide_render = h; ob.keyframe_insert("hide_render", frame=f)
                for fc in pk._fcurves(ob):
                    if fc.data_path == "hide_render":
                        for kp in fc.keyframe_points:
                            kp.interpolation = 'CONSTANT'
            if gl:
                segs = _edge_segments(ob, gl.get("angle", 30.0), gl.get("mode", "circ"), gl.get("center", (0.0, 0.0)))
                if segs:
                    _line_obj("BP_ghost_" + ob.name, ob, segs, gl.get("radius", 0.06), gmat,
                              _env((a_on, a_off), fade), (a_on, a_off), coll)
                    st["line_segments"] += len(segs)
        else:                                          # far side: outline its faces on the plane
            back += 1
            if not sl:
                continue
            Mi = M.inverted()
            bm = bmesh.new(); bm.from_mesh(ob.data)
            segs = []
            for e in bm.edges:
                w0, w1 = M @ e.verts[0].co, M @ e.verts[1].co
                if abs((w0 - o).dot(n)) < eps and abs((w1 - o).dot(n)) < eps:
                    segs.append((e.verts[0].co.copy(), e.verts[1].co.copy()))
                    if abs(w0.z - w1.z) < 1e-3 or True:
                        rk_ = ob.get("ring", 0)
                        for w in (w0, w1):
                            side = "R" if w.x > 0 else "L"
                            pr = probe.setdefault("%s%d" % (side, rk_), [1e9, -1e9, 1e9, -1e9])
                            pr[0] = min(pr[0], abs(w.x)); pr[1] = max(pr[1], abs(w.x))
                            pr[2] = min(pr[2], w.z); pr[3] = max(pr[3], w.z)
            bm.free()
            if segs:
                _line_obj("BP_sec_" + ob.name, ob, segs, sl.get("radius", 0.1), smat,
                          _env((t0 + fade, t1 - fade), fade), (t0, t1), coll)
                st["line_segments"] += len(segs)
                if cut.get("fill"):
                    fo = _cap_obj("BP_cap_" + ob.name, ob, segs, Mi @ (M @ Vector((0, 0, 0)) + n * 0.03) - Mi @ (M @ Vector((0, 0, 0))),
                                  _fill_mat(cut["fill"]), coll)
                    if fo:
                        _key_prop(fo, "pk_xray", _env((t0 + fade, t1 - fade), fade))
                        _window(fo, t0, t1)
                        st["caps"] = st.get("caps", 0) + 1
    st["cut_front"] = st.get("cut_front", 0) + front
    st["cut_back"] = st.get("cut_back", 0) + back
    for k in sorted(probe):
        p = probe[k]
        print("[blueprint] section %-4s |x| %.2f..%.2f  z %.2f..%.2f" % (k, *p))


def _sphere_grid(cg, g, coll, st):
    """blueprint grid on a sphere (e.g. the coffer layout: rows x cols cells between elevations el0..el1), one line
    object per cell (its right meridian + its top/bottom arcs), drawn on row by row, cell by cell round the ring.
    Rides on cg["follow"] (selector; first object) with Copy Transforms."""
    tgt = pk.select(cg["follow"])[0]
    Mi = tgt.matrix_world.inverted()
    c = Vector(cg.get("center", (0, 0, 0)))
    r = cg["r"]
    rows, cols = cg["rows"], cg["cols"]
    e0, e1 = cg["el"]
    az0 = cg.get("az0", 0.0)
    t0, t1 = cg["t"]
    row_dt, cell_dt, fade = cg.get("row_dt", 0.25), cg.get("cell_dt", 0.02), cg.get("fade", 0.15)
    mat = _emit_mat("BP_sgrid", cg.get("hex", g.get("line_hex", "#8BE6FF")), cg.get("strength", 4.0))

    def P(el, az):
        e, a = math.radians(el), math.radians(az)
        return Mi @ (c + Vector((r * math.cos(e) * math.cos(a), r * math.cos(e) * math.sin(a), r * math.sin(e))))
    n = 0
    for i in range(rows):
        ea, eb = e0 + (e1 - e0) * i / rows, e0 + (e1 - e0) * (i + 1) / rows
        for j in range(cols):
            aa, ab = az0 + 360.0 * j / cols, az0 + 360.0 * (j + 1) / cols
            segs = [(P(ea, aa), P(eb, aa))]
            m = 6                                       # bottom arc of the cell (+ the top arc on the last row)
            for ee in ((ea, eb) if i == rows - 1 else (ea,)):
                segs += [(P(ee, aa + (ab - aa) * k / m), P(ee, aa + (ab - aa) * (k + 1) / m)) for k in range(m)]
            ton = t0 + i * row_dt + j * cell_dt
            name = "BP_sg_%d_%02d" % (i, j)
            lo = bpy.data.objects.new(name, _tubes(name, segs, cg.get("radius", 0.08)))
            coll.objects.link(lo); lo.data.materials.append(mat); lo.visible_shadow = False
            cst = lo.constraints.new('COPY_TRANSFORMS'); cst.target = tgt
            _key_prop(lo, "pk_xray", [(ton, 0.0), (ton + fade, 1.0), (t1 - 0.35, 1.0), (t1, 0.0)])
            _window(lo, ton, t1)
            n += 1; st["line_segments"] += len(segs)
    st["sphere_grid_cells"] = st.get("sphere_grid_cells", 0) + n


def apply(g):
    sc = bpy.context.scene
    sc.frame_set(1)                      # pieces at rest (edge classification in world rest coordinates)
    st = {"xray_pieces": 0, "line_objects": 0, "line_segments": 0}
    coll = _coll()
    lmat = _emit_mat("BP_line", g.get("line_hex", "#8BE6FF"), g.get("line_strength", 5.0))
    for cut in g.get("cut", []):
        _cut(cut, g, coll, st)
    for xr in g.get("xray", []):
        objs = pk.select(xr["select"])
        fade, peak = xr.get("fade", 0.5), xr.get("peak", 1.0)
        env = _env(xr["t"], fade, peak)
        for ob in objs:
            _key_prop(ob, "pk_xray", env)
        st["xray_pieces"] += len(objs)
        ln = xr.get("lines")
        if not ln:
            continue
        rad = ln.get("radius", 0.09)
        for ob in objs:
            if ob.type != 'MESH':
                continue
            segs = _edge_segments(ob, ln.get("angle", 30.0), ln.get("mode", "all"), ln.get("center", (0.0, 0.0)))
            if not segs:
                continue
            sx = max(ob.matrix_world.to_scale()) or 1.0
            lo = bpy.data.objects.new("BP_lines_" + ob.name, _tubes("BP_lines_" + ob.name, segs, rad / sx))
            coll.objects.link(lo)
            lo.data.materials.append(lmat)
            lo.visible_shadow = False
            c = lo.constraints.new('COPY_TRANSFORMS'); c.target = ob
            _key_prop(lo, "pk_xray", [(t, min(1.0, v / max(peak, 1e-3))) for t, v in env])
            _window(lo, xr["t"][0], xr["t"][1])
            st["line_objects"] += 1; st["line_segments"] += len(segs)
    for cg in g.get("sphere_grid", []):
        _sphere_grid(cg, g, coll, st)
    gd = g.get("grid")
    if gd:
        n, R = 128, gd.get("radius", (35.0, 120.0))[1]
        cx, cy = gd.get("center", (0.0, 0.0))
        z = gd.get("z", -0.19)
        me = bpy.data.meshes.new("BP_grid")
        me.from_pydata([(cx, cy, z)] + [(cx + R * math.cos(2 * math.pi * k / n), cy + R * math.sin(2 * math.pi * k / n), z)
                                        for k in range(n)], [], [(0, 1 + k, 1 + (k + 1) % n) for k in range(n)])
        go = bpy.data.objects.new("BP_grid", me); coll.objects.link(go)
        go.data.materials.append(_emit_mat("BP_grid", gd.get("hex", "#63CFFF"), gd.get("strength", 1.4), grid=gd))
        go.visible_shadow = False
        _key_prop(go, "pk_xray", _env(gd["t"], gd.get("fade", 0.6)))
        _window(go, gd["t"][0], gd["t"][1])
        st["grid"] = True
    return st
