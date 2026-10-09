# 名建筑拆解 · 制作流程

每集按这个顺序走。质量底线见 [STANDARD.md](STANDARD.md)，样例见 `episodes/ep01_pantheon/`。
自动化入口：`.claude/workflows/arch-episode.js`（Workflow 名 `arch-episode`），它跑第 1–7 步的 Claude 部分，停在草稿交付。

## 分工

| 谁 | 做什么 |
|---|---|
| **用户** | 定选题；在 Sketchfab 登录并下载模型（Claude 只列链接，不代为登录或建账号）；看草稿、提意见；确认定稿；确认发布 |
| **Claude** | 查证与脚本、模型方案、导入扫描、建模、episode JSON、渲染、叠字配乐、发布清单；每次交付前按第 9 节自查 |

## 时间目标（一座新建筑）

| 步骤 | 人工 | 机器 |
|---|---|---|
| 1 查证 + 脚本 + 标注 | 20–30 min（与第 2 步并行） | — |
| 2 模型方案（搜索候选、列下载链接） | 10 min | — |
| 3 用户下载模型（多集攒一批） | 用户 5 min/集 | — |
| 4 导入扫描 `import_scan.py` | 5 min | 3–8 min |
| 5 builder / 部件 | 30–60 min（同风格复用时 15 min） | build < 3 s |
| 6 episode JSON（拆解、镜头、标注、场地） | 20–40 min，静帧循环每轮约 30 s | — |
| 7 草稿 540×960 + 叠字 + 配乐 | 5 min | 约 20 min（960 帧 × 1.0–1.3 s） |
| 8 定稿 1080×1920 | 5 min | 空闲机器约 25–50 min（按预设 1.4–2.9 s/帧估）；机器被别的会话占满时明显更久（ep01 实测 3.3–6.5 s/帧），见第 8 节 |
| 9 发布 | 5 min | 几分钟 |

跑顺后目标：每集人工 1.5–2.5 h，机器 45–65 min。多集时第 1–2 步一次性并行做完，模型清单一次发给用户下载，渲染排队（一次一个 Blender）。

---

## 1. 查证 + 脚本 + 标注（先于一切建模）

产出（放 `episodes/epNN_slug/`）：
- `SCRIPT.md`：规格、节拍表（时间 / 画面 / 镜头 / 屏上文字）、钩子逻辑、循环说明、模型与材质、**事实核对表**（屏上每个数字和名字一行：结论 / 来源 URL / 置信度）、标题与话题（抖音、B 站）、配乐与命令。以 ep01 的 SCRIPT.md 为模板。
- `labels.json`：`[{id, t_in, t_out, text, sub, anchor_part, size?}]`，主 ≤ 14 字、副 ≤ 22 字，5–7 条。
- `captions.json`：片头钩子 C0（0–2.6 s）+ 片尾答案 C1（最后约 4 s）。
- 需要深挖的结构问题另写 `FACTS_<主题>.md`。

要点：先找"这座建筑为什么了不起"的一个问题做钩子，再把每个揭示步骤排成对这个问题的回答；每一步都想好**怎么把作用画出来**（力线、光线、水流、人的尺度……）。

## 2. 模型方案

- 外观一律自建（kit 部件 + 该建筑的 builder）。列出需要的部件：哪些已有（`realkit`：科林斯柱、檐部、山花、檐口环、穹顶台阶；`paperkit`：墙、穹顶壳、藻井、拱、楼梯、门……），哪些要新写。
- 室内揭晓镜头如果需要真实感，找扫描：Sketchfab 公共 API 搜 CC BY / CC0 且可下载的模型：
  `https://api.sketchfab.com/v3/search?type=models&q=<建筑名>&downloadable=true&license=by`（`license=cc0` 同理；看 `faceCount`、`license.label`、`user.displayName`、`viewerUrl`）。
  挑 2–3 个候选（室内完整、比例对、面数 ≤ 2M），把模型页链接和许可列给用户下载 glTF/GLB 到 `models/<slug>/`。
- 署名文字当场写进该集 `assets.md`（CC BY 必须在视频简介里署名）。

## 3. 用户下载（批量）

给用户一张表：集数 / 模型页链接 / 许可 / 作者 / 保存为 `models/<slug>/<文件名>.glb`。多集一起给，一次下完。

## 4. 导入扫描

```bash
python3 kit/import_scan.py downscale models/<slug>/<scan>.glb models/<slug>/<scan>_4k.glb --size 4096   # Blender 外压贴图
kit/blender_locked.sh -b --factory-startup -P kit/import_scan.py -- prep episodes/epNN_slug/scan_prep.json
```
`scan_prep.json` 写真实尺寸（`measure.real_diameter` 等）、入口朝向、渲染检查图路径；产出 `models/<slug>/<name>_prepped.{blend,json}`，看检查图确认比例和朝向。以 ep01 的 `scan_prep.json` 为模板。

