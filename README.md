<div align="center">

<img src="icon.png" width="120" alt="Danload Icon"/>

# Danload

**Universal Media Downloader · 全能媒体下载器**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows-lightgrey)](#download--下载)
[![Release](https://img.shields.io/github/v/release/Danub3/Danload)](https://github.com/Danub3/Danload/releases/latest)

[English](#english) · [中文](#中文)

</div>

---

## English

### What is Danload?

Danload is a free, clean desktop app for downloading videos, audio, and files at their original quality — with built-in ProRes transcoding for editors.

### Features

| Feature | Description |
|---------|-------------|
| **Original Quality** | Downloads the highest available quality, no re-encoding |
| **ProRes Export** | One-click transcode to Apple ProRes — ready for Final Cut Pro, DaVinci Resolve |
| **Audio Only** | Extract audio directly |
| **File Download** | General-purpose URL file downloader |
| **Browser Cookie** | Access member-only or login-required content via your browser's cookies |
| **Custom Save Location** | Choose where files are saved |
| **Auto Update** | Notifies you when a new version is available |
| **Bilingual UI** | Switch between English and Chinese in-app |

### Download

Go to [Releases](https://github.com/Danub3/Danload/releases/latest) and download:
- **macOS** → `.dmg`
- **Windows** → `.exe`

### Build from Source

**Requirements:**
- Python 3.10+
- ffmpeg (`brew install ffmpeg` on macOS)

```bash
git clone https://github.com/Danub3/Danload.git
cd Danload
pip install customtkinter yt-dlp pyinstaller
pyinstaller Danload.spec
```

### Supported Sites

Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) — supports 1000+ sites including YouTube, Bilibili, Twitter/X, Instagram, TikTok, and more.

---

## 中文

### 什么是 Danload？

Danload 是一款免费、简洁的桌面应用，支持原画质下载视频、音频和文件，并内置 ProRes 转码功能，专为视频编辑者设计。

### 功能特性

| 功能 | 说明 |
|------|------|
| **原画下载** | 下载最高可用画质，不经过二次压缩 |
| **ProRes 转码** | 一键转码为 Apple ProRes，直接导入 Final Cut Pro、DaVinci Resolve |
| **纯音频提取** | 直接提取视频音轨 |
| **文件下载** | 通用 URL 文件下载 |
| **浏览器 Cookie** | 通过浏览器 Cookie 访问需要登录或会员权限的内容 |
| **自定义保存位置** | 自由选择文件保存路径 |
| **自动更新提示** | 有新版本时自动提醒 |
| **中英文切换** | 应用内一键切换界面语言 |

### 下载

前往 [Releases](https://github.com/Danub3/Danload/releases/latest) 下载：
- **Mac 用户** → `.dmg`
- **Windows 用户** → `.exe`

### 从源码构建

**环境要求：**
- Python 3.10+
- ffmpeg（Mac 使用 `brew install ffmpeg` 安装）

```bash
git clone https://github.com/Danub3/Danload.git
cd Danload
pip install customtkinter yt-dlp pyinstaller
pyinstaller Danload.spec
```

### 支持网站

基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，支持 1000+ 网站，包括 YouTube、Bilibili、Twitter/X、Instagram、抖音等。

---

## License

MIT © [Danub3](https://github.com/Danub3)
