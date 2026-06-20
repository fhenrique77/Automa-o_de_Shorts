from __future__ import annotations

import importlib
import re
import unicodedata
import threading
from collections import Counter
from urllib.parse import parse_qs, urlparse
import subprocess
from pathlib import Path
import json
from typing import Any

from config import (
    AUDIO_BITRATE,
    CLIP_COUNT,
    CLIP_MAX_DURATION,
    CLIP_MIN_DURATION,
    CLIP_TITLE_PREFIX,
    DESCRIPTION_MAX_CHARS,
    LOW_RESOURCE_MODE,
    FFMPEG_CRF,
    FFMPEG_PRESET,
    FFMPEG_THREADS,
    HASHTAGS,
    MAX_POST_HASHTAGS,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    TEMP_CLIPS_DIR,
    VERTICAL_OUTPUT,
    WHISPER_THREADS,
    WHISPER_LANGUAGE,
    WHISPER_MODEL,
)
from utils import resolve_ffmpeg_executable, resolve_ytdlp_js_runtimes

CONTENT_HASHTAG_RULES = (
    # Financas e negocios
    ("mercado imobiliario", "#imoveis"),
    ("imovel", "#imoveis"),
    ("imoveis", "#imoveis"),
    ("ganhar dinheiro", "#dinheiro"),
    ("dinheiro", "#dinheiro"),
    ("renda", "#renda"),
    ("investimento", "#investimentos"),
    ("investimentos", "#investimentos"),
    ("financas", "#financas"),
    ("bolsa", "#bolsadevalores"),
    ("acoes", "#acoes"),
    ("cripto", "#cripto"),
    ("bitcoin", "#bitcoin"),
    ("venda", "#vendas"),
    ("vendas", "#vendas"),
    ("empreendedor", "#empreendedorismo"),
    ("empreendedorismo", "#empreendedorismo"),
    ("negocio", "#negocios"),
    ("negocios", "#negocios"),
    ("marketing", "#marketing"),
    ("marca", "#branding"),
    # Desenvolvimento pessoal
    ("conteudo", "#conteudo"),
    ("produtividade", "#produtividade"),
    ("lideranca", "#lideranca"),
    ("carreira", "#carreira"),
    ("disciplina", "#disciplina"),
    ("foco", "#foco"),
    ("habito", "#habitos"),
    ("habitos", "#habitos"),
    ("motivacao", "#motivacao"),
    ("sucesso", "#sucesso"),
    ("crescimento", "#crescimentopessoal"),
    ("autoconhecimento", "#autoconhecimento"),
    ("proposito", "#proposito"),
    ("mentalidade", "#mentalidade"),
    ("mindset", "#mindset"),
    # Saude e bem-estar
    ("saude", "#saude"),
    ("saude mental", "#saudemental"),
    ("ansiedade", "#ansiedade"),
    ("depressao", "#depressao"),
    ("terapia", "#terapia"),
    ("psicologia", "#psicologia"),
    ("trauma", "#trauma"),
    ("exercicio", "#fitness"),
    ("treino", "#treino"),
    ("dieta", "#dieta"),
    ("alimentacao", "#alimentacao"),
    ("sono", "#qualidadedevida"),
    # Relacionamentos
    ("relacionamento", "#relacionamento"),
    ("familia", "#familia"),
    ("casal", "#relacionamento"),
    ("amor", "#amor"),
    ("amizade", "#amizade"),
    # Tecnologia e educacao
    ("tecnologia", "#tecnologia"),
    ("inteligencia artificial", "#ia"),
    ("chatgpt", "#chatgpt"),
    ("openai", "#openai"),
    ("programacao", "#programacao"),
    ("educacao", "#educacao"),
    ("faculdade", "#faculdade"),
    ("estudo", "#estudos"),
    # Midia
    ("youtube", "#youtube"),
    ("podcast", "#podcast"),
    ("rede social", "#redessociais"),
    ("instagram", "#instagram"),
    ("tiktok", "#tiktok"),
    # Conteudo e engajamento
    ("estrategia", "#estrategia"),
    ("segredo", "#segredo"),
    ("dica", "#dica"),
    ("erro", "#erro"),
    ("verdade", "#verdade"),
    ("historia", "#historia"),
    ("experiencia", "#experiencia"),
    # Espiritualidade e fe (conteudo atual do canal)
    ("deus", "#espiritualidade"),
    ("jesus", "#jesus"),
    ("fe", "#fe"),
    ("espiritualidade", "#espiritualidade"),
    ("biblia", "#biblia"),
    ("oracao", "#oracao"),
    ("crenca", "#fe"),
    ("religiao", "#religiao"),
    ("vida eterna", "#fe"),
    ("espirito", "#espiritualidade"),
    ("cosmos", "#cosmos"),
    ("universo", "#universo"),
    ("espaco", "#cosmos"),
    ("ciencia", "#ciencia"),
    ("descoberta", "#curiosidades"),
    # IA e tecnologia 2026 (alta tração no BR)
    ("inteligencia artificial", "#inteligenciaartificial"),
    ("ia", "#inteligenciaartificial"),
    ("ai", "#ai"),
    ("futuro", "#futuro"),
    ("inovacao", "#inovacao"),
    # GymTok / Fitness (30M+ tags global)
    ("academia", "#gymtok"),
    ("musculacao", "#gymtok"),
    ("emagrecimento", "#emagrecer"),
    ("corpo", "#fitness"),
    ("proteina", "#fitness"),
    # Humor e entretenimento
    ("engraçado", "#humor"),
    ("comedia", "#comedy"),
    ("meme", "#memes"),
    ("piada", "#humor"),
    # Curiosidades e conhecimento
    ("curiosidade", "#curiosidades"),
    ("fato", "#curiosidades"),
    ("voce sabia", "#vocesabia"),
    ("incrivel", "#incrivel"),
    ("surpreendente", "#curiosidades"),
)

