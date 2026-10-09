# 名建筑拆解 · arch-teardown-kit

竖屏短视频系列"名建筑拆解"的制作工具和流程：一座世界名建筑，从完整的样子开始，一块一块拆开（爆炸图），每一步揭示一个结构、用一条查证过的标注讲清它**起什么作用**，最后合回原样、无缝循环。40 秒，1080×1920，纯配乐。

每集用一个适合这座建筑的光影预设（黄昏、蓝调时刻、阴天压顶、夜景泛光、晨雾、正午硬光），全集不换。

第 1 集：罗马万神殿（`episodes/ep01_pantheon/`，黄昏）——穹顶分层散开讲"越往上越薄越轻"，镜头钻进天眼切到真实扫描的室内，砖墙变半透明、金色力线沿砖拱流进 8 根墩柱，最后在圆厅里放进一个 43.3 米的球。

- 质量标准：[docs/STANDARD.md](docs/STANDARD.md)
- 制作流程与时间目标：[docs/PROCESS.md](docs/PROCESS.md)
- 自动化：[.claude/workflows/](.claude/workflows/README.md)（Workflow `arch-episode`，参数 `{building, slug}`，跑到草稿为止）
- 工具箱参考（部件、JSON 字段、光影预设、渲染预算）：[kit/README.md](kit/README.md)

## 快速开始

需要：macOS，Blender 5.2（`/Applications/Blender.app`，或设 `BLENDER=`），python3 + numpy + opencv-python + Pillow，ffmpeg，Noto Sans SC 字体（`~/Library/Fonts`，或设 `ARCH_KIT_FONTS=`）。

```bash
git clone <this repo> arch-teardown-kit && cd arch-teardown-kit
python3 kit/config.py                      # 看路径设置（models/ music/ out/ 默认在仓库里，均不入库）

# 1. 取回 ep01 的外部素材（扫描模型需在 Sketchfab 手动下载，见 episodes/ep01_pantheon/assets.md）
mkdir -p music && curl -L -o music/bach_air_usaf.mp3 \
  "https://upload.wikimedia.org/wikipedia/commons/e/ec/Air_-_Air_Force_Strings_-_United_States_Air_Force_Band.mp3"
python3 kit/import_scan.py downscale models/pantheon/the_pantheon_interior.glb models/pantheon/the_pantheon_interior_4k.glb --size 4096
kit/blender_locked.sh -b --factory-startup -P kit/import_scan.py -- prep episodes/ep01_pantheon/scan_prep.json

# 2. 静帧检查（约 30 s）
kit/blender_locked.sh -b --factory-startup -P kit/run_episode.py -- episodes/ep01_pantheon/episode.json \
  --draft --samples 8 --stills out/ep01_test --still-t 0 5.5 13.2 24 29.5

# 3. 草稿 540×960（帧 + 标注 + 配乐，约 20 min）-> out/ep01_draft.mp4 + _share.mp4
python3 kit/produce.py episodes/ep01_pantheon/episode.json draft

# 4. 定稿 1080×1920（按 render_segments 分段渲染，可中断续跑）-> out/ep01_final.mp4
python3 kit/produce.py episodes/ep01_pantheon/episode.json final
```

一台 8 GB 的机器上一次只跑一个 Blender：所有 Blender 调用都经过 `kit/blender_locked.sh`（多个项目共用时把 `ARCH_BLENDER_LOCK` 指到同一个锁目录）。

## 目录

