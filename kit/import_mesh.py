"""import_mesh.py - reusable step: a detailed closed mesh (STL, e.g. a 3D-print model) -> aligned, segmented,
material-tagged skin pieces the kit can load in place of a builder's procedural exterior.

The mesh itself is never committed (licence unknown for most downloaded models): everything this writes goes to
the models folder (ARCH_KIT_MODELS). Only this code and the episode's prep JSON live in the repo.

Two stages, so the heavy numpy / scipy work never runs inside Blender:

Stage A, plain python3:
    python3 kit/import_mesh.py prepare CONFIG.json
  reads the STL (binary), welds it, applies the alignment (pivot -> rotate about Z -> post shift -> scale xy / z,
  ground level -> z 0), measures the dome / heights for the report, classifies every face into a palette name
  (region + face normal + window-recess detection) and writes a Wavefront OBJ (one usemtl block per palette name,
  slot 0 = the cut-face colour) + a JSON with the transform and measurements.

Stage B, inside Blender (through kit/blender_locked.sh):
    kit/blender_locked.sh -b --factory-startup -P kit/import_mesh.py -- segment CONFIG.json
  imports the OBJ, builds one cutter volume per region (box / cylinder / plan polygon; later regions minus earlier
  ones, so the parts partition the mesh), intersects the mesh with each cutter (Manifold boolean: closed, filled cut
  faces that take material slot 0 = the cut colour), applies per-region post transforms (minaret vertical rescale; z_map = piecewise-linear vertical remap),
  and saves the pieces into OUT.blend (collection "mesh_skin") + OUT.json (object -> part, pivot, meta).

CONFIG keys (see episodes/ep02_hagia_sophia/mesh_prep.json):
  stl, obj, out_blend, out_json      paths (models/... resolves under ARCH_KIT_MODELS)
  align   {pivot:[x,y] (mesh units), rotate_z_deg, post_shift:[x,y] (units, after the rotation), scale_xy, scale_z,
           ground_z (mesh units -> world z 0)}
  cut_col palette name of the filled cut faces (material slot 0)
  windows {dirs: ["+x","-x","+y","-y"], cell, filter_m, depth:[min,max], w:[min,max], h:[min,max], col}
  regions [{name, part, meta, shape, mat, sub:[...], drop, post}] in priority order. shape:
           {"box":[x0,x1,y0,y1,z0,z1]} | {"cyl":[cx,cy,r,z0,z1]} | {"poly":[[x,y],...], "z":[z0,z1]}
           | {"union":[shape, ...]}; "auto_base": {"annulus":[r0,r1]} lifts a cylinder's z0 to the top of what
           surrounds it (minaret on a roof). mat: {wall, roof, roof_k, dome, dome_k, cap, cap_z, bands:[[z0,z1,col]],
           ground, ground_z, windows: true|false}. sub: child regions (same keys) carved out of this one first.
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402


# ============================================================================ shared: region geometry tests
def _in_shape(sh, P):
    """numpy: boolean mask of points P (N x 3) inside a shape spec."""
    import numpy as np
    if "union" in sh:
        m = np.zeros(len(P), bool)
        for s in sh["union"]:
            m |= _in_shape(s, P)
        return m
    if "box" in sh:
        x0, x1, y0, y1, z0, z1 = sh["box"]
        return (P[:, 0] >= x0) & (P[:, 0] <= x1) & (P[:, 1] >= y0) & (P[:, 1] <= y1) & (P[:, 2] >= z0) & (P[:, 2] <= z1)
    if "cyl" in sh:
        cx, cy, r, z0, z1 = sh["cyl"]
        return (np.hypot(P[:, 0] - cx, P[:, 1] - cy) <= r) & (P[:, 2] >= z0) & (P[:, 2] <= z1)
    if "poly" in sh:
        from matplotlib.path import Path
        z0, z1 = sh["z"]
        return Path(sh["poly"]).contains_points(P[:, :2]) & (P[:, 2] >= z0) & (P[:, 2] <= z1)
    raise ValueError("unknown shape %s" % sh)


def _flat_regions(cfg):
    """priority-ordered leaf regions: a region's 'sub' children come before the region itself (they are carved
    out of it); children inherit part / meta / mat keys they do not set."""
    out = []
    for r in cfg["regions"]:
        for s in r.get("sub", []):
            c = dict(r); c.pop("sub", None)
            c.update(s)
            c["meta"] = dict(r.get("meta", {}), **s.get("meta", {}))
            c["mat"] = dict(r.get("mat", {}), **s.get("mat", {}))
            c["shape"] = {"and": [s["shape"], r["shape"]]}
            out.append(c)
        rr = dict(r); rr.pop("sub", None)
        out.append(rr)
    return out


def _in_region(sh, P):
    if "and" in sh:
        m = _in_shape_any(sh["and"][0], P)
        for s in sh["and"][1:]:
            m &= _in_shape_any(s, P)
        return m
    return _in_shape(sh, P)


def _in_shape_any(sh, P):
    return _in_region(sh, P) if "and" in sh else _in_shape(sh, P)


# ============================================================================ Stage A: prepare (python3)
def read_stl(path):
    import numpy as np
    with open(path, "rb") as f:
        head = f.read(80)
        n = int(np.frombuffer(f.read(4), "<u4")[0])
        dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        d = np.frombuffer(f.read(n * 50), dt)
    assert not head.startswith(b"solid ") or len(d) == n, "ASCII STL is not supported"
    V = d["v"].reshape(-1, 3).astype(np.float64)
    u, inv = np.unique(V.round(6), axis=0, return_inverse=True)
    return u, inv.reshape(-1, 3).astype(np.int64)


def align(V, a):
    import numpy as np
    t = math.radians(a["rotate_z_deg"])
    R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    W = np.empty_like(V)
    W[:, :2] = ((V[:, :2] - a["pivot"]) @ R.T - a.get("post_shift", [0.0, 0.0])) * a["scale_xy"]
    W[:, 2] = (V[:, 2] - a["ground_z"]) * a["scale_z"]
    return W


def _slice_pts(V, F, z):
    """points where the mesh crosses the plane z (2 per crossing triangle), xy only."""
    import numpy as np
    p = V[F]
    h = p[:, :, 2] - z
    m = (h.min(1) < 0) & (h.max(1) > 0)
    p, h = p[m], h[m]
    out = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        c = (h[:, a] * h[:, b]) < 0
        t = h[c, a] / (h[c, a] - h[c, b])
        out.append(p[c, a, :2] + (p[c, b, :2] - p[c, a, :2]) * t[:, None])
    return np.concatenate(out) if out else np.zeros((0, 2))


def measure(V, F, cfg):
    """heights / radii reported against the episode's verified values."""
    import numpy as np
    rep = {}
    r = np.hypot(V[:, 0], V[:, 1])
    rep["crown_z"] = float(V[r < 1.5, 2].max())
    # dome shell crown (below the finial: the finial is thin, take the 85th percentile of the top cap)
    top = V[(r < 4.0)]
    rep["dome_shell_crown_z"] = float(np.percentile(top[:, 2], 99.0)) if len(top) else None
    prof = []
    for z in np.arange(30.0, 60.0, 0.5):
        P = _slice_pts(V, F, z)
        rr = np.hypot(P[:, 0], P[:, 1])
        rr = rr[rr < 30.0]
        prof.append([float(z), float(rr.max()) if len(rr) else 0.0, float(np.median(rr)) if len(rr) else 0.0])
    rep["dome_profile_z_rmax_rmed"] = prof
    for k, (x, y) in cfg.get("measure_points", {}).items():
        m = np.hypot(V[:, 0] - x, V[:, 1] - y) < cfg.get("measure_radius", 3.0)
        rep["top_" + k] = float(V[m, 2].max()) if m.any() else None
    return rep


