"""import_scan.py - reusable step: photogrammetry GLB -> real-scale, aligned, lit .blend asset.

Two stages, because big scans ship with 8K textures that must never reach Blender on this 8 GB machine.

Stage A, plain python3 (no Blender): re-embed every image at a smaller size.
    python3 kit/import_scan.py downscale SRC.glb DST.glb [--size 4096] [--quality 90]
  JPEGs are decoded with PIL draft mode (DCT scaling), so an 8192^2 JPEG never exists in memory at full size.
  The BIN chunk is rebuilt (bufferView offsets/lengths, 4-byte alignment, chunk padding) and re-checked.

Stage B, inside Blender (run through kit/blender_locked.sh):
    kit/blender_locked.sh -b --factory-startup -P kit/import_scan.py -- prep CONFIG.json
  CONFIG keys (see models/pantheon/interior_prep.json):
    glb            downscaled GLB to import
    out_blend      .blend to write (textures packed)          out_json   transform + measurements for the kit
    collection     collection name for the scan meshes        prefix     object-name prefix
    measure        {"mode": "rotunda", "real_diameter": 43.3, "real_height": 43.3, "slice_above_floor": 5.0,
                    "use": "mean" | "diameter" | "height"}
                   or {"mode": "bbox", "axis": "z", "real": 12.0}
    remove_oculus_cap  true (default): delete faces that close the oculus (scans often cap it with a 'sky' face,
                   which blocks the sun)
    align          {"entrance_to_az": 270}  rotunda only: turn the widest wall opening (the door) to this plan azimuth
                   (kit convention: portico faces -Y = 270 deg); {"rotate_z_deg": a} forces a rotation instead
    shading        {"emission": 0.78, "principled": 0.22, "roughness": 0.8}  baked-light scans: mostly unlit
    sunbeam        {"sun_az": 75, "sun_el": 55, "strength": 30, "volume_density": 0.06, "anisotropy": 0.3} or null
                   (sun + a volume cylinder only along the beam; volume object casts no shadow)
    render         {"path": ".png", "res": [1080, 1920], "samples": 24, "camera": {"loc": [..], "target": [..], "lens": 14}}
  Meshes are baked to world space (identity object transforms), joined per material, floor at z=0, centre at origin.
"""
import io
import json
import math
import os
import struct
import sys
import time

GLB_MAGIC, CH_JSON, CH_BIN = 0x46546C67, 0x4E4F534A, 0x004E4942


# ============================================================================ Stage A: GLB texture downscale
def _read_glb(f):
    magic, ver, _ = struct.unpack("<III", f.read(12))
    assert magic == GLB_MAGIC and ver == 2, "not a glTF 2.0 binary"
    clen, ctype = struct.unpack("<II", f.read(8))
    assert ctype == CH_JSON
    js = json.loads(f.read(clen))
    blen, btype = struct.unpack("<II", f.read(8))
    assert btype == CH_BIN
    return js, f.tell(), blen


def _resize_image(data, mime, size, quality):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    w, h = im.size
    if max(w, h) <= size:
        return data, (w, h), (w, h)
    tw, th = (size, round(h * size / w)) if w >= h else (round(w * size / h), size)
    if im.format == "JPEG":
        im.draft(im.mode if im.mode in ("RGB", "L") else "RGB", (tw, th))   # DCT-domain 1/2,1/4,1/8 decode
    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") and mime == "image/png" else "RGB")
    if im.size != (tw, th):
        im = im.resize((tw, th), Image.LANCZOS)
    out = io.BytesIO()
    if mime == "image/png":
        im.save(out, "PNG", optimize=False, compress_level=6)
    else:
        im.save(out, "JPEG", quality=quality, subsampling=0, optimize=True)
    im.close()
    return out.getvalue(), (w, h), (tw, th)


