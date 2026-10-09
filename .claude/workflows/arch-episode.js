export const meta = {
  name: 'arch-episode',
  description: 'Make one 名建筑拆解 episode up to a reviewed 540x960 draft: facts + script + labels, model plan, builder, episode JSON, draft render with labels and music',
  whenToUse: 'User names a building for the 名建筑拆解 series (e.g. "做下一集：圣索菲亚大教堂"). Args: {building, slug, style?, repo?}. Stops at the draft; the 1080p final is rendered after the user approves the draft.',
  phases: [
    { title: 'Research', detail: 'facts + SCRIPT.md + labels (with sources) in parallel with the model plan (Sketchfab CC BY / CC0 candidates, self-built components, the lighting preset that suits the building)' },
    { title: 'Geometry', detail: 'import scan if downloaded, builder with explode meta, shots of the complete building' },
    { title: 'Episode', detail: 'episode.json: one lighting preset for the whole episode, explode schedule, camera, labels, setting; stills loop' },
    { title: 'Draft', detail: 'produce.py draft: frames + overlay + music, then objective checklist review and fixes' },
    { title: 'Report', detail: 'short Chinese report: draft paths, download list, open issues' },
  ],
}

// ---------------------------------------------------------------- args
const A = args || {}
if (!A.building || !A.slug) {
  throw new Error('arch-episode needs args {building: "Hagia Sophia, Istanbul", slug: "ep02_hagia_sophia", style?: "real", repo?: "~/claude-projects/arch-teardown-kit"}')
}
const BUILDING = A.building
const SLUG = A.slug
const STYLE = A.style || 'real'
const REPO = A.repo || '~/claude-projects/arch-teardown-kit'
const NUM = (SLUG.match(/^ep(\d+)/) || [null, '??'])[1]
const MODEL_KEY = SLUG.replace(/^ep\d+_/, '')
const EP_DIR = `${REPO}/episodes/${SLUG}`
const MODELS = `${REPO}/models/${MODEL_KEY}`
const PRESETS = ['golden_hour', 'blue_hour', 'overcast_drama', 'night_flood', 'morning_mist', 'noon_hard']

const COMMON = `
You are working on the 名建筑拆解 (architecture teardown) short-video series, repo ${REPO} (expand ~).
Episode: ${NUM} · ${BUILDING}. Episode folder: ${EP_DIR}. Models folder: ${MODELS} (not committed). Style: "${STYLE}".
Read ${REPO}/docs/STANDARD.md (the quality bar the user approved) and ${REPO}/docs/PROCESS.md (the production steps and commands) before you start, and follow them. The complete worked example is ${REPO}/episodes/ep01_pantheon/ (episode.json, labels.json, captions.json, SCRIPT.md, FACTS_walls.md, assets.md, scan_prep.json) with its builder ${REPO}/kit/build_pantheon.py; kit reference: ${REPO}/kit/README.md.
Hard rules: run Blender only through ${REPO}/kit/blender_locked.sh (one Blender at a time, 8 GB machine); never let Blender open textures above 4K (downscale with kit/import_scan.py first); style "paper" was rejected by the user, so use it only if the style arg says so; do not log in to, create accounts on, or download from any site on the user's behalf.
Lighting (STANDARD.md section 4, kit/README.md "Lighting presets"): the episode uses ONE lighting preset from kit/light_presets.py (${PRESETS.join(', ')}), chosen because it suits this building (material, setting, character, the story of the episode) and held from the first frame to the last: no preset switches, no time-of-day changes inside the episode. golden_hour is ep01's choice, not a default. Guard-rails: the building separates from the background (value and warm/cool), the structures the labels explain are lit, no pink-purple ground (measure a ground patch: hue 20-40 or 200-230 deg, never 290-350), captions and labels legible over the sky band. The blueprint / x-ray graphics layer and blueprint label cards are optional kit features that are off in the standard: never add a "graphics" block or "card_style".
Write in Chinese for everything that appears on screen or goes to the user; code comments in English.`

