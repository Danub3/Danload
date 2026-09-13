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

### Maintenance release 1.2.1

- Updated yt-dlp to 2026.8.19.
- Bundled the EJS scripts and Deno runtime required by current YouTube extraction.
- Preserved authenticated quality during Bilibili CDN/HTTP 403 retries.
- Added optional subtitles to video downloads, with language and SRT/VTT controls.
- Made user-visible progress monotonic across download and processing stages.
- Made the proxy field explicit: an empty value uses direct application requests.
- Cancellation now interrupts active network responses and ffmpeg work, then removes only this download's temporary files.
- A transient Bilibili CDN failure now removes new single-stream leftovers, refreshes metadata, and retries once without changing the selected credentials or quality policy.
- Completed MKV, MP4, and ProRes outputs are checked with ffprobe for the expected container plus video and audio streams before success is shown.
- Error summaries stay in a fixed-height status area; the full copyable error remains available by clicking the summary.

### What is Danload?

Danload is a free, clean desktop app for downloading videos, audio, and files at their original quality — with built-in ProRes transcoding for editors.

### Features

| Feature | Description |
|---------|-------------|
| **Original Quality** | Downloads the highest available quality, no re-encoding |
| **Video Output** | Choose MKV, MP4, or ProRes from the video mode |
| **ProRes Export** | One-click transcode to Apple ProRes — ready for Final Cut Pro, DaVinci Resolve |
| **Audio Only** | Extract audio directly |
| **Video Subtitles** | Optionally download manual or automatic subtitles alongside video |
| **File Download** | General-purpose URL file downloader |
| **Browser Cookie** | Access member-only or login-required content via your browser's cookies |
| **Proxy Support** | Route all downloads through HTTP/SOCKS proxy (Clash, V2Ray, etc.) |
| **Custom Save Location** | Choose where files are saved |
| **Persistent Settings** | Remembers your save location and video output format |
| **Auto Update** | Notifies you when a new version is available |
| **Bilingual UI** | Switch between English and Chinese in-app |
| **Appearance** | Follows the system theme by default, with a light/dark toggle |

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
# Output: installer_output/Danload-1.2.1-Windows-x64-Setup.exe
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

### 维护版本 1.2.1

- yt-dlp 更新至 2026.8.19。
- 打包当前 YouTube 解析所需的 EJS 脚本与 Deno 运行时。
- B 站 CDN / HTTP 403 重试期间保持登录画质，不再匿名降级。
- 视频下载可同时下载字幕，并可选择语言策略与 SRT/VTT。
- 下载、封装与转码阶段的可见进度保持单调递增。
- 代理输入框为空时显式使用应用直连模式。
- 取消会立即中断当前网络请求和 ffmpeg 处理，并只清理本次下载登记的临时文件。
- B 站 CDN 出现瞬时故障时，会清理本轮新增的单流残留、刷新元数据并重试一次，同时保持原有登录凭据与画质策略。
- MKV、MP4 和 ProRes 完成前会通过 ffprobe 检查容器以及视频、音频流，单流文件不会显示为下载完成。
- 错误摘要固定在稳定高度的状态区中，点击摘要仍可查看并复制完整错误。

### 什么是 Danload？

Danload 是一款免费、简洁的桌面应用，支持原画质下载视频、音频和文件，并内置 ProRes 转码功能，专为视频编辑者设计。

### 功能特性

| 功能 | 说明 |
|------|------|
| **原画下载** | 下载最高可用画质，不经过二次压缩 |
| **视频输出** | 视频模式可选择 MKV、MP4 或 ProRes |
| **ProRes 转码** | 一键转码为 Apple ProRes，直接导入 Final Cut Pro、DaVinci Resolve |
| **纯音频提取** | 直接提取视频音轨 |
| **视频附带字幕** | 下载视频时可同时下载人工字幕或自动字幕 |
| **文件下载** | 通用 URL 文件下载 |
| **浏览器 Cookie** | 通过浏览器 Cookie 访问需要登录或会员权限的内容 |
| **代理支持** | 所有下载均可通过 HTTP/SOCKS 代理（Clash、V2Ray 等） |
| **自定义保存位置** | 自由选择文件保存路径 |
| **设置持久化** | 自动记住保存路径和视频输出格式 |
| **自动更新提示** | 有新版本时自动提醒 |
| **中英文切换** | 应用内一键切换界面语言 |
| **外观主题** | 默认跟随系统，也可在应用内切换深色与浅色 |

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
# 输出：installer_output/Danload-1.2.1-Windows-x64-Setup.exe
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
