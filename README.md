<div align="center">

<a href="https://linux.do/" title="LINUX DO 社区">
  <img src="resources/linux-do.svg" width="88" height="88" alt="LINUX DO" />
</a>

### [LINUX&nbsp;DO](https://linux.do/)

**本项目在 [LINUX DO](https://linux.do/) 社区分享与交流** · 欢迎同好围观、反馈、吹水

[![LINUX DO](https://img.shields.io/badge/Community-LINUX%20DO-1c1c1e?style=for-the-badge&labelColor=ffb003&logoColor=white)](https://linux.do/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](./LICENSE)

</div>

---

# 一览成文 YilanChengWen

把 **在线视频 / 本地音视频** 转写为文字，并可选用大模型整理成结构化文章。

| 项 | 内容 |
| --- | --- |
| 中文名 | **一览成文** |
| 英文名 | **YilanChengWen** |
| Python 包 | `video_to_article` |
| 许可证 | [MIT](./LICENSE) |
| 版本 | 见 `src/video_to_article/__init__.py` |
| 作者博客 | [blog.yilanapp.com](https://blog.yilanapp.com/) |

## 能做什么

- 多平台链接下载（B 站 / YouTube / 抖音 / 小红书 / 微博等，能力随 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 更新）
- 本地音频、视频直接转写
- 默认本地 ASR（FunASR SenseVoice），可选 Whisper
- 大模型按**提示词模板**生成成稿；也可仅下载、不转写
- 桌面 GUI（单条 / 批量 / B 站搜索 / 仅下载 / 补跑工具）

### 成稿类型由提示词决定（重点）

**产出的文章形态完全取决于你配置的提示词**，可高度自定义：

| 目录 | 作用 |
| --- | --- |
| `prompts/articles/` | 成稿模板（GUI 下拉可选） |
| `prompts/system/` | 系统基础提示（默认不在界面展示） |

- **默认模板** `snack_recipe`：面向**美食视频**，整理成食谱向结构
- 你可按视频类型自行新增 `.md` 模板（教程、访谈、评测、科普……），无需改代码
- 不同模板 = 不同文章结构与语气；扩展方式就是往 `prompts/articles/` 加文件

## 环境要求

- Windows 10/11（GUI 与打包脚本按 Windows 编写；CLI 也可在其他系统开发）
- Python **3.10+**（推荐 3.12）
- **FFmpeg**（开发环境可装系统版；绿色包可内置 `ffmpeg/`）

## 软件下载与离线模型（弱网推荐）

若不便从源码构建，或网络不稳定，可用预编译绿色包 + FunASR 语音模型。

链接：https://pan.quark.cn/s/6971a6e70b44

说明：

- 分享内容面向 **弱网 / 不便联网下模型** 的场景，含 **软件本体** 与 **转写用语音模型**（体积较大）。
- 也可在 GitHub [Releases](https://github.com/DEKVIW/video-to-article/releases) 下载对应版本的主程序 zip；模型包较大时，弱网优先用网盘。

### 解压建议

| 程序解压位置 | 建议 | 模型默认位置 |
| --- | --- | --- |
| **纯英文路径**（如 `D:\Apps\YilanChengWen\`） | **强烈推荐** | 程序旁 `models\funasr\` |
| **含中文路径**（如 `…\我的项目\…`） | 能运行，但不理想 | 不会用中文路径当「可靠加载路径」，见下表 |

底层 FunASR / SentencePiece 对 **含中文的模型文件路径** 兼容差，程序会尽量把缓存放到 **纯英文路径**。

### 离线模型怎么放

1. 解压绿色包到目标目录，双击 `YilanChengWen.exe`。
2. 解压模型包，将其中的 **`models` 文件夹** 合并到 `YilanChengWen.exe` **同级**（不要多套一层目录）。
3. 确认存在：

   `models\funasr\models\iic\SenseVoiceSmall\model.pt`

4. 仅「下载视频 / 字幕」、不做本地转写时，**不需要**语音模型。

| 场景 | 能否直接用 |
| --- | --- |
| 程序在 **英文路径**，模型在 exe 同级 `models\funasr\` | ✅ 标准用法 |
| 程序在中文路径，模型放到同盘 **`盘符:\YilanChengWenData\models\funasr\`** | ✅ 与自动策略一致（路径须为纯英文） |
| 设置 → 转写 →「FunASR 模型目录」填 **纯英文** 路径 | ✅ 自定义优先 |

**中文路径下不要默认「拷到程序同级就一定能读」**；最省事仍是：程序解压到英文目录 + 模型合并到 exe 旁。

### 模型实际落在哪

- **英文程序路径**：`程序目录\models\funasr\`
- **中文程序路径**（自动避开中文路径加载）：
  - 优先：同盘 `盘符:\YilanChengWenData\models\funasr\`
  - 回退：`%LOCALAPPDATA%\YilanChengWen\models\funasr\`
- **自定义**：设置中的「FunASR 模型目录」或环境变量 `YILAN_FUNASR_DIR` / `VQE_FUNASR_DIR`（须纯英文）
- 运行日志里「FunASR/ModelScope 模型缓存目录」= 本次实际使用的目录

首次联网转写也会把模型下到上述缓存位置（约 1GB 级磁盘）。

## 本地环境启动

在项目根目录 PowerShell：

```powershell
# 1. 虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip

# 2. 安装本包 + GUI 依赖
pip install -e ".[gui]"
# 或：pip install -r requirements.txt
#     pip install "PySide6>=6.6" "PySide6-Fluent-Widgets>=1.6"

# 3. 配置（勿把含密钥的 config.json 提交到 Git）
copy config.example.json config.json
# 编辑 config.json：填入 LLM API Key 等

# 4. 启动 GUI
python gui_app.py
# 或
.\run_gui.bat
# 或
python -m video_to_article.gui
```

命令行入口（可选）：

```powershell
python transcribe.py --help
# 可编辑安装后也可：
# video-to-article --help
```

> 首次本地转写会下载 FunASR 模型（体积较大）。开发与绿色版均可使用离线模型包；放置规则见上文「绿色版下载与离线模型」。建议项目/程序路径尽量使用纯英文。

## 打包构建

```powershell
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_gui_onedir.ps1
```

本地产物（默认 **不进 Git**，见 `.gitignore`）：

| 路径 | 说明 |
| --- | --- |
| `dist/YilanChengWen/` | 最新可运行目录 |
| `dist/releases/YilanChengWen-x.y.z.zip` | 对外分发主程序 zip（一般不含语音大模型权重） |
| `dist/releases/YilanChengWen-models-funasr-sensevoice.zip` | 可选：离线 FunASR 模型（需另打） |

```powershell
# 仅打 FunASR 离线模型包（可选）
python packaging/make_models_funasr_zip.py
```

用户：解压主程序 zip → 双击 `YilanChengWen.exe`；需要离线转写时按上文合并 `models`（注意英文/中文路径差异）。

## 源码结构

```text
.
├── src/video_to_article/   # 核心包（下载 / 转写 / 成稿 / GUI）
├── prompts/                # 提示词（articles 成稿 + system 基础）
├── packaging/              # PyInstaller / 元数据 / 入口
├── scripts/                # 打包脚本
├── resources/              # 图标、社区徽章资源
├── config.example.json     # 配置示例
├── gui_app.py              # 开发启动 GUI
├── transcribe.py           # 开发启动 CLI
├── pyproject.toml
├── LICENSE
└── README.md
```

**不会**进入版本库的内容（见 `.gitignore`）：`.venv/`、`build/`、`dist/`、`docs/`、`data/`、`models/`、`output/`、`logs/`、个人 `config.json`、大体积 FFmpeg 二进制等。

## 技术栈

- Python 3.10+ · yt-dlp · FunASR / faster-whisper
- LLM：OpenAI / Anthropic 兼容接口
- GUI：PySide6 · QFluentWidgets
- 打包：PyInstaller（onedir）

## 免责声明

请仅处理你有权使用的音视频内容，并遵守各平台服务条款与当地法律法规。下载、转写与二次创作后果由使用者自行承担。

## 社区与反馈

- 社区讨论：[LINUX DO](https://linux.do/)
- 博客：[blog.yilanapp.com](https://blog.yilanapp.com/)

欢迎 Issue / PR。较大改动建议先开 Issue。提交前请确认未包含 API Key、`config.json`、个人音视频与 `dist/`。

## License

[MIT License](./LICENSE) © 2026 一览成文 YilanChengWen contributor(s)