## 5. builder / 部件

- 复杂建筑写 `build_<slug>.py`（`build(pk, spec)`，放在 episode 目录或 `kit/`，run_episode 先找 episode 目录），尺寸用命名常量集中在文件头，调用 kit 部件。以 `kit/build_pantheon.py` 为模板。
- 给每块打上拆解要用的 meta：`layer`（skin / core）、`side`（R / L，铰链面上分缝）、`ring`（分层）、`sub`（子部件）。
- 分离后会露出的面给骨料 / 切面颜色；会分开的部件错开 3–6 cm，避免共面。
- 通用的新部件写进 `realkit.py` / `paperkit.py`，并在 `kit/README.md` 的部件表里补一行。

## 6. episode JSON

复制 `episodes/ep01_pantheon/episode.json`，按节拍表改：
- **光影预设**：按这座建筑选一个（材质、所处环境、建筑性格、这一集的故事；表和护栏见 STANDARD.md 第 4 节，键的细节见 `kit/README.md` 的 Lighting presets），写 `"real_look": {"preset": "<名字>"}`，全集只用这一个，不换预设、不换时段。由 Claude 按建筑直接选定，在 `SCRIPT.md` 的"模型与材质"里写一句为什么选它；ep01 的 `golden_hour` 不是默认值。复制过来的 ep01 光影要换掉：`real_look` 整个改成 `{"preset": "<名字>"}`（ep01 的黄昏数值和 `sun_keys` 只属于 ep01），删掉 ep01 的 `grade`（episode 有 `grade` 时预设的调色不生效）和 `real_palette` 里的地面色（预设自带）。不加 `graphics`（蓝图 / X 光图层不属于标准）。
- `palette` / `real_palette`（按材质命名，名字决定材质配方；预设已带地面暖石色修正，`real_palette` 只写这座建筑需要的）、`setting`（场地 + 远景城市）、`scan`（如有）。
- `groups`（铰链）→ `explode`（按时间顺序的拆开 / 合回）→ `visibility`（只在某段需要的昂贵部件：扫描、光柱体积）。
- `camera`：关键帧 `{t, az, el, dist, target, lens, interp}`，镜头一直在动；循环片最后一个关键帧 = 第 1 帧。
- `anchors`（`follow` 跟随部件）+ `overlay.anchor_for` / `overlay.place`（标签位置，避开安全区与动作）。
- `stills`：5–6 张关键时刻静帧；`music`：配乐文件、起点、淡入淡出、−14 LUFS。

静帧循环（每轮约 30 s），看颜色、镜头、拆解时机：
```bash
kit/blender_locked.sh -b --factory-startup -P kit/run_episode.py -- episodes/epNN_slug/episode.json \
  --draft --samples 8 --stills out/epNN_test --still-t 0 5.5 9 13.2 24 29.5
```
第一张（t 0，钩子帧）先过光影护栏（STANDARD.md 第 4 节）：建筑和背景分得开、地面不偏粉紫、标签指的结构受光、顶部字幕读得清。静帧没有调色和字幕；要看预设本身带调色和钩子字幕的样子，用
`python3 kit/preset_stills.py episodes/epNN_slug/episode.json out/epNN_look --presets <预设> --draft`（约 6 s/个）。拿不准两个预设时可以把两个都列上并排看，定下一个再往下做。

## 7. 草稿 540×960（给用户审）

```bash
python3 kit/produce.py episodes/epNN_slug/episode.json draft
```
= 锚点 → 960 帧草稿（`draft_render`：6 samples、shadow_res 0.3、无光追）→ 调色（episode 的 `grade`，没有就用预设的）+ 叠字 + 引线 + 顶部字幕（放大到 1080×1920 编码）→ 配乐 → `out/epNN_draft.mp4` + `_share.mp4` + `out/epNN_draft/contact.jpg`。
中断后重跑同一命令，已渲染的帧会跳过。只重做叠字：`--from overlay`；只重混音乐：`--from finish`。

标签版式在草稿帧上迭代，不用重渲（几秒一轮）：
```bash
python3 kit/overlay.py episodes/epNN_slug/episode.json out/epNN_draft/frames out/epNN_draft/anchors.json /dev/null \
  --only-check --check out/epNN_layout --check-t 4 9 13 17 24 30
```
改了 `labels.json` / `overlay.place` 之后跑 `produce.py ... draft --from overlay`。

## 8. 定稿 1080×1920