def auto_bases(V, F, regions):
    """cylinders with auto_base: z0 = top of whatever stands in the annulus around them (+5 cm)."""
    import numpy as np
    for rg in regions:
        ab = rg.get("auto_base")
        if not ab or "cyl" not in rg["shape"]:
            continue
        cx, cy, r, z0, z1 = rg["shape"]["cyl"]
        a0, a1 = ab["annulus"]
        d = np.hypot(V[:, 0] - cx, V[:, 1] - cy)
        ring = (d > a0) & (d < a1) & (V[:, 2] < ab.get("z_max", 40.0))
        zb = float(V[ring, 2].max()) + 0.05 if ring.any() else z0
        # never cut lower than the ground
        rg["shape"]["cyl"] = [cx, cy, r, max(z0, zb), z1]
        rg["base_z"] = rg["shape"]["cyl"][3]
        print("[import_mesh] %-12s auto base z %.2f" % (rg["name"], rg["base_z"]))


def window_faces(V, F, cent, nrm, area, cand, wcfg):
    """window panels on axis-aligned walls. Print / game meshes model a window as a slightly recessed panel framed by
    a bevelled reveal: projected onto the wall plane (u, z) per facing direction d, the reveal leaves a thin outline
    without d-facing samples, so every panel is its own island of d-facing cells. Islands of window size (w, h) whose
    offset lies depth[0..1] behind the wall around them (a ring of cells outside their bbox) are windows.
    Returns a boolean mask over faces."""
    import numpy as np
    from scipy import ndimage
    cell = wcfg.get("cell", 0.1)
    d0, d1 = wcfg.get("depth", [0.02, 1.2])
    w0, w1 = wcfg.get("w", [0.5, 4.5])
    h0, h1 = wcfg.get("h", [0.9, 8.0])
    ring = wcfg.get("ring", 3)
    fill = wcfg.get("fill", 0.55)                 # island must cover this share of its bbox (arched panels ~0.75)
    out = np.zeros(len(F), bool)
    rng = np.random.default_rng(3)
    p = V[F]
    for dname in wcfg.get("dirs", ["+x", "-x", "+y", "-y"]):
        ax = 0 if dname[1] == "x" else 1
        sg = 1.0 if dname[0] == "+" else -1.0
        uax = 1 - ax
        idx = np.where(cand & (nrm[:, ax] * sg > 0.97))[0]
        if not len(idx):
            continue
        ns = np.clip((area[idx] / (cell * cell * 0.12)).astype(int), 1, 40000)
        rep = np.repeat(idx, ns)
        a = rng.random(len(rep)); b = rng.random(len(rep))
        flip = a + b > 1
        a[flip], b[flip] = 1 - a[flip], 1 - b[flip]
        q = p[rep, 0] * (1 - a - b)[:, None] + p[rep, 1] * a[:, None] + p[rep, 2] * b[:, None]
        u, z, o = q[:, uax], q[:, 2], q[:, ax] * sg
        u0, z0 = u.min() - 1, z.min() - 1
        I = ((u - u0) / cell).astype(int); J = ((z - z0) / cell).astype(int)
        H = np.full((J.max() + 3, I.max() + 3), -1e9)
        np.maximum.at(H, (J, I), o)
        known = H > -1e8
        # split islands also at depth steps (a panel flush with the wall but cut off by a sill line stays apart)
        # the reveal outline is ~1 cell wide and dotted: erode the d-facing mask by one cell so it closes, label,
        # then grow the labels back over the eroded rim for the face lookup
        ke = ndimage.binary_erosion(known, structure=np.ones((3, 3), bool))
        lab, nl = ndimage.label(ke)
        objs = ndimage.find_objects(lab)
        ok = np.zeros(nl + 1, bool)
        for k, sl in enumerate(objs, start=1):
            if sl is None:
                continue
            hh = (sl[0].stop - sl[0].start + 2) * cell
            ww = (sl[1].stop - sl[1].start + 2) * cell
            if not (w0 <= ww <= w1 and h0 <= hh <= h1):
                continue
            comp = lab[sl] == k
            if comp.mean() < fill:
                continue
            oc = np.median(H[sl][comp])
            j0, j1 = max(sl[0].start - ring, 0), min(sl[0].stop + ring, H.shape[0])
            i0, i1 = max(sl[1].start - ring, 0), min(sl[1].stop + ring, H.shape[1])
            box = H[j0:j1, i0:i1]
            mring = (lab[j0:j1, i0:i1] != k) & (box > -1e8)
            mring[sl[0].start - j0:sl[0].stop - j0, sl[1].start - i0:sl[1].stop - i0] = False
            if mring.sum() < 8:
                continue
            wall = np.median(box[mring])
            if d0 < wall - oc < d1:
                ok[k] = True
        ci = np.clip(((cent[idx, uax] - u0) / cell).astype(int), 0, H.shape[1] - 1)
        cj = np.clip(((cent[idx, 2] - z0) / cell).astype(int), 0, H.shape[0] - 1)
        labf = np.where(lab > 0, lab, ndimage.maximum_filter(lab, size=3))
        hit = ok[labf[cj, ci]]
        out[idx[hit]] = True
        print("[import_mesh] windows %s: %d panels of %d islands, %d faces" % (dname, ok.sum(), nl, hit.sum()))
    return out


