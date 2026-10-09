"""light_presets.py - the lighting preset library for style "real" (plain python: read by realkit.py in Blender
and by overlay.py / preset_stills.py outside it).

ONE preset per episode, held from the first frame to the last (no transitions inside an episode). Pick the one that
suits the building (material, setting, character, story); the selection guide is in README.md.

Episode JSON:  "real_look": {"preset": "blue_hour", ...any LOOK key overrides it}
A preset brings three things, each only used when the episode does not give its own:
  look     realkit.LOOK keys (sun, sky, rim, floods, shaft, mist, city windows, exposure, bloom ...)
  palette  real_palette entries under the episode's "real_palette" (episode wins) - ground colour fix etc.
  grade    overlay.py grade, used only when the episode has no "grade" key at all
Episodes without "preset" render exactly as before (none of this is read).

Look keys added for this library (realkit.lighting / _cine_sky / _finish / _r_facade; all off when absent):
  sky_flat        the sky that LIGHTS the scene is a flat colour sky_light_hex x sky_strength (no physical sky:
                  blue hour, night, overcast)
  floods          list of flood groups (spot lights), placed from the building's own footprint:
                  {"ring": n, "margin": m, "h": lamp height, "aim": 0..1 of building height, "e": irradiance at the
                   aim point, "spread": cone deg, "blend", "hex", "size": lamp radius}   n lamps round the footprint,
                   found by ray casts at 15 % height, each pointing up its bit of wall (grazing wash, strong falloff)
                  {"az": [deg...], "dist": m from centre, "h", "aim", "e", "spread", "blend", "hex", "size"}
                   distant floods (rooftops across the square) for the upper parts; az as the camera (0 = front, -Y)
  shaft           {"e", "dist", "cover" (x footprint radius), "blend", "size", "hex", "aim"} a spot from the sun
                  direction that lights the building and a pool round it only (a break in the clouds)
  interior        {"e", "hex", "z": 0..1 of height, "size"} warm point light inside (doorways, windows glow), or a
                  list of such dicts (several lamps on the building's axis, e.g. one at a dome's window ring and a
                  weaker low one for the arches and half domes); window_glow reads the first one's colour
  mist, mist_hex, mist_strength, mist_start, mist_density, mist_z, mist_top
                  every realkit surface fades to mist_hex by camera distance (1 - exp(-density x (d - start))) x mist,
                  thinner with height: full below mist_z[0] m, mist_top x at mist_z[1] m and above (ground mist)
  stars           0..1 faint star field in the camera sky (above the horizon glow)
  cloud_low       (dz0, dz1) clouds fade in above the horizon between these view heights (default 0.03, 0.15)
  setting_haze    haze on the near props (bollards, fountain; default 0.7) - keep low at night or they glow
  city_windows    emission strength of lit windows in the city ring (window_hex, windows_lit = fraction lit)
"""

# warm stone ground (ep01 final: the grey piazza read pink-purple under a red-orange sun + violet sky fill)
GROUND_FIX = {"piazza": "#B8AC96", "table": "#B8AC96", "paving": "#BEB29B", "paving_light": "#D4C9B3"}

# pink / salmon / mauve on low-saturation surfaces -> warm stone; lilac -> blue (ep01 final, see README grade notes)
HUE_FIX = [{"from": [296, 34], "to": 32, "k": 1.0, "soft": 40, "sat": [0.34, 0.55]},
           {"from": [228, 298], "to": 222, "k": 0.6, "soft": 35, "sat": [0.3, 0.6]}]

