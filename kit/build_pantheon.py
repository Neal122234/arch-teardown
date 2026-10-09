"""build_pantheon.py - Episode 01 geometry: the Pantheon, Rome, built from paperkit components.

Called by run_episode.py (episode JSON: "builder": "build_pantheon.py") as build(pk, spec).
All dimensions in metres, derived from the module D = 43.3 m (inner diameter = inner height).
Orientation: rotunda centre at the origin, portico facing -Y (azimuth 270 deg in plan).
Part names (exact): ground, ring_wall, relieving_arches, portico_columns, pediment,
intermediate_block, dome_outer, coffers, oculus, doors, floor, section_sphere.
"""
import math

D = 43.3                 # inner diameter == height to the top of the dome
R = D / 2                # 21.65
T_WALL = 6.05            # drum wall thickness
RO = R + T_WALL          # 27.7 outer drum radius
G = -0.2                 # top of the piazza board (floor disc sits on it, rotunda floor top = 0)
Z_DRUM = 30.0            # top of the exterior drum
R_DOME_IN = R + 0.75     # dome shell inner surface (behind the coffers)
OCULUS_R = 4.35          # oculus diameter 8.7 m
PORTICO_Z = 1.3          # portico podium height
COL_H, COL_D = 14.15, 1.5
BLOCK_Y = -38.5          # front face of the intermediate block
FRONT_Y, ROW2_Y, ROW3_Y = -50.0, -45.0, -40.2
INSCRIPTION = "M\u00b7AGRIPPA\u00b7L\u00b7F\u00b7COS\u00b7TERTIVM\u00b7FECIT"
import config as _config
SERIF = _config.SERIF_FONT                    # ARCH_KIT_SERIF overrides (macOS Times New Roman by default)


def _sph_r(z_abs, rad=R_DOME_IN, zc=R):
    return math.sqrt(max(rad * rad - (z_abs - zc) ** 2, 0.0))


def build(pk, spec):
    """style paper: flat paper pieces; style real (pk.STYLE == "real"): same parts and roles, but detailed
    classical components from realkit (Corinthian columns, dentilled entablature + inscription, moulded
    cornices, dome step rings) and flush segment joints."""
    tag = lambda objs, role: [o.__setitem__("role", role) or o for o in objs]
    real = getattr(pk, "STYLE", "paper") == "real"
    if real:
        import realkit as rk

    # ---------------------------------------------------------------- ground (piazza board, podium, steps)
    if real:   # piazza slab flush with the endless piazza (same fading material)
        tag([pk.box_piece("ground", -46, 46, -90, 42, G - 0.4, rk.GROUND_Z - 0.002, "piazza", bevel=0.0,
                          meta={"recipe": "ground"})], "board")      # just under the endless piazza: no seam
    else:
        tag([pk.box_piece("ground", -40, 40, -66, 36, G - 0.6, G, "paving", bevel=0.15)], "board")
    tag([pk.box_piece("ground", -18.2, 18.2, -52.6, BLOCK_Y + 0.4, G, PORTICO_Z, "travertine_dark",
                      top_col="paving_light", bevel=0.1)], "podium")
    tag(pk.stairs("ground", -12.5, 12.5, -57.0, G, 5, 0.9, (PORTICO_Z - G) / 5, col="travertine", direction=1), "steps")

    # ---------------------------------------------------------------- floor (polychrome marble)
    pk.floor_disc("floor", (0, 0, G), R + 0.02, -G, "giallo", tile=3.7,
                  tile_cols=("porphyry", "granite_grey"), circle_col="giallo", tile_thick=0.1)

    # ---------------------------------------------------------------- ring wall (drum)
    if real and spec.get("wall_layers"):
        _layered_drum(pk, rk, spec, tag)
    else:
        _solid_drum(pk, rk if real else None, spec, tag, real)
    _dome_and_top(pk, rk if real else None, spec, tag, real)
    if real and spec.get("wall_diagram"):
        _wall_diagram(pk, spec)
    return pk.stats()


AGG = ["agg_0", "agg_1", "agg_1", "agg_1", "agg_2", "agg_2", "agg_2", "agg_3", "agg_3", "agg_4", "agg_4", "agg_5"]
AGG_HEX = {"agg_0": "#5B544C", "agg_1": "#726759", "agg_2": "#8E7762", "agg_3": "#AC977B", "agg_4": "#C8BA9C",
           "agg_5": "#E2D9C5", "concrete": "#A59B89"}
RC = RO - 1.2            # layered drum: brick skin RC..RO, concrete core R..RK, relieving arches in the gap
RK = RC - 0.35
HINGE_Y = RO + 0.05


def _side(az):
    return "R" if math.cos(math.radians(az)) > 1e-6 else "L"