STOPWORDS = {
    "a",
    "o",
    "os",
    "as",
    "um",
    "uma",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "ou",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "por",
    "para",
    "com",
    "sem",
    "que",
    "se",
    "eu",
    "vc",
    "voce",
    "voces",
    "ele",
    "ela",
    "eles",
    "elas",
    "isso",
    "essa",
    "esse",
    "essas",
    "esses",
    "aqui",
    "ali",
    "entao",
    "tambem",
    "muito",
    "muita",
    "muitos",
    "muitas",
    "porque",
    "quando",
    "onde",
    "como",
    "sobre",
    "mais",
    "menos",
    "meio",
    "ja",
    "nao",
    "sim",
    "tipo",
    "pra",
    "pro",
    "ser",
    "ter",
}

TITLE_HOOKS = (
    (("erro",), "O erro que quase todo mundo comete"),
    (("segredo", "revelacao", "revelação"), "O que ninguem te conta"),
    (("dica",), "Essa dica vale ouro"),
    (("como",), "Como isso funciona na pratica"),
    (("por que",), "Por que isso importa"),
    (("dinheiro", "renda", "investimento", "investimentos"), "Como ganhar dinheiro com isso"),
    (("podcast",), "O trecho que vale ouro"),
)

TITLE_FALLBACK_HOOKS = (
    "Veja isso",
    "Trecho forte",
    "Nao perca isso",
    "O ponto mais importante",
)

DESCRIPTION_TEMPLATES = (
    {
        "title_emoji": "🔥",
        "summary_emoji": "💬",
        "cta": "🎯 Gostou do corte? Não esqueça de deixar o seu LIKE e SE INSCREVER no canal para não perder os próximos vídeos!",
    },
    {
        "title_emoji": "💡",
        "summary_emoji": "📝",
        "cta": "👉 Curte, comenta e compartilha com alguém que precisa ouvir isso! 🔔 Ative o sininho!",
    },
    {
        "title_emoji": "⚡",
        "summary_emoji": "🗣️",
        "cta": "❤️ Se esse trecho te impactou, deixa o LIKE e segue o canal! Sua força nos motiva a continuar! 💪",
    },
    {
        "title_emoji": "🎙️",
        "summary_emoji": "✨",
        "cta": "🔔 Quer mais cortes como esse? Se inscreve e ativa as notificações pra não perder nenhum!",
    },
    {
        "title_emoji": "💎",
        "summary_emoji": "💭",
        "cta": "🚀 Salva esse vídeo e manda pra quem precisa ouvir! Conhecimento bom é pra ser compartilhado! 📲",
    },
    {
        "title_emoji": "🧠",
        "summary_emoji": "📌",
        "cta": "⭐ Esse tipo de conteúdo te agrada? Deixa o like e se inscreve no canal! Vem com a gente! 🙌",
    },
    {
        "title_emoji": "🎯",
        "summary_emoji": "🔍",
        "cta": "💬 Comenta aqui embaixo o que você achou desse trecho! Sua opinião é muito importante pra gente! ✅",
    },
    {
        "title_emoji": "🏆",
        "summary_emoji": "📣",
        "cta": "👊 Marca aquele amigo que precisa ouvir isso! Não esquece do LIKE e de SE INSCREVER!",
    },
)


