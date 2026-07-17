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

五、离线 FunASR 模型（推荐网络不稳时使用）
  主程序默认不附带语音权重（体积约 900MB）。
  本地转写（默认 FunASR / SenseVoice）需要模型，可二选一：

  【方式 1：离线模型包（推荐）】
  1. 另下：YilanChengWen-models-funasr-sensevoice.zip（与主程序版本无关）
  2. 解压后，把其中的 models 文件夹复制到 YilanChengWen.exe 同级
     （与已有 models 合并；不要多套一层目录）
  3. 确认存在：
       models\funasr\models\iic\SenseVoiceSmall\model.pt
  4. 再启动程序做转写（一般不再联网下 SenseVoice）

  【方式 2：首次转写时自动下载】
  · 需能访问 ModelScope 等源；失败则改用方式 1

  说明：仅「下载视频/字幕」不需要模型包；Whisper 为另一套可选模型。

六、第一次使用建议
  1. 设置 → 大模型：填 API Key / Base URL / 模型名
  2. 若要本地转写：按第五节放好 FunASR 模型
  3. YouTube 视频：配置 cookies，或用「补跑工具」刷新
  4. 先用「单条处理」试 1 条链接，确认 output 有结果
  5. 扩展文章类型：在 prompts\articles\ 新增 .md（含 {transcript_text}）后点刷新
  6. 更多说明与更新：https://blog.yilanapp.com/

七、常见问题
  · 杀软拦截：对绿色目录添加信任，或使用安装版
  · 启动后闪退：查看 logs\app.log
  · 提示未找到 FFmpeg：检查 ffmpeg\ffmpeg.exe 是否存在（见第四节）
  · 转写很慢 / 占内存：关闭其它程序；批量时限制条数 1～3
  · 一直在下载模型：检查 models 路径是否多套一层（见第五节）
  · 不要把 config.json（含 Key）随压缩包公开分享

八、卸载
  绿色版：直接删除整个文件夹即可
  安装版：控制面板 / 设置 → 应用 → 卸载
