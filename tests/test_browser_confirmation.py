"""Local DOM fixtures only: no platform pages, credentials or uploads."""
import unittest

from publication import PublicationAttempt, PublicationUncertainError


class BrowserConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception as exc:
            cls.playwright.stop()
            raise unittest.SkipTest(f"Local Chromium unavailable: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def test_receipt_uses_link_in_actual_confirmation_container(self):
        self.page.set_content('<a href="https://youtu.be/xxxxxxxxxxx">Unrelated video</a><div id="receipt"></div>')
        attempt = PublicationAttempt('youtube')
        attempt.before_submit(self.page)
        self.page.locator('#receipt').evaluate('''element => {
            element.setAttribute('role', 'dialog');
            element.innerHTML = '<span>Video published</span><a href="https://youtu.be/abcdefghijk">View</a>';
        }''')
        receipt = attempt.confirm(self.page, timeout_ms=1000)
        self.assertEqual(receipt.post_url, 'https://youtu.be/abcdefghijk')

    def test_generic_sharing_dialog_and_hidden_text_do_not_confirm(self):
        self.page.set_content('<div>Editor</div>')
        attempt = PublicationAttempt('instagram')
        attempt.before_submit(self.page)
        self.page.set_content('<div role="dialog">Sharing <button>Copy link</button></div><p hidden>Your reel has been shared</p>')
        with self.assertRaises(PublicationUncertainError):
            attempt.confirm(self.page, timeout_ms=0)


if __name__ == '__main__':
    unittest.main()
