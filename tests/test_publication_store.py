from datetime import datetime
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from delivery_queue import dispatch_pending
from publication import PublicationReceipt
from publication_store import PublicationStore
from utils import filter_duplicate_clips, filter_unused_videos


class StoreTests(unittest.TestCase):
    def setUp(self):
        media_check = patch("delivery_queue.validate_video_clip")
        media_check.start()
        self.addCleanup(media_check.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.path = self.base / "queue.sqlite3"
        self.video = self.base / "clip.mp4"
        self.video.write_bytes(b"clip")
        self.payload = dict(video_path=str(self.video), video_id="source", source_url="source-url",
                            title="Same title", start=10, end=30)

    @staticmethod
    def successful(platform):
        def send(videos, on_submitting, on_confirmed):
            on_submitting(videos[0])
            receipt = PublicationReceipt(platform, "Explicit confirmation", datetime.now().isoformat())
            on_confirmed(videos[0], receipt)
            return [receipt]
        return Mock(side_effect=send)

    def test_restart_retries_only_failed_platform(self):
        with PublicationStore(self.path) as store:
            store.enqueue(self.payload, ['youtube', 'instagram'])
            yt = self.successful('youtube')
            ig = Mock(side_effect=RuntimeError('Login missing'))
            dispatch_pending(store, {'youtube': yt, 'instagram': ig})
        with PublicationStore(self.path) as store:
            store.recover()
            yt = self.successful('youtube')
            ig = self.successful('instagram')
            dispatch_pending(store, {'youtube': yt, 'instagram': ig})
            yt.assert_not_called()
            ig.assert_called_once()
            self.assertTrue(all(row['state'] == 'confirmed' for row in store.list_deliveries()))

    def test_batch_partial_success_is_recorded_per_clip(self):
        with PublicationStore(self.path) as store:
            store.enqueue(self.payload, ['youtube'])
            store.enqueue({**self.payload, 'start': 50, 'end': 70}, ['youtube'])
            first = self.successful('youtube')
            count = 0
            def upload(videos, **callbacks):
                nonlocal count
                count += 1
                if count == 2:
                    raise RuntimeError('Login failed')
                return first(videos, **callbacks)
            dispatch_pending(store, {'youtube': upload})
            self.assertEqual([r['state'] for r in store.list_deliveries()], ['confirmed', 'failed'])
            self.assertEqual(len([r for r in store.history() if r.get('state') == 'confirmed']), 1)

    def test_ambiguous_click_never_retries_without_review(self):
        def unknown(videos, on_submitting, on_confirmed):
            on_submitting(videos[0])
            raise TimeoutError('No response after click')
        with PublicationStore(self.path) as store:
            store.enqueue(self.payload, ['instagram'])
            sender = Mock(side_effect=unknown)
            dispatch_pending(store, {'instagram': sender})
            dispatch_pending(store, {'instagram': sender})
            sender.assert_called_once()
            row = store.list_deliveries()[0]
            self.assertEqual(row['state'], 'uncertain')
            store.resolve(row['id'], 'not-published', 'Checked account posts and drafts')
            dispatch_pending(store, {'instagram': self.successful('instagram')})
            self.assertEqual(store.get(row['id'])['state'], 'confirmed')

    def test_interrupted_submission_recovers_as_uncertain(self):
        with PublicationStore(self.path) as store:
            store.enqueue(self.payload, ['tiktok'])
            row = store.list_deliveries()[0]
            store.transition(row['id'], 'starting')
            store.transition(row['id'], 'submitting')
        with PublicationStore(self.path) as store:
            store.recover()
            self.assertEqual(store.get(row['id'])['state'], 'uncertain')
            sender = Mock()
            dispatch_pending(store, {'tiktok': sender})
            sender.assert_not_called()

    def test_interrupted_preparation_is_safe_to_retry(self):
        with PublicationStore(self.path) as store:
            store.enqueue(self.payload, ['youtube'])
            row = store.list_deliveries()[0]
            store.transition(row['id'], 'starting')
            store.recover()
            self.assertEqual(store.get(row['id'])['state'], 'failed')

    def test_receipt_committed_before_browser_close_failure(self):
        def close_failure(videos, **callbacks):
            self.successful('youtube')(videos, **callbacks)
            raise RuntimeError('Browser close failed')
        with PublicationStore(self.path) as store:
            store.enqueue(self.payload, ['youtube'])
            dispatch_pending(store, {'youtube': close_failure})
            self.assertEqual(store.list_deliveries()[0]['state'], 'confirmed')

    def test_enqueue_is_idempotent_even_after_publication(self):
        with PublicationStore(self.path) as store:
            first = store.enqueue(self.payload, ['youtube'])
            dispatch_pending(store, {'youtube': self.successful('youtube')})
            again = store.enqueue({**self.payload, 'title': 'Changed title'}, ['youtube'])
            self.assertEqual(first, again)
            self.assertEqual(len(store.list_deliveries()), 1)
            self.assertEqual(store.list_deliveries()[0]['state'], 'confirmed')

    def test_local_identity_uses_content_instead_of_filename(self):
        other = self.base / 'renamed.mp4'
        other.write_bytes(self.video.read_bytes())
        with PublicationStore(self.path) as store:
            first = store.enqueue({**self.payload, 'video_id': 'local:clip'}, ['youtube'], owned=False)
            second = store.enqueue({**self.payload, 'video_id': 'local:renamed', 'video_path': str(other)}, ['youtube'], owned=False)
            self.assertEqual(first, second)

    def test_legacy_import_once_and_corruption_fails_closed(self):
        legacy = self.base / 'historico.json'
        entry = dict(video_id='old', posted_at=datetime.now().isoformat(), start=1, end=25, platforms=['youtube'])
        legacy.write_text(json.dumps([entry]), encoding='utf-8')
        with PublicationStore(self.path, legacy) as store:
            self.assertEqual(len(store.history()), 1)
        with PublicationStore(self.path, legacy) as store:
            self.assertEqual(len(store.history()), 1)
        self.assertEqual(json.loads(legacy.read_text()), [entry])
        legacy.write_text('{broken', encoding='utf-8')
        with self.assertRaises(RuntimeError):
            PublicationStore(self.base / 'fresh.sqlite3', legacy)

    def test_all_duplicates_return_empty(self):
        history = [{**self.payload, 'posted_at': datetime.now().isoformat()}]
        self.assertEqual(filter_unused_videos(['source'], lambda url: url, history), [])
        self.assertEqual(filter_duplicate_clips([dict(start=11, end=29)], 'source', history), [])

    def test_expired_pending_files_are_not_dispatched(self):
        with PublicationStore(self.path) as store:
            store.enqueue(self.payload, ['youtube'], retention_days=0)
            store.recover()
            sender = Mock()
            dispatch_pending(store, {'youtube': sender})
            sender.assert_not_called()
            self.assertEqual(store.list_deliveries()[0]['state'], 'expired')

    def test_uncertain_history_remains_reserved_after_retention(self):
        with PublicationStore(self.path) as store:
            store.enqueue(self.payload, ['youtube'])
            row = store.list_deliveries()[0]
            store.transition(row['id'], 'starting')
            store.transition(row['id'], 'submitting')
            store.recover()
            with patch('publication_store.time.time', return_value=time.time() + 100 * 86400):
                self.assertEqual(filter_duplicate_clips([dict(start=10, end=30)], 'source', store.history()), [])

    def test_manual_confirmation_requires_same_platform_link_and_note(self):
        with PublicationStore(self.path) as store:
            store.enqueue(self.payload, ['instagram'])
            row = store.list_deliveries()[0]
            store.transition(row['id'], 'starting')
            store.transition(row['id'], 'submitting')
            store.recover()
            with self.assertRaises(ValueError):
                store.resolve(row['id'], 'published', 'Checked', 'https://youtu.be/abcdefghijk')
            with self.assertRaises(ValueError):
                store.resolve(row['id'], 'not-published', '')
            store.resolve(row['id'], 'published', 'Checked account post', 'https://www.instagram.com/reel/abc123/')
            self.assertEqual(store.get(row['id'])['state'], 'confirmed')


if __name__ == '__main__':
    unittest.main()