def downscale_glb(src, dst, size=4096, quality=90, log=print):
    """Rewrite SRC.glb with every embedded image scaled so its long side <= size. Returns a report dict."""
    import gc
    with open(src, "rb") as f:
        js, bin0, blen = _read_glb(f)
        assert len(js.get("buffers", [])) == 1 and "uri" not in js["buffers"][0], "expects one embedded buffer"
        img_views = {im["bufferView"]: im.get("mimeType", "image/jpeg") for im in js.get("images", []) if "bufferView" in im}
        new_img, report = {}, []
        for iv, mime in img_views.items():                       # one image at a time, freed after encoding
            bv = js["bufferViews"][iv]
            f.seek(bin0 + bv.get("byteOffset", 0))
            data = f.read(bv["byteLength"])
            t0 = time.time()
            new, s0, s1 = _resize_image(data, mime, size, quality)
            new_img[iv] = new
            report.append(dict(view=iv, name=bv.get("name"), mime=mime, src=s0, dst=s1,
                               bytes_in=len(data), bytes_out=len(new), sec=round(time.time() - t0, 2)))
            log(f"  image view {iv}: {s0} -> {s1}  {len(data)/1e6:.1f} MB -> {len(new)/1e6:.1f} MB")
            del data
            gc.collect()
        # new layout: all views in original order of offset, each 4-byte aligned (keeps accessor alignment)
        order = sorted(range(len(js["bufferViews"])), key=lambda i: js["bufferViews"][i].get("byteOffset", 0))
        spans = [(js["bufferViews"][i].get("byteOffset", 0), js["bufferViews"][i].get("byteOffset", 0) + js["bufferViews"][i]["byteLength"]) for i in order]
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            assert b0 >= a1, "overlapping bufferViews are not supported"
        pos, plan = 0, []
        for i in order:
            bv = js["bufferViews"][i]
            pos = (pos + 3) & ~3
            n = len(new_img[i]) if i in new_img else bv["byteLength"]
            plan.append((i, bv.get("byteOffset", 0), bv["byteLength"], pos, n))
            pos += n
        total = pos
        for i, _, _, npos, n in plan:
            js["bufferViews"][i]["byteOffset"] = npos
            js["bufferViews"][i]["byteLength"] = n
        js["buffers"][0]["byteLength"] = total
        js.setdefault("asset", {}).setdefault("extras", {})["downscaled"] = f"images <= {size}px by kit/import_scan.py"
        jbytes = json.dumps(js, separators=(",", ":")).encode()
        jbytes += b" " * ((4 - len(jbytes) % 4) % 4)
        bpad = (4 - total % 4) % 4
        length = 12 + 8 + len(jbytes) + 8 + total + bpad
        tmp = dst + ".tmp"
        with open(tmp, "wb") as o:
            o.write(struct.pack("<III", GLB_MAGIC, 2, length))
            o.write(struct.pack("<II", len(jbytes), CH_JSON)); o.write(jbytes)
            o.write(struct.pack("<II", total + bpad, CH_BIN))
            cur = 0
            for i, oofs, olen, npos, n in plan:
                o.write(b"\0" * (npos - cur)); cur = npos
                if i in new_img:
                    o.write(new_img[i])
                else:
                    f.seek(bin0 + oofs)
                    left = olen
                    while left:
                        chunk = f.read(min(left, 8 << 20)); o.write(chunk); left -= len(chunk)
                cur += n
            o.write(b"\0" * bpad)
    os.replace(tmp, dst)
    verify_glb(dst)
    return dict(src=src, dst=dst, bytes_in=os.path.getsize(src), bytes_out=os.path.getsize(dst), images=report)


def verify_glb(path):
    """Structural check: header length, chunk sizes, every view/accessor inside the buffer, images decodable."""
    from PIL import Image
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        _, _, length = struct.unpack("<III", f.read(12))
        assert length == size, f"header length {length} != file size {size}"
        f.seek(0)
        js, bin0, blen = _read_glb(f)
        assert bin0 + blen == size and blen % 4 == 0 and blen >= js["buffers"][0]["byteLength"]
        for bv in js["bufferViews"]:
            assert bv.get("byteOffset", 0) % 4 == 0 and bv.get("byteOffset", 0) + bv["byteLength"] <= js["buffers"][0]["byteLength"]
        csize = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
        ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
        for a in js["accessors"]:
            bv = js["bufferViews"][a["bufferView"]]
            el = csize[a["componentType"]] * ncomp[a["type"]]
            stride = bv.get("byteStride", el)
            end = a.get("byteOffset", 0) + stride * (a["count"] - 1) + el
            assert end <= bv["byteLength"], "accessor overruns its bufferView"
        sizes = []
        for im in js.get("images", []):
            bv = js["bufferViews"][im["bufferView"]]
            f.seek(bin0 + bv["byteOffset"])
            i = Image.open(io.BytesIO(f.read(bv["byteLength"])))
            i.verify()
            sizes.append(i.size)
    return sizes


