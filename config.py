from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

PODCAST_URL = "https://www.youtube.com/watch?v=SEU_VIDEO_AQUI"
LOW_RESOURCE_MODE = True
HEADLESS_MODE = True  # Se True, executa navegadores invisíveis em segundo plano
WHISPER_MODEL = "tiny"
WHISPER_LANGUAGE: str | None = "pt"
WHISPER_THREADS = 1
TRANSCRIPT_LANGUAGE_PREFERENCES = ["pt", "pt-BR", "pt-PT", "en"]
ALLOW_WHISPER_FALLBACK = True

TEMP_VIDEOS_DIR = BASE_DIR / "temp_videos"
TEMP_CLIPS_DIR = BASE_DIR / "temp_clips"
YOUTUBE_COOKIES_FILE = BASE_DIR / "cookies.txt"

CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
TOKEN_FILE = BASE_DIR / "token.json"

MANUAL_CLIPS: list[dict[str, float | str]] = []
AUTO_SELECT_CLIPS = True

# --- Google Gemini AI Curation ---
USE_AI_CURATION = True
import os
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

CLIP_COUNT = 1
CLIP_MIN_DURATION = 15.0
CLIP_MAX_DURATION = 55.0
QUEUE_MODE = False
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5.0

AUTHORIZED_SOURCE_URLS: list[str] = [
	"https://www.youtube.com/channel/UCxofEyVnYeyIIljOzCqH70A/videos",
]
# Quantos videos recentes considerar por fonte ao escolher aleatoriamente.
AUTHORIZED_SOURCE_VIDEO_LIMIT = 10
AUTHORIZED_SOURCES_FILE = BASE_DIR / "authorized_sources.txt"
SOURCE_SCHEDULES_FILE = BASE_DIR / "source_schedules.json"

YOUTUBE_CATEGORY_ID = "22"
YOUTUBE_PRIVACY_STATUS = "public"
YOUTUBE_UPLOAD_ENABLED = True

TIKTOK_UPLOAD_ENABLED = True
TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=webapp&lang=pt-BR"
TIKTOK_LOGIN_URL = "https://www.tiktok.com/login/phone-or-email/email?lang=pt-BR"
TIKTOK_USER_DATA_DIR = BASE_DIR / "browser_data_tiktok"
TIKTOK_CAPTION_MAX_CHARS = 2200

INSTAGRAM_UPLOAD_ENABLED = True
INSTAGRAM_URL = "https://www.instagram.com/"
INSTAGRAM_USER_DATA_DIR = BASE_DIR / "browser_data_instagram"
INSTAGRAM_CAPTION_MAX_CHARS = 2200

FACEBOOK_UPLOAD_ENABLED = True
FACEBOOK_URL = "https://www.facebook.com/"
FACEBOOK_USER_DATA_DIR = BASE_DIR / "browser_data_facebook"
FACEBOOK_CAPTION_MAX_CHARS = 2200

# --- Hashtags Estratégicas (Pesquisa Mercado Brasileiro 2026) ---
# Arquitetura: base universal (YouTube Shorts obrigatório) + amplificadores virais
# Sweet Spot validado: 3-6 hashtags por post (mais que isso = penalização por hashtag stuffing)
HASHTAGS = [
    # --- OBRIGATÓRIAS (YouTube Shorts SEO) ---
    "#Shorts",         # Tag técnica mandatória — sem ela o vídeo flutua sem classificação
    "#viral",          # Farol de viralidade — 2ª tag mais importante segundo a pesquisa
    # --- AMPLIFICADORES BRASILEIROS (TikTok FYP + YouTube discovery) ---
    "#podcast",        # Identidade do conteúdo + nicho de busca ativo no BR
    "#motivacao",      # Alta densidade de busca no segmento BR/pt-BR
    "#empreendedorismo", # Cluster B2B/educacional — pico de engajamento 18h-20h semana
    "#sucesso",        # Gatilho emocional — alta taxa de save/compartilhamento
]

# Tags extras exclusivas do TikTok (adicionadas ao caption além das HASHTAGS acima)
# Limite TikTok: 3-6 tags — priorizando FYP seed audience e descoberta algorítmica
TIKTOK_EXTRA_HASHTAGS = [
    "#foryou",         # Sinaliza ao algoritmo desejo de distribuição FYP ampla
    "#fyp",            # Variante primária do FYP — maior volume de anexos no BR
    "#foryoupage",     # Variante secundária para cobertura máxima
    "#tiktokbrasil",   # Direciona para feed nacional (evita entrega fora do BR)
    "#trending",       # Associa o vídeo às correntes de tendência ativas
    "#viralbrasil",    # Subcorrente viral localizada — concorrência menor que #viral
]

# Limite de hashtags por post — NÃO aumente: acima de 6 ativa filtro antispam
MAX_POST_HASHTAGS = 6
DESCRIPTION_MAX_CHARS = 800
CLIP_TITLE_PREFIX = "Trecho que vale ouro"

CLEANUP_TEMP_FILES = True
TEMP_PENDING_RETENTION_DAYS = 7
TEMP_LEGACY_MAX_AGE_HOURS = 24

# Detecção de duplicatas
HISTORY_FILE = BASE_DIR / "historico.json"
PUBLICATION_DB = BASE_DIR / "publicacoes.sqlite3"
HISTORY_VIDEO_DAYS = 30     # Nao reusar o mesmo video por N dias
HISTORY_CLIP_DAYS = 90      # Nao reusar o mesmo trecho por N dias
VERTICAL_OUTPUT = True
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
FFMPEG_PRESET = "ultrafast"
FFMPEG_THREADS = 1
FFMPEG_CRF = 20
AUDIO_BITRATE = "160k"

# --- Anti-Detecção de Vídeo (TikTok Content ID bypass) ---
# Aplica transformações sutis ao vídeo para invalidar o hash perceptual
# usado pelo TikTok para identificar conteúdo repostado.
ANTI_DETECTION_ENABLED = True
ANTI_DETECTION_HFLIP = True                 # Espelhamento horizontal
ANTI_DETECTION_SPEED_RANGE = (1.03, 1.07)   # Faixa de micro-aceleração
ANTI_DETECTION_ZOOM_RANGE = (0.02, 0.05)    # Faixa de zoom (% de crop nas bordas)
