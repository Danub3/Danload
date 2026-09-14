# Danload 1.2.2 maintenance notes

Date: 2026-09-14

## Product boundary

Danload keeps URL downloads quality-first. Video downloads use yt-dlp's native
selection and retain the actual final container and extension produced after
stream merging. The app does not offer a download-time MKV/MP4/ProRes choice,
force a remux, or rename a file to imply editor compatibility.

Local editor conversion is a separate workflow for a user-selected file. It
always writes a new sibling file, preserves the source, avoids overwriting an
existing output, supports cancellation and cleanup, and validates the result
with ffprobe. The UI exposes Auto, H.264, HEVC, ProRes, and FFV1 presets so the
non-default formats below are actual user choices rather than internal-only
plans.

## Conversion presets

- `auto` keeps an already compatible H.264, HEVC, ProRes, or FFV1 stream where
  possible. HDR/high-bit-depth material prefers HEVC; alpha or 4:4:4 material
  prefers ProRes. Ordinary incompatible SDR material uses H.264.
- H.264 and HEVC outputs are MP4 files. They are re-encodes when the source
  codec cannot be copied, so they are visually near-lossless rather than
  mathematically lossless. Compatible video and audio streams may be copied.
- ProRes output is an optional MOV editing intermediate. It is not a universal
  download default and is not claimed to be bit-for-bit lossless for an
  incompatible source.
- FFV1 output is MKV with FFV1 video and FLAC audio. It is mathematically
  lossless, but large and less compatible with some editing applications.

Every conversion plan carries its target container, extension, codec, pixel
format, audio policy, and quality model into the ffmpeg command and output
validation. Resolution, frame rate, sample aspect ratio, color/HDR tags, audio
layout, stream count, duration, and source-file preservation are checked where
the source metadata provides a meaningful value.

## Regression coverage

The test suite covers native-container download selection, removal of the old
forced-packaging paths, Bilibili retry cleanup, output collision handling,
cancellation, subtitle stages, and all conversion preset families.