# ============================================================================ Stage B: Blender
def _np_verts(objs):
    import numpy as np
    out = []
    for o in objs:
        me = o.data
        a = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", a)
        a = a.reshape(-1, 3)
        M = np.array(o.matrix_world, dtype=np.float64)
        out.append((a @ M[:3, :3].T + M[:3, 3]).astype(np.float32))
    return np.concatenate(out)


def fit_circle(xy, iters=4, keep=0.03):
    """Kasa least-squares circle, then re-fit on points within +-keep*r of the circle (drops columns, niches)."""
    import numpy as np
    sel = xy
    for _ in range(iters):
        x, y = sel[:, 0].astype(np.float64), sel[:, 1].astype(np.float64)
        A = np.c_[2 * x, 2 * y, np.ones_like(x)]
        cx, cy, c = np.linalg.lstsq(A, x * x + y * y, rcond=None)[0]
        r = math.sqrt(c + cx * cx + cy * cy)
        d = np.hypot(xy[:, 0] - cx, xy[:, 1] - cy)
        sel = xy[np.abs(d - r) < keep * r]
    return cx, cy, r, float(np.std(np.hypot(sel[:, 0] - cx, sel[:, 1] - cy) - r)), len(sel)


def radial_mode(xy, cx, cy, lo, hi, bins=400):
    import numpy as np
    d = np.hypot(xy[:, 0] - cx, xy[:, 1] - cy)
    h, e = np.histogram(d, bins=bins, range=(lo, hi))
    k = int(np.argmax(h))
    return 0.5 * (e[k] + e[k + 1])


