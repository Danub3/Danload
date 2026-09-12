import os
import tempfile
import unittest

from app import DownloaderApp


class DownloadAttemptTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(DownloaderApp)

    def test_explicit_cookie_never_falls_back_to_anonymous(self):
        with tempfile.NamedTemporaryFile() as cookie_file:
            attempts = self.app._download_attempts({
                'cookie_file': cookie_file.name,
                'use_browser_cookie': False,
            })
        self.assertEqual([attempt[0] for attempt in attempts], ['file', 'file'])
        self.assertEqual([attempt[2] for attempt in attempts], [False, True])

    def test_missing_cookie_file_is_an_error(self):
        missing = os.path.join(tempfile.gettempdir(), 'danload-missing-cookies.txt')
        with self.assertRaises(FileNotFoundError):
            self.app._download_attempts({'cookie_file': missing})

    def test_conservative_retry_keeps_proxy_and_credentials(self):
        options = self.app._attempt_options(
            {'proxy': 'http://127.0.0.1:7890', 'concurrent_fragment_downloads': 4},
            'file', '/tmp/cookies.txt', True)
        self.assertEqual(options['proxy'], 'http://127.0.0.1:7890')
        self.assertEqual(options['cookiefile'], '/tmp/cookies.txt')
        self.assertEqual(options['concurrent_fragment_downloads'], 1)


class CancellationAndSubtitleTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(DownloaderApp)

    def test_progress_hook_cancels_before_updating_ui(self):
        self.app.is_cancelled = True
        with self.assertRaisesRegex(Exception, 'CANCELLED_BY_USER'):
            self.app.progress_hook({'status': 'downloading', 'filename': '/tmp/example.part'})
        self.assertEqual(self.app.cleanup_target, '/tmp/example.part')

    def test_no_matching_subtitle_is_not_silent(self):
        self.app._detect_original_audio_lang = lambda info: 'fr'
        self.app.t = lambda key: 'No matching subtitles'
        with self.assertRaisesRegex(RuntimeError, 'No matching subtitles'):
            self.app._download_subtitles_only(
                'https://example.invalid/video', {},
                {'subtitles': {'en': [{}]}},
                {'subtitle_policy': 'automatic', 'subtitle_format': 'srt'})


if __name__ == '__main__':
    unittest.main()