def _layered_drum(pk, rk, spec, tag):
    """Style real + spec wall_layers: the 6 m drum as two nested layers so an exploded view can open the brick skin
    (brick facing, cornices) like doors and show the relieving arches on the concrete core inside the wall.
    32 segments with seams at az 270/90 (x = 0) so a whole half can swing on a hinge at the back (0, HINGE_Y).
    Meta: layer core|skin, side R|L (x sign), front (skin behind the intermediate block)."""
    pk.set_palette({k: v for k, v in AGG_HEX.items() if k not in pk._PAL})
    n_seg = 32
    az0 = 270.0
    door = (n_seg - 1, 0)
    ZD = Z_DRUM
    core = [(R, G), (RK, G), (RK, ZD), (R_DOME_IN + 0.8, ZD), (R_DOME_IN + 0.8, R), (R, R)]
    core_c = ["concrete", "concrete", "concrete", "brick", "marble_white", "attic"]
    core_d = [(R, 12.2), (RK, 12.2), (RK, ZD), (R_DOME_IN + 0.8, ZD), (R_DOME_IN + 0.8, R), (R, R)]
    core_dc = ["travertine", "concrete", "concrete", "brick", "marble_white", "attic"]
    skin = [(RC, G), (RO, G), (RO, ZD), (RK + 0.06, ZD), (RK + 0.06, ZD - 0.4), (RC, ZD - 0.4)]
    skin_c = ["brick", "brick", "travertine", "travertine", "brick", "brick"]
    skin_d = [(RC, 12.2), (RO, 12.2), (RO, ZD), (RK + 0.06, ZD), (RK + 0.06, ZD - 0.4), (RC, ZD - 0.4)]
    skin_dc = ["travertine", "brick", "travertine", "travertine", "brick", "brick"]
    pieces = []
    for s_ in range(n_seg):
        a0, a1 = az0 + s_ * 360 / n_seg, az0 + (s_ + 1) * 360 / n_seg
        d = s_ in door
        for layer, prof, cols in (("core", core_d if d else core, core_dc if d else core_c),
                                  ("skin", skin_d if d else skin, skin_dc if d else skin_c)):
            for o in pk.revolve_pieces("ring_wall", prof, 1, cols=cols, az0=a0, az1=a1, bevel=0.14):
                o["layer"] = layer; o["seg"] = s_
                o["side"] = _side((a0 + a1) / 2)
                o["front"] = abs(((a0 + a1) / 2 - 270 + 180) % 360 - 180) < 34.0
                pieces.append(o)
    tag(pieces, "drum")
    corn = []
    for k, (z0, z1, ri, ro_) in enumerate([(12.0, 12.9, RO - 0.3, RO + 0.55), (22.8, 23.7, RO - 0.3, RO + 0.55),
                                           (ZD - 0.6, ZD + 0.5, RO - 0.9, RO + 0.7)]):
        corn += rk.cornice_ring("ring_wall", RO + 0.02, z0, z1 - z0, ro_ - RO, "travertine", n_seg=n_seg,
                                r_back=max(ri, RC + 0.05), ring=k, az0=az0, az1=az0 + 360,
                                skip=list(door) if k < 2 else None, bevel=0.05)
    for o in corn:
        o["layer"] = "skin"; o["side"] = _side(o["az"])
        o["front"] = abs((o["az"] - 270 + 180) % 360 - 180) < 34.0
    tag(corn, "cornice")
    inner = []
    for k in range(1, 8):
        a = 270 + 45 * k
        inner += pk.revolve_pieces("ring_wall", [(R - 0.25, 0.0), (R + 0.02, 0.0), (R + 0.02, 9.6), (R - 0.25, 9.6)], 1,
                                   col="niche", az0=a - 11, az1=a + 11, bevel=0.05)
        pts = [(19.9 * math.cos(math.radians(a + d)), 19.9 * math.sin(math.radians(a + d)), 0.0) for d in (-6.5, 6.5)]
        inner += pk.columns_at("ring_wall", pts, 10.0, 1.0, shaft="giallo", base="marble_white", capital="marble_white")
    tag(inner, "interior")
    # relieving arches on the core's outer face (hidden by the skin until it opens)
    tiers = [(3.2, 7.0), (15.0, 6.0), (25.0, 4.6)]
    for k, (zs, span) in enumerate(tiers):
        azs = [270 + 15 + 30 * i for i in range(12)]
        azs = [a for a in azs if min((a - 270) % 360, (270 - a) % 360) > 40]
        arc = pk.arches("relieving_arches", (0, 0, 0), RK, zs, azs, span, band=0.95, protrude=0.25,
                        col="brick_dark", ring=k, n=24)
        for o in arc:
            o["side"] = _side(o["az"]); o["layer"] = "core"


def _solid_drum(pk, rk, spec, tag, real):
    n_seg = 16
    az0 = 270 - 180 / n_seg          # segment 0 is centred on the entrance axis
    prof = [(R, G), (RO, G), (RO, Z_DRUM), (R_DOME_IN + 0.8, Z_DRUM), (R_DOME_IN + 0.8, R),
            (R, R), (R, 12.2)]
    cols = ["brick", "brick", "travertine", "brick", "marble_white", "attic", "marble_int"]
    door_prof = [(R, 12.2), (RO, 12.2), (RO, Z_DRUM), (R_DOME_IN + 0.8, Z_DRUM), (R_DOME_IN + 0.8, R), (R, R)]
    door_cols = ["travertine", "brick", "travertine", "brick", "marble_white", "attic"]
    drum = []
    for s_ in range(n_seg):
        if s_ == 0:
            drum += pk.revolve_pieces("ring_wall", door_prof, 1, cols=door_cols,
                                      az0=az0, az1=az0 + 360 / n_seg, bevel=0.14)
        else:
            drum += pk.revolve_pieces("ring_wall", prof, 1, cols=cols,
                                      az0=az0 + s_ * 360 / n_seg, az1=az0 + (s_ + 1) * 360 / n_seg, bevel=0.14)
    for i, o in enumerate(drum):
        o["seg"] = i
    tag(drum, "drum")
    # exterior cornices (travertine bands on the brick drum)
    corn = []
    for k, (z0, z1, ri, ro_) in enumerate([(12.0, 12.9, RO - 0.3, RO + 0.55), (22.8, 23.7, RO - 0.3, RO + 0.55),
                                           (Z_DRUM - 0.6, Z_DRUM + 0.5, RO - 0.9, RO + 0.7)]):
        if real:     # moulded profile: bed moulding + corona + sima
            corn += rk.cornice_ring("ring_wall", RO, z0, z1 - z0, ro_ - RO, "travertine", n_seg=n_seg, r_back=ri,
                                    ring=k, az0=az0, az1=az0 + 360, skip=[0] if k < 2 else None, bevel=0.05)
            continue
        corn += pk.ring_band("ring_wall", ri, ro_, z0, z1, "travertine", n_seg=n_seg, ring=k,
                             az0=az0, az1=az0 + 360, skip=[0] if k < 2 else None, bevel=0.08)
    tag(corn, "cornice")
    # interior: 7 niches with paired giallo-antico columns + interior entablature
    inner = []
    for k in range(1, 8):
        a = 270 + 45 * k
        inner += pk.revolve_pieces("ring_wall", [(R - 0.25, 0.0), (R + 0.02, 0.0), (R + 0.02, 9.6), (R - 0.25, 9.6)], 1,
                                   col="niche", az0=a - 11, az1=a + 11, bevel=0.05)
        pts = [(19.9 * math.cos(math.radians(a + d)), 19.9 * math.sin(math.radians(a + d)), 0.0) for d in (-6.5, 6.5)]
        inner += pk.columns_at("ring_wall", pts, 10.0, 1.0, shaft="giallo", base="marble_white", capital="marble_white")
    inner += pk.ring_band("ring_wall", R - 0.9, R + 0.02, 10.0, 11.3, "marble_white", n_seg=n_seg,
                          az0=az0, az1=az0 + 360, skip=[0], ring=3, bevel=0.05)
    tag(inner, "interior")

    # ---------------------------------------------------------------- relieving arches (brick arches in the drum)
    tiers = [(3.2, 7.0), (15.0, 6.0), (25.0, 4.6)]
    for k, (zs, span) in enumerate(tiers):
        azs = [270 + 15 + 30 * i for i in range(12)]
        azs = [a for a in azs if min((a - 270) % 360, (270 - a) % 360) > 40]
        if real:     # flush brick voussoir arches (the material draws the radial joints)
            pk.arches("relieving_arches", (0, 0, 0), RO, zs, azs, span, band=0.95, protrude=0.035,
                      col="brick_dark", ring=k, n=24)
        else:
            pk.arches("relieving_arches", (0, 0, 0), RO, zs, azs, span, band=0.8, protrude=0.22,
                      col="brick_dark", ring=k)