def measure_rotunda(V, cfg, log=print):
    """V: Nx3 world verts (z up), scan units. Measures, in scan units:
      z_floor      densest height band in the lowest 10 % (the pavement)
      cx, cy       axis of the rotunda: circle fit on the cleanest horizontal band between 35 % and 60 % of the height
      drum_r       wall radius at floor + slice_above_floor (real m): per-degree innermost surface -> median -> refit
                   (columns stand on the wall line, niches lie behind it, aedicules in front: the median ignores both)
      dome sphere  least-squares sphere through the coffered dome (62-93 % of height) -> apex = centre z + radius
      oculus       hole radius, intrados edge height (lowest point of the rim), lip top (highest vertex)
      entrance     plan azimuth of the longest run of empty 1-degree bins at floor + 3 m (the open doorway)
    scale_from_diameter = real_diameter / (2 drum_r); scale_from_height = real_height / (dome apex - floor)."""
    import numpy as np
    V = V.astype(np.float64)
    z = V[:, 2]
    zmin, zmax = float(z.min()), float(z.max())
    lowband = z[z < zmin + 0.1 * (zmax - zmin)]
    h, e = np.histogram(lowband, bins=200)
    k = int(np.argmax(h)); z_floor = 0.5 * (e[k] + e[k + 1])
    H = zmax - z_floor
    # axis: cleanest circular band
    best = None
    for f in np.linspace(0.35, 0.60, 11):
        xy = V[np.abs(z - (z_floor + f * H)) < 0.004 * H][:, :2]
        if len(xy) < 500:
            continue
        cx, cy, r, sd, n = fit_circle(xy, iters=2, keep=0.05)
        if best is None or sd / r < best[0]:
            best = (sd / r, cx, cy, r, float(f))
    _, cx, cy, r_band, f_band = best
    s_est = cfg["real_diameter"] / (2 * r_band)
    # drum radius at floor + slice_above_floor
    zs = z_floor + cfg.get("slice_above_floor", 5.0) / s_est
    sl = V[np.abs(z - zs) < 0.3 / s_est]
    d = np.hypot(sl[:, 0] - cx, sl[:, 1] - cy)
    a = ((np.degrees(np.arctan2(sl[:, 1] - cy, sl[:, 0] - cx)) + 360) % 360).astype(int) % 360
    inner = np.full(360, np.nan)
    for kk in range(360):
        m = a == kk
        if m.any():
            inner[kk] = d[m].min()
    med = float(np.nanmedian(inner))
    drum_r = float(d[np.abs(d - med) < 0.015 * med].mean())
    # dome sphere
    D = V[(z > z_floor + 0.62 * H) & (z < z_floor + 0.93 * H)]
    A = np.c_[2 * D, np.ones(len(D))]
    sol = np.linalg.lstsq(A, (D * D).sum(1), rcond=None)[0]
    sc = sol[:3]; sr = float(np.sqrt(sol[3] + sc @ sc))
    apex = float(sc[2] + sr)
    # oculus
    top = V[z > zmax - 0.02 * H]
    r_oc = float(np.percentile(np.hypot(top[:, 0] - cx, top[:, 1] - cy), 5))
    rim = V[(np.hypot(V[:, 0] - cx, V[:, 1] - cy) < r_oc + 0.02 * drum_r) & (z > z_floor + 0.8 * H)]
    z_intr = float(rim[:, 2].min()) if len(rim) else zmax
    # entrance: longest circular run of empty bins at floor + 3 m
    sl = V[np.abs(z - (z_floor + 3.0 / s_est)) < 0.3 / s_est]
    a = ((np.degrees(np.arctan2(sl[:, 1] - cy, sl[:, 0] - cx)) + 360) % 360).astype(int) % 360
    cnt = np.bincount(a, minlength=360)
    empty = cnt < max(3, 0.05 * np.median(cnt))
    runs, cur = [], None
    for kk in range(720):
        if empty[kk % 360]:
            cur = [kk, kk] if cur is None else [cur[0], kk]
        elif cur is not None:
            runs.append(cur); cur = None
    runs = [r_ for r_ in runs if r_[0] < 360 and r_[1] - r_[0] < 359]
    lr = max(runs, key=lambda r_: r_[1] - r_[0]) if runs else [0, -1]
    ent = ((lr[0] + lr[1] + 1) / 2.0) % 360
    s_d, s_h = cfg["real_diameter"] / (2 * drum_r), cfg["real_height"] / (apex - z_floor)
    use = cfg.get("use", "mean")
    s = {"diameter": s_d, "height": s_h}.get(use, 0.5 * (s_d + s_h))
    out = dict(z_floor=float(z_floor), cx=float(cx), cy=float(cy), axis_band_frac=f_band, band_r=float(r_band),
               slice_z=float(zs), drum_r=drum_r, dome_sphere_c=[float(v) for v in sc], dome_sphere_r=sr, dome_apex_z=apex,
               oculus_r=r_oc, oculus_intrados_z=z_intr, oculus_lip_top_z=zmax,
               entrance_az_scan=float(ent), entrance_gap_deg=int(lr[1] - lr[0] + 1),
               scale_from_diameter=float(s_d), scale_from_height=float(s_h), scale_use=use, scale=float(s))
    log(f"  measure: floor z={z_floor:.3f} axis=({cx:.3f},{cy:.3f}) drum r@+{cfg.get('slice_above_floor', 5.0)}m={drum_r:.3f} "
        f"band r={r_band:.3f} dome sphere r={sr:.3f} apex={apex:.3f} oculus r={r_oc:.3f} intrados z={z_intr:.3f} "
        f"lip z={zmax:.3f} | scale d={s_d:.4f} h={s_h:.4f} -> {s:.4f} ({use}) | entrance az={ent:.1f} (gap {lr[1]-lr[0]+1} deg)")
    return out


def _bake_world(objs):
    for o in objs:
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world.identity()


