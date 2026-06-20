from __future__ import annotations

import importlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import HISTORY_FILE, HISTORY_VIDEO_DAYS, HISTORY_CLIP_DAYS


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


# ---------------------------------------------------------------------------
#  Sistema de histórico para detecção de duplicatas
# ---------------------------------------------------------------------------

def load_history() -> list[dict[str, Any]]:
    """Carrega o historico de clipes publicados."""
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history: list[dict[str, Any]]) -> None:
    """Salva o historico de clipes publicados, removendo entradas expiradas."""
    cutoff = datetime.now() - timedelta(days=max(HISTORY_VIDEO_DAYS, HISTORY_CLIP_DAYS))
    cutoff_str = cutoff.isoformat()

    # Remove entradas mais antigas que o maior dos dois períodos
    cleaned = [
        entry for entry in history
        if entry.get("posted_at", "") >= cutoff_str
    ]

    HISTORY_FILE.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def record_clips(
    video_id: str,
    video_url: str,
    clips: list[dict[str, Any]],
    platforms: list[str],
) -> None:
    """Registra clipes publicados no historico."""
    history = load_history()
    now = datetime.now().isoformat()

    for clip in clips:
        # Extrai apenas campos serializaveis (upload_queue pode conter Path objects)
        clip_start = clip.get("start", 0)
        clip_end = clip.get("end", 0)
        clip_title = str(clip.get("title", ""))

        entry = {
            "video_id": video_id,
            "video_url": video_url,
            "start": float(clip_start) if clip_start else 0,
            "end": float(clip_end) if clip_end else 0,
            "title": clip_title,
            "platforms": platforms,
            "posted_at": now,
        }
        history.append(entry)

    save_history(history)
    print(f"Historico atualizado: {len(clips)} clipe(s) registrado(s) para o video {video_id}.")


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

    print("Todos os videos candidatos ja foram usados recentemente. Permitindo reutilizacao.")
    return video_urls


def filter_duplicate_clips(
    clips: list[dict[str, Any]],
    video_id: str,
    history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Remove clipes que ja foram publicados recentemente.
    Se todos forem duplicatas, retorna a lista original.
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

    print("Todos os clipes são duplicatas recentes. Permitindo reutilizacao para nao travar.")
    return clips


def build_social_caption(title: str, description: str, limit: int, tags: list[str] | None = None) -> str:
    """Cria uma legenda limitando ao tamanho maximo e anexando tags se existirem."""
    caption = description.strip() or title.strip()
    
    if tags:
        caption_lower = caption.lower()
        missing_tags = [tag for tag in tags if tag.strip() and tag.lower() not in caption_lower]
        if not caption and missing_tags:
            caption = " ".join(missing_tags)
        elif missing_tags:
            caption = f"{caption}\n\n{' '.join(missing_tags)}"
            
    if len(caption) > limit:
        caption = caption[:limit].rstrip()
    return caption