// ---------------------------------------------------------------- schemas
const RESEARCH_SCHEMA = {
  type: 'object',
  properties: {
    hook: { type: 'string', description: 'C0 caption: text / sub' },
    answer: { type: 'string', description: 'C1 closing caption: text / sub' },
    beats: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          t: { type: 'string', description: 'time range in s, e.g. "2.0-7.0"' },
          reveal: { type: 'string', description: 'which structure is taken apart / shown' },
          how_function_is_shown: { type: 'string', description: 'how the FUNCTION is visualised (force lines, light, water, scale...)' },
          label: { type: 'string', description: 'main / sub' },
          part: { type: 'string', description: 'model part the label points at' },
        },
        required: ['t', 'reveal', 'label'],
      },
    },
    unverified: { type: 'array', items: { type: 'string' }, description: 'claims dropped or softened because sources disagree' },
    files: { type: 'array', items: { type: 'string' } },
  },
  required: ['hook', 'answer', 'beats', 'files'],
}

const MODEL_SCHEMA = {
  type: 'object',
  properties: {
    scan_needed: { type: 'boolean', description: 'true if an interior/detail reveal should use a real scan' },
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' }, author: { type: 'string' }, license: { type: 'string' },
          url: { type: 'string' }, faces: { type: 'number' }, use: { type: 'string' },
          save_as: { type: 'string', description: 'path under models/<key>/ the user should save the GLB to' },
          recommended: { type: 'boolean' },
        },
        required: ['name', 'author', 'license', 'url', 'save_as'],
      },
    },
    downloaded: { type: 'array', items: { type: 'string' }, description: 'model files already present in the models folder' },
    components_reuse: { type: 'array', items: { type: 'string' } },
    components_new: { type: 'array', items: { type: 'string' } },
    lighting: {
      type: 'object',
      properties: {
        preset: { type: 'string', enum: PRESETS },
        why: { type: 'string', description: 'one or two Chinese sentences: why this preset suits THIS building (material, setting, character, the story/hook)' },
        risks: { type: 'string', description: 'which guard-rail this building is at risk of failing under the preset, and the planned fix (e.g. dark stone sinking into a night sky -> stronger floods)' },
        overrides: { type: 'string', description: 'LOOK keys to override for this building, if any (usually none)' },
      },
      required: ['preset', 'why', 'risks'],
    },
    notes: { type: 'string' },
  },
  required: ['scan_needed', 'candidates', 'downloaded', 'components_reuse', 'components_new', 'lighting'],
}

const STEP_SCHEMA = {
  type: 'object',
  properties: {
    done: { type: 'boolean' },
    files: { type: 'array', items: { type: 'string' } },
    stills: { type: 'array', items: { type: 'string' } },
    render_s_per_frame: { type: 'number' },
    issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['done', 'files', 'issues'],
}

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    checks: {
      type: 'array',
      items: {
        type: 'object',
        properties: { item: { type: 'string' }, pass: { type: 'boolean' }, evidence: { type: 'string' } },
        required: ['item', 'pass', 'evidence'],
      },
    },
    must_fix: { type: 'array', items: { type: 'string' } },
  },
  required: ['checks', 'must_fix'],
}