def _join_by_material(objs, prefix):
    import bpy
    groups = {}
    for o in objs:
        key = o.data.materials[0].name if o.data.materials else "_none"
        groups.setdefault(key, []).append(o)
    result = []
    for i, (mat, lst) in enumerate(sorted(groups.items())):
        bpy.ops.object.select_all(action="DESELECT")
        for o in lst:
            o.select_set(True)
        bpy.context.view_layer.objects.active = lst[0]
        if len(lst) > 1:
            bpy.ops.object.join()
        o = bpy.context.view_layer.objects.active
        o.name = o.data.name = f"{prefix}{i:02d}"
        o["scan_material"] = mat
        result.append(o)
    return result


def scan_material(mat, emission=0.85, principled=0.15, roughness=0.8, strength=1.0):
    """Photogrammetry texture = baked light. Mix(emission(tex), principled(tex)) keeps the photo look,
    while the principled share still picks up our sun (the oculus light disc) and shadows."""
    nt = mat.node_tree
    img = next((n.image for n in nt.nodes if n.type == "TEX_IMAGE" and n.image), None)
    nt.nodes.clear()          # rebuild from scratch (python refs to surviving nodes are unsafe after removals)
    tex = None
    if img is not None:
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission"); em.inputs["Strength"].default_value = strength
    pb = nt.nodes.new("ShaderNodeBsdfPrincipled"); pb.inputs["Roughness"].default_value = roughness
    mix = nt.nodes.new("ShaderNodeMixShader"); mix.inputs[0].default_value = principled / max(emission + principled, 1e-6)
    if tex:
        tex.interpolation = "Linear"
        nt.links.new(tex.outputs["Color"], em.inputs["Color"])
        nt.links.new(tex.outputs["Color"], pb.inputs["Base Color"])
    nt.links.new(em.outputs[0], mix.inputs[1])
    nt.links.new(pb.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    mat["scan_shading"] = json.dumps(dict(emission=emission, principled=principled, roughness=roughness))
    mat.use_backface_culling = False
    return mat


def add_sunbeam(coll, drum_r, height, oculus_r=4.35, sun_az=75.0, sun_el=55.0, strength=15.0, volume_density=0.05,
                angle_deg=0.53, anisotropy=0.3, volume_color=(1.0, 0.97, 0.9)):
    """Sun through the oculus + a volume only along the beam (a slanted cylinder from above the oculus to the wall).
    Keeping the medium inside the shaft means the rest of the room is not fogged; the dome's shadow trims the
    cylinder to the real beam. sun_az/el: direction TO the sun (kit plan azimuth, deg)."""
    import bpy
    import bmesh
    from mathutils import Vector
    sun = bpy.data.lights.new("scan_sun", "SUN")
    sun.energy = strength; sun.angle = math.radians(angle_deg); sun.color = (1.0, 0.95, 0.86)
    so = bpy.data.objects.new("scan_sun", sun)
    d = Vector((math.cos(math.radians(sun_az)) * math.cos(math.radians(sun_el)),
                math.sin(math.radians(sun_az)) * math.cos(math.radians(sun_el)), math.sin(math.radians(sun_el))))
    so.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    so.location = (0, 0, height + 10)
    coll.objects.link(so)
    vol = None
    if volume_density > 0:
        O = Vector((0, 0, height))
        l_in = drum_r / max(math.cos(math.radians(sun_el)), 0.2) + 2.0
        above = 4.0
        me = bpy.data.meshes.new("scan_volume")
        bm = bmesh.new()
        r = oculus_r * 1.1
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=r, radius2=r, depth=l_in + above)
        bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, (l_in + above) / 2))
        bm.to_mesh(me); bm.free()
        vol = bpy.data.objects.new("scan_volume", me)
        vol.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
        vol.location = O - d * l_in
        m = bpy.data.materials.new("scan_volume")
        nt = m.node_tree; nt.nodes.clear()
        pv = nt.nodes.new("ShaderNodeVolumePrincipled"); pv.inputs["Density"].default_value = volume_density
        pv.inputs["Anisotropy"].default_value = anisotropy
        pv.inputs["Color"].default_value = (*volume_color, 1.0)
        o = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(pv.outputs[0], o.inputs["Volume"])
        me.materials.append(m)
        vol.display_type = "BOUNDS"
        vol.visible_shadow = False          # the cylinder would otherwise plug the oculus in the shadow map
        coll.objects.link(vol)
    return so, vol