```
kit/                     工具箱（Blender 无头 Python + 普通 python3）
  config.py              所有路径与环境变量（ARCH_KIT_MODELS / _MUSIC / _OUT / _FONTS / _SERIF / _DIN, BLENDER, ARCH_BLENDER_LOCK）
  paperkit.py            场景、部件、拆解动画（explode / groups / reassemble）、镜头、锚点导出、渲染设置
  realkit.py             真实材质：程序化 PBR 配方、天空与阳光、场地与远景城市、古典部件、扫描载入 + 逆 AgX LUT
  light_presets.py       光影预设库（6 个，每个带灯光与天空、地面色修正、调色），每集选一个
  preset_stills.py       每个预设一张钩子静帧 + 带中文名的对比表
  blueprint.py           可选的蓝图 / X 光图层（episode 写了 graphics 才启用，默认关闭，不属于标准）
  run_episode.py         一集的 Blender 入口：build -> 动画 -> 静帧 / 帧 / 锚点
  produce.py             一条命令出片：锚点 -> 分段渲染（可续跑） -> overlay -> finish
  render_final.sh        定稿帧：每个 render_segments 段一个 Blender 进程，可续跑（produce.py final 做同样的事）
  bench_render.py        测速：一个 Blender 进程里比较几组渲染参数（选 render_segments 用）
  overlay.py             调色、2D 标签卡、引线、顶部字幕，编码 H.264（安全区检查）
  finish.py              配乐（两遍 loudnorm 到 −14 LUFS、淡入淡出）+ 分享版（1080×1920，5 Mb/s，40 s 约 26 MB）；
                         无音乐版就是 overlay 的 silent.mp4
  import_scan.py         摄影测量 GLB：Blender 外压贴图；Blender 内缩放对齐、存 .blend
  build_pantheon.py      ep01 的 builder（新建筑照这个写 build_<key>.py）
  blender_locked.sh      一次一个 Blender 的锁
  episodes/ep01_pantheon_paper.json   早期纸模版 ep01（已被否定的风格，留作对照）
  lookdev/               look-dev 静帧脚本（扫描外观对比、揭晓静帧）
episodes/ep01_pantheon/  完整样例：episode.json labels.json captions.json SCRIPT.md FACTS_walls.md assets.md scan_prep.json
docs/                    STANDARD.md（质量标准） PROCESS.md（流程、分工、时间、自查清单）
.claude/workflows/       arch-episode.js（Claude Code Workflow）+ README
models/ music/ out/      本地素材与产出，不入库
```

## 许可

- 代码（`kit/`、`.claude/`）：MIT，见 [LICENSE](LICENSE)。
- 文档与每集的脚本、标注、事实表（`docs/`、`episodes/`）：同样按 MIT 提供。
- 外部素材**不在仓库里**，各自保留原许可：Sketchfab 扫描为 CC BY 4.0（视频简介必须署名，文字见各集 `assets.md`），配乐为公有领域录音，Noto Sans SC 为 SIL OFL 1.1。

## 链接

- Blender：https://www.blender.org/download/
- Sketchfab 搜索 API（找 CC BY / CC0 扫描）：https://docs.sketchfab.com/data-api/v3/index.html
- ep01 室内扫描 "The Pantheon Interior" by artfletch：https://sketchfab.com/3d-models/the-pantheon-interior-5f35ab370082403e8c7829388f4e0c30
- ep01 外观对照 "Agrippa Pantheon" by Fovea：https://sketchfab.com/3d-models/agrippa-pantheon-074e9fe9154f41169cb2e79f5330e58f
- ep01 配乐（Wikimedia Commons）：https://commons.wikimedia.org/wiki/File:Air_-_Air_Force_Strings_-_United_States_Air_Force_Band.mp3
- Noto Sans SC：https://fonts.google.com/noto/specimen/Noto+Sans+SC
- 发布工具：[one-manifest-publisher](https://github.com/Neal122234/one-manifest-publisher)（一份清单发多平台）

---

## English

**Architecture Teardown** is a vertical short-video series: a famous building starts complete, is taken apart piece by piece as an exploded view, each step reveals one structure with one fact-checked label that explains what it *does*, then everything reassembles into a seamless 40 s loop (1080×1920, 24 fps, music only). Each episode is lit with one cinematic lighting preset chosen for its building (golden hour, blue hour, overcast drama, night floodlighting, morning mist, hard noon light), held for the whole episode.

This repo holds the Blender (5.2, EEVEE, headless Python) toolkit, the approved quality standard (`docs/STANDARD.md`, Chinese), the production process (`docs/PROCESS.md`), a Claude Code workflow that takes a building name to a reviewed draft (`.claude/workflows/arch-episode.js`), and episode 1 (Pantheon, Rome) as the worked example.

Quick start: see the commands above (`kit/produce.py EPISODE.json draft|final`). Models, music and renders are not committed; each episode's `assets.md` lists sources, licences and attribution. Code is MIT; external assets keep their own licences (CC BY 4.0 scans, public-domain music, OFL fonts).