def fetch_youtube_transcript_segments(
    youtube_url: str,
    languages: list[str] | None = None,
) -> list[dict[str, float | str]]:
    from config import TRANSCRIPT_LANGUAGE_PREFERENCES, YOUTUBE_COOKIES_FILE
    preferred_languages = languages or TRANSCRIPT_LANGUAGE_PREFERENCES

    import yt_dlp
    import json
    import urllib.request
    
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': preferred_languages,
        'dump_single_json': True,
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {'youtube': ['player-client=android,web,default']},
        'js_runtimes': resolve_ytdlp_js_runtimes(),
        'remote_components': ['ejs:github'],
    }
    if YOUTUBE_COOKIES_FILE and YOUTUBE_COOKIES_FILE.exists():
        ydl_opts['cookiefile'] = str(YOUTUBE_COOKIES_FILE)

    transcript_api_segments = _fetch_youtube_transcript_api_segments(
        youtube_url,
        preferred_languages,
    )
    if transcript_api_segments:
        return transcript_api_segments
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=False)
    except Exception as exc:
        raise RuntimeError(f"Erro yt_dlp extraindo legenda: {exc}") from exc

    subs_info = info_dict.get('subtitles', {})
    if not subs_info:
        subs_info = info_dict.get('automatic_captions', {})
        
    if not subs_info:
        transcript_api_segments = _fetch_youtube_transcript_api_segments(
            youtube_url,
            preferred_languages,
        )
        if transcript_api_segments:
            return transcript_api_segments

        raise RuntimeError("Esse video nao possui legendas disponiveis nem automaticas.")

    selected_lang = None
    for lang in preferred_languages:
        if lang in subs_info:
            selected_lang = lang
            break
            
    if not selected_lang:
        selected_lang = list(subs_info.keys())[0]
        
    sub_formats = subs_info[selected_lang]
    json3_entry = next((fmt for fmt in sub_formats if fmt.get('ext') == 'json3'), None)
    
    if not json3_entry:
        raise RuntimeError("Nao foi possivel encontrar o formato json3 da legenda.")
        
    try:
        req = urllib.request.Request(json3_entry['url'])
        with urllib.request.urlopen(req) as response:
            sub_data = json.loads(response.read().decode())
    except Exception as exc:
        transcript_api_segments = _fetch_youtube_transcript_api_segments(
            youtube_url,
            preferred_languages,
        )
        if transcript_api_segments:
            return transcript_api_segments

        raise RuntimeError(f"Erro ao baixar json3 da legenda: {exc}") from exc
        
    segments: list[dict[str, float | str]] = []
    
    events = sub_data.get('events', [])
    for event in events:
        if 'segs' not in event or 'tStartMs' not in event:
            continue
            
        start_sec = event['tStartMs'] / 1000.0
        duration_sec = event.get('dDurationMs', 0) / 1000.0
        end_sec = start_sec + duration_sec
        
        text = "".join([seg.get('utf8', '') for seg in event['segs']]).strip()
        if not text:
            continue
            
        segments.append({
            "start": float(start_sec),
            "end": float(end_sec),
            "text": text
        })

    if not segments:
        raise RuntimeError("A legenda esta vazia.")
        
    return segments


def _fetch_youtube_transcript_api_segments(
    youtube_url: str,
    preferred_languages: list[str],
) -> list[dict[str, float | str]] | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None

    try:
        transcript = YouTubeTranscriptApi().fetch(
            extract_video_id(youtube_url),
            languages=preferred_languages,
        )
    except Exception:
        return None

    segments: list[dict[str, float | str]] = []
    for snippet in transcript:
        text = str(snippet.text).strip()
        if not text:
            continue

        start = float(snippet.start)
        end = start + float(snippet.duration)
        segments.append({
            "start": start,
            "end": end,
            "text": text,
        })

    return segments or None