def _dome_and_top(pk, rk, spec, tag, real):
    # ---------------------------------------------------------------- intermediate block (with passage)
    xb, yb0, yb1, zb = 17.6, BLOCK_Y, -21.0, 25.0
    if real:
        wall = "brick"
        blk = [pk.box_piece("intermediate_block", -xb, -4.3, yb0, yb1, G, 23.2, wall, top_col="roof_lead"),
               pk.box_piece("intermediate_block", 4.3, xb, yb0, yb1, G, 23.2, wall, top_col="roof_lead"),
               pk.box_piece("intermediate_block", -4.3, 4.3, yb0, yb1, 12.2, 23.2, wall, top_col="roof_lead")]
        path = [(-xb, yb1), (-xb, yb0), (xb, yb0), (xb, yb1)]
        blk += rk.entablature_real("intermediate_block", path, 23.2, col="travertine", depth=1.2,
                                   ceiling=(-xb + 1.0, xb - 1.0, yb0 + 1.0, yb1))
        zt = 23.2 + rk.ARCHITRAVE[-1][1] + rk.FRIEZE_H + rk.CORNICE_H
        blk += rk.pediment_real("intermediate_block", -xb, xb, yb0, yb1, zt, 6.6, col="travertine",
                                tymp_col="brick", cornice_col="travertine", roof_col="roof_lead")
    blk = blk if real else [pk.box_piece("intermediate_block", -xb, -4.3, yb0, yb1, G, zb, "travertine_dark", top_col="roof_lead"),
           pk.box_piece("intermediate_block", 4.3, xb, yb0, yb1, G, zb, "travertine_dark", top_col="roof_lead"),
           pk.box_piece("intermediate_block", -4.3, 4.3, yb0, yb1, 12.2, zb, "travertine_dark", top_col="roof_lead")]
    if not real:
        blk += [pk.box_piece("intermediate_block", -xb - 0.4, xb + 0.4, yb0 - 0.4, yb1, zb, zb + 1.0, "travertine",
                             top_col="roof_lead")]
    # the 'second pediment' on the block (visible above the portico roof)
    blk += [] if real else pk.gable("intermediate_block", -xb, xb, yb0 - 0.3, yb0 + 3.0, zb + 1.0, 6.6,
                    col="travertine", tymp_col="travertine_dark", roof_col="roof_lead", cornice_col="travertine",
                    overhang=0.5)[:2]

    # ---------------------------------------------------------------- doors (bronze) + grille
    pk.door("doors", 0.0, BLOCK_Y + 1.2, PORTICO_Z, 6.2, 7.6, leaf="bronze", frame="marble_white", facing=-1)
    mb = pk.MB()
    zg0, zg1 = PORTICO_Z + 7.6 + 0.7, 12.2
    mb.box(-4.3, 4.3, BLOCK_Y + 1.0, BLOCK_Y + 1.3, zg0, zg0 + 0.3, "bronze")
    for i in range(9):
        x = -4.0 + i * 1.0
        mb.box(x - 0.09, x + 0.09, BLOCK_Y + 1.05, BLOCK_Y + 1.25, zg0, zg1, "bronze_dark")
    pk.finish(mb, pk._pname("doors"), "doors", pivot=(0, BLOCK_Y + 1.2, zg0), bevel=0.02)

    # ---------------------------------------------------------------- portico: 8 front (grey granite) + 2x4 (pink granite)
    xs = [-15.6 + i * 31.2 / 7 for i in range(8)]
    kw = dict(base="marble_white", capital="marble_white")
    cols_at = rk.columns_real if real else pk.columns_at
    cols_at("portico_columns", [(x, FRONT_Y, PORTICO_Z) for x in xs], COL_H, COL_D, shaft="granite_grey", **kw)
    for y in (ROW2_Y, ROW3_Y):
        cols_at("portico_columns", [(xs[i], y, PORTICO_Z) for i in (0, 2, 5, 7)], COL_H, COL_D,
                shaft="granite_pink", **kw)

    # ---------------------------------------------------------------- pediment (entablature + gable + roof)
    if real:     # architrave / frieze with the inscription / dentilled cornice, then the pediment proper
        xf, yf, yb = 15.6 + 0.72, FRONT_Y - 0.72, BLOCK_Y + 0.3
        path = [(-xf, yb), (-xf, yf), (xf, yf), (xf, yb)]
        ent = rk.entablature_real("pediment", path, PORTICO_Z + COL_H, col="marble_white", depth=1.4,
                                  ceiling=(-xf + 1.3, xf - 1.3, yf + 1.3, yb), inscription=INSCRIPTION,
                                  font=SERIF, text_col="bronze", text_size=0.95)
        for o in ent:
            o["role"] = "inscription" if o.get("sub") == "inscription" else "entablature"
        zt = PORTICO_Z + COL_H + rk.ARCHITRAVE[-1][1] + rk.FRIEZE_H + rk.CORNICE_H
        tag(rk.pediment_real("pediment", -xf, xf, yf, yb, zt, 7.2, col="marble_white", tymp_col="tympanum",
                             cornice_col="marble_white", roof_col="roof_lead"), "gable")
    else:
        pk.gable("pediment", -17.1, 17.1, -51.3, BLOCK_Y, PORTICO_Z + COL_H, 7.2, col="travertine",
                 tymp_col="travertine_dark", roof_col="roof_lead", cornice_col="marble_white",
                 entab_h=2.9, entab_col="travertine")

    # ---------------------------------------------------------------- dome (outer shell, ring by ring)
    # ring 0: haunch (inside the drum top)
    e_top = math.degrees(math.asin((Z_DRUM - R) / R_DOME_IN))
    haunch = [(R_DOME_IN * math.cos(math.radians(e_top * j / 4)), R + R_DOME_IN * math.sin(math.radians(e_top * j / 4)))
              for j in range(5)]
    prof = haunch + [(R_DOME_IN + 0.8, Z_DRUM), (R_DOME_IN + 0.8, R)]
    bands = real and spec.get("wall_layers")
    if bands:        # offset off the drum's inner step / ledge (no coplanar faces once parts separate)
        prof = [(r_, max(z_, R + 0.03)) for r_, z_ in haunch] + [(R_DOME_IN + 0.77, Z_DRUM), (R_DOME_IN + 0.77, R + 0.03)]
        pk.revolve_pieces("dome_outer", prof, 16, cols=["coffer_plain"] * 4 + [AGG[0], "brick", AGG[0]],
                          ring=0, bevel=0.1)
    else:
        pk.revolve_pieces("dome_outer", prof, 16, col="coffer_plain",
                          cols=["coffer_plain"] * 4 + ["lead_light", "brick", "marble_white"], ring=0, bevel=0.1)
    # rings 1..6: the stepped rings on the lower dome
    if real:
        rk.step_rings("dome_outer", Z_DRUM, 6, 1.0, RO - 0.4, 0.95, _sph_r, "step_ring", ring0=1,
                      cut_cols=AGG[1:7] if bands else None, inner_col="coffer_plain" if bands else None)
    for k in ([] if real else range(6)):
        z0, z1 = Z_DRUM + k * 1.0, Z_DRUM + (k + 1) * 1.0
        ro_ = RO - 0.4 - 0.95 * k
        prof = [(_sph_r(z0), z0), (ro_, z0), (ro_, z1), (_sph_r(z1), z1)]
        pk.revolve_pieces("dome_outer", prof, 16, cols=["lead_light", "lead_light", "lead_light", "coffer_plain"],
                          ring=1 + k, bevel=0.1)
    # rings 7..11: upper shell, flatter outer profile (lead sheet) closing toward the oculus
    zc, Ro = 15.276, 30.22
    p0, p1 = math.radians(43.3), math.radians(80.67)
    outer = lambda u: (Ro * math.cos(p0 + (p1 - p0) * u), zc + Ro * math.sin(p0 + (p1 - p0) * u) - R)
    el0 = math.degrees(math.asin((Z_DRUM + 6.0 - R) / R_DOME_IN))
    el1 = math.degrees(math.acos(OCULUS_R / R_DOME_IN))
    if bands:        # one call per ring: each band's cut faces carry its aggregate colour
        for k in range(5):
            e0k, e1k = el0 + (el1 - el0) * k / 5, el0 + (el1 - el0) * (k + 1) / 5
            pk.dome_shell("dome_outer", (0, 0, R), R_DOME_IN, e0k, e1k, 1, 20,
                          (lambda u, k=k: outer((k + u) / 5)), col_out="lead", col_in="coffer_plain",
                          col_edge=AGG[7 + k], ring0=7 + k, bevel=0.1)
    else:
        pk.dome_shell("dome_outer", (0, 0, R), R_DOME_IN, el0, el1, 5, 20, outer, col_out="lead",
                      col_in="coffer_plain", col_edge="lead_light", ring0=7, bevel=0.1)

    # ---------------------------------------------------------------- coffers: 5 rings x 28
    pk.coffers("coffers", (0, 0, R), R, 5, 28, 6.0, 57.0, 0.62, rib="coffer_rib", recess="coffer_in",
               back="coffer_back", az0=270 - 360 / 56)

    # ---------------------------------------------------------------- oculus (bronze rim)
    z_in = R + math.sqrt(R_DOME_IN ** 2 - OCULUS_R ** 2)
    pk.revolve_pieces("oculus", [(OCULUS_R - 0.1, z_in - 0.3), (OCULUS_R + 0.45, z_in - 0.3),
                                 (OCULUS_R + 0.45, 45.25), (OCULUS_R - 0.1, 45.25)], 8, col="bronze", bevel=0.05)

    # ---------------------------------------------------------------- inscribed sphere (diagram)
    pk.uv_sphere_globe("section_sphere", (0, 0, R), R, spec.get("sphere_line", "#1F8FD0"),
                       spec.get("sphere_fill", "#6EC3F2"))
    for o in pk.PARTS["section_sphere"]:
        o.scale = (0, 0, 0)          # hidden until revealed by the schedule



