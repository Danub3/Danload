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
from danload_core import editing_conversion_plan


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

    def test_locate_downloaded_media_accepts_native_extension_from_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = os.path.join(directory, 'clip')
            output = f'{base}.mxf'
            with open(output, 'wb') as media:
                media.write(b'video')
            self.assertEqual(self.app._locate_downloaded_media(base, {}), output)

    def test_locate_downloaded_media_prefers_yt_dlp_reported_path(self):
        with tempfile.TemporaryDirectory() as directory:
            reported = os.path.join(directory, 'clip.actual')
            fallback = os.path.join(directory, 'clip.other')
            for path in (reported, fallback):
                with open(path, 'wb') as media:
                    media.write(b'video')
            info = {'filepath': reported}
            self.assertEqual(self.app._locate_downloaded_media(
                os.path.join(directory, 'clip'), info), reported)

    def test_locate_downloaded_media_resolves_relative_reported_path(self):
        with tempfile.TemporaryDirectory() as directory:
            reported = os.path.join(directory, 'clip.actual')
            with open(reported, 'wb') as media:
                media.write(b'video')
            self.assertEqual(
                self.app._locate_downloaded_media(
                    os.path.join(directory, 'clip'),
                    {'filepath': os.path.basename(reported)}),
                reported)

    def test_output_collision_detects_unknown_existing_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, 'clip')
            self.app._logger = None
            self.app._log_diagnostic = lambda *args, **kwargs: None
            with open(f'{root}.mxf', 'wb') as media:
                media.write(b'video')
            options = {'outtmpl': f'{root}.%(ext)s'}
            metadata = {'title': 'clip', 'id': '1'}
            with mock.patch('app.yt_dlp.YoutubeDL') as youtube_dl:
                youtube_dl.return_value.__enter__.return_value.prepare_filename.return_value = f'{root}.mxf'
                self.assertEqual(
                    self.app._unique_media_output_template(options, metadata),
                    f'{root} (1).%(ext)s')

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

    def test_native_containers_require_matching_container_and_streams(self):
        self._validate('.mkv', 'mkv', 'matroska,webm')
        self._validate('.mp4', 'mp4', 'mov,mp4,m4a,3gp,3g2,mj2')
        self._validate('.mov', 'mov', 'mov,mp4,m4a,3gp,3g2,mj2')
        self._validate('.webm', 'webm', 'matroska,webm', 'vp9')

    def test_video_without_audio_is_rejected(self):
        with tempfile.NamedTemporaryFile(suffix='.mkv') as media:
            self.app._probe_media = lambda _path: {
                'format': {'format_name': 'matroska,webm'},
                'streams': [{'codec_type': 'video', 'codec_name': 'hevc'}],
            }
            with self.assertRaisesRegex(RuntimeError, 'video and audio'):
                self.app._validate_video_output(media.name, 'mkv')


