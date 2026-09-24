from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from subprocess import CompletedProcess

from utils import validate_video_clip
from publication_store import PublicationStore
from delivery_queue import dispatch_pending
from repair_media import repair_delivery
from runtime import TempWorkspace


class MediaValidationTests(unittest.TestCase):
    def test_invalid_queued_media_never_reaches_uploader(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            media = base / "clip.mp4"
            media.write_bytes(b"incomplete")
            with PublicationStore(base / "queue.sqlite3") as store:
                store.enqueue(dict(video_path=str(media), video_id="id", title="Clip"), ["youtube"])
                sender = Mock()
                with patch("delivery_queue.validate_video_clip", side_effect=RuntimeError("audio missing")):
                    dispatch_pending(store, {"youtube": sender})
                sender.assert_not_called()
                self.assertEqual(store.get(1)["state"], "failed")

    def test_audio_only_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "audio-only.mp4"
            media.write_bytes(b"fixture")
            with patch("utils.resolve_ffmpeg_executable", return_value="ffmpeg"):
                with patch("utils.subprocess.run", return_value=CompletedProcess([], 1, "", "Stream map 0:v:0 matches no streams")):
                    with self.assertRaisesRegex(RuntimeError, "video"):
                        validate_video_clip(media)

    def test_audio_missing_at_end_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "truncated-audio.mp4"
            media.write_bytes(b"fixture")
            def fake_ffmpeg(command, **_kwargs):
                if "-sseof" in command and "-af" in command:
                    return CompletedProcess(command, 0, "", "")
                if "-vf" in command:
                    return CompletedProcess(command, 0, "", "[Parsed_showinfo_0] n:0")
                if "-af" in command:
                    return CompletedProcess(command, 0, "", "[Parsed_ashowinfo_0] n:0")
                return CompletedProcess(command, 1, "", "Duration: 00:00:43.00")
            with patch("utils.resolve_ffmpeg_executable", return_value="ffmpeg"):
                with patch("utils.subprocess.run", side_effect=fake_ffmpeg):
                    with self.assertRaisesRegex(RuntimeError, "audio no fim"):
                        validate_video_clip(media, minimum_duration=40)

    def test_repair_replaces_same_file_without_creating_new_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            clips = base / "clips"
            original = clips / "old" / "clip.mp4"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"audio-only")
            with PublicationStore(base / "queue.sqlite3") as store:
                payload = dict(video_path=str(original), video_id="id", source_url="https://www.youtube.com/watch?v=abcdefghijk",
                               title="Clip", start=10, end=40)
                store.enqueue(payload, ["youtube", "instagram"])
                def download(_url, _start, _end, output):
                    Path(output).parent.mkdir(parents=True, exist_ok=True)
                    Path(output).write_bytes(b"raw")
                def render(_input, output_path):
                    Path(output_path).write_bytes(b"video-and-audio")
                with patch("repair_media.download_clip_section", side_effect=download):
                    with patch("repair_media.cut_clip", side_effect=render):
                        with patch("repair_media.validate_video_clip"):
                            with TempWorkspace(base / "videos", clips, protected_paths=store.protected_paths()) as workspace:
                                repair_delivery(store, 1, workspace)
                self.assertEqual(original.read_bytes(), b"video-and-audio")
                self.assertEqual(len(store.list_deliveries()), 2)

    def test_repair_refuses_uncertain_or_confirmed(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            original = base / "clips" / "clip.mp4"
            original.parent.mkdir()
            original.write_bytes(b"fixture")
            with PublicationStore(base / "queue.sqlite3") as store:
                store.enqueue(dict(video_path=str(original), video_id="id", source_url="https://www.youtube.com/watch?v=abcdefghijk",
                                   title="Clip", start=0, end=30), ["youtube"])
                store.transition(1, "starting")
                store.transition(1, "submitting")
                store.recover()
                with TempWorkspace(base / "videos", original.parent, protected_paths=store.protected_paths()) as workspace:
                    with self.assertRaisesRegex(RuntimeError, "incerta"):
                        repair_delivery(store, 1, workspace)


if __name__ == "__main__":
    unittest.main()
