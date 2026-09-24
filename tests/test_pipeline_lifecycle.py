from argparse import Namespace
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
import io
from contextlib import redirect_stderr
from unittest.mock import patch

import main
from downloader import _resolve_downloaded_file
from runtime import RunLock, TempWorkspace
from publication_store import PublicationStore
from publication import PublicationReceipt


class PipelineLifecycleTests(unittest.TestCase):
    def setUp(self):
        media_check = patch("delivery_queue.validate_video_clip")
        media_check.start()
        self.addCleanup(media_check.stop)
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.store = PublicationStore(self.base / "queue.sqlite3")
        self.addCleanup(self.store.__exit__)
        self.args = Namespace(input_video=None, dry_run=False, no_cleanup=False, queue=False,
                              manual=False, clip_count=1, source_url=[], url="test")

    def run_fake_pipeline(self, *, youtube=None, instagram=None, dry_run=False):
        self.args.dry_run = dry_run
        workspace = TempWorkspace(self.base / "videos", self.base / "clips")

        def fake_source(url, args, count, schedules, index, workspace):
            clip = workspace.clips / "clip.mp4"
            clip.write_bytes(b"rendered")
            payload = {"video_path": clip, "title": "clip", "video_id": "id", "source_url": "test"}
            workspace.register_clip(payload)
            return ([] if args.dry_run else [payload]), [clip]

        with ExitStack() as stack:
            stack.enter_context(patch.object(main, "load_source_schedules", return_value={}))
            stack.enter_context(patch.object(main, "resolve_source_urls", return_value=["test"]))
            stack.enter_context(patch.object(main, "process_source_url", side_effect=fake_source))
            for platform, enabled in (("YOUTUBE", True), ("INSTAGRAM", True), ("TIKTOK", False), ("FACEBOOK", False)):
                stack.enter_context(patch.object(main, f"{platform}_UPLOAD_ENABLED", enabled))
            def uploader(platform, result):
                def send(videos, on_submitting, on_confirmed, **kwargs):
                    if not result:
                        raise RuntimeError("Failure before submit")
                    on_submitting(videos[0])
                    receipt = PublicationReceipt(platform, "Explicit success", "2026-09-21T12:00:00+00:00")
                    on_confirmed(videos[0], receipt)
                    return [receipt]
                return send
            yt = stack.enter_context(patch.object(main, "upload_youtube_videos", side_effect=uploader("youtube", youtube)))
            ig = stack.enter_context(patch.object(main, "upload_instagram_videos", side_effect=uploader("instagram", instagram)))
            with workspace:
                main.run_pipeline(self.args, workspace, self.store)
            if dry_run:
                yt.assert_not_called()
                ig.assert_not_called()
        return workspace

    def test_successful_uploads_remove_rendered_clips(self):
        workspace = self.run_fake_pipeline(youtube=["clip"], instagram=["clip"])
        self.assertFalse(workspace.clips.exists())

    def test_partial_upload_keeps_clips(self):
        with self.assertRaises(RuntimeError):
            self.run_fake_pipeline(youtube=["clip"], instagram=[])
        self.assertEqual(len(list((self.base / "clips").rglob("clip.mp4"))), 1)
        states = {row['platform']: row['state'] for row in self.store.list_deliveries()}
        self.assertEqual(states, {'youtube': 'confirmed', 'instagram': 'failed'})

    def test_total_upload_failure_keeps_clips(self):
        with self.assertRaises(RuntimeError):
            self.run_fake_pipeline(youtube=[], instagram=[])
        self.assertEqual(len(list((self.base / "clips").rglob("clip.mp4"))), 1)

    def test_dry_run_keeps_preview_without_upload(self):
        workspace = self.run_fake_pipeline(dry_run=True)
        self.assertTrue((workspace.clips / "clip.mp4").exists())

    def test_exhausted_source_retry_cleans_partial_download(self):
        with TempWorkspace(self.base / "videos", self.base / "clips") as workspace:
            calls = []

            def fail(*args):
                directory = workspace.videos / "source_01"
                self.assertFalse(directory.exists())
                directory.mkdir()
                (directory / "partial.mp4.part").write_bytes(b"partial")
                calls.append(True)
                raise RuntimeError("Download retries exhausted")

            with patch.object(main, "_process_source_url", side_effect=fail), patch.object(main, "RETRY_DELAY_SECONDS", 0):
                with self.assertRaises(RuntimeError):
                    main.run_with_retries("source", lambda: main.process_source_url("test", self.args, 1, {}, 1, workspace))
            self.assertEqual(len(calls), main.RETRY_ATTEMPTS)
            self.assertFalse((workspace.videos / "source_01").exists())

    def test_main_does_not_start_pipeline_when_lock_is_held(self):
        with RunLock(self.base / ".podcast_automation.lock"):
            with patch.object(main, "BASE_DIR", self.base), patch.object(main, "parse_args", return_value=self.args):
                with patch.object(main, "run_pipeline") as pipeline, patch.object(main, "TempWorkspace") as workspace:
                    main.main()
                    pipeline.assert_not_called()
                    workspace.assert_not_called()

    def test_local_input_inside_temp_root_is_preserved(self):
        root = self.base / "clips"
        root.mkdir()
        original = root / "original.mp4"
        original.write_bytes(b"original")
        self.args.input_video = str(original)
        self.args.input_title = None
        self.args.input_description = None
        self.args.input_tags = ""
        self.args.dry_run = True
        with TempWorkspace(self.base / "videos", root, protected_path=original, retention_days=0) as workspace:
            main.run_pipeline(self.args, workspace, self.store)
        self.assertEqual(original.read_bytes(), b"original")

    def test_partial_download_is_not_returned_as_finished_video(self):
        (self.base / "video.f401.mp4.part").write_bytes(b"partial")
        with self.assertRaises(FileNotFoundError):
            _resolve_downloaded_file(self.base / "video.webm", self.base)

    def test_existing_queue_is_retried_without_generating_a_new_clip(self):
        clip = self.base / "ready.mp4"
        clip.write_bytes(b"ready")
        payload = dict(video_path=str(clip), title="ready", video_id="id", start=1, end=25)
        self.store.enqueue(payload, ['instagram'], owned=False)
        def send(videos, on_submitting, on_confirmed):
            on_submitting(videos[0])
            on_confirmed(videos[0], PublicationReceipt('instagram', 'Your reel has been shared', '2026-09-21'))
        with patch.object(main, 'enabled_uploaders', return_value={'instagram': send}):
            with patch.object(main, 'process_source_url') as generate:
                with TempWorkspace(self.base / 'videos', self.base / 'clips') as workspace:
                    main.run_pipeline(self.args, workspace, self.store)
                generate.assert_not_called()
        self.assertEqual(self.store.list_deliveries()[0]['state'], 'confirmed')

    def test_queue_arguments_reject_ambiguous_actions(self):
        cases = [
            ['--resolution', 'published'],
            ['--retry-pending', '--input-video', 'local.mp4'],
            ['--resolve-delivery', '1'],
            ['--dry-run', '--retry-pending'],
            ['--dry-run', '--repair-delivery', '1'],
        ]
        for flags in cases:
            with self.subTest(flags=flags), patch('sys.argv', ['main.py', *flags]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main.parse_args()
                self.assertEqual(error.exception.code, 2)

    def test_rate_limited_transcript_is_not_retried(self):
        from unittest.mock import Mock
        operation = Mock(side_effect=RuntimeError('HTTP Error 429: Too Many Requests'))
        with self.assertRaises(RuntimeError):
            main.run_with_retries('Transcript', operation, should_retry=lambda exc: '429' not in str(exc))
        operation.assert_called_once()


if __name__ == "__main__":
    unittest.main()
