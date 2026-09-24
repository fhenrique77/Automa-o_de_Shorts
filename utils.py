from __future__ import annotations

import importlib
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import HISTORY_FILE, HISTORY_VIDEO_DAYS, HISTORY_CLIP_DAYS, PUBLICATION_DB
from publication_store import PublicationStore


def resolve_ffmpeg_executable() -> str:
    """Resolve o caminho do ffmpeg no sistema ou via imageio-ffmpeg."""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        imageio_ffmpeg = importlib.import_module("imageio_ffmpeg")
    except ImportError as exc:
        raise RuntimeError(
            "Instale imageio-ffmpeg ou adicione ffmpeg ao PATH do Windows."
        ) from exc

    raw_exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    clean_exe = raw_exe.parent / "ffmpeg.exe"
    if not clean_exe.exists():
        shutil.copy(raw_exe, clean_exe)
    return str(clean_exe)


def resolve_ytdlp_js_runtimes() -> dict[str, dict[str, str]]:
    """Resolve runtimes JavaScript usados pelo yt-dlp para challenge solving do YouTube."""
    node_executable = shutil.which("node")
    if node_executable:
        return {"node": {"path": node_executable}}

    deno_executable = shutil.which("deno")
    if deno_executable:
        return {"deno": {"path": deno_executable}}

    return {}


def validate_video_clip(path: str | Path, *, minimum_duration: float = 0) -> None:
    """Require video and audio frames at both ends of a sufficiently long file."""
    media = Path(path)
    if not media.is_file() or not media.stat().st_size:
        raise RuntimeError(f"Arquivo de video ausente ou vazio: {media}")
    ffmpeg = resolve_ffmpeg_executable()
    for seek_tail in (False, True):
        if seek_tail:
            probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(media)],
                                   capture_output=True, text=True, errors="replace")
            match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr or "")
            if not match:
                raise RuntimeError(f"Duracao do video nao identificada: {media}")
            hours, minutes, seconds = match.groups()
            duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            if duration + 0.5 < minimum_duration:
                raise RuntimeError(f"Video menor que o trecho esperado: {media}")
            if duration <= 3:
                break
        for kind, filter_name in (("v", "showinfo"), ("a", "ashowinfo")):
            command = [ffmpeg, "-hide_banner", "-loglevel", "info"]
            if seek_tail:
                command.extend(["-sseof", "-2"])
            command.extend(["-i", str(media), "-map", f"0:{kind}:0",
                            f"-frames:{kind}", "1",
                            f"-{'vf' if kind == 'v' else 'af'}", filter_name,
                            "-f", "null", "-"])
            result = subprocess.run(command, capture_output=True, text=True, errors="replace")
            diagnostics = result.stderr or ""
            if result.returncode or f"Parsed_{filter_name}" not in diagnostics or " n:" not in diagnostics:
                stream = "video" if kind == "v" else "audio"
                location = "no fim" if seek_tail else "no inicio"
                raise RuntimeError(f"Arquivo sem quadro decodificavel de {stream} {location}: {media}")


# ---------------------------------------------------------------------------
#  Sistema de histórico para detecção de duplicatas
# ---------------------------------------------------------------------------

def load_history() -> list[dict[str, Any]]:
    """Load transactional history and queue reservations; fail closed on corruption."""
    with PublicationStore(PUBLICATION_DB, HISTORY_FILE) as store:
        return store.history()


def is_video_used(video_id: str, history: list[dict[str, Any]] | None = None) -> bool:
    """Verifica se um video ja foi usado nos ultimos HISTORY_VIDEO_DAYS dias."""
    if history is None:
        history = load_history()

    cutoff = (datetime.now() - timedelta(days=HISTORY_VIDEO_DAYS)).isoformat()

    for entry in history:
        if entry.get("video_id") == video_id and entry.get("posted_at", "") >= cutoff:
            return True
    return False


def is_clip_duplicate(
    video_id: str,
    start: float,
    end: float,
    history: list[dict[str, Any]] | None = None,
    overlap_threshold: float = 0.5,
) -> bool:
    """
    Verifica se um clipe ja foi publicado nos ultimos HISTORY_CLIP_DAYS dias.
    Compara por sobreposição de tempo, não apenas timestamps exatos.
    Um clipe é considerado duplicata se mais de 50% do tempo se sobrepõe.
    """
    if history is None:
        history = load_history()

    cutoff = (datetime.now() - timedelta(days=HISTORY_CLIP_DAYS)).isoformat()
    clip_duration = end - start

    for entry in history:
        if entry.get("video_id") != video_id:
            continue
        if entry.get("posted_at", "") < cutoff:
            continue

        entry_start = float(entry.get("start", 0))
        entry_end = float(entry.get("end", 0))

        # Calcula sobreposição
        overlap_start = max(start, entry_start)
        overlap_end = min(end, entry_end)
        overlap = max(0, overlap_end - overlap_start)

        if clip_duration > 0 and (overlap / clip_duration) >= overlap_threshold:
            return True

    return False


def filter_unused_videos(
    video_urls: list[str],
    extract_id_fn,
    history: list[dict[str, Any]] | None = None,
) -> list[str]:
    """
    Filtra videos que ja foram usados recentemente.
    Se todos ja foram usados, retorna a lista original (para não travar).
    """
    if history is None:
        history = load_history()

    unused = [
        url for url in video_urls
        if not is_video_used(extract_id_fn(url), history)
    ]

    if unused:
        skipped = len(video_urls) - len(unused)
        if skipped > 0:
            print(f"Filtro de duplicatas: {skipped} video(s) ja usado(s) recentemente, {len(unused)} disponivel(is).")
        return unused

    print("Todos os videos candidatos ja foram usados recentemente; fonte ignorada.")
    return []


def filter_duplicate_clips(
    clips: list[dict[str, Any]],
    video_id: str,
    history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Remove clipes que ja foram publicados recentemente.
    Se todos forem duplicatas, retorna uma lista vazia.
    """
    if history is None:
        history = load_history()

    unique = [
        clip for clip in clips
        if not is_clip_duplicate(video_id, float(clip["start"]), float(clip["end"]), history)
    ]

    if unique:
        removed = len(clips) - len(unique)
        if removed > 0:
            print(f"Filtro de duplicatas: {removed} clipe(s) duplicado(s) removido(s), {len(unique)} unico(s).")
        return unique

    print("Todos os clipes sao duplicatas recentes; nenhum sera publicado.")
    return []


def build_social_caption(title: str, description: str, limit: int, tags: list[str] | None = None) -> str:
    """Cria uma legenda limitando ao tamanho maximo e anexando tags se existirem."""
    caption = description.strip() or title.strip()
    
    if tags:
        caption_lower = caption.lower()
        missing_tags = [
            tag for tag in tags
            if tag.strip() and tag.lower() not in caption_lower
        ]
        if not caption and missing_tags:
            caption = " ".join(missing_tags)
        elif missing_tags:
            caption = f"{caption}\n\n{' '.join(missing_tags)}"
            
    if len(caption) > limit:
        # Trunca na ultima palavra completa, nunca no meio
        truncated = caption[:limit]
        last_newline = truncated.rfind("\n")
        last_space = truncated.rfind(" ")
        cut_point = max(last_newline, last_space)
        if cut_point > limit // 3:
            caption = truncated[:cut_point].rstrip()
        else:
            caption = truncated.rstrip()
    return caption
