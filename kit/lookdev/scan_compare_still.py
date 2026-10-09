"""Render the agrippa exterior scan with the ep01 hero camera + realkit sky/sun (compare still)."""
import bpy, sys, os, json, time, math
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # kit/
sys.path.insert(0, KIT)
import paperkit as pk
import import_scan as isc
import config
from mathutils import Matrix
argv = sys.argv[sys.argv.index("--") + 1:]
out = argv[0]
emis = float(argv[1]) if len(argv) > 1 else 1.0
vt = argv[2] if len(argv) > 2 else "AgX"
spec = json.load(open(os.path.join(KIT, "episodes/ep01_pantheon_paper.json")))
pk.STYLE = "real"
pk.new_scene()
import realkit
bpy.ops.import_scene.gltf(filepath=config.resolve("models/pantheon/agrippa_pantheon_2k.glb"))
ms = [o for o in bpy.context.scene.objects if o.type == "MESH"]
isc._bake_world(ms)
for o in list(bpy.context.scene.objects):
    if o.type not in ("MESH",) and not o.name.startswith("PK_"):
        bpy.data.objects.remove(o)
CX, CY, ZG, R_SCAN = -0.75, 7.80, -10.63, 15.02
S = 27.7 / R_SCAN
M = Matrix.Translation((0, 0, realkit.GROUND_Z)) @ Matrix.Scale(S, 4) @ Matrix.Translation((-CX, -CY, -ZG))
for o in ms:
    o.data.transform(M)
import bmesh, numpy as np
CROP = "--nocrop" not in argv
if CROP:   # keep the building (rotunda + block + portico) and drop the piazza's houses and pavement
    kept = 0
    for o in ms:
        me = o.data; n = len(me.polygons)
        c = np.empty(n * 3, dtype=np.float32); me.polygons.foreach_get("center", c); c = c.reshape(-1, 3)
        r = np.hypot(c[:, 0], c[:, 1])
        keep = (r < 30.8) | ((np.abs(c[:, 0]) < 18.9) & (c[:, 1] > -56.0) & (c[:, 1] < -18.0))
        keep &= (c[:, 2] > realkit.GROUND_Z + 0.35) | (r < 27.0) | ((np.abs(c[:, 0]) < 17.0) & (c[:, 1] > -53.0) & (c[:, 1] < -20.0))
        kill = np.nonzero(~keep)[0]
        bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[int(i)] for i in kill], context="FACES")
        bm.to_mesh(me); bm.free(); kept += len(me.polygons)
    print("[scan] cropped to building: %d faces" % kept)
    pk.set_palette(realkit.real_palette(spec["palette"], spec.get("real_palette")))
    pk.backdrop(col=spec.get("backdrop", "table"))
done = set()
for o in ms:
    for m in o.data.materials:
        if m.name not in done:
            isc.scan_material(m, emission=0.78, principled=0.22, strength=emis); done.add(m.name)
realkit.lighting(spec.get("real_look", {}))
pk.camera_rig(lens=spec.get("lens", 38))
shot = [s for s in spec["shots"] if s["name"] == "hero_exterior"][0]
pk.camera_keys([dict(shot, t=0.0)])
q = dict(spec.get("render", {})); q.update(spec.get("real_render", {}))
samples = q.pop("samples", 16)
pk.render_setup(samples=samples, quality=q)
if vt != "AgX":
    bpy.context.scene.view_settings.view_transform = vt
    bpy.context.scene.view_settings.look = "None"
import numpy as np
V = isc._np_verts(ms)
print("[scan] scale %.4f  bbox %s %s  top z %.2f" % (S, V.min(0).round(1), V.max(0).round(1), V[:, 2].max()))
ts = []
for i in range(2):
    t = time.time(); dt = pk.render_still(0.0, out); ts.append(round(dt, 2))
print("[scan] render times", ts, "maxrss %.0f MB" % isc._mem_mb())