def transcribe_video(
    video_path: str | Path,
    model_name: str = WHISPER_MODEL,
    language: str | None = WHISPER_LANGUAGE,
) -> list[dict[str, float | str]]:
    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Arquivo de video nao encontrado: {video_file}")

    try:
        whisper = importlib.import_module("whisper")
    except ImportError as exc:
        raise RuntimeError(
            "Instale openai-whisper e torch antes de transcrever o video."
        ) from exc

    try:
        torch = importlib.import_module("torch")
    except ImportError as exc:
        raise RuntimeError("Instale torch antes de transcrever o video.") from exc

    try:
        torch.set_num_threads(max(1, int(WHISPER_THREADS)))
        torch.set_num_interop_threads(1)
    except (RuntimeError, TypeError, ValueError):
        pass

    model = whisper.load_model(model_name, device="cpu")
    transcribe_kwargs: dict[str, Any] = {"fp16": False}
    if language:
        transcribe_kwargs["language"] = language

    result = model.transcribe(str(video_file), **transcribe_kwargs)
    segments: list[dict[str, float | str]] = []
    for segment in result.get("segments", []):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            {
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "text": text,
            }
        )

    return segments


def extract_video_id(youtube_url: str) -> str:
    parsed_url = urlparse(youtube_url)
    if parsed_url.hostname in {"youtu.be"}:
        video_id = parsed_url.path.lstrip("/")
        if video_id:
            return video_id

    if parsed_url.hostname and "youtube.com" in parsed_url.hostname:
        query_value = parse_qs(parsed_url.query).get("v", [""])[0]
        if query_value:
            return query_value

    raise ValueError(f"Nao foi possivel extrair o ID do video a partir da URL: {youtube_url}")


def normalize_manual_clips(clips: list[dict[str, float | str]]) -> list[dict[str, float | str]]:
    normalized_clips: list[dict[str, float | str]] = []
    for index, clip in enumerate(clips, start=1):
        start = float(clip["start"])
        end = float(clip["end"])
        if end <= start:
            raise ValueError(f"O clipe manual {index} precisa ter end maior que start.")
        title = str(clip.get("title") or f"{CLIP_TITLE_PREFIX} {index}")
        normalized_clips.append({"start": start, "end": end, "title": title})
    return normalized_clips


def _build_clip_plan_heuristic(
    segments: list[dict[str, float | str]],
    clip_count: int = CLIP_COUNT,
    min_duration: float = CLIP_MIN_DURATION,
    max_duration: float = CLIP_MAX_DURATION,
) -> list[dict[str, float | str]]:
    if not segments:
        return []

    total_duration = max(float(segment["end"]) for segment in segments)
    target_duration = min(max_duration, max(min_duration, total_duration / max(clip_count, 1)))
    anchors = _build_anchor_points(total_duration, clip_count)

    clips: list[dict[str, float | str]] = []
    for index, anchor in enumerate(anchors, start=1):
        start, end = _build_window(anchor, target_duration, total_duration, min_duration, max_duration)
        text = _collect_text(segments, start, end)
        title = _build_title(text, index)
        clips.append({"start": round(start, 2), "end": round(end, 2), "title": title})

    return clips


