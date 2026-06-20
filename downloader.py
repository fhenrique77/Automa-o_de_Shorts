from __future__ import annotations

import os
from pathlib import Path

from config import TEMP_VIDEOS_DIR, YOUTUBE_COOKIES_FILE
from utils import resolve_ffmpeg_executable, resolve_ytdlp_js_runtimes

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
        output_dir.glob(f"{prepared_file.stem}.*"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if matches:
        return matches[0]

    raise FileNotFoundError(f"Nao foi possivel localizar o arquivo baixado em {output_dir}")


def download_video(url: str, output_dir: str | Path = TEMP_VIDEOS_DIR) -> Path:
    if not url.strip():
        raise ValueError("A URL do video nao pode estar vazia.")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ffmpeg_executable = resolve_ffmpeg_executable()
    ffmpeg_dir = str(Path(ffmpeg_executable).parent)
    _ensure_ffmpeg_in_path(ffmpeg_dir)
    _configure_ytdlp_ffmpeg(ffmpeg_executable)

    options = {
        "format": "bv*+ba/b",
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
    """Baixa apenas a secao especifica do video usando o recurso download_ranges do yt-dlp."""
    if not url.strip():
        raise ValueError("A URL do video nao pode estar vazia.")

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_executable = resolve_ffmpeg_executable()
    ffmpeg_dir = str(Path(ffmpeg_executable).parent)
    _ensure_ffmpeg_in_path(ffmpeg_dir)
    _configure_ytdlp_ffmpeg(ffmpeg_executable)

    def _get_ranges(info_dict, ydl):
        return [{"start_time": start, "end_time": end}]

    options = {
        "format": "bv*+ba/b",
        "outtmpl": str(out_path),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "retries": 5,
        "quiet": False,
        "consoletitle": False,
        "ffmpeg_location": ffmpeg_dir,
        "js_runtimes": resolve_ytdlp_js_runtimes(),
        "remote_components": ["ejs:github"],
        "download_ranges": _get_ranges,
        "force_keyframes_at_cuts": True,
        "cookiefile": str(YOUTUBE_COOKIES_FILE),
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])

    if not out_path.exists():
        raise FileNotFoundError(f"Falha silenciosa ao baixar recorte de video parcial para: {out_path}")

    return out_path

