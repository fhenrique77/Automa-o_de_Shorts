from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from publication_store import PublicationStore
from main import run_pipeline


class PipelineQueueTests(unittest.TestCase):
    def test_uncertain_delivery_is_preserved_while_new_source_is_processed(self):
        with tempfile.TemporaryDirectory() as temp:
            with PublicationStore(Path(temp) / "queue.sqlite3") as store:
                clip = Path(temp) / "clip.mp4"
                clip.write_bytes(b"clip")
                payload = dict(video_path=str(clip), video_id="old-source",
                               source_url="old-source", title="Old clip", start=10, end=30)
                store.enqueue(payload, ["youtube"])
                delivery = store.list_deliveries()[0]
                store.transition(delivery["id"], "starting")
                store.transition(delivery["id"], "submitting")
                store.recover()

                args = SimpleNamespace(dry_run=False, input_video=None,
                                       retry_pending=False, queue=False,
                                       manual=False, clip_count=1)
                workspace = SimpleNamespace(manifest={"clips": []}, on_clip_ready=None)
                uploader = Mock()
                with patch("main.enabled_uploaders", return_value={"youtube": uploader}), \
                     patch("main.load_source_schedules", return_value={}), \
                     patch("main.resolve_source_urls", return_value=["new-source"]), \
                     patch("main.run_with_retries", return_value=([], None)) as process, \
                     patch("main.cleanup_confirmed"):
                    run_pipeline(args, workspace, store)

                process.assert_called_once()
                uploader.assert_not_called()
                self.assertEqual(store.get(delivery["id"])["state"], "uncertain")

    def test_retry_pending_never_generates_new_source(self):
        with tempfile.TemporaryDirectory() as temp:
            with PublicationStore(Path(temp) / "queue.sqlite3") as store:
                args = SimpleNamespace(dry_run=False, input_video=None, retry_pending=True)
                workspace = SimpleNamespace()
                with patch("main.enabled_uploaders", return_value={"youtube": Mock()}), \
                     patch("main.cleanup_confirmed"), \
                     patch("main.load_source_schedules") as schedules:
                    run_pipeline(args, workspace, store)
                schedules.assert_not_called()


if __name__ == "__main__":
    unittest.main()