// ---------------------------------------------------------------- 1. research || model plan
phase('Research')
const [research, models] = await parallel([
  () => agent(`${COMMON}

Task: facts, script and labels for this episode (PROCESS.md step 1). No 3D work.
1. Find the one question that makes ${BUILDING} remarkable (the hook) and 5-7 reveals that answer it, in teardown order: start on the complete recognisable building, take it apart one structure at a time, reassemble for a seamless loop. For each reveal decide how its FUNCTION is made visible (like ep01's gold force lines into the 8 piers), not just which part it is.
2. Verify every number, name and date that will be on screen against at least two reliable sources (encyclopaedias, scholarly publications, official heritage sites). Soften or drop anything the sources disagree on, as ep01 did ("引向" not "撑着"). Deep structural questions go in FACTS_<topic>.md with sources.
3. Write in ${EP_DIR}/ (create it): SCRIPT.md (same sections as ep01: spec, beat sheet with times/picture/camera/on-screen text, hook logic, loop, model and materials, fact table with source URLs and confidence, Douyin + Bilibili titles and tags, music), labels.json (main <= 14 Chinese characters, sub <= 22), captions.json (C0 hook 0-2.6 s, C1 answer at the end with "名建筑拆解 ${NUM} · <中文名>"), FACTS_*.md as needed.
4. Music: default to the ep01 track (music/bach_air_usaf.mp3, public domain) unless another public-domain / CC0 recording clearly fits better; if you pick another, give its Wikimedia Commons (or similar) URL and licence in SCRIPT.md.
Return the beats and captions you wrote.`, { label: 'facts + script', phase: 'Research', schema: RESEARCH_SCHEMA }),

  () => agent(`${COMMON}

Task: model plan (PROCESS.md step 2). No Blender.
1. Decide which parts of ${BUILDING} the self-built exterior needs, split into kit components that already exist (realkit / paperkit, see kit/README.md tables) and new ones to write.
2. Decide whether a reveal should use a real photogrammetry scan (usually an interior). If yes, search Sketchfab's public API (no login needed), e.g.
   curl -s 'https://api.sketchfab.com/v3/search?type=models&downloadable=true&license=by&count=24&q=<name>'
   and the same with license=cc0, plus 1-2 alternative names/spellings. Keep candidates whose licence is CC BY or CC0, that are downloadable, show the right space at the right proportions, and have <= ~2M faces. Give 2-3 candidates with author, licence label, model page URL (viewerUrl), face count, what you would use it for, and the file name the user should save the glTF/GLB as under ${MODELS}/. Mark one recommended.
3. List model files already in ${MODELS}/ (it may not exist yet).
4. Write ${EP_DIR}/assets.md in the same format as episodes/ep01_pantheon/assets.md: every external asset with source URL, licence, the attribution line for the video description, and how to fetch it (the user downloads Sketchfab models; the music can be fetched with curl from Wikimedia Commons).
5. Pick the lighting preset for ${BUILDING}: read the preset table, the selection guide and the guard-rails in kit/README.md ("Lighting presets") and STANDARD.md section 4. Decide from the building itself: its main materials and colours, where it stands (square, landscape, water, desert, city), its character, and the story the hook tells. Give the reason in one or two Chinese sentences that name those facts (not "it looks nice"), and say which guard-rail this building risks under the preset and how you would fix it with light. One preset for the whole episode; do not propose switching.`, { label: 'model plan', phase: 'Research', schema: MODEL_SCHEMA }),
])
if (!research || !models) throw new Error('research or model plan failed; rerun with resumeFromRunId after fixing')
if (!models.lighting || !PRESETS.includes(models.lighting.preset)) throw new Error(`model plan returned no valid lighting preset (${JSON.stringify(models.lighting)})`)
const LIGHT = models.lighting
log(`lighting preset ${LIGHT.preset}: ${LIGHT.why}`)
const haveScan = models.scan_needed && models.downloaded.some(f => /\.(glb|gltf)$/i.test(f))
log(`${research.beats.length} beats; scan ${models.scan_needed ? (haveScan ? 'downloaded' : 'needed, waiting for the user download') : 'not needed'}`)

