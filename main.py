from __future__ import annotations

import sys
import os

# Fix Windows console encoding to avoid 'charmap' codec errors with Unicode titles
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
import importlib
import json
import random
import time as time_module
from pathlib import Path
from datetime import datetime, time
from uuid import uuid4
from config import (
    BASE_DIR,
    PUBLICATION_DB,
    HISTORY_FILE,
    ALLOW_WHISPER_FALLBACK,
    AUTO_SELECT_CLIPS,
    AUTHORIZED_SOURCE_URLS,
    AUTHORIZED_SOURCES_FILE,
    AUTHORIZED_SOURCE_VIDEO_LIMIT,
    SOURCE_SCHEDULES_FILE,
    CLIP_COUNT,
    CLIP_MAX_DURATION,
    CLIP_MIN_DURATION,
    CLEANUP_TEMP_FILES,
    TEMP_PENDING_RETENTION_DAYS,
    TEMP_LEGACY_MAX_AGE_HOURS,
    MANUAL_CLIPS,
    PODCAST_URL,
    QUEUE_MODE,
    RETRY_ATTEMPTS,
    RETRY_DELAY_SECONDS,
    TEMP_CLIPS_DIR,
    TEMP_VIDEOS_DIR,
    YOUTUBE_COOKIES_FILE,
    TRANSCRIPT_LANGUAGE_PREFERENCES,
    WHISPER_MODEL,
    YOUTUBE_UPLOAD_ENABLED,
    YOUTUBE_CATEGORY_ID,
    YOUTUBE_PRIVACY_STATUS,
    TIKTOK_UPLOAD_ENABLED,
    INSTAGRAM_UPLOAD_ENABLED,
    FACEBOOK_UPLOAD_ENABLED,
)
from cutter import (
    build_clip_plan,
    cut_clip,
    extract_video_id,
    fetch_youtube_transcript_segments,
    enrich_clips_with_metadata,
    normalize_manual_clips,
    transcribe_video,
)
from downloader import download_clip_section, download_video
from uploader import upload_videos as upload_youtube_videos
from tiktok_uploader import upload_videos as upload_tiktok_videos
from instagram_uploader import upload_videos as upload_instagram_videos
from facebook_uploader import upload_videos as upload_facebook_videos
from utils import filter_unused_videos, filter_duplicate_clips
from runtime import AlreadyRunningError, RunLock, TempWorkspace, remove_temp_path
from publication_store import PublicationStore
from delivery_queue import dispatch_pending
from repair_media import repair_delivery


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automacao de cortes de podcast para YouTube"
    )
    parser.add_argument("--url", default=PODCAST_URL, help="URL do podcast no YouTube")
    parser.add_argument(
        "--input-video",
        default=None,
        help="Caminho para um MP4 local. Quando informado, o pipeline pula o download e publica esse arquivo diretamente.",
    )
    parser.add_argument(
        "--input-title",
        default=None,
        help="Titulo usado quando --input-video for informado.",
    )
    parser.add_argument(
        "--input-description",
        default=None,
        help="Descricao usada quando --input-video for informado.",
    )
    parser.add_argument(
        "--input-tags",
        default="",
        help="Lista de hashtags separadas por virgula para --input-video.",
    )
    parser.add_argument("--model", default=WHISPER_MODEL, help="Modelo do Whisper")
    parser.add_argument(
        "--language",
        default=None,
        help="Idioma da transcricao, por exemplo pt ou en",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Usar somente os cortes manuais definidos em config.py",
    )
    parser.add_argument(
        "--source-url",
        action="append",
        default=[],
        help="URL autorizada de video, playlist ou canal. Pode repetir a flag.",
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        default=QUEUE_MODE,
        help="Processa todas as fontes permitidas em ordem, sem intervenção.",
    )
    parser.add_argument(
        "--clip-count",
        type=int,
        default=CLIP_COUNT,
        help="Quantidade de shorts a gerar a partir de um unico video",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nao faz upload, apenas gera os arquivos localmente",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Mantem os arquivos temporarios ao final da execucao",
    )
    queue_actions = parser.add_mutually_exclusive_group()
    queue_actions.add_argument("--queue-status", action="store_true", help="Exibe entregas e estados, sem publicar")
    queue_actions.add_argument("--retry-pending", action="store_true", help="Processa somente entregas pendentes seguras")
    queue_actions.add_argument("--resolve-delivery", type=int, help="ID de uma entrega incerta revisada manualmente")
    queue_actions.add_argument("--repair-delivery", type=int, help="Refaz o clipe de uma entrega ainda nao enviada")
    parser.add_argument("--resolution", choices=["published", "not-published"])
    parser.add_argument("--resolution-note", default="")
    parser.add_argument("--post-url", default=None)
    args = parser.parse_args()
    if args.resolve_delivery is not None and (not args.resolution or not args.resolution_note.strip()):
        parser.error("--resolve-delivery exige --resolution e --resolution-note")
    if args.resolve_delivery is None and (args.resolution or args.resolution_note or args.post_url):
        parser.error("Opcoes de revisao exigem --resolve-delivery")
    if args.input_video and (args.queue_status or args.retry_pending or args.resolve_delivery is not None or args.repair_delivery is not None):
        parser.error("Acoes da fila nao podem ser combinadas com --input-video")
    if args.dry_run and (args.retry_pending or args.resolve_delivery is not None or args.repair_delivery is not None):
        parser.error("--dry-run nao pode reenviar ou resolver entregas")
    return args