def enrich_clips_with_metadata(
    clips: list[dict[str, float | str]],
    segments: list[dict[str, float | str]] | None = None,
) -> list[dict[str, float | str | list[str]]]:
    enriched_clips: list[dict[str, float | str | list[str]]] = []

    for clip in clips:
        start = float(clip["start"])
        end = float(clip["end"])
        title = str(clip.get("title") or CLIP_TITLE_PREFIX)
        # Limpa >> do titulo
        title = title.replace(">>", "").replace("<<", "").strip()
        title = " ".join(title.split())  # remove espacos duplicados
        clip_text = _collect_text(segments, start, end) if segments else ""

        # Se o clip ja veio com description da IA, preserva; senao, gera
        existing_description = str(clip.get("description", "")).strip()
        existing_hashtags = clip.get("hashtags", [])
        has_ai_metadata = bool(existing_description and existing_description != title)

        if has_ai_metadata:
            # IA ja forneceu descricao — limpa >> e usa direto
            description = existing_description.replace(">>", "").replace("<<", "").strip()
            hashtags = [str(h).replace(">>", "") for h in existing_hashtags] if existing_hashtags else _build_hashtags(title, clip_text)
            summary = _build_summary(title, clip_text)
        else:
            hashtags = _build_hashtags(title, clip_text)
            summary = _build_summary(title, clip_text)
            description = _build_description(title, summary, hashtags)

        enriched_clip = dict(clip)
        enriched_clip["title"] = title
        enriched_clip["summary"] = summary
        enriched_clip["hashtags"] = hashtags
        enriched_clip["description"] = description
        enriched_clips.append(enriched_clip)

    return enriched_clips


def cut_clip(
    video_path: str | Path,
    output_path: str | Path | None = None,
    vertical: bool = VERTICAL_OUTPUT,
) -> Path:
    ffmpeg_executable = resolve_ffmpeg_executable()

    video_file = Path(video_path)
    clip_file = Path(output_path) if output_path is not None else TEMP_CLIPS_DIR / "clip.mp4"
    clip_file.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg_executable,
        "-y",
        "-i",
        str(video_file),
        "-movflags",
        "+faststart",
        "-threads",
        str(max(1, int(FFMPEG_THREADS))),
    ]

    if vertical:
        command.extend(
            [
                "-vf",
                (
                    f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,"
                    f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2"
                ),
                "-c:v",
                "libx264",
                "-preset",
                FFMPEG_PRESET,
                "-crf",
                str(FFMPEG_CRF),
                "-c:a",
                "aac",
                "-b:a",
                AUDIO_BITRATE,
            ]
        )
    else:
        command.extend(
            [
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
            ]
        )

    command.append(str(clip_file))

    try:
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr_text = exc.stderr.decode("utf-8", errors="replace").strip() if exc.stderr else ""
        stdout_text = exc.stdout.decode("utf-8", errors="replace").strip() if exc.stdout else ""
        message = stderr_text or stdout_text or "Falha desconhecida ao cortar o clipe."
        raise RuntimeError(message) from exc

    return clip_file



def _build_anchor_points(total_duration: float, clip_count: int) -> list[float]:
    if clip_count <= 1:
        return [total_duration / 2]
    return [total_duration * (index + 1) / (clip_count + 1) for index in range(clip_count)]


def _build_window(
    anchor: float,
    duration: float,
    total_duration: float,
    min_duration: float,
    max_duration: float,
) -> tuple[float, float]:
    start = max(0.0, anchor - duration / 2)
    end = min(total_duration, start + duration)

    if end - start < min_duration:
        end = min(total_duration, start + min_duration)

    if end - start > max_duration:
        end = start + max_duration

    if end > total_duration:
        end = total_duration
        start = max(0.0, end - duration)

    return start, end


def _collect_text(segments: list[dict[str, float | str]], start: float, end: float) -> str:
    if not segments:
        return ""

    parts = []
    for segment in segments:
        if float(segment["end"]) > start and float(segment["start"]) < end:
            text = str(segment["text"]).strip()
            # Remove indicadores de mudanca de falante que o YouTube nao aceita
            text = text.replace(">>", "").replace("<<", "").strip()
            if text:
                parts.append(text)
    return " ".join(parts)


def _build_hashtags(title: str, text: str) -> list[str]:
    normalized_title = _normalize_text(title)
    normalized_text = _normalize_text(text)
    normalized_combined = f"{normalized_title} {normalized_text}".strip()

    hashtags: list[str] = []
    for base_hashtag in HASHTAGS:
        _append_unique(hashtags, base_hashtag)

    for keyword, hashtag in CONTENT_HASHTAG_RULES:
        if _contains_keyword(normalized_combined, keyword):
            _append_unique(hashtags, hashtag)

    focus_words = _extract_focus_words(normalized_combined)
    for word in focus_words:
        candidate_hashtag = f"#{word}"
        _append_unique(hashtags, candidate_hashtag)

    limit = MAX_POST_HASHTAGS if LOW_RESOURCE_MODE else MAX_POST_HASHTAGS + 2
    return hashtags[:limit]


