import math
import unittest

from danload_core import (
    choose_subtitle_languages,
    editing_conversion_plan,
    highest_video_summary,
    media_format_selector,
    progress_fraction,
    resolve_download_selection,
    sanitize_diagnostic,
    selected_format_summary,
    stage_progress,
)


class ProgressTests(unittest.TestCase):
    def test_download_fraction_prefers_exact_total(self):
        self.assertEqual(progress_fraction({
            "downloaded_bytes": 25,
            "total_bytes": 100,
            "_percent_str": "99.0%",
        }), 0.25)

    def test_estimate_and_percent_fallbacks(self):
        self.assertEqual(progress_fraction({
            "downloaded_bytes": 50,
            "total_bytes_estimate": 200,
        }), 0.25)
        self.assertEqual(progress_fraction({"_percent_str": "\x1b[0;32m12.5%\x1b[0m"}), 0.125)

    def test_stage_progress_is_monotonic_and_finite(self):
        first = stage_progress(0.0, "media", 0.8)
        self.assertEqual(stage_progress(first, "media", 0.2), first)
        self.assertEqual(stage_progress(first, "media", math.nan), first)
        self.assertEqual(stage_progress(first, "complete", 1.0), 1.0)

    def test_attached_subtitle_stage_follows_media_and_postprocessing(self):
        media_done = stage_progress(0.0, "media", 1.0)
        postprocess_done = stage_progress(media_done, "postprocess", 1.0)
        subtitle_started = stage_progress(postprocess_done, "subtitle", 0.0)
        subtitle_done = stage_progress(subtitle_started, "subtitle", 1.0)
        self.assertEqual((media_done, postprocess_done), (0.88, 0.95))
        self.assertGreater(subtitle_done, subtitle_started)
        self.assertLess(subtitle_done, 1.0)


class DownloadSelectionTests(unittest.TestCase):
    def test_quality_first_media_selectors(self):
        self.assertEqual(media_format_selector('video'), 'bv*+ba/b')
        self.assertEqual(media_format_selector('audio'), 'bestaudio/best')
        self.assertIsNone(media_format_selector('general_file'))

    def test_video_download_keeps_native_container(self):
        self.assertEqual(resolve_download_selection('video', None, True),
                         ('video', None, True))

    def test_non_video_modes_cannot_attach_subtitles(self):
        self.assertEqual(
            resolve_download_selection('audio', 'ignored', True),
            ('audio', None, False))
        self.assertEqual(
            resolve_download_selection('general_file', 'ignored', True),
            ('general_file', None, False))

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_download_selection('subtitles', 'SRT', True)


class EditingConversionPlanTests(unittest.TestCase):
    def test_hdr_av1_and_opus_choose_hevc_and_aac(self):
        plan = editing_conversion_plan({'streams': [
            {'codec_type': 'video', 'codec_name': 'av1', 'pix_fmt': 'yuv420p10le'},
            {'codec_type': 'audio', 'codec_name': 'opus'},
        ]})
        self.assertFalse(plan['copy_video'])
        self.assertEqual(plan['target_codec'], 'hevc')
        self.assertEqual(plan['output_pixel_format'], 'yuv420p10le')
        self.assertEqual(plan['video_label'], 'HEVC')
        self.assertFalse(plan['copy_audio'])

    def test_existing_prores_and_aac_are_stream_copied(self):
        plan = editing_conversion_plan({'streams': [
            {'codec_type': 'video', 'codec_name': 'prores', 'pix_fmt': 'yuv422p10le'},
            {'codec_type': 'audio', 'codec_name': 'aac'},
        ]})
        self.assertTrue(plan['copy_video'])
        self.assertTrue(plan['copy_audio'])

    def test_full_chroma_source_uses_prores_4444(self):
        plan = editing_conversion_plan({'streams': [
            {'codec_type': 'video', 'codec_name': 'vp9', 'pix_fmt': 'yuv444p10le'},
        ]})
        self.assertEqual(plan['video_profile'], 4)
        self.assertEqual(plan['output_pixel_format'], 'yuv444p10le')

    def test_alpha_pixel_formats_use_prores_4444_with_alpha(self):
        plan = editing_conversion_plan({'streams': [
            {'codec_type': 'video', 'codec_name': 'ffv1', 'pix_fmt': 'gbrap10le'},
        ]})
        self.assertEqual(plan['target_codec'], 'ffv1')
        self.assertEqual(plan['quality_model'], 'video_stream_copy')
        self.assertEqual(plan['container'], 'mkv')

    def test_file_without_video_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'video stream'):
            editing_conversion_plan({'streams': [
                {'codec_type': 'audio', 'codec_name': 'aac'},
            ]})


class SubtitleTests(unittest.TestCase):
    INFO = {
        "subtitles": {"ja": [{}], "en-US": [{}]},
        "automatic_captions": {"zh-Hans": [{}], "en": [{}]},
    }

    def test_original_and_english(self):
        self.assertEqual(
            choose_subtitle_languages(self.INFO, "ja", "original_english"),
            ["ja", "en"],
        )

    def test_automatic_only_and_no_subtitles(self):
        self.assertEqual(choose_subtitle_languages(
            {"automatic_captions": {"en": [{}]}}, "en", "english"), ["en"])
        self.assertEqual(choose_subtitle_languages({}, "en", "automatic"), [])

    def test_automatic_policy_selects_one_language(self):
        info = {"automatic_captions": {"fr": [{}], "en": [{}], "zh-Hans-en": [{}]}}
        self.assertEqual(choose_subtitle_languages(info, "fr", "automatic"), ["fr"])

    def test_missing_requested_language_is_explicit(self):
        self.assertEqual(choose_subtitle_languages(self.INFO, "fr", "english"), ["en"])

    def test_original_falls_back_when_audio_language_is_unknown(self):
        info = {"subtitles": {"zh-CN": [{}], "danmaku": [{}]}}
        self.assertEqual(choose_subtitle_languages(info, "en", "original"), ["zh-CN"])


class DiagnosticTests(unittest.TestCase):
    def test_format_summaries(self):
        info = {
            "formats": [
                {"format_id": "a", "height": 1080, "fps": 60, "vcodec": "avc1.1"},
                {"format_id": "b", "height": 2160, "fps": 30, "vcodec": "av01.1"},
            ],
            "requested_downloads": [
                {"format_id": "b", "height": 2160, "fps": 30, "vcodec": "av01.1"},
                {"format_id": "251", "acodec": "opus"},
            ],
        }
        self.assertIn("b/2160p", highest_video_summary(info))
        self.assertIn("b/2160p", selected_format_summary(info))
        self.assertIn("251/opus", selected_format_summary(info))

    def test_diagnostics_redact_urls_credentials_and_home(self):
        value = "proxy=http://name:secret@host:1 cookiefile=/Users/test/c.txt https://x.test/a?q=sig"
        cleaned = sanitize_diagnostic(value, home="/Users/test")
        self.assertNotIn("secret", cleaned)
        self.assertNotIn("q=sig", cleaned)
        self.assertNotIn("/Users/test", cleaned)


if __name__ == "__main__":
    unittest.main()
