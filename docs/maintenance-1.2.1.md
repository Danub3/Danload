# Danload 1.2.1 maintenance notes

Date: 2026-09-12

## Official references

- yt-dlp stable release `2026.08.19`: https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19
- yt-dlp EJS setup guide: https://github.com/yt-dlp/yt-dlp/wiki/EJS
- YouTube SABR tracking issue: https://github.com/yt-dlp/yt-dlp/issues/12482

The stable release added YouTube player-client maintenance and additional client
fallbacks. The EJS guide states that current YouTube extraction requires a
supported JavaScript runtime and matching `yt-dlp-ejs` scripts. Pip installs
must use the `default` dependency group to install those scripts.

## Root causes addressed

1. The previous pip requirement installed yt-dlp core without `yt-dlp-ejs`.
   The app also did not bundle a JavaScript runtime, so complete YouTube format
   extraction depended on software that happened to be installed on the user's
   machine.
2. A global, old browser User-Agent and global HTTP chunk/concurrency overrides
   replaced extractor defaults for every site. The app now leaves YouTube
   client and request-header selection to yt-dlp and applies site headers only
   where required.
3. An authenticated 403 retry eventually switched to an anonymous attempt.
   This could turn a Bilibili member-quality failure into a lower-quality public
   download. Retries now retain the selected authentication and proxy scope.
4. Video downloads implicitly started a second subtitle pass and discarded all
   subtitle errors. Subtitles are now an explicit option nested under video,
   with language and SRT/VTT controls disabled until enabled. Subtitle failure
   preserves the completed video and reports a partial-success state.
5. Per-stream percentages were displayed as overall progress. Download,
   subtitle, and post-processing values now map to monotonic overall stages.
6. An empty proxy field now creates an explicit direct opener and passes
   `proxy=''` to yt-dlp, so stale settings and environment HTTP proxies do not
   silently route application requests. This cannot override a system-level
   VPN, TUN, or transparent network extension; those routes need their own
   direct/bypass rules.
7. Cancellation now signals a shared event immediately, closes tracked urllib
   responses, interrupts active yt-dlp sessions and ffmpeg processes, and
   removes only paths registered by the current download. The UI thread does
   not wait for network or process cleanup.
8. Bilibili DASH video and audio use separate CDN requests. A transient failure
   after one stream completed could therefore leave a playable but silent MP4
   beside an error. Danload now protects files that predate the operation,
   removes only newly tracked attempt artifacts, re-extracts fresh media URLs,
   and retries once with the same credentials, proxy, and format policy. A
   final failure also removes newly created single-stream leftovers.
9. Video success is now conditional on an ffprobe check of the expected file
   extension, container, video stream, and audio stream. ProRes output also
   requires a ProRes video codec. The status row has a fixed height and generic
   errors are compacted to one summary while the full error remains clickable.

The installed yt-dlp `2026.08.19` Bilibili extractor reads the primary DASH
`baseUrl` but does not expose the API's `backupUrl` list as alternate format
URLs. Re-extracting metadata is therefore the conservative application-level
way to obtain a different CDN URL without patching yt-dlp internals.

## Public regression samples

- YouTube `aqz-KE-bpKQ`: selected `401+251`, 2160p60 AV1 plus Opus. Test-mode
  reads succeeded for both media URLs. The expected merge failed only because
  yt-dlp `--test` intentionally truncates each input to 10 KiB.
- Bilibili `BV1GJ411x7h7`: selected `100026+30280`, 1080p25 AV1 plus AAC without
  login. Both test-mode media reads succeeded. The extractor correctly reported
  that 1080P high-bitrate requires a premium login.
- YouTube `Ks-_Mh1QhMc`: Deno/EJS challenge solving ran successfully and the
  subtitle stage downloaded an English SRT alongside the video workflow.

YouTube may still require fresh cookies, a suitable player client, or a PO Token
for account-, region-, or rollout-specific formats. Danload does not fabricate
tokens or force a fixed client. Its diagnostic log records the yt-dlp version,
extractor, highest visible candidate, selected formats, authentication/proxy
flags, retry profile, and sanitized warnings without storing URLs, cookies,
proxy credentials, or full personal paths.
