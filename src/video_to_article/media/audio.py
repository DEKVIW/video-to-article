import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from ..data_paths import local_audio_dir
from ..logging_config import configure_logging
from ..paths import AUDIO_EXTENSIONS, FUNASR_MODEL_DIR, VIDEO_EXTENSIONS
from ..text_utils import format_time, import_required, traditional_to_simplified
from ..paths import MODEL_DIR
from .download import download_audio  # re-export for existing imports

logger = configure_logging()

__all__ = [
    "download_audio",
    "prepare_local_audio",
    "extract_audio_from_local_video",
    "transcribe_audio",
    "transcribe_audio_with_whisper",
    "transcribe_audio_with_funasr",
    "extract_funasr_text",
    "resolve_funasr_model_name",
    "resolve_funasr_vad_model_name",
]

FUNASR_MODEL_ALIASES = {
    "sensevoice": "iic/SenseVoiceSmall",
    "sensevoice-small": "iic/SenseVoiceSmall",
    "paraformer": "paraformer-zh",
    "paraformer-zh": "paraformer-zh",
}

# Required beside model.pt for SenseVoice (sentencepiece); used for completeness checks.
SENSEVOICE_REQUIRED_FILES = (
    "model.pt",
    "chn_jpn_yue_eng_ko_spectok.bpe.model",
    "config.yaml",
    "configuration.json",
)


def _path_has_non_ascii(path: Path | str) -> bool:
    try:
        str(path).encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def _project_sensevoice_dir() -> Path:
    return FUNASR_MODEL_DIR / "models" / "iic" / "SenseVoiceSmall"


def _project_vad_dir() -> Path:
    return FUNASR_MODEL_DIR / "models" / "iic" / "speech_fsmn_vad_zh-cn-16k-common-pytorch"


def _sensevoice_complete(dir_path: Path) -> bool:
    return all((dir_path / name).is_file() for name in SENSEVOICE_REQUIRED_FILES)


def _ascii_funasr_root() -> Path:
    """Windows-safe cache root when project path contains non-ASCII (e.g. 中文目录).

    SentencePiece / FunASR native code cannot open model files under non-ASCII
    paths on Windows even if Python pathlib sees them as existing.
    """
    env = (os.environ.get("VQE_FUNASR_DIR") or "").strip()
    if env:
        root = Path(env)
        if not _path_has_non_ascii(root):
            root.parent.mkdir(parents=True, exist_ok=True)
            return root
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "C:\\YilanChengWen"
    root = Path(base) / "YilanChengWen" / "models" / "funasr"
    root.parent.mkdir(parents=True, exist_ok=True)
    return root


def _ensure_windows_junction(link: Path, target: Path) -> bool:
    """Create a directory junction (no admin) so native code can open via ASCII path."""
    target = target.resolve()
    link.parent.mkdir(parents=True, exist_ok=True)

    if link.exists() or link.is_symlink():
        try:
            if (link / "models").is_dir() or link.resolve() == target:
                return True
            # Empty placeholder dir blocks mklink /J
            if link.is_dir() and not any(link.iterdir()):
                link.rmdir()
            else:
                return (link / "models").is_dir()
        except OSError:
            return False

    try:
        if sys.platform.startswith("win"):
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0 and link.exists():
                logger.info(f"已创建模型目录联接（避免中文路径）: {link} -> {target}")
                return True
            logger.warning(
                f"创建目录联接失败 (code={completed.returncode}): "
                f"{(completed.stderr or completed.stdout or '').strip()}"
            )
        else:
            link.symlink_to(target, target_is_directory=True)
            return True
    except OSError as e:
        logger.warning(f"无法创建模型目录联接: {e}")
    return False