def _normalize_local_title(video_path: Path) -> str:
    stem = video_path.stem.replace("_", " ").replace("-", " ").strip()
    if not stem:
        return "Video local"
    return stem[:72].strip()


def _parse_input_tags(raw_tags: str) -> list[str]:
    tags: list[str] = []
    for raw_tag in raw_tags.replace(";", ",").split(","):
        tag = raw_tag.strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag.lstrip('#')}"
        if tag not in tags:
            tags.append(tag)
    return tags


def _build_local_upload_queue(args: argparse.Namespace) -> tuple[list[dict[str, object]], list[Path], Path]:
    local_video = Path(str(args.input_video)).expanduser().resolve()
    if not local_video.exists():
        raise FileNotFoundError(f"Video local nao encontrado em {local_video}")

    title = str(args.input_title or _normalize_local_title(local_video)).strip()
    if not title:
        title = "Video local"

    description = str(args.input_description or "Video enviado automaticamente a partir de um arquivo local.").strip()
    tags = _parse_input_tags(str(args.input_tags))
    if not tags:
        tags = ["#podcast", "#shorts", "#viral"]

    payload = {
        "video_path": local_video,
        "title": title,
        "description": description,
        "tags": tags,
        "source_url": str(local_video),
        "video_id": f"local:{local_video.stem}",
        "start": 0.0,
        "end": 0.0,
    }

    return [payload], [], local_video


def run_with_retries(label: str, operation, should_retry=None):
    attempts = max(1, int(RETRY_ATTEMPTS))
    delay_seconds = max(0.0, float(RETRY_DELAY_SECONDS))
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if should_retry is not None and not should_retry(exc):
                raise
            if attempt >= attempts:
                break
            print(
                f"{label} falhou na tentativa {attempt}/{attempts}: {exc}"
            )
            if delay_seconds:
                print(f"Tentando novamente em {delay_seconds:.0f} segundos...")
                time_module.sleep(delay_seconds)

    if last_error is not None:
        raise last_error

    raise RuntimeError(f"{label} falhou sem retorno de erro.")


def load_authorized_source_file() -> list[str]:
    sources_file = Path(AUTHORIZED_SOURCES_FILE)
    if not sources_file.exists():
        return []

    loaded_urls: list[str] = []
    for raw_line in sources_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line not in loaded_urls:
            loaded_urls.append(line)

    return loaded_urls


