"""reveal.py - hero disassembly still: our real-style exterior, dome (shell + oculus ring) lifted and tilted open,
the photogrammetry interior (interior_prepped.blend) inside the drum; scan dome (above the spring line) moves with the shell.
blender -b -P reveal.py -- OUT.png [key=value ...]"""
import bpy, sys, os, json, time, math, importlib.util
import numpy as np, bmesh
from mathutils import Vector, Matrix, Euler
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # kit/
sys.path.insert(0, KIT)
import paperkit as pk
import import_scan as isc
import config
argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
P = dict(lift=30.0, tilt=36.0, tilt_az=-38.0, cam_az=-38.0, cam_el=15.0, cam_dist=172.0, tz=40.0, ty=-8.0, tx=0.0, lens=38.0,
         scan_emis=1.0, tex=2048, z_split=21.9, repeat=2, beam=1.0, samples=16, shadow_res=0.45, sun_el=78.0, sun_az=-38.0)
for kv in argv[1:]:
    k, v = kv.split("="); P[k] = v if k == "kill_rings" else float(v)
T0 = time.time()
spec = json.load(open(os.path.join(KIT, "episodes/ep01_pantheon_paper.json")))
pk.STYLE = "real"; pk.FPS = 24
pk.new_scene()
import realkit
realkit.LOOK.update(spec.get("real_look", {}))
pk.set_palette(realkit.real_palette(spec["palette"], spec.get("real_palette")))
pk.backdrop(col=spec.get("backdrop", "table"))
sp = importlib.util.spec_from_file_location("builder", os.path.join(KIT, "build_pantheon.py"))
bp = importlib.util.module_from_spec(sp); sp.loader.exec_module(bp)
bp.build(pk, spec)
spec = dict(spec, schedule=[], section=[], camera=[])
pk.apply_episode(spec)
q = dict(spec.get("render", {})); q.update(spec.get("real_render", {})); q.pop("samples", None)
q["shadow_res"] = P["shadow_res"]
pk.render_setup(samples=int(P["samples"]), quality=q)
R, RDI = bp.R, bp.R_DOME_IN
print("[rev] built our scene %.1fs" % (time.time() - T0))

# ---------------------------------------------------------------- hide our interior (the scan replaces it)
hidden = 0
for part in ("floor", "coffers", "section_sphere"):
    for o in pk.PARTS.get(part, []):
        o.hide_render = True; hidden += 1
for o in pk.PARTS.get("ring_wall", []):
    if o.get("role") == "interior":
        o.hide_render = True; hidden += 1

def kill_faces(o, pred):
    me = o.data
    if o.data.users > 1:
        o.data = me = me.copy()
    bm = bmesh.new(); bm.from_mesh(me)
    M = o.matrix_world; N = M.to_3x3().inverted().transposed()
    dead = [f for f in bm.faces if pred(M @ f.calc_center_median(), (N @ f.normal).normalized())]
    if dead:
        bmesh.ops.delete(bm, geom=dead, context="FACES")
    bm.to_mesh(me); bm.free()
    return len(dead)

# drum: inner wall faces at r = R (the scan's walls/niches lie behind that surface)
nk = 0
for o in pk.PARTS.get("ring_wall", []):
    if o.get("role") == "drum":
        nk += kill_faces(o, lambda c, n: math.hypot(c.x, c.y) < R + 0.35 and c.z < R - 0.05 and
                         (n.x * c.x + n.y * c.y) / max(math.hypot(c.x, c.y), 1e-6) < -0.5)
# dome shell: inner faces (towards the dome centre) -> the scan's coffered dome shows from below
C = Vector((0, 0, R))
KILL_RINGS = [int(x) for x in str(P.get("kill_rings", "0-11")).split("-")]
for o in pk.PARTS.get("dome_outer", []):
    if KILL_RINGS[0] <= o.get("ring", 0) <= KILL_RINGS[-1]:
        nk += kill_faces(o, lambda c, n: (c - C).length < RDI + 0.2 and n.dot((c - C).normalized()) < -0.6)
print("[rev] rings", sorted(set(o.get("ring", -1) for o in pk.PARTS.get("dome_outer", []))))
print("[rev] hid %d interior pieces, deleted %d inner faces" % (hidden, nk))

# ---------------------------------------------------------------- append the scan
t = time.time()
blend = config.resolve("models/pantheon/interior_prepped.blend")
bpy.ops.wm.append(directory=blend + "/Collection/", filename="pantheon_interior_scan")
coll = bpy.data.collections["pantheon_interior_scan"]
for img in bpy.data.images:
    if img.size[0] > P["tex"]:
        img.scale(int(P["tex"]), int(P["tex"]))