def funasr_runtime_root() -> Path:
    """Directory FunASR should use as MODELSCOPE_CACHE / local model parent.

    Prefers project models/funasr when path is ASCII-safe; otherwise uses
    %LOCALAPPDATA%\\YilanChengWen\\models\\funasr (optionally junctioned).
    """
    project = FUNASR_MODEL_DIR
    if not _path_has_non_ascii(project):
        project.mkdir(parents=True, exist_ok=True)
        return project

    safe = _ascii_funasr_root()
    # If project already has weights, expose them via junction under ASCII path
    if project.is_dir() and any(project.rglob("model.pt")):
        if not (safe / "models").exists():
            if not _ensure_windows_junction(safe, project.resolve()):
                safe.mkdir(parents=True, exist_ok=True)
                logger.warning(
                    "项目路径含非 ASCII 字符，FunASR 将使用 ASCII 缓存目录: %s "
                    "（可将 models\\funasr 整夹拷到该目录，或把项目放到纯英文路径）",
                    safe,
                )
        return safe
    safe.mkdir(parents=True, exist_ok=True)
    return safe


def resolve_funasr_model_name(funasr_model: str) -> tuple[str, bool]:
    """Resolve FunASR model aliases, preferring complete local caches."""
    model_name = FUNASR_MODEL_ALIASES.get(funasr_model, funasr_model)
    is_sensevoice = model_name in {"iic/SenseVoiceSmall", "SenseVoiceSmall"} or funasr_model in {
        "sensevoice",
        "sensevoice-small",
    }

    if not is_sensevoice:
        return model_name, False

    candidates = [
        funasr_runtime_root() / "models" / "iic" / "SenseVoiceSmall",
        _project_sensevoice_dir(),
    ]
    # Deduplicate while preserving order
    seen: set[str] = set()
    for cand in candidates:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if _sensevoice_complete(cand):
            # Prefer ASCII-safe path for native loaders (SentencePiece on Windows).
            # Do NOT Path.resolve() — it expands junctions back to the Chinese path.
            path_str = str(cand.absolute())
            if _path_has_non_ascii(path_str):
                safe_cand = funasr_runtime_root() / "models" / "iic" / "SenseVoiceSmall"
                if _sensevoice_complete(safe_cand) and not _path_has_non_ascii(safe_cand):
                    return str(safe_cand.absolute()), True
                logger.warning(
                    "本地 SenseVoice 位于含中文/非 ASCII 的路径，SentencePiece 可能无法读取。"
                    "将回退为模型 ID 以便下载到 ASCII 缓存，或请把项目放到纯英文路径。"
                )
                return model_name, True
            return path_str, True

    # Incomplete local dir (e.g. only model.pt): do NOT force local path — allow hub download
    incomplete = _project_sensevoice_dir()
    if (incomplete / "model.pt").exists() and not _sensevoice_complete(incomplete):
        logger.warning(
            "本地 SenseVoice 不完整（缺少 bpe/config 等），将尝试从 ModelScope 重新拉取到缓存目录"
        )
    return model_name, True


def resolve_funasr_vad_model_name() -> str:
    """Resolve the default FunASR VAD model, preferring local cache."""
    candidates = [
        funasr_runtime_root() / "models" / "iic" / "speech_fsmn_vad_zh-cn-16k-common-pytorch",
        _project_vad_dir(),
    ]
    for cand in candidates:
        if (cand / "model.pt").is_file():
            path_str = str(cand.absolute())
            if _path_has_non_ascii(path_str):
                safe = funasr_runtime_root() / "models" / "iic" / "speech_fsmn_vad_zh-cn-16k-common-pytorch"
                if (safe / "model.pt").is_file() and not _path_has_non_ascii(safe):
                    return str(safe.absolute())
                continue
            return path_str
    return "fsmn-vad"


