import math
import os
import re


STAGE_RANGES = {
    "parse": (0.0, 0.05),
    "media": (0.05, 0.88),
    "subtitle": (0.05, 0.95),
    "postprocess": (0.88, 0.99),
    "subtitle_finalize": (0.95, 0.99),
    "complete": (1.0, 1.0),
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
