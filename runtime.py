"""Execution lock and bounded, recoverable temporary-file lifecycle."""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import shutil
import stat
import time
from uuid import uuid4


class AlreadyRunningError(RuntimeError):
    pass


class RunLock:
    """OS-owned lock: automatically released even if Python is terminated."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.handle = open(self.path, "a+b")
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise AlreadyRunningError("Outra execucao do bot esta ativa; esta execucao sera ignorada.") from exc
        return self

    def __exit__(self, *exc):
        # Keep the file: deleting it could let two processes lock different files.
        self.handle.close()
        self.handle = None


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def remove_temp_path(path: Path, root: Path, attempts: int = 3) -> bool:
    """Delete only verified descendants; report failure without masking the job error."""
    path, root = Path(path).absolute(), Path(root).absolute()
    for attempt in range(attempts):
        try:
            if not path.exists() and not path.is_symlink():
                return True
            resolved_root = root.resolve()
            resolved = path.resolve()
            if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
                raise ValueError(f"Caminho fora da area temporaria: {path}")
            for parent in (path, *path.parents):
                if _is_link(parent):
                    raise ValueError(f"Link/junction recusado na limpeza: {parent}")
                if parent == root:
                    break
            if path.is_dir():
                # Validate the whole tree before passing an absolute path to rmtree.
                for current, directories, files in os.walk(path, followlinks=False):
                    for name in directories + files:
                        child = Path(current) / name
                        if _is_link(child) or not child.resolve().is_relative_to(resolved_root):
                            raise ValueError(f"Link/junction recusado na limpeza: {child}")
                shutil.rmtree(path)
            else:
                path.unlink()
            return True
        except (OSError, ValueError) as exc:
            if isinstance(exc, ValueError) or attempt == attempts - 1:
                print(f"AVISO: nao foi possivel limpar {path}: {exc}")
                return False
            time.sleep(0.2 * (attempt + 1))
    return False


class TempWorkspace:
    """One run per directory; pending clips survive for a bounded recovery period."""

    def __init__(self, videos_root: Path, clips_root: Path, *, cleanup: bool = True,
                 retention_days: float = 7, legacy_hours: float = 24,
                 protected_path: Path | None = None, protected_paths=()):
        self.videos_root = Path(videos_root).absolute()
        self.clips_root = Path(clips_root).absolute()
        self.cleanup = cleanup
        self.retention_seconds = max(0, retention_days) * 86400
        self.legacy_seconds = max(0, legacy_hours) * 3600
        self.protected_path = protected_path.resolve() if protected_path else None
        self.protected_paths = [Path(path).resolve() for path in protected_paths]
        if self.protected_path:
            self.protected_paths.append(self.protected_path)
        self.on_clip_ready = None
        self.run_id = f"run_{uuid4().hex}"
        self.videos = self.videos_root / self.run_id
        self.clips = self.clips_root / self.run_id
        self.manifest = {
            "version": 1, "created_at": time.time(), "keep": not cleanup,
            "pending": False, "clips": [],
        }

    def _protected(self, path: Path) -> bool:
        return any(protected == path.resolve() or protected.is_relative_to(path.resolve())
                   for protected in self.protected_paths)

    def _write_manifest(self) -> None:
        destination = self.clips / ".run.json"
        temporary = self.clips / ".run.json.tmp"
        temporary.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(destination)

    def cleanup_stale(self) -> None:
        """Call only while holding RunLock; preserve legacy inputs until the age limit."""
        now = time.time()
        for root in (self.videos_root, self.clips_root):
            if not root.exists():
                continue
            if _is_link(root):
                raise ValueError(f"Pasta temporaria nao pode ser link/junction: {root}")
            for item in root.iterdir():
                try:
                    if self._protected(item) or _is_link(item):
                        continue
                    marker = item / ".run.json" if item.is_dir() else None
                    if marker and marker.exists():
                        metadata = json.loads(marker.read_text(encoding="utf-8"))
                        if metadata.get("keep"):
                            continue
                        if root == self.clips_root and metadata.get("pending"):
                            if now < float(metadata["expires_at"]):
                                continue
                        # A managed run cannot still own the global lock here.
                    else:
                        # Pre-migration files may belong to an older bot without a lock.
                        newest = item.stat().st_mtime
                        if item.is_dir():
                            newest = max([newest] + [p.stat().st_mtime for p in item.rglob("*")])
                        age_limit = self.legacy_seconds if root == self.videos_root else self.retention_seconds
                        if now - newest < age_limit:
                            continue
                    if remove_temp_path(item, root):
                        print(f"Residuo temporario removido: {item}")
                except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                    print(f"AVISO: residuo preservado para inspecao em {item}: {exc}")

    def __enter__(self):
        for root in (self.videos_root, self.clips_root):
            if root.exists() and _is_link(root):
                raise ValueError(f"Pasta temporaria nao pode ser link/junction: {root}")
        if self.cleanup:
            self.cleanup_stale()
        self.videos.mkdir(parents=True)
        self.clips.mkdir(parents=True)
        self._write_manifest()
        (self.videos / ".run.json").write_text(
            json.dumps({"version": 1, "keep": not self.cleanup}), encoding="utf-8"
        )
        print(f"Execucao {self.run_id}: temporarios isolados.")
        return self

    def register_clip(self, clip: dict) -> None:
        self.manifest["pending"] = True
        self.manifest["expires_at"] = time.time() + self.retention_seconds
        if self.on_clip_ready:
            clip["clip_id"] = self.on_clip_ready(clip)
        self.manifest["clips"].append(dict(clip))
        self._write_manifest()

    def mark_uploads_complete(self) -> None:
        self.manifest["pending"] = False
        self._write_manifest()

    def cleanup_source(self, source_index: int) -> None:
        if self.cleanup:
            remove_temp_path(self.videos / f"source_{source_index:02d}", self.videos_root)

    def __exit__(self, *exc):
        if not self.cleanup:
            print(f"Temporarios preservados por configuracao: {self.run_id}")
            return
        remove_temp_path(self.videos, self.videos_root)
        if self.manifest["pending"]:
            print(f"Clipes para revisao/reenvio preservados em {self.clips}; retencao de {self.retention_seconds / 86400:g} dias.")
        else:
            remove_temp_path(self.clips, self.clips_root)
        for root in (self.videos_root, self.clips_root):
            try:
                if root.exists() and not any(root.iterdir()):
                    root.rmdir()
            except OSError as error:
                print(f"AVISO: nao foi possivel remover pasta vazia {root}: {error}")