def _build_summary(title: str, text: str) -> str:
    cleaned_text = " ".join(text.split())
    if cleaned_text:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned_text) if part.strip()]
        if sentences:
            summary = " ".join(sentences[:2]).strip()
        else:
            summary = cleaned_text
    else:
        summary = title.strip()

    summary = summary[:220].rstrip()
    if summary and summary[-1] not in ".!?":
        summary = summary.rstrip(",;:")
    return summary


def _build_description(title: str, summary: str, hashtags: list[str]) -> str:
    # Seleciona um template deterministicamente baseado no conteudo do titulo
    template_index = sum(ord(c) for c in title) % len(DESCRIPTION_TEMPLATES)
    template = DESCRIPTION_TEMPLATES[template_index]

    title_emoji = template["title_emoji"]
    summary_emoji = template["summary_emoji"]
    cta = template["cta"]

    lines = [
        f"{title_emoji} {title.strip()}",
        "",
        f"{summary_emoji} {summary.strip()}",
        "",
        cta,
        "",
        " ".join(hashtags)
    ]
    description = "\n".join(lines)
    if len(description) > DESCRIPTION_MAX_CHARS:
        description = description[:DESCRIPTION_MAX_CHARS].rstrip()
    return description


def _extract_focus_words(text: str, limit: int = 3) -> list[str]:
    tokens = [token for token in text.split() if len(token) >= 4 and token not in STOPWORDS]
    if not tokens:
        return []

    ranked_tokens = Counter(tokens)
    focus_words: list[str] = []
    for token, _ in ranked_tokens.most_common():
        if token in STOPWORDS or token.isdigit():
            continue
        _append_unique(focus_words, token)
        if len(focus_words) >= limit:
            break
    return focus_words


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized_keyword = _normalize_text(keyword)
    if " " in normalized_keyword:
        return normalized_keyword in text
    return normalized_keyword in text.split()


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _build_title(text: str, index: int) -> str:
    cleaned_text = " ".join(text.split())
    if not cleaned_text:
        return f"{CLIP_TITLE_PREFIX} {index}"

    hook = _select_title_hook(cleaned_text, index)
    snippet = _build_title_snippet(cleaned_text)

    if snippet:
        title = f"{hook}: {snippet}" if hook else snippet
    else:
        title = hook or f"{CLIP_TITLE_PREFIX} {index}"

    return _truncate_title(title, limit=72)


def _select_title_hook(text: str, index: int) -> str:
    normalized_text = _normalize_text(text)
    for keywords, hook in TITLE_HOOKS:
        if any(_contains_keyword(normalized_text, keyword) for keyword in keywords):
            return hook

    if TITLE_FALLBACK_HOOKS:
        return TITLE_FALLBACK_HOOKS[(max(index, 1) - 1) % len(TITLE_FALLBACK_HOOKS)]

    return CLIP_TITLE_PREFIX


def _build_title_snippet(text: str, limit: int = 7) -> str:
    words = [part.strip(".,;:!?\"'()[]{}") for part in text.split()]
    words = [word for word in words if word]

    while words and _normalize_text(words[0]) in STOPWORDS:
        words.pop(0)

    if not words:
        words = [part.strip(".,;:!?\"'()[]{}") for part in text.split() if part.strip(".,;:!?\"'()[]{}")]

    snippet = " ".join(words[:limit]).strip()
    if snippet and snippet[-1] not in ".!?":
        snippet = snippet.rstrip(",;:-")
    return snippet


def _truncate_title(title: str, limit: int) -> str:
    if len(title) <= limit:
        return title

    truncated = title[:limit].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip(" ,;:-")






