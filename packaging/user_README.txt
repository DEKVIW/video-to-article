一览成文（YilanChengWen）— 桌面版使用说明
==========================================

一、这是什么？
  视频转写 · 多类型文章模板 · 可选封面。
  把视频/本地音视频整理成可发布的结构化文章（默认含美食教程模板，可扩展）。

二、怎么用？（不需要“安装到系统”也可以）

  【方式 A：绿色版（推荐，免安装）】
  1. 解压整个文件夹到任意位置（如 D:\Apps\YilanChengWen）
  2. 双击  YilanChengWen.exe  启动
  3. 首次打开后，用「设置」填写大模型 API Key 等
  4. 粘贴视频链接，选择文章模板（下拉），点「开始」

  【方式 B：安装版】
  1. 双击  YilanChengWen-Setup.exe  安装
  2. 按向导完成（可选桌面快捷方式）
  3. 从开始菜单或桌面图标启动
  4. 同样在「设置」里填 API Key

三、程序旁边有哪些重要文件夹？
  config.json             你的密钥与默认配置（勿公开分享）
  config.example.json     配置模板
  prompts\articles\       成稿文章模板（GUI 下拉只显示这里）
  prompts\system\         系统基础提示词（默认不在 GUI 展示）
  data\                   下载缓存、cookies、清单
  output\                 生成的文章与结果
  models\                 语音模型（默认不随主程序；见下方离线模型）
  logs\                   日志
  ffmpeg\                 自带 ffmpeg.exe / ffprobe.exe（优先使用）

四、FFmpeg（音视频处理）
  正式绿色包一般已自带：程序目录\ffmpeg\ffmpeg.exe 与 ffprobe.exe
  程序优先使用该目录，无需再安装系统 FFmpeg。

  若该目录为空或缺失：
  · 将 ffmpeg.exe、ffprobe.exe 拷入程序旁的 ffmpeg\ 文件夹，或
  · 自行安装系统 FFmpeg 并加入 PATH

五、FunASR 语音模型放在哪？（重要）
  主程序默认不附带语音权重（约 900MB 级）。仅「下载视频/字幕」不需要模型。
  本地转写（默认 FunASR / SenseVoice）需要模型。

  【强烈建议】把程序解压到纯英文路径，例如：
       D:\Apps\YilanChengWen\
  不要放在含中文的路径（如「我的项目」「下载」等），避免模型加载异常。

  【模型实际存储位置 — 自动规则】
  · 程序在纯英文路径时：
       程序目录\models\funasr\
       例：D:\Apps\YilanChengWen\models\funasr\
  · 程序路径含中文时（自动避开中文路径）：
       优先：与程序同盘的  盘符:\YilanChengWenData\models\funasr\
       例：程序在 F:\中文\... 则用  F:\YilanChengWenData\models\funasr\
       若无法使用同盘，才回退到用户目录：
       %LOCALAPPDATA%\YilanChengWen\models\funasr\
       （在资源管理器地址栏输入 %LOCALAPPDATA%\YilanChengWen 可打开）
  · 日志中「FunASR/ModelScope 模型缓存目录」一行 = 本次实际使用的目录。

  【方式 1：离线模型包（弱网推荐）】
  1. 另下：YilanChengWen-models-funasr-sensevoice.zip（与主程序版本无关）
  2. 解压后，把其中的 models 文件夹复制到 YilanChengWen.exe 同级并合并
  3. 确认存在：
       models\funasr\models\iic\SenseVoiceSmall\model.pt
  4. 若程序在中文路径下，也可把上述 funasr 目录整夹拷到
       盘符:\YilanChengWenData\models\funasr\  或设置里的自定义目录

  【方式 2：首次转写时自动下载】
  · 需能访问 ModelScope；模型会下到上面的「缓存目录」
  · 首次较慢、约占约 1GB 磁盘

  【方式 3：自定义模型目录（可选）】
  · 设置 → 转写 →「FunASR 模型目录」
    填写纯英文路径，例如：
       E:\AI-Models\YilanChengWen\funasr
  · 或设置环境变量（高级）：
       VQE_FUNASR_DIR  或  YILAN_FUNASR_DIR
  · 自定义目录优先于自动规则；目录须为纯英文（无中文）

  说明：Whisper 为另一套可选模型，缓存在 models\whisper\。

六、第一次使用建议
  1. 设置 → 大模型：填 API Key / Base URL / 模型名
  2. 若要本地转写：按第五节准备 FunASR 模型（或允许首次联网下载）
  3. YouTube 视频：配置 cookies，或用「补跑工具」刷新
  4. 先用「单条处理」试 1 条链接，确认 output 有结果
  5. 扩展文章类型：在 prompts\articles\ 新增 .md（含 {transcript_text}）后点刷新
  6. 更多说明与更新：https://blog.yilanapp.com/

七、常见问题
  · 杀软拦截：对绿色目录添加信任，或使用安装版
  · 启动后闪退：查看 logs\app.log
  · 提示未找到 FFmpeg：检查 ffmpeg\ffmpeg.exe 是否存在（见第四节）
  · 转写很慢 / 占内存：关闭其它程序；批量时限制条数 1～3
  · 一直在下载模型：检查 models 是否多套一层；或看日志中的缓存目录
  · C 盘空间紧张：把程序放到 D/E 盘英文路径，或在设置中指定其它盘的模型目录
  · 不要把 config.json（含 Key）随压缩包公开分享

八、卸载
  绿色版：删除程序文件夹；若用过自动/自定义模型目录，可一并删除
    程序旁 models\、同盘 YilanChengWenData\、或
    %LOCALAPPDATA%\YilanChengWen\
  安装版：控制面板 / 设置 → 应用 → 卸载