用户确认草稿后渲一次：
```bash
python3 kit/produce.py episodes/epNN_slug/episode.json final     # = kit/render_final.sh + overlay（--preset slow）+ finish
```
**定稿渲染设置（每集标准）：12 samples，结构图解段 16，光追全关，shadow_res 0.45。**
质量按 episode JSON 的 `render_segments` 分时间段设置（每个镜头段一段），每段一个 Blender 进程（`run_episode.py --segment NAME --skip-existing`），中断后重跑同一命令只补缺的帧。ep01 的实际设置：

```json
"render_segments": [
  {"name": "exterior", "t": [0.0, 10.6],    "samples": 12, "raytracing": 0, "shadow_res": 0.45},
  {"name": "interior", "t": [10.6, 15.0],   "samples": 12, "raytracing": 0, "shadow_res": 0.45},
  {"name": "portico",  "t": [15.0, 20.45],  "samples": 12, "raytracing": 0, "shadow_res": 0.45},
  {"name": "diagram",  "t": [20.45, 26.95], "samples": 16, "raytracing": 0, "shadow_res": 0.45},
  {"name": "cutaway",  "t": [26.95, 40.0],  "samples": 12, "raytracing": 0, "shadow_res": 0.45}
]
```
理由（`render_segments_note`）：光追全关（和用户认可的草稿 2 一致；扫描室内开不开差别 rms 0.3–1.1/255，却多花 20 %）；shadow_res 0.45；12 samples 的噪点已低于草稿 2（对照 64 samples 参考帧）；墙体结构图段（半透明外皮 + 暗空腔最容易出噪点）用 16。可用的键：`samples, shadow_res, raytracing, fast_gi, shadow_rays, shadow_steps, vol_tile, vol_samples, denoise`。

**新一集先测速再定分段**：每类镜头挑一帧（外景、室内 + 光柱、结构图……），在一个 Blender 进程里比几组参数：
```bash
BENCH_OUT=out/epNN_bench BENCH_FRAMES="25,325,577" \
BENCH_VARIANTS='[{"name":"s16_rt","samples":16,"raytracing":1},{"name":"s12_nort","samples":12,"raytracing":0},{"name":"s8_sh30","samples":8,"shadow_res":0.3}]' \
kit/blender_locked.sh -b --factory-startup -P kit/run_episode.py -P kit/bench_render.py -- episodes/epNN_slug/episode.json
```
看 `bench.json` 的时间和各变体的 PNG，每段取"噪点不高于草稿 2 里最快的"。

**质量底线 = ep01 草稿 2**（540×960，6 samples，shadow_res 0.3，光追关，放大 2 倍）：定稿至少和它一样锐、一样干净。噪点算法：每个变体和同设置的 64 samples 参考帧相减，取高频部分的 RMS（差图减去它的 σ2 高斯模糊，8-bit 色阶，越小越干净）；草稿 2 用同样方法算（540 s6 对 540 s64，都放大 2 倍再比）。

ep01 测速（M2 8 GB，1080×1920，同一 Blender 进程测 3 帧，秒/帧，负载 5–8，误差约 ±0.25 s；噪点依次是门廊 / 墙体拱券图解 / 室内）：

| 方案 | 外景 t=1 | 拱券 t=24 | 室内 t=13.5 | 噪点 门廊/拱券/室内 |
|---|---|---|---|---|
| 草稿 2（540，6 samples，shadow_res 0.3，光追关，放大） | 0.39 s | 0.46 s | 0.65 s | 2.20 / 3.64 / 0.57 |
| A 原定稿设置：16 samples，shadow_res 0.45，光追开 | 1.46 s | 1.73 s | 2.68 s | 光追改变了画面，不参与比较 |
| B 16 samples，光追关 | 1.39 s | 1.72 s | 2.20 s | 1.43 / 2.96 / 0.41 |
| **H 12 samples，光追关（采用）** | **1.03 s** | **1.26 s** | **1.76 s** | **1.62 / 3.54 / 0.43** |
| C 8 samples，光追关 | 1.17 s | 1.26 s | 1.40 s | 2.17 / 4.50 / 0.48，拱券段比草稿 2 脏 |
| D 8 samples，shadow_res 0.30 | 0.90 s | 1.47 s | 1.43 s | 比 C 更脏 |
| E 草稿 2 的设置直接渲 1080 | 0.82 s | 1.00 s | 1.11 s | 比 D 更脏 |
| F 8 samples，体积 tile 16 | 0.91 s | 1.17 s | 1.63 s | 光柱样子变了，没提速 |
| G 8 samples + OIDN 降噪 | 1.70 s | 1.55 s | 2.23 s | 更慢，还把砖和扫描贴图抹糊 |
| 参考 64 samples，光追关 | 3.83 s | 4.92 s | 6.99 s | — |

