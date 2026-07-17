"""Settings dialog — full config coverage for Phase C."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...config import deep_update, load_config, save_config


def _scroll_page(inner: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    return scroll


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("一览成文 — 设置")
        self.resize(640, 560)
        self._config: dict[str, Any] = {}

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self._build_llm_tab()
        self._build_transcribe_tab()
        self._build_youtube_tab()
        self._build_cover_tab()
        self._build_host_tab()

        note = QLabel("设置写入项目根目录 config.json。密钥仅保存在本机，请勿提交到 Git。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        root.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.load_from_disk()

    def _build_llm_tab(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.llm_provider = QLineEdit()
        self.llm_api_key = QLineEdit()
        self.llm_api_key.setEchoMode(QLineEdit.Password)
        self.llm_base_url = QLineEdit()
        self.llm_model = QLineEdit()
        self.llm_temperature = QLineEdit()
        self.llm_max_tokens = QSpinBox()
        self.llm_max_tokens.setRange(256, 128000)
        self.llm_timeout = QSpinBox()
        self.llm_timeout.setRange(10, 3600)
        self.llm_retries = QSpinBox()
        self.llm_retries.setRange(0, 20)
        form.addRow("Provider", self.llm_provider)
        form.addRow("API Key", self.llm_api_key)
        form.addRow("Base URL", self.llm_base_url)
        form.addRow("Model", self.llm_model)
        form.addRow("Temperature", self.llm_temperature)
        form.addRow("Max tokens", self.llm_max_tokens)
        form.addRow("超时(秒)", self.llm_timeout)
        form.addRow("重试次数", self.llm_retries)
        self.tabs.addTab(_scroll_page(page), "大模型")

    def _build_transcribe_tab(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.tr_engine = QComboBox()
        self.tr_engine.addItem("funasr", "funasr")
        self.tr_engine.addItem("whisper", "whisper")
        self.tr_funasr = QLineEdit()
        self.tr_model_size = QComboBox()
        for size in ("tiny", "base", "small"):
            self.tr_model_size.addItem(size, size)
        self.tr_threads = QSpinBox()
        self.tr_threads.setRange(1, 64)
        self.tr_auto = QCheckBox("auto_optimize（配置字段，供兼容）")
        form.addRow("默认 ASR 引擎", self.tr_engine)
        form.addRow("FunASR 模型", self.tr_funasr)
        form.addRow("Whisper 大小", self.tr_model_size)
        form.addRow("CPU 线程", self.tr_threads)
        form.addRow(self.tr_auto)
        tip = QLabel("工作台「高级 ASR」勾选后可覆盖本次运行；此处为默认值。")
        tip.setWordWrap(True)
        form.addRow(tip)
        self.tabs.addTab(_scroll_page(page), "转写")

    def _build_youtube_tab(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.yt_browser = QComboBox()
        self.yt_browser.addItem("（空）", "")
        for name in ("chrome", "edge", "firefox"):
            self.yt_browser.addItem(name, name)
        self.yt_cookies_file = QLineEdit()
        self.yt_po_token = QLineEdit()
        form.addRow("默认从浏览器读 cookies", self.yt_browser)
        form.addRow("默认 cookies 文件", self.yt_cookies_file)
        form.addRow("PO Token", self.yt_po_token)
        tip = QLabel("工作台里的 Cookies 选项会覆盖这里的默认值。")
        tip.setWordWrap(True)
        form.addRow(tip)
        self.tabs.addTab(_scroll_page(page), "YouTube / 下载")

    def _build_cover_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)

        base = QGroupBox("基础开关与服务")
        form = QFormLayout(base)
        self.cover_enable = QCheckBox("启用 AI 封面流水线")
        self.cover_generate = QCheckBox("调用生图 API")
        self.cover_export = QCheckBox("导出封面提示词文件")
        self.cover_generate.setChecked(True)
        self.cover_export.setChecked(True)
        self.cover_provider = QLineEdit()
        self.cover_base_url = QLineEdit()
        self.cover_api_key = QLineEdit()
        self.cover_api_key.setEchoMode(QLineEdit.Password)
        self.cover_model = QLineEdit()
        self.cover_edit_model = QLineEdit()
        self.cover_mode = QLineEdit()
        self.cover_size = QLineEdit()
        self.cover_format = QLineEdit()
        self.cover_brand = QLineEdit()
        form.addRow(self.cover_enable)
        form.addRow(self.cover_generate)
        form.addRow(self.cover_export)
        form.addRow("Provider", self.cover_provider)
        form.addRow("Base URL", self.cover_base_url)
        form.addRow("API Key", self.cover_api_key)
        form.addRow("Model", self.cover_model)
        form.addRow("Edit model", self.cover_edit_model)
        form.addRow("mode", self.cover_mode)
        form.addRow("size", self.cover_size)
        form.addRow("output_format", self.cover_format)
        form.addRow("brand", self.cover_brand)
        layout.addWidget(base)

        flags = QGroupBox("参考图与策略")
        ff = QFormLayout(flags)
        self.cover_use_ref = QCheckBox("use_reference_image")
        self.cover_enable_edit = QCheckBox("enable_image_edit")
        self.cover_send_b64 = QCheckBox("send_local_reference_as_base64")
        self.cover_fallback_t2i = QCheckBox("fallback_to_text_to_image")
        self.cover_use_model_url = QCheckBox("use_model_output_url_in_frontmatter")
        self.cover_force_t2i = QCheckBox("force_text_to_image_for_noisy_thumbnail")
        self.cover_openai_edit = QLineEdit()
        self.cover_ref_url = QLineEdit()
        for w in (
            self.cover_use_ref,
            self.cover_enable_edit,
            self.cover_send_b64,
            self.cover_fallback_t2i,
            self.cover_use_model_url,
            self.cover_force_t2i,
        ):
            ff.addRow(w)
        ff.addRow("openai_edit_strategy", self.cover_openai_edit)
        ff.addRow("reference_image_url", self.cover_ref_url)
        layout.addWidget(flags)

        text = QGroupBox("风格文案")
        tf = QFormLayout(text)
        self.cover_style = QPlainTextEdit()
        self.cover_style.setMinimumHeight(90)
        self.cover_negative = QPlainTextEdit()
        self.cover_negative.setMinimumHeight(90)
        tf.addRow("style", self.cover_style)
        tf.addRow("negative_prompt", self.cover_negative)
        layout.addWidget(text)

        timeouts = QGroupBox("超时与轮询（高级）")
        timeouts.setCheckable(True)
        timeouts.setChecked(False)
        to = QFormLayout(timeouts)
        self.cover_submit_to = QSpinBox()
        self.cover_submit_to.setRange(10, 3600)
        self.cover_download_to = QSpinBox()
        self.cover_download_to.setRange(10, 3600)
        self.cover_poll_to = QSpinBox()
        self.cover_poll_to.setRange(10, 3600)
        self.cover_poll_interval = QSpinBox()
        self.cover_poll_interval.setRange(1, 120)
        self.cover_max_wait = QSpinBox()
        self.cover_max_wait.setRange(30, 7200)
        to.addRow("submit_timeout_seconds", self.cover_submit_to)
        to.addRow("download_timeout_seconds", self.cover_download_to)
        to.addRow("poll_timeout_seconds", self.cover_poll_to)
        to.addRow("poll_interval_seconds", self.cover_poll_interval)
        to.addRow("max_wait_seconds", self.cover_max_wait)
        layout.addWidget(timeouts)
        self.cover_timeouts_box = timeouts

        pre = QGroupBox("参考图预处理阈值（高级）")
        pre.setCheckable(True)
        pre.setChecked(False)
        pf = QFormLayout(pre)
        self.cover_enable_pre = QCheckBox("enable_reference_preprocess")
        self.cover_text_thr = QDoubleSpinBox()
        self.cover_text_thr.setDecimals(3)
        self.cover_text_thr.setRange(0, 10)
        self.cover_min_food = QDoubleSpinBox()
        self.cover_min_food.setDecimals(3)
        self.cover_min_food.setRange(0, 1)
        self.cover_crop_food = QDoubleSpinBox()
        self.cover_crop_food.setDecimals(3)
        self.cover_crop_food.setRange(0, 1)
        self.cover_crop_top = QDoubleSpinBox()
        self.cover_crop_top.setDecimals(3)
        self.cover_crop_top.setRange(0, 1)
        self.cover_crop_bottom = QDoubleSpinBox()
        self.cover_crop_bottom.setDecimals(3)
        self.cover_crop_bottom.setRange(0, 1)
        pf.addRow(self.cover_enable_pre)
        pf.addRow("reference_text_score_threshold", self.cover_text_thr)
        pf.addRow("reference_min_food_score", self.cover_min_food)
        pf.addRow("reference_crop_min_food_score", self.cover_crop_food)
        pf.addRow("reference_crop_top_ratio", self.cover_crop_top)
        pf.addRow("reference_crop_bottom_ratio", self.cover_crop_bottom)
        layout.addWidget(pre)
        self.cover_pre_box = pre
        layout.addStretch(1)
        self.tabs.addTab(_scroll_page(page), "AI 封面")

    def _build_host_tab(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.host_enable = QCheckBox("启用图床上传")
        self.host_provider = QLineEdit()
        self.host_api_url = QLineEdit()
        self.host_token = QLineEdit()
        self.host_token.setEchoMode(QLineEdit.Password)
        self.host_token_field = QLineEdit()
        self.host_file_field = QLineEdit()
        self.host_url_path = QLineEdit()
        self.host_timeout = QSpinBox()
        self.host_timeout.setRange(10, 3600)
        self.host_extra = QPlainTextEdit()
        self.host_extra.setPlaceholderText('JSON 对象，例如 {"album":"food"}')
        self.host_extra.setMaximumHeight(100)
        form.addRow(self.host_enable)
        form.addRow("Provider", self.host_provider)
        form.addRow("API URL", self.host_api_url)
        form.addRow("Token", self.host_token)
        form.addRow("token_field", self.host_token_field)
        form.addRow("file_field", self.host_file_field)
        form.addRow("url_json_path", self.host_url_path)
        form.addRow("timeout_seconds", self.host_timeout)
        form.addRow("extra_fields (JSON)", self.host_extra)
        self.tabs.addTab(_scroll_page(page), "图床")

    def load_from_disk(self) -> None:
        self._config = load_config() or {}
        llm = self._config.get("llm") or {}
        self.llm_provider.setText(str(llm.get("provider", "")))
        self.llm_api_key.setText(str(llm.get("api_key", "")))
        self.llm_base_url.setText(str(llm.get("base_url", "")))
        self.llm_model.setText(str(llm.get("model", "")))
        self.llm_temperature.setText(str(llm.get("temperature", "0.3")))
        self.llm_max_tokens.setValue(int(llm.get("max_tokens") or 12000))
        self.llm_timeout.setValue(int(llm.get("timeout_seconds") or 180))
        self.llm_retries.setValue(int(llm.get("max_retries") or 3))

        tr = self._config.get("transcribe") or {}
        idx = self.tr_engine.findData(str(tr.get("asr_engine") or "funasr"))
        self.tr_engine.setCurrentIndex(idx if idx >= 0 else 0)
        self.tr_funasr.setText(str(tr.get("funasr_model") or "sensevoice"))
        sidx = self.tr_model_size.findData(str(tr.get("model_size") or "tiny"))
        self.tr_model_size.setCurrentIndex(sidx if sidx >= 0 else 0)
        self.tr_threads.setValue(int(tr.get("cpu_threads") or 4))
        self.tr_auto.setChecked(bool(tr.get("auto_optimize", True)))

        yt = self._config.get("youtube") or {}
        browser = str(yt.get("cookies_from_browser") or "")
        idx = self.yt_browser.findData(browser)
        self.yt_browser.setCurrentIndex(idx if idx >= 0 else 0)
        self.yt_cookies_file.setText(str(yt.get("cookies_file") or ""))
        self.yt_po_token.setText(str(yt.get("po_token") or ""))

        cover = self._config.get("ai_cover") or {}
        self.cover_enable.setChecked(bool(cover.get("enable")))
        self.cover_generate.setChecked(bool(cover.get("generate_image", True)))
        self.cover_export.setChecked(bool(cover.get("export_prompt", True)))
        self.cover_provider.setText(str(cover.get("provider") or ""))
        self.cover_base_url.setText(str(cover.get("base_url") or ""))
        self.cover_api_key.setText(str(cover.get("api_key") or ""))
        self.cover_model.setText(str(cover.get("model") or ""))
        self.cover_edit_model.setText(str(cover.get("edit_model") or ""))
        self.cover_mode.setText(str(cover.get("mode") or "auto"))
        self.cover_size.setText(str(cover.get("size") or "1344x768"))
        self.cover_format.setText(str(cover.get("output_format") or "jpg"))
        self.cover_brand.setText(str(cover.get("brand") or ""))
        self.cover_use_ref.setChecked(bool(cover.get("use_reference_image", True)))
        self.cover_enable_edit.setChecked(bool(cover.get("enable_image_edit", True)))
        self.cover_send_b64.setChecked(bool(cover.get("send_local_reference_as_base64", True)))
        self.cover_fallback_t2i.setChecked(bool(cover.get("fallback_to_text_to_image", True)))
        self.cover_use_model_url.setChecked(bool(cover.get("use_model_output_url_in_frontmatter", False)))
        self.cover_force_t2i.setChecked(bool(cover.get("force_text_to_image_for_noisy_thumbnail", False)))
        self.cover_openai_edit.setText(str(cover.get("openai_edit_strategy") or "auto"))
        self.cover_ref_url.setText(str(cover.get("reference_image_url") or ""))
        self.cover_style.setPlainText(str(cover.get("style") or ""))
        self.cover_negative.setPlainText(str(cover.get("negative_prompt") or ""))
        self.cover_submit_to.setValue(int(cover.get("submit_timeout_seconds") or 300))
        self.cover_download_to.setValue(int(cover.get("download_timeout_seconds") or 180))
        self.cover_poll_to.setValue(int(cover.get("poll_timeout_seconds") or 120))
        self.cover_poll_interval.setValue(int(cover.get("poll_interval_seconds") or 5))
        self.cover_max_wait.setValue(int(cover.get("max_wait_seconds") or 600))
        self.cover_enable_pre.setChecked(bool(cover.get("enable_reference_preprocess", True)))
        self.cover_text_thr.setValue(float(cover.get("reference_text_score_threshold") or 1.25))
        self.cover_min_food.setValue(float(cover.get("reference_min_food_score") or 0.38))
        self.cover_crop_food.setValue(float(cover.get("reference_crop_min_food_score") or 0.42))
        self.cover_crop_top.setValue(float(cover.get("reference_crop_top_ratio") or 0.18))
        self.cover_crop_bottom.setValue(float(cover.get("reference_crop_bottom_ratio") or 0.18))

        host = self._config.get("image_host") or {}
        self.host_enable.setChecked(bool(host.get("enable")))
        self.host_provider.setText(str(host.get("provider") or ""))
        self.host_api_url.setText(str(host.get("api_url") or ""))
        self.host_token.setText(str(host.get("token") or ""))
        self.host_token_field.setText(str(host.get("token_field") or "token"))
        self.host_file_field.setText(str(host.get("file_field") or "image"))
        self.host_url_path.setText(str(host.get("url_json_path") or "url"))
        self.host_timeout.setValue(int(host.get("timeout_seconds") or 180))
        extra = host.get("extra_fields") or {}
        try:
            self.host_extra.setPlainText(json.dumps(extra, ensure_ascii=False, indent=2) if extra else "{}")
        except (TypeError, ValueError):
            self.host_extra.setPlainText("{}")

    def _collect_updates(self) -> dict[str, Any]:
        try:
            temperature = float(self.llm_temperature.text().strip() or "0.3")
        except ValueError:
            temperature = 0.3
        try:
            extra_fields = json.loads(self.host_extra.toPlainText().strip() or "{}")
            if not isinstance(extra_fields, dict):
                raise ValueError("extra_fields 必须是 JSON 对象")
        except json.JSONDecodeError as exc:
            raise ValueError(f"图床 extra_fields JSON 无效: {exc}") from exc

        return {
            "llm": {
                "provider": self.llm_provider.text().strip(),
                "api_key": self.llm_api_key.text().strip(),
                "base_url": self.llm_base_url.text().strip(),
                "model": self.llm_model.text().strip(),
                "temperature": temperature,
                "max_tokens": self.llm_max_tokens.value(),
                "timeout_seconds": self.llm_timeout.value(),
                "max_retries": self.llm_retries.value(),
            },
            "transcribe": {
                "asr_engine": self.tr_engine.currentData() or "funasr",
                "funasr_model": self.tr_funasr.text().strip() or "sensevoice",
                "model_size": self.tr_model_size.currentData() or "tiny",
                "cpu_threads": self.tr_threads.value(),
                "auto_optimize": self.tr_auto.isChecked(),
            },
            "youtube": {
                "cookies_from_browser": self.yt_browser.currentData() or "",
                "cookies_file": self.yt_cookies_file.text().strip(),
                "po_token": self.yt_po_token.text().strip(),
            },
            "ai_cover": {
                "enable": self.cover_enable.isChecked(),
                "generate_image": self.cover_generate.isChecked(),
                "export_prompt": self.cover_export.isChecked(),
                "provider": self.cover_provider.text().strip(),
                "base_url": self.cover_base_url.text().strip(),
                "api_key": self.cover_api_key.text().strip(),
                "model": self.cover_model.text().strip(),
                "edit_model": self.cover_edit_model.text().strip(),
                "mode": self.cover_mode.text().strip() or "auto",
                "size": self.cover_size.text().strip() or "1344x768",
                "output_format": self.cover_format.text().strip() or "jpg",
                "brand": self.cover_brand.text().strip(),
                "use_reference_image": self.cover_use_ref.isChecked(),
                "enable_image_edit": self.cover_enable_edit.isChecked(),
                "send_local_reference_as_base64": self.cover_send_b64.isChecked(),
                "fallback_to_text_to_image": self.cover_fallback_t2i.isChecked(),
                "use_model_output_url_in_frontmatter": self.cover_use_model_url.isChecked(),
                "force_text_to_image_for_noisy_thumbnail": self.cover_force_t2i.isChecked(),
                "openai_edit_strategy": self.cover_openai_edit.text().strip() or "auto",
                "reference_image_url": self.cover_ref_url.text().strip(),
                "style": self.cover_style.toPlainText().strip(),
                "negative_prompt": self.cover_negative.toPlainText().strip(),
                "submit_timeout_seconds": self.cover_submit_to.value(),
                "download_timeout_seconds": self.cover_download_to.value(),
                "poll_timeout_seconds": self.cover_poll_to.value(),
                "poll_interval_seconds": self.cover_poll_interval.value(),
                "max_wait_seconds": self.cover_max_wait.value(),
                "enable_reference_preprocess": self.cover_enable_pre.isChecked(),
                "reference_text_score_threshold": self.cover_text_thr.value(),
                "reference_min_food_score": self.cover_min_food.value(),
                "reference_crop_min_food_score": self.cover_crop_food.value(),
                "reference_crop_top_ratio": self.cover_crop_top.value(),
                "reference_crop_bottom_ratio": self.cover_crop_bottom.value(),
            },
            "image_host": {
                "enable": self.host_enable.isChecked(),
                "provider": self.host_provider.text().strip(),
                "api_url": self.host_api_url.text().strip(),
                "token": self.host_token.text().strip(),
                "token_field": self.host_token_field.text().strip() or "token",
                "file_field": self.host_file_field.text().strip() or "image",
                "url_json_path": self.host_url_path.text().strip() or "url",
                "timeout_seconds": self.host_timeout.value(),
                "extra_fields": extra_fields,
            },
        }

    def _save(self) -> None:
        try:
            current = load_config() or {}
            deep_update(current, self._collect_updates())
            save_config(current)
            self._config = current
            QMessageBox.information(self, "设置", "已保存到 config.json")
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