def classify(V, F, regions, cfg):
    """palette name per face (region + normal + windows). Returns (names list, index per face, region per face)."""
    import numpy as np
    p = V[F]
    cent = p.mean(1)
    n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    nrm = n / (2 * area[:, None] + 1e-15)
    reg = np.full(len(F), -1)
    for i, rg in enumerate(regions):
        free = reg < 0
        m = _in_region(rg["shape"], cent[free])
        reg[np.where(free)[0][m]] = i
    names = [cfg.get("cut_col", "brick_byz")]
    lab = np.zeros(len(F), np.int32)

    def nid(nm):
        if nm not in names:
            names.append(nm)
        return names.index(nm)
    win_cand = np.zeros(len(F), bool)
    for i, rg in enumerate(regions):
        if rg.get("mat", {}).get("windows"):
            win_cand |= reg == i
    wcfg = cfg.get("windows", {})
    win = window_faces(V, F, cent, nrm, area, win_cand & (np.abs(nrm[:, 2]) < 0.2), wcfg) if win_cand.any() else \
        np.zeros(len(F), bool)
    nz = nrm[:, 2]
    for i, rg in enumerate(regions):
        m = reg == i
        if not m.any():
            continue
        mt = rg.get("mat", {})
        out = np.full(m.sum(), nid(mt.get("wall", "render_salmon")))
        nzz, cz = nz[m], cent[m, 2]
        for z0, z1, col in mt.get("bands", []):
            out[(cz >= z0) & (cz < z1)] = nid(col)
        if mt.get("dome"):
            out[nzz > mt.get("dome_k", 0.25)] = nid(mt["dome"])
        if mt.get("roof"):
            out[nzz > mt.get("roof_k", 0.75)] = nid(mt["roof"])
        if mt.get("cap"):
            out[(cz > mt.get("cap_z", 1e9)) & (nzz > mt.get("cap_k", 0.12))] = nid(mt["cap"])
        if mt.get("ground"):
            out[(nzz > 0.9) & (cz < mt.get("ground_z", 0.5))] = nid(mt["ground"])
        if mt.get("radial_windows"):
            rw = mt["radial_windows"]            # {r_max, z:[z0,z1], k, col}: recessed faces facing out from the axis
            cxy = cent[m, :2]
            rr = np.hypot(cxy[:, 0], cxy[:, 1]) + 1e-9
            rad = (nrm[m, 0] * cxy[:, 0] + nrm[m, 1] * cxy[:, 1]) / rr
            ww = (rad > rw.get("k", 0.8)) & (rr < rw["r_max"]) & (cz > rw["z"][0]) & (cz < rw["z"][1])
            out[ww] = nid(rw["col"])
        if mt.get("windows"):
            out[win[m]] = nid(wcfg.get("col", "window_grille"))
        lab[m] = out
    return names, lab, reg