def _mem_mb():
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20)   # macOS: bytes


def prep(cfg, log=print):
    import bpy
    import numpy as np
    from mathutils import Matrix
    T0 = time.time()
    rep = dict(steps={})
    bpy.ops.wm.read_factory_settings(use_empty=True)
    t = time.time()
    bpy.ops.import_scene.gltf(filepath=cfg["glb"])
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    rep["steps"]["import_s"] = round(time.time() - t, 1); rep["mem_after_import_mb"] = round(_mem_mb())
    rep["source_meshes"] = [o.name for o in meshes]
    rep["faces"] = int(sum(len(o.data.polygons) for o in meshes))
    log(f"  imported {len(meshes)} meshes, {rep['faces']} faces in {rep['steps']['import_s']} s, maxrss {rep['mem_after_import_mb']} MB")
    _bake_world(meshes)
    for o in list(bpy.context.scene.objects):
        if o.type != "MESH":
            bpy.data.objects.remove(o)
    V = _np_verts(meshes)
    rep["bbox_scan"] = [V.min(0).round(3).tolist(), V.max(0).round(3).tolist()]
    mc = cfg["measure"]
    if mc["mode"] == "rotunda":
        m = measure_rotunda(V, mc, log)
        s = m["scale"]
        rot = cfg.get("align", {}).get("rotate_z_deg")
        if rot is None:
            rot = cfg.get("align", {}).get("entrance_to_az", m["entrance_az_scan"]) - m["entrance_az_scan"]
        C = (m["cx"], m["cy"], m["z_floor"])
    else:
        ax = "xyz".index(mc.get("axis", "z"))
        s = mc["real"] / float(V[:, ax].max() - V[:, ax].min())
        m = dict(scale=s); rot = cfg.get("align", {}).get("rotate_z_deg", 0.0)
        C = (float(V[:, 0].mean()), float(V[:, 1].mean()), float(V[:, 2].min()))
    del V
    M = Matrix.Rotation(math.radians(rot), 4, "Z") @ Matrix.Scale(s, 4) @ Matrix.Translation((-C[0], -C[1], -C[2]))
    for o in meshes:
        o.data.transform(M)
    capped = 0
    if mc["mode"] == "rotunda" and cfg.get("remove_oculus_cap", True):
        # scans often close the oculus with a 'sky' face (photographed sky): it blocks our sun, so cut it out
        import bmesh
        r_cut = 0.95 * m["oculus_r"] * s
        z_cut = (m["oculus_intrados_z"] - m["z_floor"]) * s - 0.5
        for o in meshes:
            n = len(o.data.polygons)
            c = np.empty(n * 3, dtype=np.float32); o.data.polygons.foreach_get("center", c); c = c.reshape(-1, 3)
            kill = np.nonzero((np.hypot(c[:, 0], c[:, 1]) < r_cut) & (c[:, 2] > z_cut))[0]
            if len(kill):
                bm = bmesh.new(); bm.from_mesh(o.data); bm.faces.ensure_lookup_table()
                bmesh.ops.delete(bm, geom=[bm.faces[int(i)] for i in kill], context="FACES")
                bm.to_mesh(o.data); bm.free()
                capped += len(kill)
        log(f"  removed {capped} faces capping the oculus (r < {r_cut:.2f} m, z > {z_cut:.2f} m)")
    rep["oculus_cap_faces_removed"] = capped
    coll = bpy.data.collections.new(cfg.get("collection", "scan"))
    bpy.context.scene.collection.children.link(coll)
    for o in meshes:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    objs = _join_by_material(meshes, cfg.get("prefix", "scan_"))
    sh = cfg.get("shading", {})
    for o in objs:
        for mat in o.data.materials:
            scan_material(mat, **sh)
    V = _np_verts(objs)
    bb = [V.min(0).round(3).tolist(), V.max(0).round(3).tolist()]
    if mc["mode"] == "rotunda":
        m2 = measure_rotunda(V, dict(mc, use="diameter"), lambda *_: None)
        f0 = m2["z_floor"]
        check = dict(floor=round(f0, 3), centre=[round(m2["cx"], 3), round(m2["cy"], 3)], drum_r=round(m2["drum_r"], 3),
                     dome_apex=round(m2["dome_apex_z"] - f0, 3), dome_sphere_r=round(m2["dome_sphere_r"], 3),
                     dome_sphere_cz=round(m2["dome_sphere_c"][2] - f0, 3), oculus_r=round(m2["oculus_r"], 3),
                     oculus_intrados=round(m2["oculus_intrados_z"] - f0, 3), oculus_lip_top=round(m2["oculus_lip_top_z"] - f0, 3),
                     entrance_az=round(m2["entrance_az_scan"], 1))
        log(f"  after transform: {check}")
    else:
        check = {}
    del V
    for img in bpy.data.images:
        if img.source == "FILE" and not img.packed_file:
            img.pack()
    sb = cfg.get("sunbeam")
    height = check.get("oculus_lip_top", bb[1][2]) if check else bb[1][2]
    drum_r = check.get("drum_r", 0.5 * (bb[1][0] - bb[0][0]))
    if sb:
        add_sunbeam(coll, drum_r, height, oculus_r=check.get("oculus_r", 4.35), **sb)
    info = dict(
        source_glb=os.path.abspath(cfg["glb"]), blend=os.path.abspath(cfg["out_blend"]), collection=coll.name,
        objects=[o.name for o in objs], lights=[o.name for o in coll.objects if o.type == "LIGHT"],
        volume=[o.name for o in coll.objects if o.name.startswith("scan_volume")],
        materials={o.name: [mm.name for mm in o.data.materials] for o in objs},
        transform=dict(order="p_kit = Rz(rot) * S(scale) * (p_import - origin)", origin_import=list(C), scale=s,
                       rotate_z_deg=rot, matrix=[list(r) for r in M]),
        measure_scan_units=m, measured_after=check, bbox_kit=bb,
        drum_radius_m=check.get("drum_r"), oculus_rim_height_m=check.get("oculus_intrados"),
        oculus_lip_top_m=check.get("oculus_lip_top"), dome_apex_m=check.get("dome_apex"), oculus_radius_m=check.get("oculus_r"),
        shading=sh, sunbeam=sb, faces=rep["faces"],
        append_hint=f"bpy.ops.wm.append(directory='{os.path.abspath(cfg['out_blend'])}/Collection/', filename='{coll.name}')",
        colour_management="baked textures are display-referred: render with view_transform 'Standard' "
                          "(AgX flattens them); emission strength 1.0 reproduces the photo",
        credit="'The Pantheon Interior' by artfletch (Sketchfab), CC BY 4.0",
    )
    rc = cfg.get("render")
    if rc:
        info["render"] = render_still(rc, log)
    rep["steps"]["total_s"] = round(time.time() - T0, 1); rep["maxrss_mb"] = round(_mem_mb())
    info["prep_report"] = rep
    for c in list(bpy.data.objects):
        if c.name.startswith("preview_cam"):
            bpy.data.objects.remove(c)
    bpy.ops.wm.save_as_mainfile(filepath=cfg["out_blend"], compress=False)
    info["blend_bytes"] = os.path.getsize(cfg["out_blend"])
    with open(cfg["out_json"], "w") as f:
        json.dump(info, f, indent=1)
    log(f"  saved {cfg['out_blend']} ({info['blend_bytes']/1e6:.0f} MB) and {cfg['out_json']}; maxrss {rep['maxrss_mb']} MB")
    return info


