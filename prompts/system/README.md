# 系统 / 基础提示词（system）

本目录存放**中间处理或辅助**模板，默认**不在 GUI 主列表展示**：

- `format.md` — ASR 净化与格式化
- `summary.md` — 通用整合重构
- `evaluation.md` — 内容评估打分

CLI 仍可用：`python transcribe.py --prompts format`

内部流水线也可能自动调用 `format` 等模板。
