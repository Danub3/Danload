import math
import os
import re


STAGE_RANGES = {
    "parse": (0.0, 0.05),
    "media": (0.05, 0.88),
    "postprocess": (0.88, 0.95),
    "subtitle": (0.95, 0.985),
    "subtitle_finalize": (0.985, 0.99),
    "conversion": (0.0, 0.99),
    "complete": (1.0, 1.0),
}

EDITING_PRESETS = ("auto", "h264", "hevc", "prores", "ffv1")
MP4_AUDIO_COPY_CODECS = {"aac", "alac"}
MOV_AUDIO_COPY_CODECS = {
    "aac", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le",
}


def resolve_download_selection(mode, _legacy_hint=None, include_subtitles=False):
    """Map the UI hierarchy to a download mode without choosing a container."""
    if mode == "video":
        return "video", None, bool(include_subtitles)
    if mode == "audio":
        return "audio", None, False
    if mode == "general_file":
        return "general_file", None, False
    raise ValueError(f"Unknown download mode: {mode}")


def media_format_selector(download_type):
    """Return a quality-first yt-dlp selector for a media mode.

    ``bv*`` deliberately leaves codec/container decisions to yt-dlp while
    preferring the highest video representation exposed by the extractor.
    The fallback keeps progressive-only sites working, including older
    extractors that cannot expose separate audio/video streams.
    """
    if download_type == "audio":
        return "bestaudio/best"
    if download_type == "video":
        return "bv*+ba/b"
    return None


def editing_conversion_plan(probe, preset="auto"):
    """Choose an editor-compatible output without claiming lossless encoding."""
    streams = probe.get("streams") or []
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    if video is None:
        raise ValueError("The selected file does not contain a video stream")

    preset = str(preset or "auto").strip().lower()
    if preset not in EDITING_PRESETS:
        raise ValueError(f"Unknown editing conversion preset: {preset}")

    codec = str(video.get("codec_name") or "").lower()
    pixel_format = str(video.get("pix_fmt") or "").lower()
    audio_codecs = {
        str(stream.get("codec_name") or "").lower()
        for stream in streams if stream.get("codec_type") == "audio"
    }

    has_alpha = pixel_format.startswith((
        "yuva", "rgba", "argb", "abgr", "gbrap", "ayuv", "ya8", "ya16", "ya32",
    ))
    full_chroma = "444" in pixel_format or pixel_format.startswith("gbr")
    high_bit_depth = any(depth in pixel_format for depth in ("10", "12", "14", "16"))
    transfer = str(video.get("color_transfer") or "").lower()
    is_hdr = transfer in ("smpte2084", "arib-std-b67")

    if preset == "auto":
        # H.264 is compact and broadly importable for ordinary SDR material.
        # Keep HDR/high-bit-depth and 4:4:4/alpha material in a 10-bit or
        # intra-frame intermediate where an 8-bit H.264 export would discard
        # meaningful source information.
        if codec.startswith("prores"):
            target_codec = "prores"
        elif codec == "ffv1":
            target_codec = "ffv1"
        elif codec in {"h264", "avc1"}:
            target_codec = "h264"
        elif codec in {"hevc", "h265"}:
            target_codec = "hevc"
        else:
            target_codec = "prores" if has_alpha or full_chroma else (
                "hevc" if high_bit_depth or is_hdr else "h264")
    else:
        target_codec = preset

    copy_video = (
        (target_codec == "h264" and codec in {"h264", "avc1"})
        or (target_codec == "hevc" and codec in {"hevc", "h265"})
        or (target_codec == "ffv1" and codec == "ffv1")
        or (target_codec == "prores" and codec.startswith("prores"))
    )
    if target_codec == "prores":
        if has_alpha or full_chroma:
            profile = 4
            output_pixel_format = "yuva444p10le" if has_alpha else "yuv444p10le"
            video_label = "ProRes 4444"
        else:
            profile = 3
            output_pixel_format = "yuv422p10le"
            video_label = "ProRes 422 HQ"
        extension = ".mov"
        container = "mov"
        copy_audio = audio_codecs.issubset(MOV_AUDIO_COPY_CODECS)
        audio_codec = "copy" if copy_audio else "pcm_s24le"
    elif target_codec == "ffv1":
        extension = ".mkv"
        container = "mkv"
        profile = None
        output_pixel_format = pixel_format or "yuv420p"
        video_label = "FFV1 lossless"
        copy_audio = False
        audio_codec = "flac"
    else:
        profile = None
        output_pixel_format = (
            "yuv420p10le" if target_codec == "hevc" and (high_bit_depth or is_hdr)
            else "yuv420p"
        )
        video_label = "HEVC" if target_codec == "hevc" else "H.264"
        extension = ".mp4"
        container = "mp4"
        copy_audio = audio_codecs.issubset(MP4_AUDIO_COPY_CODECS)
        audio_codec = "copy" if copy_audio else "aac"

    if copy_video and copy_audio:
        quality_model = "stream_copy"
    elif copy_video:
        quality_model = "video_stream_copy"
    else:
        quality_model = "visually_near_lossless"

    return {
        "preset": preset,
        "target_codec": target_codec,
        "container": container,
        "extension": extension,
        "copy_video": copy_video,
        "video_profile": profile,
        "output_pixel_format": output_pixel_format,
        "video_label": "ProRes" if copy_video and target_codec == "prores" else video_label,
        "output_label": f"{video_label} {container.upper()}",
        "copy_audio": copy_audio,
        "audio_codec": audio_codec,
        "quality_model": ("lossless_transcode" if target_codec == "ffv1" and not copy_video
                           else quality_model),
        "audio_stream_count": sum(
            stream.get("codec_type") == "audio" for stream in streams
        ),
    }


