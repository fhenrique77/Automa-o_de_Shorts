from __future__ import annotations

import os
import subprocess
from pathlib import Path

from config import TEMP_VIDEOS_DIR, YOUTUBE_COOKIES_FILE
from utils import resolve_ffmpeg_executable, resolve_ytdlp_js_runtimes, validate_video_clip

import yt_dlp
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor


def _configure_ytdlp_ffmpeg(ffmpeg_executable: str) -> None:
    FFmpegPostProcessor._ffmpeg_location.set(ffmpeg_executable)


def _ensure_ffmpeg_in_path(ffmpeg_dir: str) -> None:
    """Adiciona o diretorio do ffmpeg ao PATH apenas se ainda nao estiver."""
    current_path = os.environ.get("PATH", "")
    if ffmpeg_dir not in current_path:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + current_path


def _resolve_downloaded_file(prepared_file: Path, output_dir: Path) -> Path:
    candidates = [prepared_file.with_suffix(".mp4"), prepared_file]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    matches = sorted(
        (item for item in output_dir.glob(f"{prepared_file.stem}.*")
         if item.is_file() and item.suffix.lower() in {".mp4", ".webm", ".mkv"}
         and item.stat().st_size > 0),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if matches:
        return matches[0]

    raise FileNotFoundError(f"Nao foi possivel localizar o arquivo baixado em {output_dir}")


def download_video(url: str, output_dir: str | Path = TEMP_VIDEOS_DIR, *, audio_only: bool = False) -> Path:
    if not url.strip():
        raise ValueError("A URL do video nao pode estar vazia.")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ffmpeg_executable = resolve_ffmpeg_executable()
    ffmpeg_dir = str(Path(ffmpeg_executable).parent)
    _ensure_ffmpeg_in_path(ffmpeg_dir)
    _configure_ytdlp_ffmpeg(ffmpeg_executable)

    options = {
        "format": "bestaudio/best" if audio_only else "bv*+ba/b",
        "outtmpl": str(output_path / "%(title).200s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "retries": 5,
        "quiet": False,
        "consoletitle": False,
        "ffmpeg_location": ffmpeg_dir,
        "js_runtimes": resolve_ytdlp_js_runtimes(),
        "remote_components": ["ejs:github"],
        "cookiefile": str(YOUTUBE_COOKIES_FILE),
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        prepared_file = Path(ydl.prepare_filename(info))

    return _resolve_downloaded_file(prepared_file, output_path)


def download_clip_section(url: str, start: float, end: float, output_path: str | Path) -> Path:
    """Baixa streams completos com retomada HTTP e recorta localmente."""
    if not url.strip():
        raise ValueError("A URL do video nao pode estar vazia.")
    if start < 0 or end <= start:
        raise ValueError("Intervalo de corte invalido.")

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_executable = resolve_ffmpeg_executable()
    ffmpeg_dir = str(Path(ffmpeg_executable).parent)
    _ensure_ffmpeg_in_path(ffmpeg_dir)
    _configure_ytdlp_ffmpeg(ffmpeg_executable)

    options = {
        "format": "bv*[protocol=https]+ba[protocol=https]/b[protocol=https]",
        "outtmpl": str(out_path.with_name(out_path.stem + ".full.%(ext)s")),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "retries": 5,
        "fragment_retries": 5,
        "quiet": False,
        "consoletitle": False,
        "ffmpeg_location": ffmpeg_dir,
        "js_runtimes": resolve_ytdlp_js_runtimes(),
        "remote_components": ["ejs:github"],
        "cookiefile": str(YOUTUBE_COOKIES_FILE),
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        prepared = Path(ydl.prepare_filename(info))
    merged = out_path.with_name(out_path.stem + ".full.mp4")
    full = merged if merged.is_file() else _resolve_downloaded_file(prepared, out_path.parent)
    validate_video_clip(full, minimum_duration=end)
    command = [ffmpeg_executable, "-y", "-ss", str(start), "-i", str(full),
               "-t", str(end - start), "-map", "0:v:0", "-map", "0:a:0",
               "-c:v", "libx264", "-preset", "fast", "-crf", "23",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out_path)]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise RuntimeError(f"Falha ao recortar video localmente: {result.stderr[-3000:]}")
    validate_video_clip(out_path, minimum_duration=(end - start) * 0.9)
    full.unlink()

    return out_path
