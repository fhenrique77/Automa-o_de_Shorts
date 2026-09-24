from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import RunLock, TempWorkspace, remove_temp_path


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.videos = self.base / "temp_videos"
        self.clips = self.base / "temp_clips"

    def workspace(self, **kwargs):
        return TempWorkspace(self.videos, self.clips, **kwargs)

    def add_clip(self, workspace):
        clip = workspace.clips / "clip.mp4"
        clip.write_bytes(b"test clip")
        workspace.register_clip({"video_path": clip, "title": "Test"})
        return clip

    def test_lock_blocks_another_process_and_is_reusable(self):
        lock = self.base / "bot.lock"
        code = (
            "from pathlib import Path; from runtime import RunLock, AlreadyRunningError; import sys\n"
            "try:\n"
            "    with RunLock(Path(sys.argv[1])): pass\n"
            "except AlreadyRunningError:\n"
            "    sys.exit(9)\n"
        )
        with RunLock(lock):
            result = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 9, result.stderr)
        with RunLock(lock):
            pass
        self.assertTrue(lock.exists())

    def test_lock_released_after_abrupt_process_exit(self):
        lock = self.base / "bot.lock"
        code = (
            "from pathlib import Path; from runtime import RunLock; import os, sys\n"
            "with RunLock(Path(sys.argv[1])): os._exit(0)\n"
        )
        result = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        with RunLock(lock):
            pass

    def test_success_removes_only_this_run_and_empty_roots(self):
        with self.workspace() as workspace:
            self.add_clip(workspace)
            (workspace.videos / "download.part").write_bytes(b"partial")
            workspace.mark_uploads_complete()
        self.assertFalse(self.videos.exists())
        self.assertFalse(self.clips.exists())

    def test_failure_keeps_ready_clips_but_removes_downloads(self):
        with self.assertRaises(RuntimeError):
            with self.workspace() as workspace:
                clip = self.add_clip(workspace)
                (workspace.videos / "download.part").write_bytes(b"partial")
                raise RuntimeError("Upload failed")
        self.assertTrue(clip.exists())
        self.assertFalse(self.videos.exists())
        metadata = json.loads((clip.parent / ".run.json").read_text(encoding="utf-8"))
        self.assertTrue(metadata["pending"])
        with self.workspace():
            self.assertTrue(clip.exists())
        with patch("runtime.time.time", return_value=time.time() + 8 * 86400):
            with self.workspace():
                self.assertFalse(clip.exists())

    def test_no_cleanup_survives_later_cleaning_runs(self):
        with self.workspace(cleanup=False) as workspace:
            clip = self.add_clip(workspace)
            raw = workspace.videos / "raw.part"
            raw.write_bytes(b"partial")
        with patch("runtime.time.time", return_value=time.time() + 100 * 86400):
            with self.workspace():
                self.assertTrue(clip.exists())
                self.assertTrue(raw.exists())

    def test_interrupted_run_recovered_on_next_start(self):
        interrupted = self.workspace()
        interrupted.__enter__()  # Simulate termination without __exit__.
        raw = interrupted.videos / "download.part"
        raw.write_bytes(b"partial")
        clip = self.add_clip(interrupted)
        with self.workspace():
            self.assertFalse(raw.exists())
            self.assertTrue(clip.exists())

    def test_legacy_age_limits_and_protected_input(self):
        self.videos.mkdir()
        self.clips.mkdir()
        old = self.videos / "old.part"
        fresh = self.videos / "fresh.part"
        protected = self.clips / "input.mp4"
        expired_clip = self.clips / "expired.mp4"
        for path in (old, fresh, protected, expired_clip):
            path.write_bytes(b"data")
        for path in (old, protected, expired_clip):
            os.utime(path, (time.time() - 10 * 86400,) * 2)
        with self.workspace(protected_path=protected):
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(protected.exists())
            self.assertFalse(expired_clip.exists())

    def test_source_cleanup_does_not_touch_other_sources(self):
        with self.workspace() as workspace:
            for index in (1, 2):
                directory = workspace.videos / f"source_{index:02d}"
                directory.mkdir()
                (directory / "download.part").write_bytes(b"partial")
            workspace.cleanup_source(1)
            self.assertFalse((workspace.videos / "source_01").exists())
            self.assertTrue((workspace.videos / "source_02" / "download.part").exists())

    def test_delete_failure_is_reported_and_retried(self):
        self.videos.mkdir()
        path = self.videos / "run_test"
        path.mkdir()
        output = io.StringIO()
        with patch("runtime.shutil.rmtree", side_effect=PermissionError("locked")) as delete:
            with patch("runtime.time.sleep"), redirect_stdout(output):
                self.assertFalse(remove_temp_path(path, self.videos))
        self.assertEqual(delete.call_count, 3)
        self.assertIn("AVISO", output.getvalue())
        self.assertTrue(path.exists())

    def test_delete_refuses_outside_path_and_root_itself(self):
        self.videos.mkdir()
        outside = self.base / "original.mp4"
        outside.write_bytes(b"original")
        self.assertFalse(remove_temp_path(outside, self.videos))
        self.assertFalse(remove_temp_path(self.videos, self.videos))
        self.assertTrue(outside.exists())

    def test_link_is_not_deleted_or_followed(self):
        self.videos.mkdir()
        outside = self.base / "original.mp4"
        outside.write_bytes(b"original")
        link = self.videos / "link.mp4"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("System does not permit creating symlinks")
        self.assertFalse(remove_temp_path(link, self.videos))
        self.assertTrue(outside.exists())

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_silent_launcher_waits_and_returns_child_exit_code(self):
        project = Path(__file__).resolve().parents[1]
        launcher = self.base / "run_bot_silent.vbs"
        launcher.write_bytes((project / launcher.name).read_bytes())
        # The real launcher runs only a harmless batch file in this test directory.
        (self.base / "run_bot.bat").write_text("@echo off\nexit /b 7\n", encoding="ascii")
        result = subprocess.run(["cscript.exe", "//Nologo", "//B", str(launcher)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 7, result.stderr)


if __name__ == "__main__":
    unittest.main()
