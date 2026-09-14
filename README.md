<div align="center">

<img src="assets/icon.png" width="120" alt="Danload Icon"/>

# Danload

**Universal Media Downloader · 全能媒体下载器**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows-lightgrey)](#download--下载)
[![Release](https://img.shields.io/github/v/release/Danub3/Danload)](https://github.com/Danub3/Danload/releases/latest)

[English](#english) · [中文](#中文)

</div>

---

## English

### Maintenance release 1.2.2

- Updated yt-dlp to 2026.8.19.
- Bundled the EJS scripts and Deno runtime required by current YouTube extraction.
- Preserved authenticated quality during Bilibili CDN/HTTP 403 retries.
- Added optional subtitles to video downloads, with language and SRT/VTT controls.
- Made user-visible progress monotonic across download and processing stages.
- Made the proxy field explicit: an empty value uses direct application requests.
- Cancellation now interrupts active network responses and ffmpeg work, then removes only this download's temporary files.
- A transient Bilibili CDN failure now removes new single-stream leftovers, refreshes metadata, and retries once without changing the selected credentials or quality policy.
- Video downloads now retain yt-dlp's actual final container and extension. Danload does not force MKV/MP4/ProRes packaging or rename a file to suggest compatibility.
- Added an independent local-file editor conversion with automatic H.264/HEVC, optional ProRes, and FFV1 presets. It preserves the source and validates resolution, frame rate, color/HDR tags, audio layout, metadata, and duration.
- Error summaries stay in a fixed-height status area; the full copyable error remains available by clicking the summary.

### What is Danload?

Danload is a free, clean desktop app for downloading videos, audio, and files at their original quality, with an independent local conversion tool for editor-friendly files.

### Features

| Feature | Description |
|---------|-------------|
| **Original Quality** | Downloads the highest available quality, no re-encoding |
| **Native Video Container** | Keeps yt-dlp's actual merged container and extension; no forced remux or fake extension |
| **Editor-Compatible Conversion** | Convert an existing local video with automatic H.264/HEVC, optional ProRes, or FFV1 output without changing the download or source file |
| **Audio Only** | Extract audio directly |
| **Video Subtitles** | Optionally download manual or automatic subtitles alongside video |
| **File Download** | General-purpose URL file downloader |
| **Browser Cookie** | Access member-only or login-required content via your browser's cookies |
| **Proxy Support** | Route all downloads through HTTP/SOCKS proxy (Clash, V2Ray, etc.) |
| **Custom Save Location** | Choose where files are saved |
| **Persistent Settings** | Remembers your save location and proxy |
| **Auto Update** | Notifies you when a new version is available |
| **Bilingual UI** | Switch between English and Chinese in-app |
| **Appearance** | Follows the system theme by default, with a light/dark toggle |

Downloads are quality-first and retain the container produced by yt-dlp. The local
conversion tool is separate: compatible H.264/HEVC/ProRes streams can be copied;
otherwise H.264 and HEVC are visually near-lossless re-encodes, ProRes is an
optional high-quality editing intermediate, and FFV1 is mathematically lossless
but much larger and less widely supported. Resolution, frame rate, color/HDR tags,
audio layout, timing, and the original file are preserved and validated.

### Download

Go to [Releases](https://github.com/Danub3/Danload/releases/latest) and download:
- **macOS** → `.dmg`
- **Windows** → `.exe`

### Build from Source

**Requirements:**
- Python 3.10+
- ffmpeg and ffprobe
- Deno 2.3+ (bundled into release builds for YouTube JavaScript challenges)
- Optional: `aria2c` on PATH enables segmented parallel transfers for direct HTTP(S) media; yt-dlp's native downloader remains the fallback.

**macOS:**

```bash
git clone https://github.com/Danub3/Danload.git
cd Danload
pip install -r requirements.txt
brew install ffmpeg deno  # if not already installed
pyinstaller Danload.spec
```

**Windows:**

```bash
git clone https://github.com/Danub3/Danload.git
cd Danload
pip install -r requirements.txt
# Download ffmpeg.exe and ffprobe.exe from https://ffmpeg.org/download.html
# Place them in the project root directory and install Deno 2.3+
python -m PyInstaller --noconfirm --clean Danload-win.spec
# Install Inno Setup 6, then build the per-user x64 installer:
iscc installer.iss
# Output: installer_output/Danload-1.2.2-Windows-x64-Setup.exe
```

### Supported Sites

Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) — supports 1000+ sites including YouTube, Bilibili, Twitter/X, Instagram, TikTok, public Telegram video posts, and more.

### Network routing

The proxy field controls Danload and yt-dlp requests. Leaving it empty disables
environment HTTP proxies for those requests. A system-level transparent proxy,
VPN, or TUN network extension can still intercept traffic below the application
layer; configure that tool with direct/bypass rules (for example for
`*.bilibili.com`, `*.bilivideo.cn`, and `*.bilivideo.com`) when its route is
slower than a direct connection.

---

## 中文

### 维护版本 1.2.2

- yt-dlp 更新至 2026.8.19。
- 打包当前 YouTube 解析所需的 EJS 脚本与 Deno 运行时。
- B 站 CDN / HTTP 403 重试期间保持登录画质，不再匿名降级。
- 视频下载可同时下载字幕，并可选择语言策略与 SRT/VTT。
- 下载、封装与转码阶段的可见进度保持单调递增。
- 代理输入框为空时显式使用应用直连模式。
- 取消会立即中断当前网络请求和 ffmpeg 处理，并只清理本次下载登记的临时文件。
- B 站 CDN 出现瞬时故障时，会清理本轮新增的单流残留、刷新元数据并重试一次，同时保持原有登录凭据与画质策略。
- 视频下载保留 yt-dlp 实际合并得到的容器和扩展名，不强制封装为 MKV/MP4/ProRes，也不通过改扩展名伪装兼容性。
- 新增独立的本地“剪辑兼容转换”：自动选择 H.264/HEVC，也可选 ProRes 或 FFV1；校验分辨率、帧率、色彩/HDR 标记、音轨、元数据和时长，原文件保持不变。
- 错误摘要固定在稳定高度的状态区中，点击摘要仍可查看并复制完整错误。

### 什么是 Danload？

Danload 是一款免费、简洁的桌面应用，支持原画质下载视频、音频和文件，并提供独立的本地剪辑兼容转换工具。

### 功能特性

| 功能 | 说明 |
|------|------|
| **原画下载** | 下载最高可用画质，不经过二次压缩 |
| **原生视频容器** | 保留 yt-dlp 实际合并的容器和扩展名，不强制重封装或伪造扩展名 |
| **剪辑兼容转换** | 将本地视频自动转换为 H.264/HEVC，也可选择 ProRes 或 FFV1，不改变下载结果，也不覆盖原文件 |
| **纯音频提取** | 直接提取视频音轨 |
| **视频附带字幕** | 下载视频时可同时下载人工字幕或自动字幕 |
| **文件下载** | 通用 URL 文件下载 |
| **浏览器 Cookie** | 通过浏览器 Cookie 访问需要登录或会员权限的内容 |
| **代理支持** | 所有下载均可通过 HTTP/SOCKS 代理（Clash、V2Ray 等） |
| **自定义保存位置** | 自由选择文件保存路径 |
| **设置持久化** | 自动记住保存路径和代理设置 |
| **自动更新提示** | 有新版本时自动提醒 |
| **中英文切换** | 应用内一键切换界面语言 |
| **外观主题** | 默认跟随系统，也可在应用内切换深色与浅色 |

下载流程以画质优先，并保留 yt-dlp 产生的实际容器。本地转换与下载相互独立：
兼容的 H.264/HEVC/ProRes 可以直接复制媒体流；否则 H.264 与 HEVC 属于视觉近无损
重新编码，ProRes 是可选的高质量剪辑中间格式，FFV1 是数学无损但体积很大且兼容性
较弱的格式。程序会校验并保留分辨率、帧率、色彩/HDR 标记、音轨布局、时长以及原文件。

### 下载

前往 [Releases](https://github.com/Danub3/Danload/releases/latest) 下载：
- **Mac 用户** → `.dmg`
- **Windows 用户** → `.exe`

### 从源码构建

**环境要求：**
- Python 3.10+
- ffmpeg 与 ffprobe
- Deno 2.3+（发布构建会将其打包，用于 YouTube JavaScript challenge）
- 可选：将 `aria2c` 加入 PATH，可为直链 HTTP(S) 媒体启用分段并发下载；未安装时自动使用 yt-dlp 原生下载。

**macOS：**

```bash
git clone https://github.com/Danub3/Danload.git
cd Danload
pip install -r requirements.txt
brew install ffmpeg deno  # 如未安装
pyinstaller Danload.spec
```

**Windows：**

```bash
git clone https://github.com/Danub3/Danload.git
cd Danload
pip install -r requirements.txt
# 从 https://ffmpeg.org/download.html 下载 ffmpeg.exe 和 ffprobe.exe
# 放到项目根目录，并安装 Deno 2.3+
python -m PyInstaller --noconfirm --clean Danload-win.spec
# 安装 Inno Setup 6，然后构建当前用户范围的 x64 安装包：
iscc installer.iss
# 输出：installer_output/Danload-1.2.2-Windows-x64-Setup.exe
```

### 支持网站

基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，支持 1000+ 网站，包括 YouTube、Bilibili、Twitter/X、Instagram、抖音、Telegram 公开频道视频帖等。

### 网络路由说明

代理输入框只控制 Danload 和 yt-dlp 自己发出的请求。留空时会禁用应用层
环境代理；系统级透明代理、VPN 或 TUN 网络扩展仍可能在更底层接管流量。
如果这类工具的线路较慢，请在其中为 `*.bilibili.com`、`*.bilivideo.cn` 和
`*.bilivideo.com` 添加直连/绕过规则。

---

## License

MIT © [Danub3](https://github.com/Danub3)