// ---------------------------------------------------------------- 2. geometry
phase('Geometry')
const geometry = await agent(`${COMMON}

Task: geometry (PROCESS.md steps 4-5).
Beats from the research step (JSON): ${JSON.stringify(research.beats)}
Model plan (JSON): ${JSON.stringify({ components_reuse: models.components_reuse, components_new: models.components_new, downloaded: models.downloaded, scan_needed: models.scan_needed, lighting: LIGHT })}
1. ${haveScan ? `A scan is downloaded in ${MODELS}/. Downscale it outside Blender (kit/import_scan.py downscale ... --size 4096), write ${EP_DIR}/scan_prep.json from the ep01 template with the real dimensions from SCRIPT.md, run the prep through kit/blender_locked.sh, and look at the check render (proportions, entrance direction).` : `No scan is available yet: build the whole building yourself; keep the reveal that would use a scan working with self-built geometry, and note in SCRIPT.md that the scan can replace it later.`}
2. Write the builder build_${MODEL_KEY}.py in ${EP_DIR}/ (run_episode finds builders next to the episode JSON first) from the kit/build_pantheon.py pattern: named dimensions at the top, kit components, and the meta every planned teardown move needs (layer, side with seams on the hinge plane, ring, sub). Separable parts must not share coplanar faces (offset 3-6 cm); faces exposed when parts separate get aggregate/cut colours. New generic components go into kit/realkit.py or kit/paperkit.py with a row in kit/README.md.
3. Start ${EP_DIR}/episode.json from the ep01 one (title, palette/real_palette, builder, setting, shots; empty explode/camera for now). Lighting: replace ep01's real_look completely with {"preset": "${LIGHT.preset}"} (ep01's golden-hour values and sun_keys belong to ep01 only), delete ep01's "grade" (an episode grade replaces the preset grade) and the ground colours in real_palette (the preset brings them); no "graphics". Render the "shots" (complete building, 3-4 angles) at --draft to out/${SLUG}_shots/. Look at them: recognisable at a glance, proportions right, materials read as real stone/brick/metal under this light, nothing painted-on where depth is expected, the building separates from the sky and the ground, no pink-purple ground. Fix geometry and materials first; fix lighting problems with light (exposure, flood/shaft strength, mist amount, single LOOK overrides), never by switching preset mid-episode. Re-render until they pass.
4. Add a line "光影" to SCRIPT.md section 2 (模型与材质) like ep01's: the preset, what the light does on this building, and the reason: ${LIGHT.why}`, { label: 'builder + shots', phase: 'Geometry', schema: STEP_SCHEMA })

// ---------------------------------------------------------------- 3. episode JSON
phase('Episode')
const episode = await agent(`${COMMON}

Task: choreography in ${EP_DIR}/episode.json (PROCESS.md step 6). The builder and shots are done: ${JSON.stringify(geometry)}
Beat sheet: ${EP_DIR}/SCRIPT.md; labels.json and captions.json are next to it.
${A.episode_note ? `NOTE FROM THE COORDINATOR: ${A.episode_note}\n` : ''}Write groups (hinges), explode (time-ordered moves and reassembly), visibility, schedule (diagram pieces only), camera (always moving, loop: last key == first key at duration), anchors with follow + overlay.anchor_for / overlay.place (spread labels, keep out of the Douyin safe areas and off moving parts), setting (calm, not empty), stills at every beat, music, draft_render, and a function visualisation for the beats that need one.
Lighting stays real_look {"preset": "${LIGHT.preset}"} for the whole episode (chosen because: ${LIGHT.why}). Plan the camera with the light: the explained structures must be lit when their labels are on screen, and the sky band behind the top caption must stay calm (no bright sun glow or busy clouds behind the text).
Loop with draft stills (kit/run_episode.py --draft --samples 8 --stills out/${SLUG}_test --still-t ...) and fix until each beat reads clearly. Check the hook still (t 0) against the lighting guard-rails with the preset grade and the real caption: python3 kit/preset_stills.py ${EP_DIR}/episode.json out/${SLUG}_look --presets ${LIGHT.preset} --draft; measure the hue of a ground patch (20-40 or 200-230 deg, never 290-350). Check the loop seam (t 0 vs t duration-1/fps) and that no part flickers at a separation (render 3 consecutive frames at each separation). Update SCRIPT.md so beat times match the JSON.`, { label: 'episode.json', phase: 'Episode', schema: STEP_SCHEMA })