def write_obj(path, V, F, names, lab):
    import numpy as np
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t = time.time()
    with open(path, "w") as f:
        f.write("# import_mesh.py aligned skin (derived from a mesh of unknown licence: do not commit)\n")
        np.savetxt(f, V, fmt="v %.4f %.4f %.4f")
        order = np.argsort(lab, kind="stable")
        for k in range(len(names)):
            sel = order[lab[order] == k]
            f.write("usemtl %s\n" % names[k])
            if len(sel):
                np.savetxt(f, F[sel] + 1, fmt="f %d %d %d")
    print("[import_mesh] wrote %s (%.1fs)" % (path, time.time() - t))


def prepare(cfg_path):
    import numpy as np
    cfg = json.load(open(cfg_path))
    base = os.path.dirname(os.path.abspath(cfg_path))
    t = time.time()
    V0, F = read_stl(config.resolve(cfg["stl"], base))
    print("[import_mesh] %d verts %d tris (%.1fs)" % (len(V0), len(F), time.time() - t))
    V = align(V0, cfg["align"])
    regions = _flat_regions(cfg)
    auto_bases(V, F, regions)
    rep = measure(V, F, cfg)
    names, lab, reg = classify(V, F, regions, cfg)
    write_obj(config.resolve(cfg["obj"], base), V, F, names, lab)   # dropped regions are removed by segment
    counts = {names[k]: int((lab == k).sum()) for k in range(len(names))}
    info = {"align": cfg["align"], "names": names, "faces_per_name": counts, "measure": rep,
            "regions": [{k: rg[k] for k in ("name", "part", "meta", "shape", "drop", "post", "base_z", "dome_center",
                                            "dome_r") if k in rg} for rg in regions],
            "bbox": [V.min(0).tolist(), V.max(0).tolist()],
            "faces_per_region": {rg["name"]: int((reg == i).sum()) for i, rg in enumerate(regions)}}
    wp = config.resolve(cfg["obj"], base)[:-4] + "_prep.json"
    json.dump(info, open(wp, "w"), indent=1)
    print("[import_mesh] faces per palette name:", counts)
    print("[import_mesh] prep json:", wp, "(%.1fs total)" % (time.time() - t))