def render_still(rc, log=print):
    import bpy
    from mathutils import Vector
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    ee = sc.eevee
    ee.taa_render_samples = rc.get("samples", 24)
    ee.use_shadows = True
    for k, v in dict(volumetric_tile_size=rc.get("vol_tile", "8"), volumetric_samples=rc.get("vol_samples", 48),
                     use_volumetric_shadows=True, volumetric_shadow_samples=16, volumetric_end=200.0,
                     use_raytracing=rc.get("raytracing", False)).items():
        if hasattr(ee, k):
            try:
                setattr(ee, k, v)
            except Exception as e:  # noqa
                log(f"  (eevee.{k} not set: {e})")
    sc.render.resolution_x, sc.render.resolution_y = rc.get("res", [1080, 1920])
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = rc.get("view_transform", "Standard")
    sc.view_settings.look = "None"
    sc.view_settings.exposure = rc.get("exposure", 0.0)
    # world: the camera sees the sky (door, oculus); lighting/volume get only a dim share, so the haze is lit
    # by the sun alone and the shaft stays a shaft (the scan itself is ~85 % emission and needs no fill)
    w = bpy.data.worlds.new("scan_world")
    nt = w.node_tree
    nt.nodes.clear()
    sky_rgb = (*rc.get("sky_color", (0.55, 0.68, 0.9)), 1.0)
    bg_cam = nt.nodes.new("ShaderNodeBackground"); bg_cam.inputs[0].default_value = sky_rgb
    bg_cam.inputs[1].default_value = rc.get("sky", 1.0)
    bg_lit = nt.nodes.new("ShaderNodeBackground"); bg_lit.inputs[0].default_value = sky_rgb
    bg_lit.inputs[1].default_value = rc.get("sky_light", 0.15)
    lp = nt.nodes.new("ShaderNodeLightPath"); mx = nt.nodes.new("ShaderNodeMixShader")
    wo = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(lp.outputs["Is Camera Ray"], mx.inputs[0])
    nt.links.new(bg_lit.outputs[0], mx.inputs[1]); nt.links.new(bg_cam.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], wo.inputs[0])
    sc.world = w
    c = rc["camera"]
    cam = bpy.data.cameras.new("preview_cam"); cam.lens = c.get("lens", 14); cam.clip_start = 0.1; cam.clip_end = 400
    co = bpy.data.objects.new("preview_cam", cam); sc.collection.objects.link(co)
    co.location = c["loc"]
    co.rotation_euler = (Vector(c["target"]) - Vector(c["loc"])).to_track_quat("-Z", "Y").to_euler()
    if "roll_deg" in c:
        co.rotation_euler.rotate_axis("Z", math.radians(c["roll_deg"]))
    sc.camera = co
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = rc["path"]
    os.makedirs(os.path.dirname(rc["path"]), exist_ok=True)
    times = []
    for i in range(max(1, rc.get("repeat", 1))):          # 1st includes shader compile; later = steady state
        t = time.time()
        bpy.ops.render.render(write_still=True)
        times.append(round(time.time() - t, 2))
    dt = times[-1]
    log(f"  rendered {rc['path']} {rc.get('res')} in {times} s; maxrss {_mem_mb():.0f} MB")
    return dict(path=rc["path"], seconds=dt, seconds_all=times, maxrss_mb=round(_mem_mb()), camera=c)


