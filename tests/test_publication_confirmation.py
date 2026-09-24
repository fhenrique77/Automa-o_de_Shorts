import unittest
from unittest.mock import Mock

from publication import PublicationAttempt, PublicationUncertainError, perform_upload, valid_post_url


class Matches:
    def __init__(self, items):
        self.items = items
    def count(self):
        return len(self.items)
    def nth(self, index):
        return self.items[index]


class Message:
    def __init__(self, text, visible=True):
        self.text, self.visible = text, visible
    def is_visible(self):
        return self.visible
    def inner_text(self):
        return self.text
    def locator(self, selector):
        return Matches([])


class Page:
    def __init__(self, *texts):
        self.messages = [Message(text) for text in texts]
        self.url = 'https://www.facebook.com/'
    def get_by_text(self, pattern):
        return Matches([message for message in self.messages if pattern.fullmatch(message.text)])


class ConfirmationTests(unittest.TestCase):
    def test_exact_new_success_confirms_each_platform(self):
        for platform, text in [('youtube', 'Video published'), ('tiktok', 'Your video has been posted.'),
                               ('instagram', 'Seu reel foi compartilhado.'), ('facebook', 'Seu reel foi publicado.')]:
            with self.subTest(platform=platform):
                page = Page()
                before, confirmed = Mock(), Mock()
                attempt = PublicationAttempt(platform, before, confirmed)
                attempt.before_submit(page)
                before.assert_called_once()
                page.messages.append(Message(text))
                receipt = attempt.confirm(page, timeout_ms=0)
                self.assertEqual(receipt.evidence, text)
                self.assertEqual(receipt.platform, platform)
                confirmed.assert_called_once_with(receipt)

    def test_redirect_progress_disappearance_and_generic_text_are_not_success(self):
        for platform in ('youtube', 'tiktok', 'instagram', 'facebook'):
            page = Page()
            attempt = PublicationAttempt(platform)
            attempt.before_submit(page)
            page.messages = [Message(text) for text in ['Seu reel', 'Sharing', 'Copy link', 'Upload complete', 'Not published', 'Publicado?']]
            with self.assertRaises(PublicationUncertainError):
                attempt.confirm(page, timeout_ms=0)

    def test_old_success_message_is_not_reused(self):
        page = Page('Video published')
        attempt = PublicationAttempt('youtube')
        attempt.before_submit(page)
        with self.assertRaises(PublicationUncertainError):
            attempt.confirm(page, timeout_ms=0)

    def test_hidden_confirmation_is_not_success(self):
        page = Page()
        attempt = PublicationAttempt('youtube')
        attempt.before_submit(page)
        page.messages = [Message('Video published', visible=False)]
        with self.assertRaises(PublicationUncertainError):
            attempt.confirm(page, timeout_ms=0)

    def test_failure_after_click_is_uncertain_and_operation_runs_once(self):
        page = Page()
        attempt = PublicationAttempt('youtube')
        def upload():
            attempt.before_submit(page)
            raise TimeoutError('Response lost')
        operation = Mock(side_effect=upload)
        with self.assertRaises(PublicationUncertainError):
            perform_upload(operation, attempt)
        operation.assert_called_once()
        with self.assertRaises(PublicationUncertainError):
            attempt.before_submit(page)

    def test_database_failure_prevents_submit(self):
        attempt = PublicationAttempt('youtube', Mock(side_effect=OSError('Disk full')))
        with self.assertRaises(OSError):
            attempt.before_submit(Page())
        self.assertFalse(attempt.submitted)

    def test_platform_links_are_validated(self):
        self.assertTrue(valid_post_url('youtube', 'https://youtu.be/abcdefghijk'))
        self.assertTrue(valid_post_url('instagram', 'https://www.instagram.com/reel/abc123/'))
        self.assertFalse(valid_post_url('youtube', 'https://youtube.com.evil.test/watch?v=abcdefghijk'))
        self.assertFalse(valid_post_url('instagram', 'https://www.instagram.com/'))
        self.assertFalse(valid_post_url('tiktok', 'https://www.youtube.com/shorts/abcdefghijk'))


if __name__ == '__main__':
    unittest.main()