# ============================================================================ Stage B: segment (Blender)
def _cutter(bpy, bm_mod, sh, name):
    """cutter object (closed, outward normals, all faces material 0) for a shape spec."""
    import bmesh
    bm = bmesh.new()

    def add_prism(poly, z0, z1):
        vb = [bm.verts.new((x, y, z0)) for x, y in poly]
        vt = [bm.verts.new((x, y, z1)) for x, y in poly]
        bm.faces.new(list(reversed(vb)))
        bm.faces.new(vt)
        for i in range(len(poly)):
            j = (i + 1) % len(poly)
            bm.faces.new([vb[i], vb[j], vt[j], vt[i]])

    def poly_ccw(poly):
        a = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                for i in range(len(poly)))
        return poly if a > 0 else list(reversed(poly))
    if "box" in sh:
        x0, x1, y0, y1, z0, z1 = sh["box"]
        add_prism([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1)
    elif "cyl" in sh:
        cx, cy, r, z0, z1 = sh["cyl"]
        n = 48
        add_prism([(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)],
                  z0, z1)
    elif "poly" in sh:
        add_prism(poly_ccw([tuple(p) for p in sh["poly"]]), sh["z"][0], sh["z"][1])
    else:
        raise ValueError(sh)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.material_index = 0
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _bool(bpy, ob, cutter, op):
    md = ob.modifiers.new("b", 'BOOLEAN')
    md.operation = op
    md.object = cutter
    md.solver = 'MANIFOLD'
    md.material_mode = 'INDEX'
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    ob.modifiers.remove(md)
    return me


def _shape_obj(bpy, sh, name, tmp):
    """cutter for a (possibly compound) shape: union -> boolean union of cutters; and -> intersection."""
    if "union" in sh:
        objs = [_shape_obj(bpy, s, "%s_u%d" % (name, i), tmp) for i, s in enumerate(sh["union"])]
        base = objs[0]
        for o in objs[1:]:
            me = _bool(bpy, base, o, 'UNION'); base.data = me
        return base
    if "and" in sh:
        objs = [_shape_obj(bpy, s, "%s_a%d" % (name, i), tmp) for i, s in enumerate(sh["and"])]
        base = objs[0]
        for o in objs[1:]:
            me = _bool(bpy, base, o, 'INTERSECT'); base.data = me
        return base
    o = _cutter(bpy, None, sh, name)
    tmp.append(o)
    return o


def segment(cfg_path):
    import bpy
    from mathutils import Vector
    cfg = json.load(open(cfg_path))
    base = os.path.dirname(os.path.abspath(cfg_path))
    prep = json.load(open(config.resolve(cfg["obj"], base)[:-4] + "_prep.json"))
    regions = prep["regions"]
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=config.resolve(cfg["obj"], base), forward_axis='Y', up_axis='Z')
    src = bpy.context.selected_objects[0]
    src.name = "MESH_src"
    names = [m.name for m in src.data.materials]
    print("[import_mesh] OBJ in %.1fs: %d polys, materials %s" % (time.time() - t0, len(src.data.polygons), names))
    # the cut colour must be slot 0 (cutter faces carry index 0); the OBJ writes it first, but an unused usemtl may
    # be dropped by the importer: insert it then
    cut = cfg.get("cut_col", "brick_byz")
    if not names or names[0] != cut:
        m = bpy.data.materials.get(cut) or bpy.data.materials.new(cut)
        src.data.materials.append(m)
        mats = list(src.data.materials)
        idx = [0] * len(src.data.polygons)
        src.data.polygons.foreach_get("material_index", idx)
        n_old = len(mats) - 1
        src.data.materials.clear()
        src.data.materials.append(m)
        for mm in mats[:-1]:
            src.data.materials.append(mm)
        src.data.polygons.foreach_set("material_index", [i + 1 for i in idx])
        names = [mm.name for mm in src.data.materials]
    tmp = []
    prev = None                     # union of all earlier cutters
    col = bpy.data.collections.new("mesh_skin")
    bpy.context.scene.collection.children.link(col)
    pieces = []
    for i, rg in enumerate(regions):
        t = time.time()
        cu = _shape_obj(bpy, rg["shape"], "CUT_%s" % rg["name"], tmp)
        own = cu.copy(); own.data = cu.data.copy(); bpy.context.scene.collection.objects.link(own); tmp.append(own)
        if prev is not None:
            own.data = _bool(bpy, own, prev, 'DIFFERENCE')
            prev.data = _bool(bpy, prev, cu, 'UNION')
        else:
            prev = cu.copy(); prev.data = cu.data.copy(); bpy.context.scene.collection.objects.link(prev)
            tmp.append(prev)
        if rg.get("drop"):
            print("[import_mesh] %-14s dropped" % rg["name"]); continue
        me = _bool(bpy, src, own, 'INTERSECT')
        if len(me.polygons) == 0:
            print("[import_mesh] %-14s EMPTY" % rg["name"]); continue
        ob = bpy.data.objects.new("MS_" + rg["name"], me)
        col.objects.link(ob)
        # pivot: region-given or the bottom centre of the piece's bbox
        xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
        piv = rg.get("pivot") or [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, min(zs)]
        post = rg.get("post") or {}
        if post.get("scale_z"):                     # vertical rescale about the piece's base (minarets)
            zb = post.get("about_z", min(zs))
            for v in me.vertices:
                v.co.z = zb + (v.co.z - zb) * post["scale_z"]
        if post.get("z_map"):                       # piecewise-linear vertical remap [[z_in, z_out], ...] (ep02 dome)
            import numpy as np
            zi, zo = (list(c) for c in zip(*post["z_map"]))
            co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
            co[:, 2] = np.interp(co[:, 2], zi, zo)
            me.vertices.foreach_set("co", co.ravel())
        for v in me.vertices:
            v.co -= Vector(piv)
        ob.location = Vector(piv)
        me.update()
        ztop = max(v.co.z for v in me.vertices) + piv[2]
        pieces.append({"object": ob.name, "part": rg["part"], "meta": rg.get("meta", {}), "pivot": list(piv),
                       "polys": len(me.polygons), "z_top": ztop, "region": rg["name"],
                       "dome_center": rg.get("dome_center"), "dome_r": rg.get("dome_r")})
        print("[import_mesh] %-14s -> %-12s %7d polys  top %.1f m  (%.1fs)" % (rg["name"], rg["part"],
                                                                            len(me.polygons), ztop, time.time() - t))
    for o in tmp:
        if o.name in bpy.data.objects:
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.objects.remove(src, do_unlink=True)
    out_blend = config.resolve(cfg["out_blend"], base)
    os.makedirs(os.path.dirname(out_blend), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True)
    info = {"blend": out_blend, "collection": "mesh_skin", "materials": names, "pieces": pieces,
            "align": prep["align"], "measure": prep["measure"], "note": "derived from a mesh of unknown licence:"
            " never commit"}
    json.dump(info, open(config.resolve(cfg["out_json"], base), "w"), indent=1)
    print("[import_mesh] saved %s with %d pieces, %d polys (%.1fs)" % (out_blend, len(pieces),
                                                                     sum(p["polys"] for p in pieces), time.time() - t0))


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if not argv or argv[0] not in ("prepare", "segment"):
        print(__doc__); sys.exit(1)
    {"prepare": prepare, "segment": segment}[argv[0]](config.find_config(argv[1]))