def prepare_local_audio(
    media_path: str,
    quality: str = "fast",
    batch_root: Optional[str] = None,
) -> tuple[str, str, bool]:
    """Return an audio path for a local audio/video file.

    Audio files are used directly. Video files are converted to mp3 first.
    """
    media_path_obj = Path(media_path)
    suffix = media_path_obj.suffix.lower()

    if suffix in AUDIO_EXTENSIONS:
        if not media_path_obj.exists():
            raise FileNotFoundError(f"本地音频文件不存在: {media_path}")
        logger.info(f"使用本地音频文件: {media_path}")
        return str(media_path_obj), media_path_obj.stem, False

    audio_path, title = extract_audio_from_local_video(media_path, quality, batch_root)
    return audio_path, title, True


def extract_audio_from_local_video(
    video_path: str,
    quality: str = "fast",
    batch_root: Optional[str] = None,
) -> tuple[str, str]:
    """Extract mp3 audio from a local video file."""
    start_time = time.time()
    logger.info(f"从本地视频提取音频: {video_path}")

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"本地视频文件不存在: {video_path}")

    video_path_obj = Path(video_path)
    if video_path_obj.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError(f"不支持的视频格式: {video_path_obj.suffix}")

    title = video_path_obj.stem
    audio_output_dir = local_audio_dir(video_path, batch_root=batch_root)
    audio_output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(audio_output_dir / f"{title}.mp3")

    quality_map = {"fast": "32", "medium": "64", "slow": "128"}
    bitrate = quality_map.get(quality, "64")

    from .ffmpeg_tools import ensure_ffmpeg_on_path, resolve_ffmpeg

    ensure_ffmpeg_on_path()
    ffmpeg_bin = resolve_ffmpeg()
    if not ffmpeg_bin:
        raise RuntimeError(
            "未找到 FFmpeg。请将 ffmpeg.exe 放到程序目录的 ffmpeg\\ 下，"
            "或安装系统 FFmpeg 并加入 PATH。"
        )

    try:
        cmd = [
            ffmpeg_bin,
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "libmp3lame",
            "-ab",
            f"{bitrate}k",
            "-ar",
            "44100",
            "-y",
            audio_path,
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        elapsed = time.time() - start_time
        logger.info(f"音频提取完成: {title} (耗时: {format_time(elapsed)})")
        return audio_path, title
    except subprocess.CalledProcessError as e:
        logger.error(f"音频提取失败: {e.stderr.decode('utf-8', errors='ignore')}")
        raise RuntimeError(f"FFmpeg 提取音频失败: {e}") from e
    except FileNotFoundError as e:
        raise RuntimeError(
            "FFmpeg 无法执行。请检查程序目录 ffmpeg\\ 或系统 PATH 中的 ffmpeg。"
        ) from e


def transcribe_audio(
    audio_path: str,
    model_size: str = "tiny",
    cpu_threads: int = 4,
    asr_engine: str = "funasr",
    funasr_model: str = "sensevoice",
) -> str:
    """Transcribe audio with the selected ASR engine."""
    if asr_engine == "whisper":
        return transcribe_audio_with_whisper(audio_path, model_size, cpu_threads)
    if asr_engine == "funasr":
        return transcribe_audio_with_funasr(audio_path, funasr_model)
    raise ValueError(f"不支持的 ASR 引擎: {asr_engine}")


def transcribe_audio_with_whisper(audio_path: str, model_size: str = "tiny", cpu_threads: int = 4) -> str:
    """Transcribe audio with faster-whisper."""
    faster_whisper = import_required("faster_whisper", "faster-whisper")
    modelscope = import_required("modelscope", "modelscope")

    start_time = time.time()
    model_path = MODEL_DIR / f"whisper-{model_size}"

    if not model_path.exists():
        logger.info(f"下载 Whisper {model_size} 模型...")
        model_map = {
            "tiny": "pengzhendong/faster-whisper-tiny",
            "base": "pengzhendong/faster-whisper-base",
            "small": "pengzhendong/faster-whisper-small",
        }
        repo_id = model_map.get(model_size)
        if not repo_id:
            raise ValueError(f"不支持的模型: {model_size}")

        download_start = time.time()
        modelscope.snapshot_download(repo_id, local_dir=str(model_path))
        logger.info(f"模型下载完成 (耗时: {format_time(time.time() - download_start)})")

    logger.info(f"加载 Whisper 模型 ({model_size})...")
    load_start = time.time()
    model = faster_whisper.WhisperModel(
        model_size_or_path=str(model_path),
        device="cpu",
        compute_type="int8",
        cpu_threads=cpu_threads,
    )
    logger.info(f"模型加载完成 (耗时: {format_time(time.time() - load_start)})")

    logger.info("开始转写音频...")
    transcribe_start = time.time()
    segments_generator, _ = model.transcribe(audio_path, language="zh")

    full_text = ""
    segment_count = 0
    for segment in segments_generator:
        full_text += segment.text.strip() + " "
        segment_count += 1

    full_text = traditional_to_simplified(full_text.strip())
    logger.info(f"转写完成: {segment_count} 段 (耗时: {format_time(time.time() - transcribe_start)})")
    logger.info(f"转写总耗时: {format_time(time.time() - start_time)}, 共 {len(full_text)} 字符")
    return full_text


def transcribe_audio_with_funasr(audio_path: str, funasr_model: str = "sensevoice") -> str:
    """Transcribe audio with FunASR."""
    # Prefer ASCII-safe cache (critical on Windows when project path has 中文)
    funasr_cache_dir = funasr_runtime_root()
    funasr_cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MODELSCOPE_CACHE"] = str(funasr_cache_dir)

    try:
        import_required("torch", "torch")
    except RuntimeError as e:
        raise RuntimeError(
            "FunASR 需要 PyTorch。请先在虚拟环境中运行: "
            "python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu"
        ) from e

    funasr = import_required("funasr", "funasr")

    model_name, is_sensevoice = resolve_funasr_model_name(funasr_model)
    vad_model_name = resolve_funasr_vad_model_name()
    start_time = time.time()
    logger.info(f"加载 FunASR 模型 ({model_name})...")
    logger.info(f"FunASR/ModelScope 模型缓存目录: {funasr_cache_dir}")
    if _path_has_non_ascii(FUNASR_MODEL_DIR):
        logger.info(
            "检测到项目 models 路径含非 ASCII 字符；已改用 ASCII 安全目录加载 "
            "（SentencePiece 无法读取中文路径下的 .bpe.model）"
        )
    load_start = time.time()

    if is_sensevoice:
        model = funasr.AutoModel(
            model=model_name,
            vad_model=vad_model_name,
            vad_kwargs={"max_single_segment_time": 30000},
            disable_update=True,
            device="cpu",
        )
        generate_kwargs = {"language": "zh", "use_itn": True, "batch_size_s": 60, "merge_vad": True}
    else:
        model = funasr.AutoModel(
            model=model_name,
            vad_model=vad_model_name,
            punc_model="ct-punc",
            disable_update=True,
            device="cpu",
        )
        generate_kwargs = {"batch_size_s": 60}

    logger.info(f"FunASR 模型加载完成 (耗时: {format_time(time.time() - load_start)})")
    logger.info("开始 FunASR 转写音频...")
    transcribe_start = time.time()
    result = model.generate(input=audio_path, **generate_kwargs)
    text = extract_funasr_text(result)
    text = traditional_to_simplified(text.strip())
    logger.info(f"FunASR 转写完成 (耗时: {format_time(time.time() - transcribe_start)})")
    logger.info(f"FunASR 转写总耗时: {format_time(time.time() - start_time)}, 共 {len(text)} 字符")
    return text


def extract_funasr_text(result) -> str:
    """Extract plain text from FunASR generate result."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return str(result.get("text") or result.get("sentence") or "")
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, dict):
                text = item.get("text") or item.get("sentence") or ""
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return " ".join(parts)
    return str(result or "")