def clamp_fraction(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def progress_fraction(data):
    downloaded = data.get("downloaded_bytes")
    total = data.get("total_bytes") or data.get("total_bytes_estimate")
    if downloaded is not None and total:
        try:
            return clamp_fraction(float(downloaded) / float(total))
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    percent = data.get("_percent_str")
    if percent:
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", str(percent))
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", cleaned)
        if match:
            return clamp_fraction(float(match.group(1)) / 100.0)
    return 0.0


def stage_progress(previous, stage, fraction):
    start, end = STAGE_RANGES[stage]
    current = start + (end - start) * clamp_fraction(fraction)
    return max(clamp_fraction(previous), current)


def _matching_languages(available, prefix):
    prefix = (prefix or "").lower()
    return sorted(
        (lang for lang in available if lang.lower() == prefix or lang.lower().startswith(prefix + "-")),
        key=lambda lang: (len(lang), lang),
    )


def choose_subtitle_languages(info, original_language="en", policy="original_english"):
    automatic = set((info.get("automatic_captions") or {}).keys())
    available = set((info.get("subtitles") or {}).keys()) | automatic
    if not available:
        return []
    if policy == "automatic":
        original_auto = _matching_languages(automatic, original_language)
        english_auto = _matching_languages(automatic, "en")
        if original_auto:
            return [original_auto[0]]
        if english_auto:
            return [english_auto[0]]
        return sorted(automatic, key=lambda lang: (len(lang), lang))[:1]

    original = _matching_languages(available, original_language)
    english = _matching_languages(available, "en")
    picks = []
    if policy in ("original", "original_english") and original:
        picks.append(original[0])
    if policy in ("english", "original_english") and english and english[0] not in picks:
        picks.append(english[0])
    if not picks and policy in ("original", "original_english"):
        manual = set((info.get("subtitles") or {}).keys()) - {"danmaku"}
        fallback = manual or (available - {"danmaku"})
        if fallback:
            picks.append(sorted(fallback, key=lambda lang: (len(lang), lang))[0])
    return picks


def format_summary(fmt):
    if not fmt:
        return "none"
    parts = [str(fmt.get("format_id") or "unknown")]
    if fmt.get("height"):
        parts.append(f"{fmt['height']}p")
    if fmt.get("fps"):
        parts.append(f"{fmt['fps']:g}fps")
    if fmt.get("vcodec") and fmt.get("vcodec") != "none":
        parts.append(str(fmt["vcodec"]).split(".", 1)[0])
    if fmt.get("acodec") and fmt.get("acodec") != "none":
        parts.append(str(fmt["acodec"]).split(".", 1)[0])
    if fmt.get("language"):
        parts.append(str(fmt["language"]))
    return "/".join(parts)


def highest_video_summary(info):
    videos = [
        fmt for fmt in (info.get("formats") or [])
        if fmt.get("vcodec") not in (None, "none")
    ]
    if not videos:
        return "none"
    best = max(videos, key=lambda fmt: (
        fmt.get("height") or 0,
        fmt.get("fps") or 0,
        fmt.get("quality") or 0,
        fmt.get("tbr") or 0,
    ))
    return format_summary(best)


def selected_format_summary(info):
    selected = info.get("requested_downloads") or info.get("requested_formats") or []
    if selected:
        return "+".join(format_summary(fmt) for fmt in selected)
    return format_summary(info)


def sanitize_diagnostic(value, home=None):
    text = str(value)
    text = re.sub(r"https?://\S+", "[URL]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)(proxy(?:_url)?=)([^\s,;]+)", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(cookie(?:file)?=)([^\s,;]+)", r"\1[REDACTED]", text)
    home = home or os.path.expanduser("~")
    if home:
        text = text.replace(home, "~")
    return text
