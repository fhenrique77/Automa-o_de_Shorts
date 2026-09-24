"""Dispatch only safe-to-retry deliveries, committing each result immediately."""
from pathlib import Path
from utils import validate_video_clip


def dispatch_pending(store, uploaders):
    counts = {"confirmed": 0, "failed": 0, "uncertain": 0}
    for delivery in store.list_deliveries():
        if delivery["platform"] not in uploaders or delivery["state"] not in {"pending", "failed"}:
            continue
        identifier = delivery["id"]
        store.transition(identifier, "starting")
        try:
            if not Path(delivery["payload"]["video_path"]).is_file():
                raise FileNotFoundError("Arquivo do clipe indisponivel; restaure o arquivo antes de tentar novamente.")
            validate_video_clip(delivery["payload"]["video_path"])
            uploaders[delivery["platform"]](
                [delivery["payload"]],
                on_submitting=lambda _clip, item=identifier: store.transition(item, "submitting"),
                on_confirmed=lambda _clip, receipt, item=identifier: store.transition(item, "confirmed", receipt=receipt),
            )
            if store.get(identifier)["state"] != "confirmed":
                raise RuntimeError("Uploader nao entregou confirmacao verificavel.")
        except Exception as exc:
            state = store.get(identifier)["state"]
            if state == "submitting":
                store.transition(identifier, "uncertain", detail=str(exc))
            elif state == "starting":
                store.transition(identifier, "failed", detail=str(exc))
            print(f"Entrega {identifier} ({delivery['platform']}): {exc}")
        state = store.get(identifier)["state"]
        counts[state] += 1
        print(f"Entrega {identifier} ({delivery['platform']}): {state}")
    return counts