def _build_clip_plan_ai(
    segments: list[dict[str, float | str]],
    clip_count: int,
    min_duration: float,
    max_duration: float,
    api_key: str,
) -> list[dict[str, float | str]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    transcript_lines = []
    for c in segments:
        s = float(c["start"])
        e = float(c["end"])
        t = str(c["text"]).strip()
        transcript_lines.append(f"[{s:.1f} - {e:.1f}] {t}")

    transcript_text = "\n".join(transcript_lines)

    prompt = f"""
Voce é um produtor de shorts viralizadores do TikTok.
Eu vou passar uma transcricao de um vídeo de podcast (com marcações de tempo).
Sua missão é escolher os {clip_count} melhores trechos independentes que entreguem curiosidade, choque ou uma grande lição.

Regras de Negocio:
1. MÍNIMO de duração de cada trecho: {min_duration} segundos.
2. MÁXIMO de duração: {max_duration} segundos.
3. Extraia o start e end respeitando os colchetes com precisão de 1 casa decimal.
4. Crie Títulos clickbait curtos em português.
5. Crie Descrições engajadoras que complementem o vídeo com algumas hashtags em alta.

RETORNO ESPERADO: Um Array JSON restrito ao seguinte esquema estrutural:
[
  {{
    "start": 10.0,
    "end": 64.5,
    "title": "A grande verdade",
    "description": "Você concorda com ele? #cortes",
    "hashtags": ["#viral", "#cortes"]
  }}
]

Transcrição a analisar:
{transcript_text[:500000]}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )
    raw_json = response.text.strip()

    if raw_json.startswith("```json"):
        raw_json = raw_json[7:]
    if raw_json.endswith("```"):
        raw_json = raw_json[:-3]

    ai_clips = json.loads(raw_json)

    clips = []
    for c in ai_clips[:clip_count]:
        raw_title = str(c["title"]).replace(">>", "").replace("<<", "").strip()
        raw_title = " ".join(raw_title.split())
        # Trunca titulo para 100 chars (limite do YouTube)
        if len(raw_title) > 100:
            raw_title = raw_title[:100].rstrip()
            if " " in raw_title:
                raw_title = raw_title.rsplit(" ", 1)[0]
            raw_title = raw_title.rstrip(" ,;:-")
        raw_desc = str(c.get("description", "")).replace(">>", "").replace("<<", "").strip()
        clips.append({
            "start": float(c["start"]),
            "end": float(c["end"]),
            "title": raw_title,
            "description": raw_desc,
            "hashtags": [str(h).replace(">>", "") for h in c.get("hashtags", [])]
        })
    return clips


def _build_clip_plan_ai_with_timeout(
    segments: list[dict[str, float | str]],
    clip_count: int,
    min_duration: float,
    max_duration: float,
    api_key: str,
    timeout_seconds: int = 30,
) -> list[dict[str, float | str]]:
    result: list[dict[str, float | str]] | None = None
    error: Exception | None = None

    def worker() -> None:
        nonlocal result, error
        try:
            result = _build_clip_plan_ai(segments, clip_count, min_duration, max_duration, api_key)
        except Exception as exc:
            error = exc

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    worker_thread.join(timeout_seconds)

    if worker_thread.is_alive():
        raise TimeoutError("Curadoria do Gemini AI excedeu o tempo limite.")

    if error is not None:
        raise error

    if result is None:
        raise RuntimeError("Curadoria do Gemini AI nao retornou clipes.")

    return result


def build_clip_plan(
    segments: list[dict[str, float | str]],
    clip_count: int = CLIP_COUNT,
    min_duration: float = CLIP_MIN_DURATION,
    max_duration: float = CLIP_MAX_DURATION,
) -> list[dict[str, float | str]]:
    if not segments:
        return []

    try:
        from config import USE_AI_CURATION, GEMINI_API_KEY
    except ImportError:
        USE_AI_CURATION = False
        GEMINI_API_KEY = ""

    if USE_AI_CURATION and GEMINI_API_KEY and GEMINI_API_KEY != "COLE SUA CHAVE AQUI DENTRO DAS ASPAS" and GEMINI_API_KEY != "":
        try:
            print("🧠 Acionando cerebro do Gemini AI para curadoria de cortes (ISSO PODE LEVAR ALGUNS SEGUNDOS)...")
            return _build_clip_plan_ai_with_timeout(
                segments,
                clip_count,
                min_duration,
                max_duration,
                GEMINI_API_KEY,
            )
        except Exception as e:
            print(f"Alerta: Falha na curadoria do Gemini AI ({e}). Executando fallback para matematica TF-IDF.")
    
    # Fallback to the original logic
    print("Curadoria por IA inativa ou sem chave/falhou. Usando matematica padrao.")
    return _build_clip_plan_heuristic(segments, clip_count, min_duration, max_duration)