// ---------------------------------------------------------------- 4. draft render + objective review
phase('Draft')
const draftPrompt = (extra) => `${COMMON}

Task: draft video (PROCESS.md step 7).
Run: python3 ${REPO}/kit/produce.py ${EP_DIR}/episode.json draft   (frames + anchors + overlay + music; resumes if interrupted)
Then open out/<episode>_draft/contact.jpg and fix what you see (layout issues via overlay --only-check and produce.py ... --from overlay; animation issues in episode.json, then delete only the affected frames and rerun produce.py).${extra || ''}
Return the paths of out/<episode>_draft.mp4, _share.mp4 and the contact sheet in files.`
let draft = await agent(draftPrompt(''), { label: 'draft render', phase: 'Draft', schema: STEP_SCHEMA })

const reviewPrompt = (d) => `${COMMON}

Task: objective review of the draft against docs/PROCESS.md section 9 (the checklist) and the measurable parts of docs/STANDARD.md. Only verifiable items: measure with ffprobe (duration, resolution, fps, audio), the loudness printed by kit/finish.py or ffmpeg ebur128, label character counts, safe areas (read overlay positions from the overlay log / anchors and the card sizes), loop seam (compare first and last frames), every on-screen number present in the SCRIPT.md fact table with a source, assets.md attribution complete, SCRIPT.md matches labels.json/captions.json; lighting: episode.json has exactly one real_look.preset (one of ${PRESETS.join(', ')}), no "graphics" block, no real_look values or "grade" carried over from ep01 (compare with episodes/ep01_pantheon/episode.json), and SCRIPT.md states the preset and its reason; on the first draft frame measure the hue of a ground patch (must be 20-40 or 200-230 deg, never 290-350) and the mean luminance of the building vs the sky right behind it (must differ clearly). Inspect the contact sheet and a few frames at the separations for flicker, interpenetration, blown-out or black frames. Do not judge taste, story or camera choices; those belong to the user.
Draft result: ${JSON.stringify(d)}`
let review = await agent(reviewPrompt(draft), { label: 'checklist review', phase: 'Draft', schema: REVIEW_SCHEMA })

if (review && review.must_fix.length) {
  log(`review: ${review.must_fix.length} must-fix item(s), one fix round`)
  draft = await agent(draftPrompt(`\nFix these review findings first, then rerun only what they affect: ${JSON.stringify(review.must_fix)}`),
    { label: 'draft fixes', phase: 'Draft', schema: STEP_SCHEMA })
  review = await agent(reviewPrompt(draft),
    { label: 'recheck', phase: 'Draft', schema: REVIEW_SCHEMA })
}

// ---------------------------------------------------------------- 5. report
phase('Report')
const report = await agent(`Write a short Chinese report (at most 15 lines, no headings, no restating file contents) for the user about episode ${NUM} · ${BUILDING}:
- the draft to watch (the _share.mp4 path) and the contact sheet path;
- the lighting preset (Chinese name + key) and the one-line reason it suits this building;
- if a scan is needed but not downloaded: a table of model links to download (author, licence, save as) from the model plan;
- checklist items that still fail, and known weak spots;
- next step: the user watches the draft; after approval run "python3 ${REPO}/kit/produce.py ${EP_DIR}/episode.json final" (set render_segments after a speed test with kit/bench_render.py, PROCESS.md step 8), then publish via video-publish-kit.
Data: ${JSON.stringify({ research: { hook: research.hook, answer: research.answer, unverified: research.unverified }, models, geometry, episode, draft, review })}`,
  { label: 'report', phase: 'Report' })

return { report, draft, review, models, research }