# ============================================================================= wall diagram (ep01 relieving-arch segment)
# A cut-open model of the drum's structure, shown only while the brick skin is ghosted: 8 concrete piers (between
# the 8 openings: entrance + 7 exedrae), hollow bays (dark voids) with 3 tiers of 3D voussoir arches springing from
# pier to pier, concrete fill, and animated gold load lines (dome base -> arch crown -> split along the arch -> into
# the pier -> down to the ground). Facts: ep01_pantheon/FACTS_walls.md (8 piers, 3 levels of arches).
# Timing lives in spec["wall_diagram"]; everything is keyed here (custom props read by the diagram materials).
DG_PIER_DEG = 18.0                       # pier width in plan (bay = 45 - 18 = 27 deg of void)
DG_BAND = 1.4                            # voussoir depth (arch ring thickness)
DG_TIERS = [(0.0, 3.8), (11.8, 12.2), (20.0, 20.0)]   # (void bottom z, springing z) per tier
DG_TOP = 29.95
DG_RA = RK * math.radians(45.0 - DG_PIER_DEG) / 2.0    # arch intrados radius (half the void width at RK)
DG_UPC = DG_RA + RK * math.radians(DG_PIER_DEG) / 2.0  # pier centre line, in u metres from the bay centre
DG_RF = RK + 0.36                        # load lines run just in front of the voussoir faces
DG_TUBE = 0.22


