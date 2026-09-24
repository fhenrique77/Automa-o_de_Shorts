"""Publication evidence and a single-submit boundary shared by browser uploaders."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import re
import time
from urllib.parse import urlparse


SUCCESS_PATTERNS = {
    "youtube": r"(?:Video published|Vídeo publicado|Video saved|Vídeo salvo)[.!]?",
    "tiktok": r"(?:Your video has been posted|Your video has been published|Video published|Published successfully|Seu vídeo foi publicado|Vídeo publicado|Publicado com sucesso)[.!]?",
    "instagram": r"(?:Your (?:reel|post) has been shared|Seu reel foi compartilhado|Sua publicação foi compartilhada|Seu vídeo foi compartilhado|Reel compartilhado|Reel shared)[.!]?",
    "facebook": r"(?:Your reel (?:has been published|has been shared|was published|was shared)|Seu reel foi publicado|Seu reel foi compartilhado|Reel publicado com sucesso)[.!]?",
}


@dataclass(frozen=True)
class PublicationReceipt:
    platform: str
    evidence: str
    confirmed_at: str
    post_url: str | None = None

    def to_dict(self):
        return asdict(self)


class PublicationUncertainError(RuntimeError):
    """A submit may have succeeded: never automatically submit it again."""


def valid_post_url(platform: str, url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower().removeprefix("www.")
    patterns = {
        "youtube": (host in {"youtube.com", "youtu.be"} and
                    (bool(re.fullmatch(r"/[\w-]{11}", parsed.path)) if host == "youtu.be" else
                     bool(re.fullmatch(r"/shorts/[\w-]{11}/?", parsed.path)) or
                     (parsed.path == "/watch" and bool(re.search(r"(?:^|&)v=[\w-]{11}(?:&|$)", parsed.query))))),
        "tiktok": host == "tiktok.com" and bool(re.fullmatch(r"/@[^/]+/video/\d+/?", parsed.path)),
        "instagram": host == "instagram.com" and bool(re.fullmatch(r"/(?:reel|p)/[\w-]+/?", parsed.path)),
        "facebook": host == "facebook.com" and bool(re.fullmatch(r"/reel/\d+/?", parsed.path)),
    }
    return bool(patterns.get(platform))


def _success_locator(page, platform):
    return page.get_by_text(re.compile(r"^" + SUCCESS_PATTERNS[platform] + r"$", re.I))


def _visible_messages(page, platform):
    matches = _success_locator(page, platform)
    result = []
    for index in range(matches.count()):
        locator = matches.nth(index)
        if locator.is_visible():
            result.append((locator, locator.inner_text().strip()))
    return result


class PublicationAttempt:
    def __init__(self, platform, on_submitting=None, on_confirmed=None):
        self.platform = platform
        self.on_submitting = on_submitting
        self.on_confirmed = on_confirmed
        self.submitted = False
        self.baseline = set()
        self.receipt = None

    def before_submit(self, page):
        if self.submitted:
            raise PublicationUncertainError("O comando de publicar ja foi enviado; confira a plataforma.")
        self.baseline = {text for _, text in _visible_messages(page, self.platform)}
        # Commit the uncertainty boundary BEFORE interacting with the remote page.
        if self.on_submitting:
            self.on_submitting()
        self.submitted = True

    def confirm(self, page, timeout_ms=120000, on_wait=None):
        if not self.submitted:
            raise RuntimeError("Confirmacao solicitada antes de publicar.")
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            for locator, text in _visible_messages(page, self.platform):
                if text in self.baseline:
                    continue
                post_url = None
                # Only use links within the confirmation container, never unrelated feed links.
                scope = locator.locator("xpath=ancestor::*[@role='dialog' or @role='alert' or @role='status' or local-name()='ytcp-video-share-dialog'][1]")
                if scope.count():
                    links = scope.locator("a[href]")
                    for index in range(links.count()):
                        href = links.nth(index).get_attribute("href") or ""
                        if valid_post_url(self.platform, href):
                            post_url = href
                            break
                receipt = PublicationReceipt(self.platform, text, datetime.now(timezone.utc).isoformat(), post_url)
                if self.on_confirmed:
                    self.on_confirmed(receipt)
                self.receipt = receipt
                return receipt
            if time.monotonic() >= deadline:
                raise PublicationUncertainError("Sem confirmacao explicita da plataforma apos publicar; reenvio bloqueado.")
            if on_wait:
                on_wait()
            page.wait_for_timeout(500)


def perform_upload(operation, attempt):
    """One attempt only. Failures after the submit boundary must never be retried."""
    try:
        operation()
        if attempt.receipt is None:
            raise RuntimeError("O uploader terminou sem comprovante de publicacao.")
        return attempt.receipt
    except Exception as exc:
        if attempt.submitted and attempt.receipt is None:
            raise PublicationUncertainError(str(exc)) from exc
        raise
