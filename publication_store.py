"""Durable delivery queue. Each clip/platform has an independently committed state."""
from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from publication import PublicationReceipt, valid_post_url


PLATFORMS = {"youtube", "tiktok", "instagram", "facebook"}


class PublicationStore(AbstractContextManager):
    def __init__(self, path: Path, legacy_history: Path | None = None):
        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS clips (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL,
                expires REAL, owned INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY, clip_id TEXT NOT NULL REFERENCES clips(id),
                platform TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL,
                error TEXT, receipt TEXT, UNIQUE(clip_id, platform)
            );
            CREATE TABLE IF NOT EXISTS legacy_history (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS delivery_events (
                id INTEGER PRIMARY KEY, delivery_id INTEGER NOT NULL REFERENCES deliveries(id),
                state TEXT NOT NULL, created REAL NOT NULL, detail TEXT NOT NULL
            );
        """)
        try:
            if legacy_history is not None:
                self._migrate_history(Path(legacy_history))
        except BaseException:
            self.db.close()
            raise

    def __exit__(self, *exc):
        self.db.close()

    def _migrate_history(self, path):
        if self.db.execute("SELECT 1 FROM metadata WHERE key='legacy_imported'").fetchone():
            return
        entries = []
        if path.exists():
            try:
                entries = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(entries, list) or any(
                    not isinstance(row, dict) or not row.get("video_id") or not row.get("posted_at") for row in entries
                ):
                    raise ValueError("Formato de historico invalido")
                for row in entries:
                    datetime.fromisoformat(row["posted_at"])
                    float(row.get("start", 0))
                    float(row.get("end", 0))
            except (OSError, ValueError, TypeError) as exc:
                raise RuntimeError("Historico antigo ilegivel; publicacao bloqueada para evitar duplicatas.") from exc
        with self.db:
            self.db.executemany("INSERT INTO legacy_history(payload) VALUES (?)", [(json.dumps(row),) for row in entries])
            self.db.execute("INSERT INTO metadata VALUES ('legacy_imported', ?)", (str(path),))

    @staticmethod
    def clip_id(payload):
        source = str(payload["video_id"])
        if source.startswith("local:"):
            digest = hashlib.sha256()
            with Path(payload["video_path"]).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            identity = "local:" + digest.hexdigest()
        else:
            identity = json.dumps([source, round(float(payload.get("start", 0)), 3), round(float(payload.get("end", 0)), 3)])
        return hashlib.sha256(identity.encode()).hexdigest()

    def enqueue(self, payload, platforms, *, owned=True, retention_days=7):
        if not set(platforms) <= PLATFORMS:
            raise ValueError("Plataforma desconhecida")
        clip_id = self.clip_id(payload)
        now = time.time()
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO clips VALUES (?, ?, ?, ?, ?)", (
                clip_id, json.dumps(payload, default=str, ensure_ascii=False), now,
                now + retention_days * 86400 if owned else None, int(owned),
            ))
            for platform in platforms:
                self.db.execute("INSERT OR IGNORE INTO deliveries(clip_id, platform, updated) VALUES (?, ?, ?)", (clip_id, platform, now))
        return clip_id

    def get(self, delivery_id):
        row = self.db.execute("SELECT d.*, c.payload, c.expires, c.owned FROM deliveries d JOIN clips c ON c.id=d.clip_id WHERE d.id=?", (delivery_id,)).fetchone()
        if row is None:
            raise ValueError("Entrega nao encontrada")
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def list_deliveries(self):
        return [self.get(row[0]) for row in self.db.execute("SELECT id FROM deliveries ORDER BY id").fetchall()]

    def transition(self, delivery_id, state, *, detail="", receipt=None):
        allowed = {
            "pending": {"starting", "expired"}, "failed": {"starting", "expired"},
            "starting": {"submitting", "failed"}, "submitting": {"confirmed", "uncertain"},
            "uncertain": {"confirmed", "pending"}, "confirmed": set(), "expired": set(),
        }
        with self.db:
            row = self.get(delivery_id)
            if state not in allowed[row["state"]]:
                raise ValueError(f"Transicao invalida: {row['state']} -> {state}")
            if state == "confirmed" and (not isinstance(receipt, PublicationReceipt) or receipt.platform != row["platform"] or not receipt.evidence):
                raise ValueError("Confirmacao exige comprovante da mesma plataforma")
            self.db.execute("UPDATE deliveries SET state=?, updated=?, error=?, receipt=?, attempts=attempts+? WHERE id=?", (
                state, time.time(), detail, json.dumps(receipt.to_dict()) if receipt else None, int(state == "starting"), delivery_id,
            ))
            self.db.execute("INSERT INTO delivery_events(delivery_id, state, created, detail) VALUES (?, ?, ?, ?)",
                            (delivery_id, state, time.time(), detail))

    def recover(self):
        for row in self.list_deliveries():
            state = row["state"]
            if state == "submitting":
                self.transition(row["id"], "uncertain", detail="Processo interrompido apos iniciar publicacao; conferir antes de reenviar.")
            elif state == "starting":
                self.transition(row["id"], "failed", detail="Interrompido antes do comando de publicar.")
            row = self.get(row["id"])
            if row["state"] in {"pending", "failed"} and row["expires"] is not None and row["expires"] <= time.time():
                self.transition(row["id"], "expired", detail="Prazo de retencao esgotado.")

    def resolve(self, delivery_id, resolution, note, post_url=None):
        row = self.get(delivery_id)
        if row["state"] != "uncertain" or not note.strip():
            raise ValueError("Resolucao exige entrega incerta e uma nota de verificacao.")
        if resolution == "published":
            if not post_url or not valid_post_url(row["platform"], post_url):
                raise ValueError("Informe um link valido da publicacao na mesma plataforma.")
            receipt = PublicationReceipt(row["platform"], "Revisao manual: " + note, datetime.now(timezone.utc).isoformat(), post_url)
            self.transition(delivery_id, "confirmed", detail=note, receipt=receipt)
        elif resolution == "not-published":
            self.transition(delivery_id, "pending", detail="Revisao manual: " + note)
        else:
            raise ValueError("Resolucao desconhecida")

    def history(self):
        history = [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM legacy_history")]
        for row in self.list_deliveries():
            if row["state"] == "expired":
                continue
            payload = row["payload"]
            # Pending and uncertain deliveries also reserve their source/interval.
            timestamp = row["updated"] if row["state"] == "confirmed" else time.time()
            history.append({**payload, "platforms": [row["platform"]], "state": row["state"],
                            "posted_at": datetime.fromtimestamp(timestamp).isoformat()})
        return history

    def protected_paths(self):
        return [Path(row["payload"]["video_path"]) for row in self.list_deliveries()
                if row["state"] in {"pending", "failed", "starting", "submitting", "uncertain"}
                and (row["expires"] is None or row["expires"] > time.time())]

    def completed_clip_ids(self):
        return {row[0] for row in self.db.execute("""SELECT clip_id FROM deliveries GROUP BY clip_id
                    HAVING SUM(CASE WHEN state != 'confirmed' THEN 1 ELSE 0 END)=0""")}