def _dg_mat(pk, name, base_hex, rough=0.9, glow_hex="#FFA41C", glow_k=0.0, pour=False, noise=0.18, tint_k=0.0,
            tint_hex="#D9932A", hide_zero=False):
    import bpy
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; N = nt.nodes; L = nt.links
    N.clear()
    out = N.new('ShaderNodeOutputMaterial')
    bs = N.new('ShaderNodeBsdfPrincipled')
    bs.inputs['Roughness'].default_value = rough
    geo = N.new('ShaderNodeNewGeometry')
    nz = N.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 0.9; nz.inputs['Detail'].default_value = 3.0
    L.new(geo.outputs['Position'], nz.inputs['Vector'])
    k = N.new('ShaderNodeMapRange')
    k.inputs['To Min'].default_value = 1.0 - noise; k.inputs['To Max'].default_value = 1.0 + noise
    L.new(nz.outputs['Fac'], k.inputs['Value'])
    mul = N.new('ShaderNodeMix'); mul.data_type = 'RGBA'; mul.blend_type = 'MULTIPLY'
    mul.inputs['Factor'].default_value = 1.0
    mul.inputs[6].default_value = (*pk.hex2lin(base_hex), 1)
    cc = N.new('ShaderNodeCombineColor')
    for i in range(3):
        L.new(k.outputs['Result'], cc.inputs[i])
    L.new(cc.outputs['Color'], mul.inputs[7])
    L.new(mul.outputs[2], bs.inputs['Base Color'])
    shader = bs.outputs[0]
    if glow_k > 0:
        ga = N.new('ShaderNodeAttribute'); ga.attribute_type = 'OBJECT'; ga.attribute_name = 'pk_glow'
        strength = ga.outputs['Fac']
        if pour:     # gold pours down the pier: lit above level = top - glow * height
            sep = N.new('ShaderNodeSeparateXYZ'); L.new(geo.outputs['Position'], sep.inputs[0])
            lv = N.new('ShaderNodeMath'); lv.operation = 'MULTIPLY_ADD'
            L.new(ga.outputs['Fac'], lv.inputs[0]); lv.inputs[1].default_value = -33.0; lv.inputs[2].default_value = 31.0
            d = N.new('ShaderNodeMath'); d.operation = 'SUBTRACT'
            L.new(sep.outputs['Z'], d.inputs[0]); L.new(lv.outputs[0], d.inputs[1])
            mk = N.new('ShaderNodeMapRange'); mk.inputs['From Min'].default_value = -0.8; mk.inputs['From Max'].default_value = 0.8
            L.new(d.outputs[0], mk.inputs['Value'])
            gt = N.new('ShaderNodeMath'); gt.operation = 'GREATER_THAN'; gt.inputs[1].default_value = 0.001
            L.new(ga.outputs['Fac'], gt.inputs[0])
            m2 = N.new('ShaderNodeMath'); m2.operation = 'MULTIPLY'
            L.new(mk.outputs['Result'], m2.inputs[0]); L.new(gt.outputs[0], m2.inputs[1])
            strength = m2.outputs[0]
        sk = N.new('ShaderNodeMath'); sk.operation = 'MULTIPLY'; sk.inputs[1].default_value = glow_k
        L.new(strength, sk.inputs[0])
        if tint_k > 0:     # the lit part also turns gold in its base colour (keeps the glow saturated under AgX)
            tk = N.new('ShaderNodeMath'); tk.operation = 'MULTIPLY'; tk.inputs[1].default_value = tint_k
            L.new(strength, tk.inputs[0])
            tm = N.new('ShaderNodeMix'); tm.data_type = 'RGBA'
            L.new(tk.outputs[0], tm.inputs['Factor']); L.new(mul.outputs[2], tm.inputs[6])
            tm.inputs[7].default_value = (*pk.hex2lin(tint_hex), 1)
            L.new(tm.outputs[2], bs.inputs['Base Color'])
        em = N.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*pk.hex2lin(glow_hex), 1)
        L.new(sk.outputs[0], em.inputs['Strength'])
        add = N.new('ShaderNodeAddShader')
        L.new(bs.outputs[0], add.inputs[0]); L.new(em.outputs[0], add.inputs[1])
        shader = add.outputs[0]
        if hide_zero:      # invisible until it glows
            hz = N.new('ShaderNodeMath'); hz.operation = 'MINIMUM'; hz.inputs[1].default_value = 1.0
            h10 = N.new('ShaderNodeMath'); h10.operation = 'MULTIPLY'; h10.inputs[1].default_value = 20.0
            L.new(ga.outputs['Fac'], h10.inputs[0]); L.new(h10.outputs[0], hz.inputs[0])
            trz = N.new('ShaderNodeBsdfTransparent')
            mz = N.new('ShaderNodeMixShader')
            L.new(hz.outputs[0], mz.inputs[0]); L.new(trz.outputs[0], mz.inputs[1]); L.new(shader, mz.inputs[2])
            shader = mz.outputs[0]
            m.surface_render_method = 'DITHERED'
    L.new(shader, out.inputs['Surface'])
    return m


