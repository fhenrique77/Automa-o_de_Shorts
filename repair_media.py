"""Rebuild the file of an unpublished delivery without changing its identity."""
from __future__ import annotations

import os
from pathlib import Path

from cutter import cut_clip
from downloader import download_clip_section
from runtime import TempWorkspace
from utils import validate_video_clip


def repair_delivery(store, delivery_id: int, workspace: TempWorkspace) -> Path:
    row = store.get(delivery_id)
    siblings = [item for item in store.list_deliveries() if item["clip_id"] == row["clip_id"]]
    unsafe = [item for item in siblings if item["state"] not in {"pending", "failed"}]
    if unsafe:
        raise RuntimeError("Entrega ja enviada ou incerta; confira as plataformas antes de reparar.")
    if not row["owned"]:
        raise RuntimeError("O video local nao pertence ao bot; forneca novamente o arquivo original.")

    payload = row["payload"]
    destination = Path(payload["video_path"]).resolve()
    if not destination.is_relative_to(workspace.clips_root.resolve()):
        raise ValueError("Caminho da entrega fora da pasta de clipes temporarios.")
    source_url = str(payload["source_url"])
    if not source_url.startswith(("https://www.youtube.com/watch?v=", "https://youtube.com/watch?v=")):
        raise ValueError("A entrega nao possui uma fonte do YouTube para reconstruir o corte.")
    start, end = float(payload["start"]), float(payload["end"])
    if start < 0 or end <= start or end - start > 60:
        raise ValueError("Intervalo do corte invalido.")

    raw = workspace.videos / "repair" / "source.mp4"
    rendered = workspace.clips / "repaired.mp4"
    print(f"Reconstruindo clipe da entrega {delivery_id}: {source_url}, {start:.1f}-{end:.1f}s")
    download_clip_section(source_url, start, end, raw)
    cut_clip(raw, output_path=rendered)
    validate_video_clip(rendered, minimum_duration=(end - start) * 0.8)
    if not destination.parent.exists():
        raise FileNotFoundError(f"Pasta do clipe pendente nao encontrada: {destination.parent}")
    os.replace(rendered, destination)
    print(f"Clipe reparado: {destination}")
    return destination
