import os
import tempfile
import unittest
from unittest import mock

from app import (
    MAIN_FRAME_VERTICAL_PADDING,
    STATUS_AREA_HEIGHT,
    WINDOW_WIDTH,
    DownloaderApp,
    entry_drag_scroll_units,
)


class EntryDragScrollTests(unittest.TestCase):
    def test_drag_inside_entry_does_not_scroll(self):
        self.assertEqual(entry_drag_scroll_units(100, 300), 0)

    def test_drag_beyond_edges_scrolls_in_selection_direction(self):
        self.assertLess(entry_drag_scroll_units(-40, 300), 0)
        self.assertGreater(entry_drag_scroll_units(340, 300), 0)

    def test_drag_farther_outside_scrolls_faster(self):
        self.assertGreater(
            abs(entry_drag_scroll_units(-100, 300)),
            abs(entry_drag_scroll_units(-1, 300)))


class WindowSizingTests(unittest.TestCase):
    def test_window_height_uses_visible_content_height(self):
        app = object.__new__(DownloaderApp)
        app.main_frame = mock.Mock()
        app.main_frame.winfo_reqheight.return_value = 412
        app.update_idletasks = mock.Mock()
        app.center_window = mock.Mock()

        app._resize_window_for_mode('audio')

        app.center_window.assert_called_once_with(
            WINDOW_WIDTH, 412 + MAIN_FRAME_VERTICAL_PADDING)

    def test_status_area_has_a_stable_nonzero_height(self):
        self.assertGreaterEqual(STATUS_AREA_HEIGHT, 32)


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

    def test_conservative_retry_disables_external_downloader(self):
        options = self.app._attempt_options(
            {'external_downloader': {'https': '/usr/bin/aria2c'},
             'external_downloader_args': {'aria2c': ['-x8']}},
            'anonymous', None, True)
        self.assertNotIn('external_downloader', options)
        self.assertNotIn('external_downloader_args', options)

    def test_retry_sleep_is_cancellable_and_bounded(self):
        self.app._ensure_download_state()
        self.app._cancel_event.set()
        with self.assertRaisesRegex(RuntimeError, 'CANCELLED_BY_USER'):
            self.app._retry_sleep(n=4)


class NetworkRoutingTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(DownloaderApp)

    def test_blank_proxy_builds_explicit_direct_opener(self):
        handler = object()
        opener = object()
        with mock.patch('app.urllib.request.ProxyHandler', return_value=handler) as proxy_handler, \
                mock.patch('app.urllib.request.build_opener', return_value=opener) as build_opener:
            result = self.app._build_opener(None)

        self.assertIs(result, opener)
        proxy_handler.assert_called_once_with({})
        build_opener.assert_called_once_with(handler)

    def test_configured_proxy_is_applied_to_all_supported_schemes(self):
        proxy = 'http://127.0.0.1:7890'
        handler = object()
        with mock.patch('app.urllib.request.ProxyHandler', return_value=handler) as proxy_handler, \
                mock.patch('app.urllib.request.build_opener'):
            self.app._build_opener(proxy)

        proxy_handler.assert_called_once_with({
            'http': proxy, 'https': proxy, 'ftp': proxy,
        })

    def test_background_opener_does_not_read_tk_variable(self):
        proxy = 'http://127.0.0.1:7890'
        self.app.proxy_var = mock.Mock()
        self.app.proxy_var.get.side_effect = RuntimeError(
            'main thread is not in main loop')
        handler = object()
        with mock.patch('app.urllib.request.ProxyHandler', return_value=handler), \
                mock.patch('app.urllib.request.build_opener'):
            self.app._build_opener(proxy)

        self.app.proxy_var.get.assert_not_called()

    def test_clearing_proxy_entry_does_not_restore_stale_setting(self):
        class Var:
            def get(self):
                return ''

        self.app.proxy = 'http://stale.example:8080'
        self.app.proxy_var = Var()
        self.assertIsNone(self.app._get_proxy())

    def test_bilibili_connection_refusal_is_transient(self):
        self.assertTrue(self.app._is_transient_network_error(
            "HTTPSConnection: [Errno 61] Connection refused"))
        self.assertTrue(self.app._is_transient_network_error('HTTP Error 503'))
        self.assertFalse(self.app._is_transient_network_error('Unsupported URL'))


class CancellationAndSubtitleTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(DownloaderApp)

    def test_progress_hook_cancels_before_updating_ui(self):
        self.app.is_cancelled = True
        with self.assertRaisesRegex(Exception, 'CANCELLED_BY_USER'):
            self.app.progress_hook({'status': 'downloading', 'filename': '/tmp/example.part'})
        self.assertEqual(self.app.cleanup_target, '/tmp/example.part')

    def test_interrupt_closes_network_and_terminates_process(self):
        self.app._ensure_download_state()
        process = mock.Mock()
        response = mock.Mock()
        ydl = mock.Mock()
        self.app._active_processes.add(process)
        self.app._active_responses.add(response)
        self.app._active_ydls.add(ydl)

        self.app._interrupt_active_download()

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=0.75)
        response.close.assert_called_once_with()
        ydl.close.assert_called_once_with()

    def test_cancel_cleanup_does_not_delete_same_prefix_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, 'video.mp4')
            partial = f'{target}.part'
            unrelated = os.path.join(directory, 'video.mp4.backup')
            for path in (target, partial, unrelated):
                with open(path, 'wb') as output:
                    output.write(b'test')

            self.app._track_artifact(target)
            self.app._cleanup_download_artifacts()

            self.assertFalse(os.path.exists(target))
            self.assertFalse(os.path.exists(partial))
            self.assertTrue(os.path.exists(unrelated))

    def test_cleanup_preserves_files_that_preceded_the_download(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = os.path.join(directory, 'existing.mp4')
            created = os.path.join(directory, 'created.mp4')
            with open(existing, 'wb') as output:
                output.write(b'original')

            self.app._begin_download_transaction(directory)
            with open(created, 'wb') as output:
                output.write(b'partial')
            self.app._track_artifact(existing, created)
            self.app._cleanup_download_artifacts()

            self.assertTrue(os.path.exists(existing))
            self.assertFalse(os.path.exists(created))

    def test_mkv_packaging_does_not_delete_a_preexisting_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = os.path.join(directory, 'existing-video')
            source = f'{base}.mp4'
            destination = f'{base}.mkv'
            with open(source, 'wb') as output:
                output.write(b'original')

            self.app._begin_download_transaction(directory)

            def fake_ffmpeg(args, **_kwargs):
                with open(args[-1], 'wb') as output:
                    output.write(b'packaged')
                return mock.Mock(returncode=0)

            self.app._run_cancellable_process = fake_ffmpeg
            result = self.app._ensure_mkv_output(base)

            self.assertEqual(result, destination)
            self.assertTrue(os.path.exists(source))
            self.assertTrue(os.path.exists(destination))

    def test_mp4_remux_uses_a_sibling_when_destination_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            base = os.path.join(directory, 'clip')
            source = f'{base}.mkv'
            existing = f'{base}.mp4'
            with open(source, 'wb') as output:
                output.write(b'mkv')
            with open(existing, 'wb') as output:
                output.write(b'original')

            self.app._begin_download_transaction(directory)

            def fake_ffmpeg(args, **_kwargs):
                with open(args[-1], 'wb') as output:
                    output.write(b'remuxed')
                return mock.Mock(returncode=0)

            self.app._run_cancellable_process = fake_ffmpeg
            result = self.app._remux_to_mp4(base)

            self.assertEqual(result, 'mp4')
            with open(existing, 'rb') as output:
                self.assertEqual(output.read(), b'original')
            with open(f'{base} (1).mp4', 'rb') as output:
                self.assertEqual(output.read(), b'remuxed')

    def test_output_collision_gets_a_unique_sibling_name(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = os.path.join(directory, 'clip.mp4')
            second = os.path.join(directory, 'clip (1).mp4')
            orphan = os.path.join(directory, 'clip (2).mp4.part')
            open(existing, 'wb').close()
            open(second, 'wb').close()
            open(orphan, 'wb').close()
            result = self.app._next_available_path(existing)
            self.assertEqual(result, os.path.join(directory, 'clip (3).mp4'))

    def test_conversion_temp_avoids_an_orphaned_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = os.path.join(directory, 'clip.mp4')
            stale = os.path.join(directory, 'clip.danload-tmp.mp4')
            open(stale, 'wb').close()
            result = self.app._conversion_temp_path(destination)
            self.assertEqual(
                result, os.path.join(directory, 'clip.danload-tmp (1).mp4'))

    def test_media_template_avoids_existing_container_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = os.path.join(directory, 'clip.mkv')
            open(existing, 'wb').close()
            self.app._log_diagnostic = lambda *args, **kwargs: None
            options = {'outtmpl': os.path.join(directory, '%(title)s.%(ext)s')}
            metadata = {'title': 'clip', 'ext': 'mp4'}
            result = self.app._unique_media_output_template(options, metadata)
            self.assertTrue(result.endswith('clip (1).%(ext)s'))

    def test_no_matching_subtitle_is_not_silent(self):
        self.app._detect_original_audio_lang = lambda info: 'fr'
        self.app.t = lambda key: 'No matching subtitles'
        with self.assertRaisesRegex(RuntimeError, 'No matching subtitles'):
            self.app._download_subtitles_only(
                'https://example.invalid/video', {},
                {'subtitles': {'en': [{}]}},
                {'subtitle_policy': 'automatic', 'subtitle_format': 'srt'})

    def test_subtitle_request_passes_selected_languages_and_format(self):
        self.app.lang = 'en'
        self.app._detect_original_audio_lang = lambda info: 'ja'
        self.app._set_status = lambda *args, **kwargs: None
        self.app._advance_progress = lambda *args, **kwargs: None
        self.app._log_diagnostic = lambda *args, **kwargs: None
        self.app.t = lambda key: 'No matching subtitles'

        class FakeYoutubeDL:
            options = None

            def __init__(self, options):
                type(self).options = options

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                self.result = {'extractor_key': 'test'}
                return self.result

        with mock.patch('app.yt_dlp.YoutubeDL', FakeYoutubeDL):
            self.app._download_subtitles_only(
                'https://example.invalid/video',
                {'format': 'best', 'merge_output_format': 'mkv',
                 'audio_multistreams': True, 'cookiefile': '/tmp/cookies.txt'},
                {'subtitles': {'ja': [{}], 'en': [{}]}},
                {'subtitle_policy': 'original_english', 'subtitle_format': 'vtt'})

        self.assertEqual(FakeYoutubeDL.options['subtitleslangs'], ['ja', 'en'])
        self.assertEqual(FakeYoutubeDL.options['subtitlesformat'], 'vtt/best')
        self.assertTrue(FakeYoutubeDL.options['writesubtitles'])
        self.assertTrue(FakeYoutubeDL.options['writeautomaticsub'])
        self.assertNotIn('format', FakeYoutubeDL.options)
        self.assertNotIn('merge_output_format', FakeYoutubeDL.options)
        self.assertNotIn('audio_multistreams', FakeYoutubeDL.options)
        self.assertEqual(FakeYoutubeDL.options['cookiefile'], '/tmp/cookies.txt')


class AttachedSubtitleStateTests(unittest.TestCase):
    class Var:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    def setUp(self):
        self.app = object.__new__(DownloaderApp)
        self.app.lang = 'en'
        self.app.subtitle_policy = 'original_english'
        self.app.cookie_file_path = self.Var('')
        self.app.use_cookie_var = self.Var(False)
        self.app.subtitle_format_var = self.Var('VTT')
        self.app._get_proxy = lambda: None
        self.app.statuses = []
        self.app.progress = []
        self.app.diagnostics = []
        self.app._set_status = lambda text, text_color: self.app.statuses.append(text)
        self.app._advance_progress = lambda stage, fraction: self.app.progress.append(
            (stage, fraction))
        self.app._log_diagnostic = lambda message, *args: self.app.diagnostics.append(
            (message, args))
        self.app.t = lambda key: {
            'status_done_video_subtitles': 'Video and subtitles downloaded! '
                                            '({video} + {languages} · {format})',
            'status_partial_subtitles': 'Video downloaded, but subtitles failed',
        }[key]

    def test_attached_subtitles_run_after_media_and_report_success(self):
        calls = []

        def download_subtitles(*args, **kwargs):
            calls.append((args, kwargs))
            return ['ja', 'en'], 'vtt'

        self.app._download_subtitles_only = download_subtitles
        result = self.app._download_attached_subtitles(
            'https://example.invalid/video', {'format': 'best'}, {},
            {'include_subtitles': True}, 'MKV')

        self.assertTrue(result)
        self.assertEqual(calls[0][1], {'show_completion': False})
        self.assertEqual(
            self.app.statuses[-1],
            'Video and subtitles downloaded! (MKV + ja, en · VTT)')
        self.assertEqual(self.app.progress, [])

    def test_attached_subtitle_failure_keeps_video_and_marks_partial(self):
        self.app._download_subtitles_only = lambda *args, **kwargs: (
            (_ for _ in ()).throw(RuntimeError('subtitle server failed')))

        result = self.app._download_attached_subtitles(
            'https://example.invalid/video', {}, {}, {}, 'ProRes MOV')

        self.assertFalse(result)
        self.assertEqual(self.app._last_error, 'subtitle server failed')
        self.assertIn('Video downloaded, but subtitles failed', self.app.statuses)
        self.assertEqual(self.app.progress, [('complete', 1.0)])

    def test_attached_subtitle_cancellation_is_not_converted_to_partial_success(self):
        self.app._download_subtitles_only = lambda *args, **kwargs: (
            (_ for _ in ()).throw(RuntimeError('CANCELLED_BY_USER')))

        with self.assertRaisesRegex(RuntimeError, 'CANCELLED_BY_USER'):
            self.app._download_attached_subtitles(
                'https://example.invalid/video', {}, {}, {}, 'MKV')

    def test_request_config_omits_subtitle_details_when_disabled(self):
        disabled = self.app._build_request_config(False)
        enabled = self.app._build_request_config(True)

        self.assertFalse(disabled['include_subtitles'])
        self.assertNotIn('subtitle_policy', disabled)
        self.assertNotIn('subtitle_format', disabled)
        self.assertEqual(enabled['subtitle_policy'], 'original_english')
        self.assertEqual(enabled['subtitle_format'], 'vtt')


class VideoOutputValidationTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(DownloaderApp)
        self.app._log_diagnostic = lambda *args, **kwargs: None

    def _validate(self, suffix, expected_container, format_name, video_codec='h264'):
        with tempfile.NamedTemporaryFile(suffix=suffix) as media:
            self.app._probe_media = lambda _path: {
                'format': {'format_name': format_name},
                'streams': [
                    {'codec_type': 'video', 'codec_name': video_codec},
                    {'codec_type': 'audio', 'codec_name': 'aac'},
                ],
            }
            self.app._validate_video_output(media.name, expected_container)

    def test_mkv_mp4_and_prores_outputs_require_matching_container_and_streams(self):
        self._validate('.mkv', 'mkv', 'matroska,webm')
        self._validate('.mp4', 'mp4', 'mov,mp4,m4a,3gp,3g2,mj2')
        self._validate('.mov', 'mov', 'mov,mp4,m4a,3gp,3g2,mj2', 'prores_ks')

    def test_video_without_audio_is_rejected(self):
        with tempfile.NamedTemporaryFile(suffix='.mkv') as media:
            self.app._probe_media = lambda _path: {
                'format': {'format_name': 'matroska,webm'},
                'streams': [{'codec_type': 'video', 'codec_name': 'hevc'}],
            }
            with self.assertRaisesRegex(RuntimeError, 'video and audio'):
                self.app._validate_video_output(media.name, 'mkv')


class BilibiliRecoveryTests(unittest.TestCase):
    URL = 'https://www.bilibili.com/video/BV1TEST/'

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = object.__new__(DownloaderApp)
        self.app.lang = 'en'
        self.app.download_folder = self.directory.name
        self.app._logger = None
        self.app._last_url = self.URL
        self.app._last_error = ''
        self.app._progress_stage = 'parse'
        self.app._ensure_download_state()
        self.app._begin_download_transaction(self.directory.name)
        self.statuses = []
        self.progress = []
        self.errors = []
        self.validated = []
        self.app._set_status = lambda text, text_color: self.statuses.append(text)
        self.app._advance_progress = lambda stage, value: self.progress.append(
            (stage, value))
        self.app._format_diagnostic = lambda *args: None
        self.app._log_diagnostic = lambda *args: None
        self.app.reset_ui_state = lambda: None
        self.app.handle_error = lambda error: self.errors.append(error)
        self.app._validate_video_output = lambda path, container: self.validated.append(
            (path, container))
        self.app.t = lambda key: {
            'status_retry_bilibili': 'Refreshing Bilibili media links...',
            'status_done_original': 'Done ({container})',
            'status_done_mkv_fallback': 'Done (MKV fallback)',
        }[key]

    def test_audio_cdn_failure_cleans_single_stream_and_reextracts(self):
        app = self.app
        incomplete = os.path.join(self.directory.name, 'clip.f30126.mp4')
        final = os.path.join(self.directory.name, 'clip.mkv')

        class FakeYoutubeDL:
            metadata_calls = 0
            download_calls = 0
            second_attempt_was_clean = False

            def __init__(self, options):
                self.options = options

            def extract_info(self, _url, download=False):
                if not download:
                    type(self).metadata_calls += 1
                    return {'extractor_key': 'Bilibili', 'formats': []}

                type(self).download_calls += 1
                if type(self).download_calls == 1:
                    with open(incomplete, 'wb') as output:
                        output.write(b'video-only')
                    app._track_artifact(incomplete)
                    raise RuntimeError('[Errno 61] Connection refused')

                type(self).second_attempt_was_clean = not os.path.exists(incomplete)
                self.assert_conservative_retry()
                with open(final, 'wb') as output:
                    output.write(b'merged')
                app._track_artifact(final)
                return {'title': 'clip', 'ext': 'mkv', 'extractor_key': 'Bilibili'}

            def assert_conservative_retry(self):
                if self.options['concurrent_fragment_downloads'] != 1:
                    raise AssertionError('retry did not use conservative fragment settings')

            def prepare_filename(self, _info):
                return final

            def close(self):
                pass

        with mock.patch('app.yt_dlp.YoutubeDL', FakeYoutubeDL):
            app.download_media(self.URL, 'video_original', 'mkv', {})

        self.assertEqual(FakeYoutubeDL.metadata_calls, 2)
        self.assertEqual(FakeYoutubeDL.download_calls, 2)
        self.assertTrue(FakeYoutubeDL.second_attempt_was_clean)
        self.assertFalse(os.path.exists(incomplete))
        self.assertTrue(os.path.exists(final))
        self.assertEqual(self.validated, [(final, 'mkv')])
        self.assertFalse(self.errors)
        self.assertIn('Refreshing Bilibili media links...', self.statuses)

    def test_final_cdn_failure_removes_all_new_partial_outputs(self):
        app = self.app
        incomplete = os.path.join(self.directory.name, 'clip.f30126.mp4')

        class AlwaysFailYoutubeDL:
            def __init__(self, options):
                self.options = options

            def extract_info(self, _url, download=False):
                if not download:
                    return {'extractor_key': 'Bilibili', 'formats': []}
                with open(incomplete, 'wb') as output:
                    output.write(b'video-only')
                app._track_artifact(incomplete)
                raise RuntimeError('[Errno 61] Connection refused')

            def close(self):
                pass

        with mock.patch('app.yt_dlp.YoutubeDL', AlwaysFailYoutubeDL):
            app.download_media(self.URL, 'video_original', 'mkv', {})

        self.assertFalse(os.path.exists(incomplete))
        self.assertEqual(len(self.errors), 1)
        self.assertIn('Connection refused', str(self.errors[0]))


if __name__ == '__main__':
    unittest.main()