def main(argv):
    if not argv:
        print(__doc__); return
    if argv[0] == "downscale":
        import argparse
        ap = argparse.ArgumentParser(prog="import_scan.py downscale")
        ap.add_argument("src"); ap.add_argument("dst")
        ap.add_argument("--size", type=int, default=4096); ap.add_argument("--quality", type=int, default=90)
        a = ap.parse_args(argv[1:])
        t = time.time()
        r = downscale_glb(a.src, a.dst, a.size, a.quality)
        print(json.dumps(dict(r, seconds=round(time.time() - t, 1), verified_sizes=verify_glb(a.dst)), indent=1))
    elif argv[0] == "prep":
        cfg = json.load(open(argv[1]))
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import config                      # models/..., out/... -> ARCH_KIT_MODELS / ARCH_KIT_OUT; else next to the JSON
        base = os.path.dirname(os.path.abspath(argv[1]))
        for k in ("glb", "out_blend", "out_json"):
            cfg[k] = config.resolve(cfg[k], base)
        if cfg.get("render"):
            cfg["render"]["path"] = config.resolve(cfg["render"]["path"], base)
        for k, v in (a.split("=", 1) for a in argv[2:]):     # quick overrides: render.samples=8
            d = cfg
            ks = k.split(".")
            for kk in ks[:-1]:
                d = d[kk]
            d[ks[-1]] = json.loads(v)
        prep(cfg)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
