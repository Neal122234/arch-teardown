# ep01 罗马万神殿 · 外部素材

模型和音乐不入库（`.gitignore`：`models/`、`music/`），按下表取回，放到对应路径（或用 `ARCH_KIT_MODELS` / `ARCH_KIT_MUSIC` 指到别处）。

## 3D 扫描（Sketchfab，CC BY 4.0，需要在视频简介里署名）

| 用途 | 模型 | 作者 | 许可 | 保存为 |
|---|---|---|---|---|
| 室内揭晓（藻井、圆厅、天眼光柱）——**成片使用** | [The Pantheon Interior](https://sketchfab.com/3d-models/the-pantheon-interior-5f35ab370082403e8c7829388f4e0c30)（约 1.0M 面，3 张 8K 贴图） | [artfletch](https://sketchfab.com/artfletch) | [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) | `models/pantheon/the_pantheon_interior.glb` |
| 外观比例对照（成片未用，用户选了自建外观） | [Agrippa Pantheon](https://sketchfab.com/3d-models/agrippa-pantheon-074e9fe9154f41169cb2e79f5330e58f)（约 669k 面，2 张 4K 贴图） | [Fovea (3dfovea)](https://sketchfab.com/3dfovea) | [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) | `models/pantheon/agrippa_pantheon.glb` |

**取回**：用户登录 Sketchfab，在模型页点 Download → glTF（`.glb`），存到上面的路径。之后：

```bash
python3 kit/import_scan.py downscale models/pantheon/the_pantheon_interior.glb models/pantheon/the_pantheon_interior_4k.glb --size 4096
kit/blender_locked.sh -b --factory-startup -P kit/import_scan.py -- prep episodes/ep01_pantheon/scan_prep.json
# -> models/pantheon/interior_prepped.blend (+ .json)，episode.json 的 scan.blend 指向它
# 对照用的外观扫描同样先压贴图：
python3 kit/import_scan.py downscale models/pantheon/agrippa_pantheon.glb models/pantheon/agrippa_pantheon_2k.glb --size 2048
```

## 音乐（公有领域）

| 曲目 | 演奏 | 许可 | 来源 | 保存为 |
|---|---|---|---|---|
| J. S. Bach, *Air*（《G 弦上的咏叹调》，BWV 1068） | United States Air Force Band — Air Force Strings | 公有领域（美国联邦政府作品） | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Air_-_Air_Force_Strings_-_United_States_Air_Force_Band.mp3) | `music/bach_air_usaf.mp3` |

```bash
mkdir -p music && curl -L -o music/bach_air_usaf.mp3 \
  "https://upload.wikimedia.org/wikipedia/commons/e/ec/Air_-_Air_Force_Strings_-_United_States_Air_Force_Band.mp3"
```
用法（`episode.json` 的 `music`）：从 4.2 s 起取 40 s，0.3 s 淡入，最后 2.7 s 淡出，−14 LUFS。

## 字体

- 标签与字幕：Noto Sans SC Bold / Medium / Black（SIL OFL 1.1），放在 `~/Library/Fonts` 或 `ARCH_KIT_FONTS`。下载：https://fonts.google.com/noto/specimen/Noto+Sans+SC
- 檐壁铭文：Times New Roman（macOS 系统字体；其他系统用 `ARCH_KIT_SERIF` 指定一个衬线字体）。

## 视频简介里的署名（复制即用）

```
室内三维扫描："The Pantheon Interior" by artfletch (https://sketchfab.com/artfletch)，CC BY 4.0，https://sketchfab.com/3d-models/the-pantheon-interior-5f35ab370082403e8c7829388f4e0c30
配乐：巴赫《G 弦上的咏叹调》BWV 1068，美国空军乐队弦乐团（United States Air Force Band, Air Force Strings）演奏，公有领域，来源 Wikimedia Commons
建筑外观为自建三维模型。事实来源：Britannica、Wikipedia、Mark & Hutchinson 1986、Lancaster 2006、Martines 2015
```
外观对照扫描（Agrippa Pantheon by Fovea）没有出现在成片里，不需要署名；如果以后的版本用到它，加一行：`"Agrippa Pantheon" by Fovea (https://sketchfab.com/3dfovea)，CC BY 4.0`。