class EditingCompatibilityTests(unittest.TestCase):
    SOURCE_PROBE = {
        'format': {'format_name': 'matroska,webm', 'duration': '10.0'},
        'streams': [
            {
                'codec_type': 'video', 'codec_name': 'av1',
                'pix_fmt': 'yuv420p10le', 'width': 3840, 'height': 2160,
                'sample_aspect_ratio': '1:1', 'avg_frame_rate': '30000/1001',
                'color_range': 'tv',
                'color_space': 'bt2020nc', 'color_transfer': 'arib-std-b67',
                'color_primaries': 'bt2020',
            },
            {
                'codec_type': 'audio', 'codec_name': 'opus',
                'channels': 2, 'channel_layout': 'stereo', 'sample_rate': '48000',
            },
        ],
    }

    OUTPUT_PROBE = {
        'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'duration': '10.0'},
        'streams': [
            {
                'codec_type': 'video', 'codec_name': 'prores',
                'pix_fmt': 'yuv422p10le', 'width': 3840, 'height': 2160,
                'sample_aspect_ratio': '1:1', 'avg_frame_rate': '30000/1001',
                'color_range': 'tv',
                'color_space': 'bt2020nc', 'color_transfer': 'arib-std-b67',
                'color_primaries': 'bt2020',
            },
            {
                'codec_type': 'audio', 'codec_name': 'pcm_s24le',
                'channels': 2, 'channel_layout': 'stereo', 'sample_rate': '48000',
            },
        ],
    }

    def setUp(self):
        self.app = object.__new__(DownloaderApp)
        self.app.lang = 'en'
        self.app._log_diagnostic = lambda *args, **kwargs: None
        self.app._ensure_download_state()

    def test_command_transcodes_av1_and_opus_without_changing_media_geometry(self):
        args, plan = self.app._build_editing_conversion_command(
            '/tmp/source.mkv', '/tmp/output.mov', self.SOURCE_PROBE)
        self.assertEqual(args[args.index('-c:v') + 1], 'libx265')
        self.assertEqual(args[args.index('-pix_fmt') + 1], 'yuv420p10le')
        self.assertEqual(args[args.index('-c:a') + 1], 'aac')
        self.assertEqual(args[args.index('-colorspace') + 1], 'bt2020nc')
        self.assertEqual(args[args.index('-color_trc') + 1], 'arib-std-b67')
        self.assertIn('-noautorotate', args)
        self.assertIn('0:a?', args)
        self.assertIn('passthrough', args)
        self.assertEqual(plan['video_label'], 'HEVC')

    def test_explicit_prores_preset_reaches_the_ffmpeg_command(self):
        args, plan = self.app._build_editing_conversion_command(
            '/tmp/source.mkv', '/tmp/output.mov', self.SOURCE_PROBE, 'prores')
        self.assertEqual(args[args.index('-c:v') + 1], 'prores_ks')
        self.assertEqual(args[args.index('-profile:v') + 1], '3')
        self.assertEqual(args[args.index('-c:a') + 1], 'pcm_s24le')
        self.assertEqual(plan['target_codec'], 'prores')
        self.assertEqual(plan['quality_model'], 'visually_near_lossless')

    def test_validator_checks_resolution_frame_rate_color_and_audio(self):
        with tempfile.NamedTemporaryFile(suffix='.mov') as output:
            self.app._probe_media = lambda _path: self.OUTPUT_PROBE
            prores_plan = editing_conversion_plan(self.SOURCE_PROBE, 'prores')
            self.app._validate_editing_output(self.SOURCE_PROBE, output.name, prores_plan)

            changed = dict(self.OUTPUT_PROBE)
            changed['streams'] = [dict(stream) for stream in self.OUTPUT_PROBE['streams']]
            changed['streams'][0]['color_transfer'] = 'bt709'
            self.app._probe_media = lambda _path: changed
            with self.assertRaisesRegex(RuntimeError, 'color_transfer'):
                self.app._validate_editing_output(self.SOURCE_PROBE, output.name, prores_plan)

            changed['streams'][0]['color_transfer'] = 'arib-std-b67'
            changed['streams'][0]['sample_aspect_ratio'] = '4:3'
            self.app._probe_media = lambda _path: changed
            with self.assertRaisesRegex(RuntimeError, 'sample aspect ratio'):
                self.app._validate_editing_output(self.SOURCE_PROBE, output.name, prores_plan)

            changed['streams'][0]['sample_aspect_ratio'] = '1:1'
            changed['streams'][1]['channel_layout'] = '5.1'
            with self.assertRaisesRegex(RuntimeError, 'channel_layout'):
                self.app._validate_editing_output(self.SOURCE_PROBE, output.name, prores_plan)

    def test_validator_accepts_implicit_limited_range_but_not_missing_full_range(self):
        with tempfile.NamedTemporaryFile(suffix='.mov') as output:
            output_probe = dict(self.OUTPUT_PROBE)
            output_probe['streams'] = [
                dict(stream) for stream in self.OUTPUT_PROBE['streams']]
            output_probe['streams'][0].pop('color_range')
            self.app._probe_media = lambda _path: output_probe
            prores_plan = editing_conversion_plan(self.SOURCE_PROBE, 'prores')
            self.app._validate_editing_output(
                self.SOURCE_PROBE, output.name, prores_plan)

            full_range_source = dict(self.SOURCE_PROBE)
            full_range_source['streams'] = [
                dict(stream) for stream in self.SOURCE_PROBE['streams']]
            full_range_source['streams'][0]['color_range'] = 'pc'
            with self.assertRaisesRegex(RuntimeError, 'color_range'):
                self.app._validate_editing_output(
                    full_range_source, output.name, prores_plan)

    def test_conversion_preserves_source_and_never_overwrites_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, 'clip.mkv')
            existing = os.path.join(directory, 'clip.edit-ready.mov')
            with open(source, 'wb') as output:
                output.write(b'source')
            with open(existing, 'wb') as output:
                output.write(b'existing')

            self.app._begin_download_transaction(directory)
            output_probe = {
                'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'duration': '10.0'},
                'streams': [
                    {
                        'codec_type': 'video', 'codec_name': 'hevc',
                        'pix_fmt': 'yuv420p10le', 'width': 3840, 'height': 2160,
                        'sample_aspect_ratio': '1:1', 'avg_frame_rate': '30000/1001',
                        'color_range': 'tv', 'color_space': 'bt2020nc',
                        'color_transfer': 'arib-std-b67', 'color_primaries': 'bt2020',
                    },
                    {
                        'codec_type': 'audio', 'codec_name': 'aac',
                        'channels': 2, 'channel_layout': 'stereo', 'sample_rate': '48000',
                    },
                ],
            }
            self.app._probe_media = lambda path: (
                self.SOURCE_PROBE if path == source else output_probe)
            self.app._set_status = lambda *args, **kwargs: None
            self.app._advance_progress = lambda *args, **kwargs: None

            def fake_ffmpeg(args, _duration):
                with open(args[-1], 'wb') as output:
                    output.write(b'converted')

            self.app._run_editing_ffmpeg = fake_ffmpeg
            self.app.t = lambda _key: 'Done ({format})'
            self.app.reset_ui_state = lambda: None
            errors = []
            self.app.handle_error = errors.append

            self.app.convert_for_editing(source)

            with open(source, 'rb') as input_file:
                self.assertEqual(input_file.read(), b'source')
            with open(existing, 'rb') as input_file:
                self.assertEqual(input_file.read(), b'existing')
            self.assertTrue(os.path.isfile(
                os.path.join(directory, 'clip.edit-ready.mp4')))
            self.assertFalse(errors)

    def test_conversion_runner_terminates_ffmpeg_when_cancelled(self):
        class FakeProcess:
            stdout = ['out_time_us=1000000\n']

            def __init__(self):
                self.terminated = False
                self.wait_calls = []

            def poll(self):
                return None if not self.terminated else -15

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.terminated = True

            def wait(self, timeout=None):
                self.wait_calls.append(timeout)
                return -15

        process = FakeProcess()
        self.app._set_status = lambda *args, **kwargs: None
        self.app._advance_progress = lambda *args, **kwargs: (
            self.app._cancel_event.set() or 0)

        with mock.patch('app.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'CANCELLED_BY_USER'):
                self.app._run_editing_ffmpeg(['ffmpeg'], 2.0)

        self.assertTrue(process.terminated)
        self.assertIn(1.0, process.wait_calls)
        self.assertNotIn(process, self.app._active_processes)


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
            app.download_media(self.URL, 'video', None, {})

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
            app.download_media(self.URL, 'video', None, {})

        self.assertFalse(os.path.exists(incomplete))
        self.assertEqual(len(self.errors), 1)
        self.assertIn('Connection refused', str(self.errors[0]))


if __name__ == '__main__':
    unittest.main()