def _dg_flow_mat(pk, name="DG_flow", hexcol="#FFA41C"):
    import bpy
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    m.surface_render_method = 'DITHERED'
    nt = m.node_tree; N = nt.nodes; L = nt.links
    N.clear()
    def attr(nm, typ):
        a = N.new('ShaderNodeAttribute'); a.attribute_type = typ; a.attribute_name = nm
        return a.outputs['Fac']
    def op(o, a, b=None, c=None):
        n = N.new('ShaderNodeMath'); n.operation = o
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                L.new(v, n.inputs[i])
        return n.outputs[0]
    s, ln, ph, fd = attr("s", 'GEOMETRY'), attr("pk_len", 'OBJECT'), attr("pk_phase", 'OBJECT'), attr("pk_fade", 'OBJECT')
    vis = op('LESS_THAN', s, ln)
    head = op('SUBTRACT', 1.0, op('MINIMUM', op('DIVIDE', op('SUBTRACT', ln, s), 2.5), 1.0))
    fr = op('FRACT', op('DIVIDE', op('SUBTRACT', s, ph), 3.2))
    pulse = op('MAXIMUM', op('SUBTRACT', 1.0, op('MULTIPLY', op('ABSOLUTE', op('SUBTRACT', fr, 0.5)), 3.2)), 0.0)
    stren = op('MULTIPLY', op('ADD', op('ADD', 1.3, op('MULTIPLY', pulse, 1.4)), op('MULTIPLY', head, 2.2)), fd)
    em = N.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*pk.hex2lin(hexcol), 1)
    L.new(stren, em.inputs['Strength'])
    tr = N.new('ShaderNodeBsdfTransparent')
    mx = N.new('ShaderNodeMixShader')
    L.new(op('MULTIPLY', vis, op('GREATER_THAN', fd, 0.001)), mx.inputs[0])
    L.new(tr.outputs[0], mx.inputs[1]); L.new(em.outputs[0], mx.inputs[2])
    out = N.new('ShaderNodeOutputMaterial'); L.new(mx.outputs[0], out.inputs['Surface'])
    return m


def _dg_set_mat(ob, mat):
    me = ob.data
    me.materials.clear(); me.materials.append(mat)
    me.polygons.foreach_set("material_index", [0] * len(me.polygons))


def _dg_P(az_c, r_ref=RK):
    a0 = math.radians(az_c)
    def P(u, v, r):
        a = a0 + u / r_ref
        return (r * math.cos(a), r * math.sin(a), v)
    return P


def _dg_prism(mb, P, poly, r0, r1, col):
    """closed block from a (u, v) polygon extruded radially r0..r1 (a wedge in plan)."""
    mb.island()
    front = [P(u, v, r1) for u, v in poly]
    back = [P(u, v, r0) for u, v in poly]
    mb.face(front, col); mb.face(list(reversed(back)), col)
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        mb.face([back[i], back[j], front[j], front[i]], col)


def _dg_strip(mb, P, us, vb, vt, r0, r1, col):
    """closed solid over u-samples `us` between bottom vb(u) and top vt(u), radially r0..r1."""
    mb.island()
    B = [(u, vb(u)) for u in us]; T = [(u, vt(u)) for u in us]
    n = len(us)
    q = lambda uv, r: P(uv[0], uv[1], r)
    for i in range(n - 1):
        mb.face([q(B[i], r1), q(B[i + 1], r1), q(T[i + 1], r1), q(T[i], r1)], col)       # front
        mb.face([q(T[i], r0), q(T[i + 1], r0), q(B[i + 1], r0), q(B[i], r0)], col)       # back
        mb.face([q(B[i], r0), q(B[i + 1], r0), q(B[i + 1], r1), q(B[i], r1)], col)       # bottom
        mb.face([q(T[i], r1), q(T[i + 1], r1), q(T[i + 1], r0), q(T[i], r0)], col)       # top
    for i, sgn in ((0, 1), (n - 1, -1)):
        pts = [q(B[i], r0), q(B[i], r1), q(T[i], r1), q(T[i], r0)]
        mb.face(pts if sgn > 0 else list(reversed(pts)), col)