规律：
- **光追全片关**（和测前设想相反）：扫描室内靠自发光，开不开几乎没区别（rms 0.3–1.1），却多花约 20 %；外景只让接触阴影略深，正常观看尺寸看不出。关光追也就是用户认可的草稿 2 的样子。
- **samples 是 1080 下最有效的提速参数**：16 → 12 省约 25 %，各段仍比草稿 2 干净；8 在拱券图解段比草稿 2 脏。噪点最重的段（半透明外皮 + 暗空腔）保留 16。
- **shadow_res 和体积 tile 不动**：降它们几乎不省时间，反而损失锐度或改变光柱；OIDN 降噪比直接多加 samples 还慢。

ep01 定稿实际耗时（黄昏预设，上面的设置，每段一个 Blender 进程，2026-09-30）：

| 段 | 帧 | samples | 秒/帧 |
|---|---|---|---|
| 外景 | 1–254 | 12 | 6.46 |
| 室内（扫描 + 光柱） | 255–360 | 12 | 6.06 |
| 门廊 | 361–491 | 12 | 5.86 |
| 拱券图解 | 492–647 | 16 | 5.95 |
| 剖切 + 球体 + 循环 | 648–960 | 12 | 3.28 |

上表是机器被别的会话占满时的实测（峰值内存约 1.33 GB，一次只开一个 Blender）；空闲时黄昏预设的钩子帧 1.5 s/帧，六个预设 1.4–2.9 s/帧。调色 + 叠字 + 配乐 + 分享版 + 联系表约 12 min（同样负载）。中断后重跑同一命令，已渲染的帧会跳过（`--skip-existing`）。定稿尽量在空闲时渲（`sysctl vm.loadavg` > 4 时同样的帧会慢 2–4 倍），渲染时别开别的重活。蓝调时刻、夜景泛光约多 20 盏聚光灯（每帧多 0.5–1.4 s），新一集先用 `bench_render.py` 测。

## 9. 交付前自查（草稿和定稿都要过）

- [ ] 时长、分辨率、帧率用 `ffprobe` 实测：40.0 s、1080×1920、24 fps、有音轨。
- [ ] 响度：`finish.py` 打印的 integrated loudness 在 −14 ± 1 LUFS。
- [ ] 联系表 `contact.jpg` 从头看到尾：首帧是完整建筑 + 钩子；每步只有一条标注；片尾答案字幕。
- [ ] 标签和字幕都不进安全区（底部 20 %、右侧 12 %），不压正在动的部件，彼此不重叠。
- [ ] 标签字数：主 ≤ 14、副 ≤ 22；屏上每个数字和名字在 SCRIPT.md 事实表里有来源。
- [ ] 循环：第 1 帧和最后一帧接得上（同向同速），所有部件在收尾前复原。
- [ ] 抽看关键段（拆开、硬切、结构图、合回）逐帧：无闪烁、无穿模、无发白、无黑帧。
- [ ] 扫描室内与外景颜色一致（同一 AgX 变换）。
- [ ] 光影：episode JSON 里只有一个 `real_look.preset`，全片不换预设、不换时段，没有 `graphics`；钩子帧过 STANDARD.md 第 4 节的护栏（建筑和背景分得开；地面一块实测色相在 20–40° 或 200–230°，不在 290–350°；标签指的结构受光；顶部字幕和标签读得清）。
- [ ] SCRIPT.md 与实际成片一致（节拍时间、标注文字）；`assets.md` 的署名齐全。
- [ ] 给用户：`_share.mp4`（手机看）+ 联系表 + 一句话说明改了什么、还有哪些已知弱点；定稿另附无音乐版 `silent.mp4`（静音音轨，抖音站内配乐用）。

## 10. 发布（用户确认后）

用 video-publish-kit（`~/claude-projects/video-publish-kit`）：写一份清单 `manifests/arch-epNN.json`，标题 / 话题取 SCRIPT.md 第 4 节，简介里放 `assets.md` 的署名和音乐来源、事实来源；先 dry-run 检查，用户确认后 `--go`。
```bash
python3 ~/claude-projects/video-publish-kit/publish.py manifests/arch-epNN.json                              # dry run
python3 ~/claude-projects/video-publish-kit/publish.py manifests/arch-epNN.json --only bilibili,douyin --go   # 发布
```

## 目录约定

```
episodes/epNN_slug/   episode.json labels.json captions.json SCRIPT.md FACTS_*.md assets.md scan_prep.json [build_slug.py]
models/<slug>/        下载的 GLB、_4k.glb、_prepped.blend/json（不入库）
music/                配乐文件（不入库）
out/                  帧、锚点、视频、联系表（不入库）
```
路径都可以用环境变量改到别处：`ARCH_KIT_MODELS`、`ARCH_KIT_MUSIC`、`ARCH_KIT_OUT`、`ARCH_KIT_FONTS`、`BLENDER`、`ARCH_BLENDER_LOCK`（见 `kit/config.py`）。
