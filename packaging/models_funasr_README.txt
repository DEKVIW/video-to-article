一览成文 — FunASR 离线模型包（SenseVoice）
==========================================

内容：默认语音转写引擎 FunASR / SenseVoiceSmall + 中文 VAD
体积：约 900 MB（未压缩）

────────────────────────────────────────
一、给谁用？
────────────────────────────────────────
  · 首次本地转写不想从网络自动下载模型
  · 网络访问 ModelScope / 外网不稳定
  · 用 U 盘 / 网盘把模型拷到另一台电脑

  注意：
  · 「仅下载」音视频 / 字幕 → 不需要本模型包
  · 只有用到「本地语音转写」（默认 FunASR）才需要

────────────────────────────────────────
二、解压到哪里？（最重要）
────────────────────────────────────────
  1. 先解压主程序绿色包，得到类似目录：

       D:\Apps\YilanChengWen\
         YilanChengWen.exe
         models\          ← 可能是空的，只有 README
         config.json
         ...

  2. 再解压本模型包，把里面的「models」文件夹
     整个放进上述目录，与 exe 同级。

  正确结果应类似：

       D:\Apps\YilanChengWen\
         YilanChengWen.exe
         models\
           funasr\
             models\
               iic\
                 SenseVoiceSmall\          ← 含 model.pt 等
                 speech_fsmn_vad_zh-cn-16k-common-pytorch\

  3. 若系统提示是否合并文件夹，选择「是 / 合并」。
     不要多套一层，例如下面这种是错的：

       ✗ ...\YilanChengWen\YilanChengWen-models-xxx\models\...
       ✗ ...\YilanChengWen\models\models\funasr\...

────────────────────────────────────────
三、如何确认安装成功？
────────────────────────────────────────
  检查是否存在文件（路径按你的安装目录改）：

    models\funasr\models\iic\SenseVoiceSmall\model.pt

  有该文件后，程序会优先用本地权重，一般不再联网下 SenseVoice。

────────────────────────────────────────
四、使用
────────────────────────────────────────
  1. 双击 YilanChengWen.exe
  2. 设置里填好大模型 API（成文需要；转写本身用本地 FunASR）
  3. 单条处理 / 批量：保持默认 ASR = FunASR（SenseVoice）
  4. 开始任务；日志里可看到 FunASR 缓存目录指向程序旁 models\funasr

────────────────────────────────────────
五、常见问题
────────────────────────────────────────
  · 仍在下载模型？
      → 路径多套了一层，或 model.pt 不存在；对照第二节检查
  · 只有 Whisper 相关文件？
      → 本包是 FunASR；Whisper 是另一套 models\whisper\
  · 磁盘空间：
      → 请预留约 1 GB 可用空间
  · 杀软拦截解压：
      → 对程序目录添加信任后重试

────────────────────────────────────────
六、本包包含哪些模型？
────────────────────────────────────────
  · iic/SenseVoiceSmall          主识别（默认）
  · iic/speech_fsmn_vad_zh-cn…   语音活动检测 VAD

  与程序内默认 funasr_model=sensevoice 一致。