def _dg_path(k, side):
    """load path in (u, v) for tier k, side -1 (left) / +1 (right) of a bay."""
    zb, zs = DG_TIERS[k]
    rc = DG_RA + DG_BAND / 2
    v0 = 29.9 if k == len(DG_TIERS) - 1 else DG_TIERS[k + 1][0] + 0.05
    pts = [(0.0, v0 - (v0 - zs - rc) * i / 4) for i in range(5)]
    for i in range(1, 19):
        th = math.pi / 2 + side * (-1) * (math.pi / 2) * i / 18 if side > 0 else math.pi / 2 + (math.pi / 2) * i / 18
        pts.append((rc * math.cos(th), zs + rc * math.sin(th)))
    sg = 1 if side > 0 else -1
    b0, b1, b2, b3 = (sg * rc, zs), (sg * rc, zs - 1.3), (sg * DG_UPC, zs - 1.1), (sg * DG_UPC, zs - 2.5)
    for i in range(1, 11):
        t = i / 10
        c = [(1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3]
        pts.append((sum(c[j] * p[0] for j, p in enumerate((b0, b1, b2, b3))),
                    sum(c[j] * p[1] for j, p in enumerate((b0, b1, b2, b3)))))
    z_end = 0.35
    zz = zs - 2.5
    nv = max(1, int((zz - z_end) / 1.5))
    for i in range(1, nv + 1):
        pts.append((sg * DG_UPC, zz - (zz - z_end) * i / nv))
    return pts


def _dg_tube(paths, name, part, pk, mat):
    """one mesh of tubes along 3D polylines; point attribute s = metres along each path."""
    import bpy, bmesh
    from mathutils import Vector
    bm = bmesh.new()
    lay = bm.verts.layers.float.new("s")
    ns = 8
    for pts in paths:
        pts = [Vector(p) for p in pts]
        acc = [0.0]
        for i in range(1, len(pts)):
            acc.append(acc[-1] + (pts[i] - pts[i - 1]).length)
        rings = []
        for i, p in enumerate(pts):
            T = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
            Nr = Vector((p.x, p.y, 0.0)).normalized()
            Nn = (Nr - T * Nr.dot(T)).normalized()
            Bn = T.cross(Nn)
            ring = []
            for j in range(ns):
                a = 2 * math.pi * j / ns
                v = bm.verts.new(p + (Nn * math.cos(a) + Bn * math.sin(a)) * DG_TUBE)
                v[lay] = acc[i]
                ring.append(v)
            rings.append(ring)
        for i in range(len(rings) - 1):
            for j in range(ns):
                jj = (j + 1) % ns
                bm.faces.new((rings[i][j], rings[i][jj], rings[i + 1][jj], rings[i + 1][j]))
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    for f in me.polygons:
        f.use_smooth = True
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    pk.part_collection(part).objects.link(ob)
    ob["pk_part"] = part; ob["pk_rest"] = (0.0, 0.0, 0.0)
    ob.visible_shadow = False
    pk.PARTS.setdefault(part, []).append(ob)
    return ob


def _dg_cone(name, part, pk, mat, r=0.78, h=1.8):
    """arrow head: tip at the origin, pointing along +Z."""
    import bpy, bmesh
    bm = bmesh.new()
    tip = bm.verts.new((0, 0, 0))
    base = [bm.verts.new((r * math.cos(2 * math.pi * j / 12), r * math.sin(2 * math.pi * j / 12), -h)) for j in range(12)]
    for j in range(12):
        bm.faces.new((tip, base[j], base[(j + 1) % 12]))
    bm.faces.new(list(reversed(base)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    pk.part_collection(part).objects.link(ob)
    ob["pk_part"] = part; ob["pk_rest"] = (0.0, 0.0, 0.0)
    ob.visible_shadow = False
    pk.PARTS.setdefault(part, []).append(ob)
    return ob


def _dg_keyprop(ob, prop, keys, interp='BEZIER'):
    for t, v in keys:
        ob[prop] = float(v)
        ob.keyframe_insert('["%s"]' % prop, frame=round(t * 24) + 1)
    import paperkit as _pk
    for fc in _pk._fcurves(ob):
        if fc.data_path == '["%s"]' % prop:
            for kp in fc.keyframe_points:
                kp.interpolation = interp


def _wall_diagram(pk, spec):
    import bpy
    from mathutils import Vector
    cfg = spec["wall_diagram"]
    fps = spec.get("fps", 24)
    M_pier = _dg_mat(pk, "DG_pier", "#8C8478", 0.92, glow_k=0.9, pour=True, tint_k=0.85)
    M_fill = _dg_mat(pk, "DG_fill", "#A69D8E", 0.95)
    M_lin = _dg_mat(pk, "DG_void", "#1A1715", 1.0, noise=0.05)
    M_arch = _dg_mat(pk, "DG_arch", "#C4693A", 0.82, glow_k=0.35, glow_hex="#FF8A1C", noise=0.28)
    M_flow = _dg_flow_mat(pk)
    M_head = _dg_mat(pk, "DG_head", "#E0901C", 0.5, glow_k=2.6, noise=0.0, hide_zero=True)
    part = "wall_diagram"
    r_front = RK - 0.03
    def tag(objs, role, **kw):
        for o in objs:
            o["role"] = role
            for k_, v_ in kw.items():
                o[k_] = v_
        return objs
    # lining = back of the voids (inner wall face), stepping out above the dome's springing (dome haunch inside)
    lin = [(R + 0.08, 0.0), (R + 0.5, 0.0), (R + 0.5, 21.35), (23.65, 21.35), (23.65, DG_TOP), (23.22, DG_TOP),
           (23.22, 21.62), (R + 0.08, 21.62)]
    tag(pk.revolve_pieces(part, lin, 8, col="concrete", az0=0.0, az1=360.0, bevel=0.0), "lining")
    piers = []
    for k in range(8):
        pc = 270.0 + 22.5 + 45.0 * k
        prof = [(R + 0.45, 0.0), (r_front, 0.0), (r_front, DG_TOP), (23.65, DG_TOP), (23.65, 21.6), (R + 0.45, 21.6)]
        piers += tag(pk.revolve_pieces(part, prof, 1, col="concrete", az0=pc - DG_PIER_DEG / 2,
                                       az1=pc + DG_PIER_DEG / 2, bevel=0.06), "pier", seg=k)
    fills, arches = [], []
    for b in range(8):
        azc = 270.0 + 45.0 * b
        P = _dg_P(azc)
        n = 28
        us = [-DG_RA + 2 * DG_RA * i / n for i in range(n + 1)]
        for k, (zb, zs) in enumerate(DG_TIERS):
            top = DG_TIERS[k + 1][0] if k + 1 < len(DG_TIERS) else DG_TOP
            r0 = R + 0.45 if top <= 21.6 else 23.65
            mb = pk.MB()
            _dg_strip(mb, P, us, lambda u, zs=zs: zs + math.sqrt(max(DG_RA ** 2 - u * u, 0.0)) + 0.1,
                      lambda u, top=top: top, r0, r_front, "concrete")
            fills += tag([pk.finish(mb, pk._pname(part), part, pivot=P(0, zs, RK), bevel=0.0)], "fill", ring=k, seg=b)
            # voussoir arch: 15 blocks with mortar gaps, through the wall thickness, faces 4 cm proud
            mb = pk.MB()
            nv, rc = 15, DG_RA + DG_BAND / 2
            g = 0.06 / rc
            ra0 = 23.7 if zs >= 20.0 else R + 0.55
            for j in range(nv):
                ta, tb = j * math.pi / nv + g / 2, (j + 1) * math.pi / nv - g / 2
                poly = [(DG_RA * math.cos(ta), zs + DG_RA * math.sin(ta)), (DG_RA * math.cos(tb), zs + DG_RA * math.sin(tb)),
                        ((DG_RA + DG_BAND) * math.cos(tb), zs + (DG_RA + DG_BAND) * math.sin(tb)),
                        ((DG_RA + DG_BAND) * math.cos(ta), zs + (DG_RA + DG_BAND) * math.sin(ta))]
                _dg_prism(mb, P, poly, ra0, RK + 0.04, "brick")
            arches += tag([pk.finish(mb, pk._pname(part), part, pivot=P(0, zs, RK), bevel=0.05)], "arch", ring=k, seg=b)
    for o in piers:
        _dg_set_mat(o, M_pier)
    for o in fills:
        _dg_set_mat(o, M_fill)
    for o in arches:
        _dg_set_mat(o, M_arch)
    for o in pk.PARTS[part]:
        if o.get("role") == "lining":
            _dg_set_mat(o, M_lin)
    # ---------------------------------------------------------------- load lines
    v = cfg.get("flow_speed", 15.0)
    t0s = cfg["flow_t0"]                   # per tier (0 = bottom)
    fade = cfg.get("flow_fade", [26.0, 26.6])
    t_hide = cfg["show"][1]
    fpart = "load_flow"
    heads = []
    for k in range(len(DG_TIERS)):
        paths3, lens = [], []
        for b in range(8):
            P = _dg_P(270.0 + 45.0 * b)
            for sd in (-1, 1):
                p3 = [P(u, vv, DG_RF) for u, vv in _dg_path(k, sd)]
                paths3.append(p3)
                L_ = sum((Vector(p3[i]) - Vector(p3[i - 1])).length for i in range(1, len(p3)))
                lens.append(L_)
        ob = _dg_tube(paths3, "load_flow_t%d" % k, fpart, pk, M_flow)
        ob["role"] = "flow"; ob["ring"] = k
        t0 = t0s[k]
        Lm = max(lens)
        _dg_keyprop(ob, "pk_len", [(t0 - 0.05, 0.0), (t0, 0.0), (t0 + Lm / v, Lm)], 'LINEAR')
        _dg_keyprop(ob, "pk_phase", [(t0, 0.0), (t_hide, v * (t_hide - t0))], 'LINEAR')
        _dg_keyprop(ob, "pk_fade", [(t0 - 0.05, 0.0), (t0, 1.0), (fade[0], 1.0), (fade[1], 0.0)], 'LINEAR')
        # arrow heads ride the growing tip, then rest at the pier foot pointing down
        for i, (p3, L_) in enumerate(zip(paths3, lens)):
            h = _dg_cone("load_head_t%d_%02d" % (k, i), fpart, pk, M_head)
            h["role"] = "head"; h["ring"] = k
            h.rotation_mode = 'QUATERNION'
            P3 = [Vector(p) for p in p3]
            acc = [0.0]
            for j in range(1, len(P3)):
                acc.append(acc[-1] + (P3[j] - P3[j - 1]).length)
            def at(sv):
                sv = min(max(sv, 0.0), acc[-1])
                j = 1
                while j < len(acc) - 1 and acc[j] < sv:
                    j += 1
                f = (sv - acc[j - 1]) / max(acc[j] - acc[j - 1], 1e-6)
                return P3[j - 1].lerp(P3[j], f), (P3[j] - P3[j - 1]).normalized()
            f0, f1 = round(t0 * fps) + 1, round((t0 + L_ / v) * fps) + 2
            for f in range(f0 - 1, f1 + 1):
                tt = (f - 1) / fps
                pos, tan = at(v * (tt - t0))
                h.location = pos
                h.rotation_quaternion = tan.to_track_quat('Z', 'Y')
                sc_ = min(max((tt - t0) / 0.2, 0.0), 1.0)
                h.scale = (sc_, sc_, sc_)
                h.keyframe_insert("location", frame=f); h.keyframe_insert("rotation_quaternion", frame=f)
                h.keyframe_insert("scale", frame=f)
            _dg_keyprop(h, "pk_glow", [(fade[0], 1.0), (fade[1], 0.0)], 'LINEAR')
            heads.append(h)
    # dome-base ring: the weight of the dome, lit first
    ring = _dg_tube([[(27.55 * math.cos(2 * math.pi * i / 96), 27.55 * math.sin(2 * math.pi * i / 96), 30.95)
                      for i in range(97)]], "load_ring", fpart, pk, M_head)
    ring["role"] = "ring"
    _dg_keyprop(ring, "pk_glow", cfg["ring"])
    # piers pour gold top -> bottom; arches glow while their lines run
    for o in piers:
        _dg_keyprop(o, "pk_glow", cfg["pier_pour"])
    for o in arches:
        k = o["ring"]
        _dg_keyprop(o, "pk_glow", [(t0s[k] + 0.15, 0.0), (t0s[k] + 0.8, 1.0), (fade[0], 1.0), (fade[1], 0.0)])
    # brick skin (and its cornices) turns to a ghost while the diagram is shown
    for o in pk.PARTS.get("ring_wall", []):
        if o.get("layer") == "skin":
            _dg_keyprop(o, "pk_ghost", cfg["ghost"])
    print("[diagram] piers %d, fills %d, arches %d, heads %d" % (len(piers), len(fills), len(arches), len(heads)))