PRESETS = {
    # ------------------------------------------------------------------ 1. golden hour (ep01 final, approved)
    "golden_hour": dict(
        zh="黄昏",
        look=dict(
            sun_az=70.0, sun_el=12.0, sun_angle=0.9, sun_strength=12.0, sun_hex="#FFB462",
            sky_strength=0.18, sky_light_hex="#8DB0D4",
            cine_sky=True, haze_hex="#76808F", haze_strength=0.95, sky_mid_hex="#62728C", sky_zenith_hex="#223453",
            sky_mid_z=0.1, sky_zenith_z=0.36, sun_glow_hex="#FFBE72", sun_glow=0.6, sun_glow_width=0.3,
            clouds=0.9, cloud_scale=0.55, cloud_cov=0.5, cloud_hex="#4C5569", cloud_lit_hex="#F0B283",
            rim_az=200.0, rim_el=14.0, rim_strength=2.6, rim_hex="#FFBF7A", rim_angle=3.0,
            exposure=-0.1, look="AgX - Medium High Contrast", bloom=0.28, bloom_threshold=0.9, bloom_size=7,
            city_haze0=0.5, city_haze1=0.88, xray_base_hex="#07182A", xray_rim_hex="#3FB8F0", xray_keep=0.22),
        palette=GROUND_FIX,
        grade=dict(vignette=0.35, bottom=[0.78, 0.18], contrast=0.12, saturation=1.06,
                   shadow_hex="#2E4F70", shadow_k=0.1, high_hex="#FFC890", high_k=0.12,
                   hue_fix=HUE_FIX,
                   shadow_cool={"rgb": [-0.025, 0, 0.035], "k": 2.0, "l": [0.35, 0.62], "sat_max": 0.2}),
    ),
    # ------------------------------------------------------------------ 2. blue hour
    "blue_hour": dict(
        zh="蓝调时刻",
        look=dict(
            sun_az=100.0, sun_el=-4.0, sun_angle=4.0, sun_strength=0.0, sun_hex="#9DB6E0",
            sky_flat=True, sky_strength=0.55, sky_light_hex="#5C7FB8",
            cine_sky=True, haze_hex="#6F7FA0", haze_strength=1.0, sky_mid_hex="#3A5687", sky_zenith_hex="#12234A",
            sky_mid_z=0.12, sky_zenith_z=0.5, sun_glow_hex="#E7A575", sun_glow=0.55, sun_glow_width=0.35,
            clouds=0.55, cloud_scale=0.5, cloud_cov=0.56, cloud_hex="#26365A", cloud_lit_hex="#9C8FA0",
            rim_strength=0.0,
            floods=[{"ring": 16, "margin": 3.0, "h": 0.3, "aim": 0.7, "e": 2.2, "spread": 95, "blend": 0.9,
                     "hex": "#FFC27A", "size": 0.3},
                    {"az": [-40, 5, 50], "dist": 95, "h": 14, "aim": 0.75, "e": 2.2, "spread": 40, "blend": 0.8,
                     "hex": "#FFD6A0", "size": 1.5}],
            interior={"e": 6.0, "hex": "#FFB56A", "z": 0.25, "size": 2.0},
            city_windows=6.0, window_hex="#FFB765", windows_lit=0.45,
            exposure=0.1, look="AgX - Medium High Contrast", bloom=0.35, bloom_threshold=0.8, bloom_size=7,
            city_haze0=0.3, city_haze1=0.7, setting_haze=0.1),
        palette=GROUND_FIX,
        grade=dict(vignette=0.4, bottom=[0.78, 0.2], contrast=0.1, saturation=1.04,
                   shadow_hex="#1F3B66", shadow_k=0.08, high_hex="#FFC890", high_k=0.08,
                   hue_fix=HUE_FIX),
    ),
    # ------------------------------------------------------------------ 3. overcast drama
    "overcast_drama": dict(
        zh="阴天压顶",
        look=dict(
            sun_az=15.0, sun_el=30.0, sun_angle=2.0, sun_strength=0.0, sun_hex="#FFF0DA",
            sky_flat=True, sky_strength=0.4, sky_light_hex="#8C97A6",
            cine_sky=True, haze_hex="#6E7680", haze_strength=1.0, sky_mid_hex="#525A66", sky_zenith_hex="#262B33",
            sky_mid_z=0.1, sky_zenith_z=0.4, sun_glow_hex="#F4EEE2", sun_glow=0.7, sun_glow_width=0.25,
            clouds=1.0, cloud_scale=0.4, cloud_cov=0.3, cloud_hex="#2E343D", cloud_lit_hex="#C4C8CE",
            cloud_low=(0.0, 0.05),
            rim_strength=0.0,
            shaft={"e": 7.5, "dist": 900, "cover": 1.5, "blend": 1.0, "size": 18.0, "hex": "#FFF0DA", "aim": 0.4},
            exposure=0.0, look="AgX - Medium High Contrast", bloom=0.2, bloom_threshold=1.0, bloom_size=7,
            city_haze0=0.45, city_haze1=0.85),
        palette=GROUND_FIX,
        grade=dict(vignette=0.45, bottom=[0.76, 0.22], contrast=0.16, saturation=0.82,
                   shadow_hex="#34465A", shadow_k=0.1, high_hex="#FFE2B8", high_k=0.06,
                   hue_fix=HUE_FIX),
    ),
    # ------------------------------------------------------------------ 4. night flood
    "night_flood": dict(
        zh="夜景泛光",
        look=dict(
            sun_az=200.0, sun_el=40.0, sun_angle=1.0, sun_strength=0.3, sun_hex="#A9BEE0",
            sky_flat=True, sky_strength=0.12, sky_light_hex="#3C5078",
            cine_sky=True, haze_hex="#2B3244", haze_strength=1.0, sky_mid_hex="#141D31", sky_zenith_hex="#060A14",
            sky_mid_z=0.1, sky_zenith_z=0.45, sun_glow=0.0,
            clouds=0.25, cloud_scale=0.5, cloud_cov=0.6, cloud_hex="#1C2436", cloud_lit_hex="#2A3246",
            rim_strength=0.0, stars=0.7,
            floods=[{"ring": 18, "margin": 2.5, "h": 0.3, "aim": 0.75, "e": 3.5, "spread": 85, "blend": 0.85,
                     "hex": "#FFB566", "size": 0.25},
                    {"az": [-45, 0, 45], "dist": 90, "h": 16, "aim": 0.85, "e": 3.0, "spread": 36, "blend": 0.8,
                     "hex": "#FFCB8A", "size": 1.5},
                    {"az": [-25, 25], "dist": 75, "h": 8.0, "aim": 0.3, "e": 1.6, "spread": 26, "blend": 0.8,
                     "hex": "#FFC27A", "size": 1.0}],
            interior={"e": 8.0, "hex": "#FFB060", "z": 0.25, "size": 2.0},
            city_windows=5.0, window_hex="#FFB565", windows_lit=0.35,
            exposure=0.2, look="AgX - Medium High Contrast", bloom=0.4, bloom_threshold=0.7, bloom_size=7,
            city_haze0=0.25, city_haze1=0.6, setting_haze=0.05),
        palette=GROUND_FIX,
        grade=dict(vignette=0.45, bottom=[0.76, 0.22], contrast=0.1, saturation=1.02,
                   shadow_hex="#14264A", shadow_k=0.08, high_hex="#FFC890", high_k=0.06,
                   hue_fix=HUE_FIX),
    ),
    # ------------------------------------------------------------------ 5. morning mist
    "morning_mist": dict(
        zh="晨雾",
        look=dict(
            sun_az=122.0, sun_el=7.0, sun_angle=3.0, sun_strength=8.0, sun_hex="#FFC98E",
            sky_strength=0.22, sky_light_hex="#B4C3D8",
            cine_sky=True, haze_hex="#CBCDCC", haze_strength=1.0, sky_mid_hex="#A9B7C8", sky_zenith_hex="#7F94AF",
            sky_mid_z=0.1, sky_zenith_z=0.5, sun_glow_hex="#FFC98A", sun_glow=1.4, sun_glow_width=0.4,
            clouds=0.35, cloud_scale=0.45, cloud_cov=0.56, cloud_hex="#A9B2BF", cloud_lit_hex="#F3DFC6",
            rim_az=122.0, rim_el=7.0, rim_strength=0.0,
            mist=0.6, mist_hex="#C8CCD0", mist_strength=1.0, mist_start=80.0, mist_density=0.004,
            mist_z=(6.0, 40.0), mist_top=0.3,
            exposure=-0.2, look="AgX - Medium High Contrast", bloom=0.35, bloom_threshold=0.85, bloom_size=8,
            city_haze0=0.7, city_haze1=0.95, city_near=120.0, city_far=300.0, ground_fade=(70.0, 300.0)),
        palette=GROUND_FIX,
        grade=dict(vignette=0.25, bottom=[0.8, 0.12], contrast=0.05, saturation=1.0,
                   shadow_hex="#5A7394", shadow_k=0.08, high_hex="#FFD9B0", high_k=0.1,
                   hue_fix=HUE_FIX),
    ),
    # ------------------------------------------------------------------ 6. noon hard light
    "noon_hard": dict(
        zh="正午硬光",
        look=dict(
            sun_az=35.0, sun_el=58.0, sun_angle=0.5, sun_strength=6.5, sun_hex="#FFF6EA",
            sky_strength=0.2, sky_light_hex="#8FB2E6",
            cine_sky=True, haze_hex="#C5D3E0", haze_strength=1.0, sky_mid_hex="#7CA5D8", sky_zenith_hex="#2B62B0",
            sky_mid_z=0.1, sky_zenith_z=0.5, sun_glow_hex="#FFFFFF", sun_glow=0.0, sun_glow_width=0.2,
            clouds=0.45, cloud_scale=1.1, cloud_cov=0.6, cloud_hex="#B3C0D2", cloud_lit_hex="#F5F7FA",
            rim_strength=0.0,
            exposure=-0.7, look="AgX - High Contrast", bloom=0.08, bloom_threshold=1.4, bloom_size=6,
            city_haze0=0.25, city_haze1=0.7),
        palette=GROUND_FIX,
        grade=dict(vignette=0.25, bottom=[0.8, 0.14], contrast=0.1, saturation=1.1,
                   shadow_hex="#1E3E78", shadow_k=0.06, high_hex="#FFF2DC", high_k=0.04,
                   hue_fix=HUE_FIX),
    ),
}

LOOK_PRESETS = {k: v["look"] for k, v in PRESETS.items()}
ZH = {k: v["zh"] for k, v in PRESETS.items()}


def preset_of(spec):
    return (spec.get("real_look") or {}).get("preset")


def palette_for(spec):
    """real_palette to use: preset palette under the episode's own (episode wins)."""
    pre = preset_of(spec)
    out = dict(PRESETS[pre].get("palette", {})) if pre else {}
    out.update(spec.get("real_palette") or {})
    return out


def grade_for(spec):
    """overlay grade: the episode's "grade" if it has one, else the preset's, else None."""
    if spec.get("grade"):
        return spec["grade"]
    pre = preset_of(spec)
    return PRESETS[pre].get("grade") if pre else None