def load_source_schedules() -> dict[str, list[dict[str, object]]]:
    schedules_file = Path(SOURCE_SCHEDULES_FILE)
    if not schedules_file.exists():
        return {}

    try:
        raw_data = json.loads(schedules_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Arquivo de agendamento invalido em {schedules_file}") from exc

    schedule_map: dict[str, list[dict[str, object]]] = {}
    entries = raw_data if isinstance(raw_data, list) else []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        source_url = str(entry.get("source_url", "")).strip()
        if not source_url:
            continue

        schedule_map.setdefault(source_url, []).append(entry)

    return schedule_map


def _normalize_day_token(token: str) -> str:
    lookup = {
        "mon": "mon",
        "monday": "mon",
        "tue": "tue",
        "tuesday": "tue",
        "wed": "wed",
        "wednesday": "wed",
        "thu": "thu",
        "thursday": "thu",
        "fri": "fri",
        "friday": "fri",
        "sat": "sat",
        "saturday": "sat",
        "sun": "sun",
        "sunday": "sun",
    }
    return lookup.get(token.strip().lower(), token.strip().lower())


def _parse_clock(value: str) -> time:
    hour_text, minute_text = value.strip().split(":", maxsplit=1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _source_allowed_now(source_url: str, schedule_map: dict[str, list[dict[str, object]]]) -> bool:
    schedules = schedule_map.get(source_url)
    if not schedules:
        return True

    current_dt = datetime.now()
    current_day = current_dt.strftime("%a").lower()
    current_time = current_dt.time()

    for schedule in schedules:
        raw_days = schedule.get("days", [])
        if isinstance(raw_days, str):
            raw_days = [raw_days]

        normalized_days = {
            _normalize_day_token(str(day))
            for day in raw_days
            if str(day).strip()
        }

        if normalized_days and "*" not in normalized_days and current_day not in normalized_days:
            continue

        start_text = str(schedule.get("start", "00:00"))
        end_text = str(schedule.get("end", "23:59"))
        start_time = _parse_clock(start_text)
        end_time = _parse_clock(end_text)

        if start_time <= end_time:
            if start_time <= current_time <= end_time:
                return True
        else:
            if current_time >= start_time or current_time <= end_time:
                return True

    return False


def expand_source_url(source_url: str, video_limit: int = AUTHORIZED_SOURCE_VIDEO_LIMIT) -> list[str]:
    normalized_url = str(source_url).strip()
    if not normalized_url:
        return []

    try:
        extract_video_id(normalized_url)
        return [normalized_url]
    except ValueError:
        pass

    try:
        yt_dlp = importlib.import_module("yt_dlp")
    except ImportError as exc:
        raise RuntimeError(
            "Instale yt-dlp para expandir canais e playlists autorizados."
        ) from exc

    options: dict[str, object] = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": False,
        "cookiefile": str(YOUTUBE_COOKIES_FILE),
    }
    if video_limit > 0:
        options["playlistend"] = video_limit

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(normalized_url, download=False)
    def flatten_entries(node):
        found = []
        if not isinstance(node, dict): return found
        etype = node.get('_type', '')
        if etype in ('url', 'url_transparent', 'video'):
            found.append(node)
        elif etype == 'playlist' or 'entries' in node:
            for child in node.get('entries', []):
                found.extend(flatten_entries(child))
        else:
            if node.get('id'): found.append(node)
        return found
        
    flat_entries = flatten_entries(info)
    resolved_urls: list[str] = []

    for entry in flat_entries[:video_limit] if video_limit > 0 else flat_entries:
        if not entry: continue
        video_id = str(entry.get("id") or "").strip()
        candidate_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
        if video_id and not video_id.startswith('UC'): # Ignore channel IDs
            if (not candidate_url or "watch?v=" not in candidate_url or "/shorts" in candidate_url or "/channel/" in candidate_url or "/playlist" in candidate_url):
                candidate_url = f"https://www.youtube.com/watch?v={video_id}"
        if not candidate_url or "watch?v=" not in candidate_url:
            continue
        if candidate_url not in resolved_urls:
            resolved_urls.append(candidate_url)
            
    return resolved_urls


def resolve_source_urls(
    args: argparse.Namespace,
    queue_mode: bool,
    schedule_map: dict[str, list[dict[str, object]]],
) -> list[str]:
    explicit_urls = [str(item).strip() for item in args.source_url if str(item).strip()]
    if explicit_urls:
        urls = explicit_urls
    else:
        urls = [str(item).strip() for item in AUTHORIZED_SOURCE_URLS if str(item).strip()]
        file_urls = load_authorized_source_file()
        for url in file_urls:
            if url not in urls:
                urls.append(url)
        if not urls:
            fallback_url = str(args.url).strip()
            if fallback_url and "SEU_VIDEO_AQUI" not in fallback_url:
                urls = [fallback_url]

    prioritized_urls: list[str] = []
    for url in urls:
        if not _source_allowed_now(url, schedule_map):
            continue
        if url not in prioritized_urls:
            prioritized_urls.append(url)

    if not queue_mode:
        if not prioritized_urls:
            return []
        randomized_urls = list(prioritized_urls)
        random.shuffle(randomized_urls)
        return randomized_urls

    return prioritized_urls


def process_source_url(
    source_url: str,
    args: argparse.Namespace,
    clip_count: int,
    schedule_map: dict[str, list[dict[str, object]]],
    source_index: int,
    workspace: TempWorkspace,
) -> tuple[list[dict[str, object]], list[Path]]:
    try:
        return _process_source_url(source_url, args, clip_count, schedule_map, source_index, workspace)
    finally:
        # Also runs after exhausted download retries, before trying another source.
        workspace.cleanup_source(source_index)


def _process_source_url(
    source_url: str,
    args: argparse.Namespace,
    clip_count: int,
    schedule_map: dict[str, list[dict[str, object]]],
    source_index: int,
    workspace: TempWorkspace,
) -> tuple[list[dict[str, object]], list[Path]]:
    print(f"\nProcessando fonte autorizada: {source_url}")

    if not _source_allowed_now(source_url, schedule_map):
        print("Fora da janela permitida para esta fonte; pulando.")
        return [], []

    resolved_video_urls = run_with_retries(
        f"Expansao da fonte {source_url}",
        lambda: expand_source_url(source_url),
    )
    if not resolved_video_urls:
        print("Nenhum video encontrado para esta fonte.")
        return [], []

    candidate_video_urls = list(resolved_video_urls)
    candidate_video_urls = filter_unused_videos(candidate_video_urls, extract_video_id)
    if not candidate_video_urls:
        print("Todos os videos desta fonte ja foram utilizados recentemente.")
        return [], []
        
    random.shuffle(candidate_video_urls)
    selected_video_url = candidate_video_urls[0]
    print(f"Video aleatorio selecionado: {selected_video_url}")

    upload_queue: list[dict[str, object]] = []
    generated_files: list[Path] = []

    video_path: Path | None = None
    segments: list[dict[str, float | str]] = []
    transcript_error: RuntimeError | None = None
    clips: list[dict[str, float | str]] = []

    print("Buscando legenda do YouTube para reduzir uso de CPU...")
    preferred_languages = [args.language] if args.language else TRANSCRIPT_LANGUAGE_PREFERENCES
    for candidate_video_url in candidate_video_urls:
        selected_video_url = candidate_video_url
        print(f"Processando video aleatorio da fonte: {selected_video_url}")
        try:
            segments = run_with_retries(
                f"Legenda do video {selected_video_url}",
                lambda _url=selected_video_url: fetch_youtube_transcript_segments(
                    _url,
                    languages=preferred_languages,
                ),
                should_retry=lambda exc: "429" not in str(exc),
            )
            print(f"Legenda obtida com {len(segments)} segmentos.")
            break
        except RuntimeError as exc:
            transcript_error = exc
            print(f"Legenda do YouTube indisponivel para {selected_video_url}: {exc}")
            if "429" in str(exc):
                print("Limite de legendas atingido; usando o fallback local sem novas consultas de legenda.")
                break

    use_manual_clips = args.manual or (MANUAL_CLIPS and not AUTO_SELECT_CLIPS)
    if use_manual_clips:
        clips = normalize_manual_clips(MANUAL_CLIPS)
        print(f"Modo manual ativo: {len(clips)} clipes configurados, sem transcricao.")
    elif AUTO_SELECT_CLIPS:
        if not segments:
            if not ALLOW_WHISPER_FALLBACK:
                raise RuntimeError(
                    "Falha ao obter a legenda do YouTube e o fallback Whisper esta desativado."
                ) from transcript_error

            print("Baixando audio para fallback com Whisper...")
            video_path = run_with_retries(
                f"Download do video {selected_video_url}",
                lambda: download_video(selected_video_url, workspace.videos / f"source_{source_index:02d}", audio_only=True),
            )
            print(f"Video salvo em {video_path}")
            print("Transcrevendo video no modo de baixo consumo...")
            segments = run_with_retries(
                f"Transcricao do video {selected_video_url}",
                lambda: transcribe_video(video_path, model_name=str(args.model), language=args.language),
            )
            print(f"Transcricao concluida com {len(segments)} segmentos.")

        clips = build_clip_plan(
            segments,
            clip_count=clip_count,
            min_duration=CLIP_MIN_DURATION,
            max_duration=CLIP_MAX_DURATION,
        )
    else:
        raise RuntimeError(
            "AUTO_SELECT_CLIPS esta desativado e nenhum clipe manual foi configurado."
        )

    if not clips:
        raise RuntimeError("Nenhum clipe foi encontrado a partir da transcricao.")

    clips = enrich_clips_with_metadata(clips, segments)

    # Filtra clipes duplicados (ja publicados recentemente)
    video_id = extract_video_id(selected_video_url)
    clips = filter_duplicate_clips(clips, video_id)

    attempt_id = uuid4().hex[:12]
    for index, clip in enumerate(clips, start=1):
        raw_clip_path = workspace.videos / f"source_{source_index:02d}" / f"raw_clip_{index:02d}.mp4"
        clip_path = workspace.clips / f"clip_{source_index:02d}_{index:02d}_{attempt_id}.mp4"
        
        print(f"Baixando seção parcial via Web do clipe {index}/{len(clips)}...")
        run_with_retries(
            f"Download parcial do clipe {index}",
            lambda _c=clip, _p=raw_clip_path: download_clip_section(
                selected_video_url, float(_c["start"]), float(_c["end"]), _p
            ),
        )
        generated_files.append(raw_clip_path)
        
        print(f"Formatando clipe {index}/{len(clips)} para formato vertical...")
        run_with_retries(
            f"Corte do clipe {clip_path.name}",
            lambda _vp=raw_clip_path, _p=clip_path: cut_clip(_vp, output_path=_p),
        )
        generated_files.append(clip_path)

        title = str(clip["title"])
        description = str(clip.get("description", title))
        hashtags = [str(tag) for tag in clip.get("hashtags", [])]

        payload = {
            "video_path": clip_path,
            "title": title,
            "description": description,
            "tags": hashtags,
            "source_url": selected_video_url,
            "video_id": video_id,
            "start": clip.get("start", 0),
            "end": clip.get("end", 0),
        }
        workspace.register_clip(payload)

        if args.dry_run:
            print(f"[DRY RUN] Clipe pronto: {clip_path}")
            print(f"[DRY RUN] Titulo: {title}")
            print(f"[DRY RUN] Hashtags: {' '.join(hashtags)}")
            description_preview = description if len(description) <= 240 else f"{description[:237].rstrip()}..."
            print(f"[DRY RUN] Descricao: {description_preview}")
            continue

        upload_queue.append(payload)

    return upload_queue, generated_files


def enabled_uploaders():
    uploaders = {}
    if YOUTUBE_UPLOAD_ENABLED:
        def youtube(videos, **callbacks):
            return upload_youtube_videos(videos, privacy_status=YOUTUBE_PRIVACY_STATUS,
                                         category_id=YOUTUBE_CATEGORY_ID, **callbacks)
        uploaders["youtube"] = youtube
    if TIKTOK_UPLOAD_ENABLED:
        uploaders["tiktok"] = upload_tiktok_videos
    if INSTAGRAM_UPLOAD_ENABLED:
        uploaders["instagram"] = upload_instagram_videos
    if FACEBOOK_UPLOAD_ENABLED:
        uploaders["facebook"] = upload_facebook_videos
    return uploaders


def show_queue(store):
    rows = store.list_deliveries()
    if not rows:
        print("Fila vazia.")
    for row in rows:
        print(f"{row['id']} | {row['platform']} | {row['state']} | {row['payload']['title']}")
        if row['error']:
            print(f"  {row['error']}")
        if row['receipt']:
            print(f"  Comprovante: {row['receipt']}")


def cleanup_confirmed(store, workspace):
    if not workspace.cleanup:
        return
    completed = store.completed_clip_ids()
    seen = set()
    for row in store.list_deliveries():
        if not row['owned'] or row['clip_id'] not in completed or row['clip_id'] in seen:
            continue
        seen.add(row['clip_id'])
        path = Path(row['payload']['video_path'])
        if not path.exists():
            continue
        marker = path.parent / '.run.json'
        try:
            if marker.exists() and json.loads(marker.read_text(encoding='utf-8')).get('keep'):
                continue
        except (OSError, ValueError):
            continue
        remove_temp_path(path, workspace.clips_root)
    current = workspace.manifest['clips']
    if current and all(clip.get('clip_id') in completed for clip in current):
        workspace.mark_uploads_complete()


def main() -> None:
    args = parse_args()
    try:
        with RunLock(BASE_DIR / ".podcast_automation.lock"):
            with PublicationStore(PUBLICATION_DB, HISTORY_FILE) as store:
                store.recover()
                if args.queue_status:
                    show_queue(store)
                    return
                if args.resolve_delivery is not None:
                    store.resolve(args.resolve_delivery, args.resolution, args.resolution_note, args.post_url)
                    print("Revisao registrada. Nenhum envio foi realizado.")
                    return
                with TempWorkspace(
                    TEMP_VIDEOS_DIR, TEMP_CLIPS_DIR,
                    cleanup=CLEANUP_TEMP_FILES and not args.no_cleanup,
                    retention_days=TEMP_PENDING_RETENTION_DAYS,
                    legacy_hours=TEMP_LEGACY_MAX_AGE_HOURS,
                    protected_path=Path(args.input_video).expanduser() if args.input_video else None,
                    protected_paths=store.protected_paths(),
                ) as workspace:
                    if args.repair_delivery is not None:
                        repair_delivery(store, args.repair_delivery, workspace)
                        return
                    run_pipeline(args, workspace, store)
    except AlreadyRunningError as exc:
        print(exc)


def run_pipeline(args: argparse.Namespace, workspace: TempWorkspace, store: PublicationStore) -> None:
    uploaders = enabled_uploaders()
    if not args.dry_run and not uploaders:
        print("Nenhuma plataforma habilitada; nenhum novo clipe sera gerado.")
        return

    def deliver():
        counts = dispatch_pending(store, uploaders)
        cleanup_confirmed(store, workspace)
        print(f"Entregas: {counts['confirmed']} confirmadas, {counts['failed']} falhas, {counts['uncertain']} incertas.")
        if counts['failed'] or counts['uncertain']:
            raise RuntimeError("Fila preservada: ha entregas com falha ou publicacao incerta.")

    backlog = [row for row in store.list_deliveries()
               if row['platform'] in uploaders and row['state'] in {'pending', 'failed', 'uncertain'}]
    if not args.dry_run and not args.input_video and (backlog or getattr(args, 'retry_pending', False)):
        deliver()
        if any(row['state'] == 'uncertain' for row in backlog):
            print("Ha entregas incertas. Use --queue-status e revise a plataforma antes de liberar reenvio.")
        return

    if args.input_video:
        queue, _, original = _build_local_upload_queue(args)
        if args.dry_run:
            print(f"[DRY RUN] Video local preservado, sem upload: {original}")
            return
        store.enqueue(queue[0], uploaders, owned=False)
        deliver()
        return

    if not args.dry_run:
        workspace.on_clip_ready = lambda payload: store.enqueue(
            payload, uploaders, owned=True, retention_days=TEMP_PENDING_RETENTION_DAYS,
        )
    schedule_map = load_source_schedules()
    queue_mode = bool(args.queue)
    source_urls = resolve_source_urls(args, queue_mode=queue_mode, schedule_map=schedule_map)
    if not source_urls:
        raise ValueError("Defina uma fonte autorizada valida.")
    if args.manual and not MANUAL_CLIPS:
        raise RuntimeError("Modo manual ativado, mas MANUAL_CLIPS esta vazio.")
    clip_count = int(args.clip_count)
    if clip_count < 1:
        raise ValueError("A quantidade de shorts precisa ser pelo menos 1.")
    errors = []
    for index, source in enumerate(source_urls, 1):
        try:
            queue, _ = run_with_retries(
                f"Processamento da fonte {source}",
                lambda: process_source_url(source, args, clip_count, schedule_map, index, workspace),
            )
            if not queue_mode and (queue or (args.dry_run and workspace.manifest['clips'])):
                break
        except Exception as exc:
            errors.append(str(exc))
            print(f"Falha na fonte {source}: {exc}")
    if not args.dry_run:
        deliver()
    if errors and not workspace.manifest['clips']:
        raise RuntimeError("Nao foi possivel gerar cortes: " + '; '.join(errors))


if __name__ == "__main__":
    main()
