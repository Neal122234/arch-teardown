# Workflows

## arch-episode — 做一集名建筑拆解（到草稿为止）

`arch-episode.js` 是 Claude Code 的 Workflow 脚本。它按 [docs/PROCESS.md](../../docs/PROCESS.md) 第 1–7 步把一座建筑做成 540×960 草稿（带标注、字幕、配乐），每个 agent 的提示词都要求先读 [docs/STANDARD.md](../../docs/STANDARD.md) 和 PROCESS.md。

| 阶段 | 做什么 |
|---|---|
| Research | 两个 agent 并行：① 查证 + `SCRIPT.md` + `labels.json` + `captions.json`（事实表带来源）；② 模型方案：用 Sketchfab 公共 API 搜 CC BY / CC0 可下载的扫描，列候选和下载链接，定哪些部件复用、哪些新写，写 `assets.md`；按建筑选**一个**光影预设（材质、环境、性格、故事），写明理由和这座建筑在护栏上的风险 |
| Geometry | 如已下载扫描：压贴图 + `import_scan.py prep`；写 `build_<key>.py`（带拆解 meta）；`episode.json` 用选定的预设（换掉 ep01 的光影和调色），渲完整建筑的定机位静帧并自查；`SCRIPT.md` 写"光影"一行 |
| Episode | `episode.json`：铰链、拆解时间表、镜头、锚点与标签位置、场地、音乐，全集一个光影预设；静帧循环直到每个节拍清楚、无闪烁、循环接得上，钩子帧过光影护栏 |
| Draft | `kit/produce.py … draft`（帧 + 锚点 + 叠字 + 配乐），再由另一个 agent 按 PROCESS.md 第 9 节做只看客观项的检查；有必改项就修一轮再复查 |
| Report | 一段不超过 15 行的中文汇报：草稿路径、光影预设和理由、待下载模型表、没过的检查项、下一步 |

定稿 1080p 不在工作流里：用户看过草稿再跑 `python3 kit/produce.py episodes/<slug>/episode.json final`（PROCESS.md 第 8 节）。

### 怎么跑

在 Claude Code 里（仓库目录下，或把 `repo` 传进去），让 Claude 调用 Workflow 工具：

```
Workflow({ name: "arch-episode",
           args: { building: "Hagia Sophia, Istanbul", slug: "ep02_hagia_sophia" } })
```

也可以直接说"用 arch-episode 做下一集：圣索菲亚大教堂，slug ep02_hagia_sophia"。

| 参数 | 必填 | 说明 |
|---|---|---|
| `building` | 是 | 建筑名（中英文都行，越具体越好：名字 + 城市） |
| `slug` | 是 | `epNN_英文名`，决定目录 `episodes/<slug>/`；模型目录是去掉 `epNN_` 的部分：`models/hagia_sophia/` |
| `style` | 否 | `real`（默认，标准做法）或 `paper`（用户否定过，只作对照） |
| `repo` | 否 | 仓库路径，默认 `~/claude-projects/arch-teardown-kit` |

如果项目级工作流没有被发现（名字列表里没有 `arch-episode`），用脚本路径跑：
`Workflow({ scriptPath: "<repo>/.claude/workflows/arch-episode.js", args: {...} })`。

### 中断与续跑

工作流被打断（比如要等用户下载模型）后，用 `Workflow({ scriptPath, resumeFromRunId: "<runId>", args: {...} })` 续跑，已经完成的 agent 走缓存。
模型还没下载时，Research 阶段会把下载表放进汇报；Geometry 阶段先用自建几何做完整片，用户下载后再跑一次 Geometry 之后的阶段（或手动按 PROCESS.md 第 4 步导入扫描）。

### 注意

- Blender 一次只开一个（`kit/blender_locked.sh`），所以 Research 之后的阶段是串行的；多集可以先并行跑多个 Research，再排队渲染。
- 工作流不会替用户登录任何网站、不会下载 Sketchfab 模型、不会发布视频；这些都在汇报里交给用户。