scan = [o for o in coll.objects if o.type == "MESH" and o.name.startswith("scan_interior")]
for o in scan:
    for m in o.data.materials:
        for n in m.node_tree.nodes:
            if n.type == "EMISSION":
                n.inputs["Strength"].default_value = P["scan_emis"]
print("[rev] appended scan %.1fs, maxrss %.0f MB" % (time.time() - t, isc._mem_mb()))

# split the scan at the dome spring: faces above z_split travel with the dome
dome_scan = []
for o in scan:
    me2 = o.data.copy()
    o2 = bpy.data.objects.new(o.name + "_dome", me2); coll.objects.link(o2)
    zs = P["z_split"]
    kill_faces(o, lambda c, n: c.z > zs)
    kill_faces(o2, lambda c, n: c.z <= zs)
    dome_scan.append(o2)

# ---------------------------------------------------------------- lift + tilt the dome group
piv = bpy.data.objects.new("REV_dome_pivot", None); bpy.context.scene.collection.objects.link(piv)
piv.location = (0, 0, R)
bpy.context.view_layer.update()
keep0 = P["z_split"] > 25.0          # split at the drum top: ring 0 (haunch) stays, the drum top is a clean annulus
movers = [o for o in pk.PARTS.get("dome_outer", []) if not (keep0 and o.get("ring", 0) == 0)] + pk.PARTS.get("oculus", []) + dome_scan
for o in movers:
    mw = o.matrix_world.copy()
    o.parent = piv
    o.matrix_parent_inverse = piv.matrix_world.inverted()
    o.matrix_world = mw
# tilt: the far side goes up, so the coffered underside turns towards the camera
a = math.radians(P["tilt_az"])
cam_dir = Vector((math.sin(a), -math.cos(a), 0))        # from target towards camera (plan)
axis = Vector((0, 0, 1)).cross(cam_dir).normalized()
piv.location = (0, 0, R + P["lift"])
piv.rotation_mode = "QUATERNION"
from mathutils import Quaternion
piv.rotation_quaternion = Quaternion(axis, -math.radians(P["tilt"]))
bpy.context.view_layer.update()

# ---------------------------------------------------------------- scan light: sun through the (moved) oculus
sun = bpy.data.objects.get("scan_sun"); vol = bpy.data.objects.get("scan_volume")
oc_top = piv.matrix_world @ Vector((0, 0, 44.23 - R))          # oculus centre after the move
dome_axis = (piv.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
if sun:
    sd = Vector((math.sin(math.radians(P["sun_az"])) * math.cos(math.radians(P["sun_el"])),
                 -math.cos(math.radians(P["sun_az"])) * math.cos(math.radians(P["sun_el"])), math.sin(math.radians(P["sun_el"]))))
    sun.rotation_euler = (-sd).to_track_quat("-Z", "Y").to_euler()
    sun.location = oc_top + sd * 5
    try:     # the scan sun lights only the scan + beam; our building keeps the kit's low warm sun
        sun.light_linking.receiver_collection = coll
    except Exception as ex:
        print("[rev] light linking unavailable:", ex)
if vol:
    if P["beam"] > 0:
        # beam from above the oculus down to the floor/wall (along -sd)
        L = (oc_top.z + 4) / max(sd.z, 0.2)
        vol.matrix_world = Matrix.Identity(4)
        me = vol.data
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=4.35 * 1.05, radius2=4.35 * 1.05, depth=L)
        bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, L / 2))
        bm.to_mesh(me); bm.free()
        vol.rotation_euler = sd.to_track_quat("Z", "Y").to_euler()
        vol.location = oc_top + sd * 4 - sd * L
        for m in me.materials:
            for n in m.node_tree.nodes:
                if n.type == "PRINCIPLED_VOLUME":
                    n.inputs["Density"].default_value *= P["beam"]
    else:
        vol.hide_render = True

# ---------------------------------------------------------------- camera
pk.camera_keys([dict(t=0.0, az=P["cam_az"], el=P["cam_el"], dist=P["cam_dist"], target=[P["tx"], P["ty"], P["tz"]], lens=P["lens"])])
sc = bpy.context.scene
ee = sc.eevee
for k, v in dict(volumetric_tile_size="8", volumetric_samples=48, use_volumetric_shadows=True,
                 volumetric_shadow_samples=16, volumetric_end=400.0).items():
    try:
        setattr(ee, k, v)
    except Exception as ex:
        print("[rev] eevee", k, ex)
print("[rev] scene ready %.1fs  maxrss %.0f MB  faces scan %d" % (time.time() - T0, isc._mem_mb(),
      sum(len(o.data.polygons) for o in scan + dome_scan)))
ts = []
for i in range(int(P["repeat"])):
    ts.append(round(pk.render_still(0.0, OUT), 2))
print("[rev] render times", ts, "maxrss %.0f MB" % isc._mem_mb(), "total %.1fs" % (time.time() - T0))
