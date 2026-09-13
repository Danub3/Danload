import customtkinter as ctk
import yt_dlp
import threading
from contextlib import contextmanager
import os
import sys
import re
import subprocess
import logging
import queue
import shutil
from logging.handlers import RotatingFileHandler
import urllib.request
import json
import webbrowser
from urllib.parse import urlparse, unquote
import time

from danload_core import (
    choose_subtitle_languages,
    highest_video_summary,
    media_format_selector,
    progress_fraction,
    resolve_download_selection,
    sanitize_diagnostic,
    selected_format_summary,
    stage_progress,
)

APP_VERSION = "1.2.1"

if sys.platform != 'win32':
    _extra_paths = ['/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin']
    os.environ['PATH'] = ':'.join(_extra_paths + [p for p in os.environ.get('PATH', '').split(':') if p not in _extra_paths])

class DummyOutput:
    def write(self, *args, **kwargs): pass
    def flush(self): pass
    def isatty(self): return False

if sys.stdout is None: sys.stdout = DummyOutput()
if sys.stderr is None: sys.stderr = DummyOutput()

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

DEFAULT_DOWNLOAD_PATH = os.path.join(os.path.expanduser('~'), 'Downloads', 'Danload')
ORIGINAL_CONTAINER_DEFAULT = 'mkv'
# Kept for integrations that imported the pre-1.2.1 container choices.
ORIGINAL_CONTAINER_VALUES = ('MKV', 'MP4')
VIDEO_FORMAT_VALUES = ('MKV', 'MP4', 'ProRes')
WINDOW_WIDTH = 720
# Kept for compatibility with older integrations; live layout sizing is
# content-driven in ``_resize_window_for_mode``.
BASE_WINDOW_HEIGHT = 465
VIDEO_WINDOW_HEIGHT = 520
MAIN_FRAME_VERTICAL_PADDING = 28
STATUS_AREA_HEIGHT = 34
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
_PROXY_UNSET = object()


def entry_drag_scroll_units(pointer_x, width, edge=8):
    """Return horizontal scroll units for a drag near/outside an entry edge."""
    if width <= 0:
        return 0
    if pointer_x < edge:
        return -min(8, max(1, (edge - pointer_x + 17) // 18))
    right_edge = width - edge
    if pointer_x > right_edge:
        return min(8, max(1, (pointer_x - right_edge + 17) // 18))
    return 0


def get_settings_path():
    if sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    elif os.name == 'nt':
        base = os.environ.get('APPDATA') or os.path.join(
            os.path.expanduser('~'), 'AppData', 'Roaming')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(
            os.path.expanduser('~'), '.config')
    return os.path.join(base, 'Danload', 'settings.json')


SETTINGS_PATH = get_settings_path()
LOG_PATH = os.path.join(os.path.dirname(SETTINGS_PATH), 'danload.log')


def get_ffmpeg_path():
    _name = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
    if hasattr(sys, '_MEIPASS'):
        p = os.path.join(sys._MEIPASS, _name)
        if os.path.exists(p): return p
    main_dir = os.path.dirname(sys.executable)
    for rel in ('', os.path.join('..', 'Frameworks')):
        p = os.path.normpath(os.path.join(main_dir, rel, _name))
        if os.path.exists(p): return p
    if sys.platform == 'darwin':
        return '/opt/homebrew/bin/ffmpeg'
    elif os.name == 'nt':
        return 'ffmpeg.exe'
    return 'ffmpeg'


def get_ffprobe_path():
    _name = 'ffprobe.exe' if os.name == 'nt' else 'ffprobe'
    if hasattr(sys, '_MEIPASS'):
        p = os.path.join(sys._MEIPASS, _name)
        if os.path.exists(p):
            return p
    main_dir = os.path.dirname(sys.executable)
    for rel in ('', os.path.join('..', 'Frameworks')):
        p = os.path.normpath(os.path.join(main_dir, rel, _name))
        if os.path.exists(p):
            return p
    if sys.platform == 'darwin':
        return '/opt/homebrew/bin/ffprobe'
    if os.name == 'nt':
        return 'ffprobe.exe'
    return 'ffprobe'


def get_aria2c_path():
    """Return an optional aria2c executable for segmented HTTP downloads.

    aria2c is deliberately optional: yt-dlp's native downloader remains the
    portable fallback for installations that do not have it.  A bundled
    executable is preferred in packaged builds, followed by the user's PATH.
    """
    executable_names = ('aria2c.exe', 'aria2c') if os.name == 'nt' else ('aria2c',)
    search_roots = []
    if hasattr(sys, '_MEIPASS'):
        search_roots.append(sys._MEIPASS)
    main_dir = os.path.dirname(sys.executable)
    search_roots.extend((main_dir, os.path.normpath(os.path.join(main_dir, '..', 'Frameworks'))))
    for name in executable_names:
        for root in search_roots:
            path = os.path.join(root, name)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    for name in executable_names:
        path = shutil.which(name)
        if path:
            return path
    return None


def get_js_runtimes():
    """Return the first bundled or installed JS runtime supported by yt-dlp."""
    executable_names = ('deno.exe', 'deno') if os.name == 'nt' else ('deno',)
    search_roots = []
    if hasattr(sys, '_MEIPASS'):
        search_roots.append(sys._MEIPASS)
    main_dir = os.path.dirname(sys.executable)
    search_roots.extend((main_dir, os.path.normpath(os.path.join(main_dir, '..', 'Frameworks'))))
    for name in executable_names:
        for root in search_roots:
            path = os.path.join(root, name)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return {'deno': {'path': path}}

    deno = shutil.which('deno')
    if deno:
        return {'deno': {'path': deno}}
    node = shutil.which('node')
    if node:
        return {'node': {'path': node}}
    return {'deno': {}}


def get_prores_encoder():
    """Return the appropriate ProRes encoder for the current platform."""
    return 'prores_videotoolbox' if sys.platform == 'darwin' else 'prores_ks'


class YDLLogger:
    def __init__(self, app):
        self.app = app

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        self.app._log_diagnostic('yt-dlp warning: %s', message)

    def error(self, message):
        self.app._log_diagnostic('yt-dlp error: %s', message)


class DownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._last_error = ""
        self._logger = logging.getLogger(f'Danload.{id(self)}')
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        try:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            handler = RotatingFileHandler(
                LOG_PATH, maxBytes=512 * 1024, backupCount=2, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            self._logger.addHandler(handler)
        except OSError:
            self._logger.addHandler(logging.NullHandler())
        self.lang = "zh"
        self.download_folder = DEFAULT_DOWNLOAD_PATH
        self.original_container = ORIGINAL_CONTAINER_DEFAULT
        self.video_format = ORIGINAL_CONTAINER_DEFAULT
        self.proxy = ""
        self.load_settings()

        # Smooth progress state (main-thread animation)
        self._progress_target = 0.0
        self._progress_displayed = 0.0
        self._progress_stage = 'parse'
        self._progress_lock = threading.Lock()
        self._ui_queue = queue.SimpleQueue()
        self._downloading = False
        self._cancel_event = threading.Event()
        self._resource_lock = threading.Lock()
        self._active_ydls = set()
        self._active_processes = set()
        self._active_responses = set()
        self._download_artifacts = set()
        self._protected_artifacts = set()

        self.i18n = {
            "zh": {
                "title": "Danload", "subtitle": "全能媒体提取引擎",
                "placeholder": "粘贴视频或文件链接...", "status_wait": "等待输入",
                "btn_start": "开始下载", "btn_cancel": "取消", "btn_open": "打开文件夹" if os.name == 'nt' else "打开 Finder",
                "opt_video": "视频", "opt_audio": "音频", "opt_general": "文件",
                "opt_cookie": "使用浏览器 Cookie", "lang_switch": "EN",
                "err_empty": "请先粘贴链接", "err_invalid": "未检测到有效链接",
                "err_no_subtitles": "没有找到符合所选语言的字幕",
                "err_telegram_unsupported": "Danload 目前支持公开 t.me 频道视频链接；Telegram Web、私有群和受限内容不能直接粘贴下载。",
                "btn_browse": "选择", "label_folder": "保存位置",
                "label_video_format": "视频输出", "include_subtitles": "同时下载字幕",
                "sub_original_english": "原语言 + 英语", "sub_original": "原语言",
                "sub_english": "英语", "sub_automatic": "自动字幕",
                "label_proxy": "代理地址", "placeholder_proxy": "http://127.0.0.1:7890（可选）",
                "status_done_original": "✅ 下载完成！（{container} 封装）",
                "status_done_mkv_fallback": "✅ 下载完成！（MKV · 原画编码不兼容 MP4）",
                "status_done_subtitles": "✅ 字幕下载完成！（{languages} · {format}）",
                "status_done_video_subtitles": "✅ 视频与字幕下载完成！（{video} + {languages} · {format}）",
                "status_partial_subtitles": "⚠️ 视频下载完成，但字幕下载失败（点击查看详情）",
                "status_retry_bilibili": "B站 CDN 节点不可用，正在刷新下载链接...",
                "update_title": "发现新版本",
                "update_msg": "Danload {ver} 已发布，当前版本 {cur}。\n\n更新内容：\n{notes}",
                "update_btn": "前往下载",
                "update_later": "稍后再说",
            },
            "en": {
                "title": "Danload", "subtitle": "Universal Media Extractor",
                "placeholder": "Paste video or file URL...", "status_wait": "Waiting for input",
                "btn_start": "Download", "btn_cancel": "Cancel", "btn_open": "Open Folder" if os.name == 'nt' else "Open Finder",
                "opt_video": "Video", "opt_audio": "Audio", "opt_general": "File",
                "opt_cookie": "Use Browser Cookie", "lang_switch": "中文",
                "err_empty": "Please paste a URL first", "err_invalid": "No valid URL detected",
                "err_no_subtitles": "No subtitles matched the selected language",
                "err_telegram_unsupported": "Danload currently supports public t.me channel video links. Telegram Web, private chats, and restricted content cannot be pasted directly.",
                "btn_browse": "Browse", "label_folder": "Save to",
                "label_video_format": "Video output", "include_subtitles": "Download subtitles",
                "sub_original_english": "Original + English", "sub_original": "Original",
                "sub_english": "English", "sub_automatic": "Automatic",
                "label_proxy": "Proxy", "placeholder_proxy": "http://127.0.0.1:7890 (optional)",
                "status_done_original": "✅ Done! ({container} container)",
                "status_done_mkv_fallback": "✅ Done! (MKV - codec incompatible with MP4)",
                "status_done_subtitles": "✅ Subtitles downloaded! ({languages} · {format})",
                "status_done_video_subtitles": "✅ Video and subtitles downloaded! ({video} + {languages} · {format})",
                "status_partial_subtitles": "⚠️ Video downloaded, but subtitles failed (click for details)",
                "status_retry_bilibili": "Bilibili CDN unavailable; refreshing media links...",
                "update_title": "New Version Available",
                "update_msg": "Danload {ver} is available (you have {cur}).\n\nWhat's new:\n{notes}",
                "update_btn": "Download",
                "update_later": "Later",
            }
        }

        self.title("Danload")
        self.center_window(WINDOW_WIDTH, VIDEO_WINDOW_HEIGHT)
        self.resizable(False, False)
        self.configure(fg_color=("#F5F5F7", "#1C1C1E"))

        self.cookie_file_path = ctk.StringVar(value="")
        self.use_cookie_var = ctk.BooleanVar(value=False)
        self.proxy_var = ctk.StringVar(value=self.proxy)
        self.video_format_var = ctk.StringVar(value=self._video_format_label(self.video_format))
        # Compatibility alias for callers that still read the old variable.
        self.original_container_var = self.video_format_var
        self.include_subtitles_var = ctk.BooleanVar(value=False)
        self.subtitle_policy = 'original_english'
        self.subtitle_format_var = ctk.StringVar(value='SRT')

        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.build_main_ui()
        self.main_frame.pack(fill="both", expand=True, padx=24, pady=14)
        self.after_idle(self._resize_window_for_mode)
        self.after(20, self._poll_ui_queue)

        self._log_diagnostic(
            'startup app=%s yt-dlp=%s js_runtime=%s', APP_VERSION,
            yt_dlp.version.__version__, next(iter(get_js_runtimes())),
        )

        update_proxy = self._get_proxy()
        threading.Thread(
            target=self.check_for_updates, args=(update_proxy,), daemon=True).start()

    def t(self, key):
        return self.i18n[self.lang][key]

    def load_settings(self):
        try:
            with open(SETTINGS_PATH, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return
        if not isinstance(data, dict):
            return

        folder = data.get('download_folder')
        if isinstance(folder, str) and folder.strip():
            self.download_folder = folder

        container = data.get('original_container')
        if isinstance(container, str) and container.lower() in ('mkv', 'mp4'):
            self.original_container = container.lower()

        video_format = data.get('video_format', self.original_container)
        if isinstance(video_format, str) and video_format.lower() in ('mkv', 'mp4', 'prores'):
            self.video_format = video_format.lower()

        proxy = data.get('proxy')
        if isinstance(proxy, str):
            self.proxy = proxy

    def _selected_original_container(self):
        video_format_var = self.__dict__.get('video_format_var')
        if video_format_var is not None:
            value = video_format_var.get().strip().lower()
        else:
            value = str(self.__dict__.get(
                'original_container', ORIGINAL_CONTAINER_DEFAULT)).strip().lower()
        if value in ('mkv', 'mp4'):
            return value
        return ORIGINAL_CONTAINER_DEFAULT

    @staticmethod
    def _video_format_label(value):
        return 'ProRes' if str(value).lower() == 'prores' else str(value).upper()

    def _save_settings(self):
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            data = {
                'download_folder': self.download_folder,
                'original_container': self._selected_original_container(),
                'video_format': self.video_format,
                'proxy': self._get_proxy() or '',
            }
            with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── Update check ─────────────────────────────────────────────────────────

    @staticmethod
    def _version_tuple(v):
        try:
            return tuple(int(x) for x in v.split('.'))
        except (ValueError, AttributeError):
            return (0,)

    def check_for_updates(self, proxy=None):
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/Danub3/Danload/releases/latest",
                headers={"User-Agent": "Danload/" + APP_VERSION}
            )
            opener = self._build_opener(proxy)
            with opener.open(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = data.get("tag_name", "").lstrip("v")
            notes = data.get("body", "").strip()
            if latest and self._version_tuple(latest) > self._version_tuple(APP_VERSION):
                self._run_on_ui(lambda: self._show_update_dialog(latest, notes))
        except Exception:
            pass

    def _show_update_dialog(self, latest_ver, notes):
        dlg = ctk.CTkToplevel(self)
        dlg.title(self.t("update_title"))
        dlg.resizable(False, False)
        dlg.grab_set()

        # Center over main window
        self.update_idletasks()
        w, h = 420, 300
        x = self.winfo_x() + (self.winfo_width() - w) // 2
        y = self.winfo_y() + (self.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{x}+{y}")

        notes_short = notes[:280] + "…" if len(notes) > 280 else notes
        msg = self.t("update_msg").format(ver=latest_ver, cur=APP_VERSION, notes=notes_short)

        ctk.CTkLabel(
            dlg, text=self.t("update_title"),
            font=("Helvetica Neue", 16, "bold"),
            text_color=("#1D1D1F", "#FFFFFF")
        ).pack(pady=(20, 0))

        textbox = ctk.CTkTextbox(
            dlg, height=160, wrap="word",
            font=("Helvetica Neue", 12),
            fg_color=("#F5F5F7", "#2C2C2E"),
            border_width=0
        )
        textbox.pack(fill="x", padx=20, pady=(10, 0), expand=False)
        textbox.insert("0.0", msg)
        textbox.configure(state="disabled")

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(pady=14)

        ctk.CTkButton(
            btn_frame, text=self.t("update_btn"), width=130,
            command=lambda: (
                webbrowser.open("https://github.com/Danub3/Danload/releases/latest"),
                dlg.destroy()
            )
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame, text=self.t("update_later"), width=100,
            fg_color="transparent", border_width=1,
            border_color=("#D1D1D6", "#3A3A3C"),
            text_color=("#1D1D1F", "#FFFFFF"),
            hover_color=("#E5E5EA", "#2C2C2E"),
            command=dlg.destroy
        ).pack(side="left", padx=8)

    # ── UI Build ────────────────────────────────────────────────────────────

    def build_main_ui(self):
        # Header
        hdr = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        hdr.pack(fill="x")

        self.title_label = ctk.CTkLabel(
            hdr, text=self.t("title"),
            font=("Helvetica Neue", 24, "bold"),
            text_color=("#1D1D1F", "#FFFFFF"))
        self.title_label.pack(side="left")

        self.subtitle_text_label = ctk.CTkLabel(
            hdr, text=self.t("subtitle"),
            font=("Helvetica Neue", 13),
            text_color=("#6E6E73", "#8E8E93"))
        self.subtitle_text_label.pack(side="left", padx=(10, 0))

        self.lang_btn = ctk.CTkButton(
            hdr, text=self.t("lang_switch"), width=48, height=26,
            fg_color="transparent", border_width=1,
            border_color=("#D1D1D6", "#3A3A3C"),
            text_color=("#1D1D1F", "#FFFFFF"),
            hover_color=("#E5E5EA", "#2C2C2E"),
            font=("Helvetica Neue", 12), corner_radius=6,
            command=self.toggle_language)
        self.lang_btn.pack(side="right")

        self.theme_btn = ctk.CTkButton(
            hdr, text="", width=32, height=26,
            fg_color="transparent", border_width=1,
            border_color=("#D1D1D6", "#3A3A3C"),
            text_color=("#1D1D1F", "#FFFFFF"),
            hover_color=("#E5E5EA", "#2C2C2E"),
            font=("Helvetica Neue", 15), corner_radius=6,
            command=self.toggle_theme)
        self.theme_btn.pack(side="right", padx=(0, 6))
        self._update_theme_button()

        # URL Entry
        self.url_entry = ctk.CTkEntry(
            self.main_frame, placeholder_text=self.t("placeholder"),
            height=44, corner_radius=10,
            border_color=("#D1D1D6", "#3A3A3C"),
            fg_color=("#FFFFFF", "#2C2C2E"),
            text_color=("#1D1D1F", "#FFFFFF"),
            placeholder_text_color=("#C7C7CC", "#636366"),
            font=("Helvetica Neue", 14))
        self.url_entry.pack(fill="x", pady=(10, 0))
        self._bind_url_entry_drag_selection()

        # Download Type
        self.option_var = ctk.StringVar(value="video")
        self.egg_container = ctk.CTkFrame(
            self.main_frame,
            fg_color=("#FFFFFF", "#2C2C2E"), corner_radius=10,
            border_width=1, border_color=("#D1D1D6", "#3A3A3C"))
        self.egg_container.pack(fill="x", pady=(8, 0))

        self.eggs = {}
        for val, key in [("video", "opt_video"), ("audio", "opt_audio"),
                         ("general_file", "opt_general")]:
            self._make_egg(val, key)

        # Video output is one setting row, matching the other rounded rows.
        self.video_output_frame = ctk.CTkFrame(
            self.main_frame,
            fg_color=("#FFFFFF", "#2C2C2E"), corner_radius=10,
            border_width=1, border_color=("#D1D1D6", "#3A3A3C"))
        self.video_format_label = ctk.CTkLabel(
            self.video_output_frame, text=self.t("label_video_format"),
            font=("Helvetica Neue", 12), text_color=("#6E6E73", "#8E8E93"))
        self.video_format_label.pack(side="left", padx=(14, 8), pady=9)

        self.video_format_segment = ctk.CTkSegmentedButton(
            self.video_output_frame,
            values=list(VIDEO_FORMAT_VALUES),
            variable=self.video_format_var,
            width=225, height=28,
            font=("Helvetica Neue", 12),
            command=self.set_video_format)
        self.video_format_segment.pack(side="right", padx=(4, 14), pady=9)

        # Subtitle controls are a separate setting row owned by video mode.
        self.subtitle_frame = ctk.CTkFrame(
            self.main_frame,
            fg_color=("#FFFFFF", "#2C2C2E"), corner_radius=10,
            border_width=1, border_color=("#D1D1D6", "#3A3A3C"))
        self.subtitle_switch = ctk.CTkSwitch(
            self.subtitle_frame, text=self.t('include_subtitles'),
            variable=self.include_subtitles_var,
            font=("Helvetica Neue", 12), text_color=("#1D1D1F", "#FFFFFF"),
            fg_color=("#D1D1D6", "#636366"), progress_color="#0071E3",
            button_color="#FFFFFF", button_hover_color="#FFFFFF",
            command=self.update_subtitle_controls)
        self.subtitle_switch.pack(side="left", padx=(14, 8), pady=9)

        self.subtitle_controls = ctk.CTkFrame(self.subtitle_frame, fg_color="transparent")
        self.subtitle_format_segment = ctk.CTkSegmentedButton(
            self.subtitle_controls, values=['SRT', 'VTT'],
            variable=self.subtitle_format_var, width=100, height=28,
            font=("Helvetica Neue", 12))
        self.subtitle_format_segment.pack(side="right")
        self.subtitle_language_menu = ctk.CTkOptionMenu(
            self.subtitle_controls, values=self._subtitle_policy_labels(),
            width=170, height=28, font=("Helvetica Neue", 12),
            command=self.set_subtitle_policy)
        self.subtitle_language_menu.set(self.t('sub_original_english'))
        self.subtitle_language_menu.pack(side="right", padx=(0, 8))

        # Save Location
        folder_frame = ctk.CTkFrame(
            self.main_frame,
            fg_color=("#FFFFFF", "#2C2C2E"), corner_radius=10,
            border_width=1, border_color=("#D1D1D6", "#3A3A3C"))
        self.folder_frame = folder_frame
        folder_frame.pack(fill="x", pady=(8, 0))

        self.folder_key_label = ctk.CTkLabel(
            folder_frame, text=self.t("label_folder"),
            font=("Helvetica Neue", 12), text_color=("#6E6E73", "#8E8E93"))
        self.folder_key_label.pack(side="left", padx=(14, 8), pady=9)

        self.folder_btn = ctk.CTkButton(
            folder_frame, text=self.t("btn_browse"), width=52, height=28,
            fg_color="transparent", border_width=1,
            border_color=("#D1D1D6", "#3A3A3C"),
            text_color=("#1D1D1F", "#FFFFFF"),
            hover_color=("#E5E5EA", "#3A3A3C"),
            font=("Helvetica Neue", 12), corner_radius=6,
            command=self.browse_download_folder)
        self.folder_btn.pack(side="right", padx=(4, 14), pady=9)

        self.folder_val_label = ctk.CTkLabel(
            folder_frame, text=self._short_path(self.download_folder),
            font=("Helvetica Neue", 12),
            text_color=("#1D1D1F", "#FFFFFF"), anchor="w")
        self.folder_val_label.pack(side="left", fill="x", expand=True)

        # Options (Cookie)
        opts_frame = ctk.CTkFrame(
            self.main_frame,
            fg_color=("#FFFFFF", "#2C2C2E"), corner_radius=10,
            border_width=1, border_color=("#D1D1D6", "#3A3A3C"))
        opts_frame.pack(fill="x", pady=(8, 0))

        cookie_row = ctk.CTkFrame(opts_frame, fg_color="transparent")
        cookie_row.pack(fill="x", padx=14, pady=10)

        self.cookie_checkbox = ctk.CTkCheckBox(
            cookie_row, text=self.t("opt_cookie"), variable=self.use_cookie_var,
            font=("Helvetica Neue", 13), text_color=("#1D1D1F", "#FFFFFF"),
            checkmark_color="#FFFFFF", fg_color="#0071E3",
            hover_color="#0077ED", border_color=("#D1D1D6", "#636366"))
        self.cookie_checkbox.pack(side="left")

        self.cookie_file_btn = ctk.CTkButton(
            cookie_row, text=self.t("btn_browse"), width=52, height=28,
            fg_color="transparent", border_width=1,
            border_color=("#D1D1D6", "#3A3A3C"),
            text_color=("#1D1D1F", "#FFFFFF"),
            hover_color=("#E5E5EA", "#3A3A3C"),
            font=("Helvetica Neue", 11), corner_radius=6,
            command=self.browse_cookie_file)
        self.cookie_file_btn.pack(side="right")

        self.cookie_file_entry = ctk.CTkEntry(
            cookie_row, textvariable=self.cookie_file_path,
            placeholder_text="cookies.txt（可选）",
            height=28, corner_radius=6,
            border_color=("#D1D1D6", "#3A3A3C"),
            fg_color=("#F5F5F7", "#1C1C1E"),
            font=("Helvetica Neue", 11))
        self.cookie_file_entry.pack(side="left", fill="x", expand=True, padx=(10, 6))

        # Proxy row
        proxy_row = ctk.CTkFrame(opts_frame, fg_color="transparent")
        proxy_row.pack(fill="x", padx=14, pady=(0, 10))

        self.proxy_key_label = ctk.CTkLabel(
            proxy_row, text=self.t("label_proxy"),
            font=("Helvetica Neue", 12), text_color=("#6E6E73", "#8E8E93"))
        self.proxy_key_label.pack(side="left", padx=(0, 8))

        self.proxy_entry = ctk.CTkEntry(
            proxy_row, textvariable=self.proxy_var,
            placeholder_text=self.t("placeholder_proxy"),
            height=28, corner_radius=6,
            border_color=("#D1D1D6", "#3A3A3C"),
            fg_color=("#F5F5F7", "#1C1C1E"),
            font=("Helvetica Neue", 11))
        self.proxy_entry.pack(side="left", fill="x", expand=True)
        self.proxy_entry.bind("<FocusOut>", lambda e: self._save_settings())

        # Pack video-only rows after the anchor exists so mode switches keep
        # them immediately above the common save/options rows.
        self.select_egg(self.option_var.get())

        # Progress bar (thin, smooth)
        self.progress_bar = ctk.CTkProgressBar(
            self.main_frame, height=5, corner_radius=3,
            progress_color="#0071E3", fg_color=("#E5E5EA", "#3A3A3C"))
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(12, 4))

        # Status label (click for error detail)
        self.status_frame = ctk.CTkFrame(
            self.main_frame, fg_color="transparent", height=STATUS_AREA_HEIGHT)
        self.status_frame.pack(fill="x", pady=(0, 6))
        self.status_frame.pack_propagate(False)
        self.status_label = ctk.CTkLabel(
            self.status_frame, text=self.t("status_wait"), height=STATUS_AREA_HEIGHT,
            text_color=("#6E6E73", "#8E8E93"),
            font=("Helvetica Neue", 12),
            wraplength=660, justify="center")
        self.status_label.pack(fill="both", expand=True)
        self.status_label.bind("<Button-1>", self._on_status_click)

        # Action buttons
        self.btn_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.btn_frame.pack(fill="x")

        self.download_btn = ctk.CTkButton(
            self.btn_frame, text=self.t("btn_start"),
            height=40, corner_radius=10,
            fg_color="#0071E3", hover_color="#0077ED",
            font=("Helvetica Neue", 15, "bold"),
            command=self.start_download_thread)
        self.download_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.cancel_btn = ctk.CTkButton(
            self.btn_frame, text=self.t("btn_cancel"),
            width=90, height=40, corner_radius=10,
            fg_color=("#FF3B30", "#FF453A"), hover_color=("#D70015", "#E03030"),
            font=("Helvetica Neue", 14), state="disabled",
            command=self.cancel_download)
        self.cancel_btn.pack(side="left", padx=(0, 6))

        self.open_dir_btn = ctk.CTkButton(
            self.btn_frame, text=self.t("btn_open"),
            width=120, height=40, corner_radius=10,
            fg_color=("#34C759", "#30D158"), hover_color=("#28A745", "#28C244"),
            font=("Helvetica Neue", 14),
            command=self.open_download_folder)
        self.open_dir_btn.pack(side="left")

    # ── Language toggle ─────────────────────────────────────────────────────

    def toggle_language(self):
        self.lang = "en" if self.lang == "zh" else "zh"
        self.title_label.configure(text=self.t("title"))
        self.subtitle_text_label.configure(text=self.t("subtitle"))
        self.url_entry.configure(placeholder_text=self.t("placeholder"))
        self.lang_btn.configure(text=self.t("lang_switch"))
        self.download_btn.configure(text=self.t("btn_start"))
        self.cancel_btn.configure(text=self.t("btn_cancel"))
        self.open_dir_btn.configure(text=self.t("btn_open"))
        self.cookie_checkbox.configure(text=self.t("opt_cookie"))
        self.cookie_file_btn.configure(text=self.t("btn_browse"))
        self.proxy_key_label.configure(text=self.t("label_proxy"))
        self.proxy_entry.configure(placeholder_text=self.t("placeholder_proxy"))
        self.folder_key_label.configure(text=self.t("label_folder"))
        self.folder_btn.configure(text=self.t("btn_browse"))
        self.video_format_label.configure(text=self.t('label_video_format'))
        self.subtitle_switch.configure(text=self.t('include_subtitles'))
        self.subtitle_language_menu.configure(values=self._subtitle_policy_labels())
        self.subtitle_language_menu.set(self.t({
            'original_english': 'sub_original_english',
            'original': 'sub_original',
            'english': 'sub_english',
            'automatic': 'sub_automatic',
        }[self.subtitle_policy]))
        for val, btn in self.eggs.items():
            emoji = btn.cget("text").split(" ")[0]
            btn.configure(text=f"{emoji} {self.t(btn.text_key)}")
        if any(w in self.status_label.cget("text") for w in ["等待", "Waiting"]):
            self.status_label.configure(text=self.t("status_wait"))

    # ── Theme and mode controls ─────────────────────────────────────────────

    def _set_appearance_mode(self, mode_string):
        super()._set_appearance_mode(mode_string)
        if hasattr(self, 'theme_btn'):
            self._update_theme_button()

    def _update_theme_button(self):
        self.theme_btn.configure(text="☾" if self._get_appearance_mode() == 'light' else "☀")

    def toggle_theme(self):
        next_mode = 'dark' if self._get_appearance_mode() == 'light' else 'light'
        ctk.set_appearance_mode(next_mode)
        self._update_theme_button()

    # ── Egg buttons ─────────────────────────────────────────────────────────

    def _make_egg(self, value, text_key):
        btn = ctk.CTkButton(
            self.egg_container, text=f"🥚 {self.t(text_key)}",
            width=100,
            fg_color="transparent", text_color=("#6E6E73", "#8E8E93"),
            hover_color=("#F5F5F7", "#3A3A3C"),
            font=("Helvetica Neue", 13), corner_radius=8,
            command=lambda v=value: self.select_egg(v))
        btn.text_key = text_key
        btn.pack(side="left", padx=6, pady=6, fill="x", expand=True)
        self.eggs[value] = btn

    def select_egg(self, selected_value):
        if (self.option_var.get() == selected_value
                and "🐣" in self.eggs[selected_value].cget("text")):
            return
        self.option_var.set(selected_value)
        for val, btn in self.eggs.items():
            if val == selected_value:
                btn.configure(text=f"💥 {self.t(btn.text_key)}")
                self.update()
                time.sleep(0.08)
                btn.configure(text=f"🐣 {self.t(btn.text_key)}",
                              text_color="#0071E3",
                              font=("Helvetica Neue", 13, "bold"))
            else:
                btn.configure(text=f"🥚 {self.t(btn.text_key)}",
                              text_color=("#6E6E73", "#8E8E93"),
                              font=("Helvetica Neue", 13, "normal"))
        if hasattr(self, 'video_output_frame'):
            self._show_video_options(selected_value)

    def _show_video_options(self, selected_value):
        for frame in (self.video_output_frame, self.subtitle_frame):
            frame.pack_forget()
        if selected_value == 'video':
            self.video_output_frame.pack(fill='x', pady=(8, 0), before=self.folder_frame)
            self.subtitle_frame.pack(fill='x', pady=(8, 0), before=self.folder_frame)
            self.update_subtitle_controls()
        else:
            self.subtitle_controls.pack_forget()
        self._resize_window_for_mode(selected_value)

    def update_subtitle_controls(self):
        if self.subtitle_controls.winfo_manager() != 'pack':
            self.subtitle_controls.pack(side='right', padx=(8, 14), pady=9)
        state = 'normal' if self.include_subtitles_var.get() else 'disabled'
        self.subtitle_language_menu.configure(state=state)
        self.subtitle_format_segment.configure(state=state)

    def _resize_window_for_mode(self, selected_value=None):
        """Fit the window to visible rows while preserving equal bottom padding."""
        self.update_idletasks()
        main_frame = self.__dict__.get('main_frame')
        if main_frame is None:
            height = (VIDEO_WINDOW_HEIGHT if selected_value == 'video'
                      else BASE_WINDOW_HEIGHT)
        else:
            height = main_frame.winfo_reqheight() + MAIN_FRAME_VERTICAL_PADDING
        self.center_window(WINDOW_WIDTH, height)

    def _bind_url_entry_drag_selection(self):
        entry = getattr(self.url_entry, '_entry', None)
        if entry is None:
            return
        self._url_dragging = False
        self._url_drag_anchor = 0
        self._url_drag_after_id = None
        entry.bind('<ButtonPress-1>', self._url_drag_start, add='+')
        entry.bind('<B1-Motion>', self._url_drag_motion, add='+')
        entry.bind('<B1-Leave>', self._url_drag_leave, add='+')
        entry.bind('<ButtonRelease-1>', self._url_drag_stop, add='+')

    def _url_drag_start(self, event):
        self._cancel_url_drag_timer()
        self._url_dragging = True
        self._url_drag_anchor = event.widget.index(f'@{event.x}')

    def _url_drag_motion(self, event):
        if not getattr(self, '_url_dragging', False):
            return
        units = entry_drag_scroll_units(event.x, event.widget.winfo_width())
        if units:
            self._schedule_url_drag_scroll()
        else:
            self._cancel_url_drag_timer()

    def _url_drag_leave(self, event):
        self._url_drag_motion(event)
        # Replace Tk's platform-dependent EntryAutoScan with the loop below.
        return 'break'

    def _schedule_url_drag_scroll(self):
        if getattr(self, '_url_drag_after_id', None) is None:
            self._url_drag_after_id = self.after(35, self._url_drag_autoscroll)

    def _url_drag_autoscroll(self):
        self._url_drag_after_id = None
        if not getattr(self, '_url_dragging', False):
            return
        entry = getattr(self.url_entry, '_entry', None)
        if entry is None or not entry.winfo_exists():
            return
        pointer_x = entry.winfo_pointerx() - entry.winfo_rootx()
        width = entry.winfo_width()
        units = entry_drag_scroll_units(pointer_x, width)
        if not units:
            return

        entry.xview_scroll(units, 'units')
        edge_x = 0 if units < 0 else max(0, width - 1)
        target = entry.index(f'@{edge_x}')
        anchor = self._url_drag_anchor
        entry.selection_range(min(anchor, target), max(anchor, target))
        entry.icursor(target)
        self._schedule_url_drag_scroll()

    def _cancel_url_drag_timer(self):
        after_id = getattr(self, '_url_drag_after_id', None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
            self._url_drag_after_id = None

    def _url_drag_stop(self, _event=None):
        self._url_dragging = False
        self._cancel_url_drag_timer()

    def _subtitle_policy_labels(self):
        return [self.t(key) for key in (
            'sub_original_english', 'sub_original', 'sub_english', 'sub_automatic')]

    def set_subtitle_policy(self, value):
        values = self._subtitle_policy_labels()
        policies = ('original_english', 'original', 'english', 'automatic')
        if value in values:
            self.subtitle_policy = policies[values.index(value)]

    def set_video_format(self, value):
        video_format = (value or '').lower()
        if video_format not in ('mkv', 'mp4', 'prores'):
            video_format = ORIGINAL_CONTAINER_DEFAULT
            self.video_format_var.set(self._video_format_label(video_format))
        self.video_format = video_format
        if video_format in ('mkv', 'mp4'):
            self.original_container = video_format
        self._save_settings()

    def set_original_container(self, value):
        """Compatibility wrapper for the pre-video-output setting API."""
        container = (value or '').lower()
        if container not in ('mkv', 'mp4'):
            container = ORIGINAL_CONTAINER_DEFAULT
            video_format_var = self.__dict__.get('video_format_var')
            if video_format_var is not None:
                video_format_var.set(self._video_format_label(container))
        self.set_video_format(container)

    # ── Smooth progress animation (main thread) ──────────────────────────────

    def _start_progress_animation(self):
        self._downloading = True
        self._progress_target = 0.0
        self._progress_displayed = 0.0
        self._progress_stage = 'parse'
        self.progress_bar.set(0)
        self._tick_progress()

    def _tick_progress(self):
        """60 fps exponential-ease animation; only runs while downloading."""
        if not self._downloading:
            return
        diff = self._progress_target - self._progress_displayed
        if abs(diff) > 0.0003:
            self._progress_displayed += diff * 0.14   # smooth factor
            self.progress_bar.set(max(0.0, min(1.0, self._progress_displayed)))
        self.after(16, self._tick_progress)

    def _advance_progress(self, stage, fraction):
        with self._progress_lock:
            self._progress_stage = stage
            self._progress_target = stage_progress(self._progress_target, stage, fraction)
            return self._progress_target

    def _run_on_ui(self, callback):
        if threading.current_thread() is threading.main_thread():
            callback()
        else:
            self._ui_queue.put(callback)

    def _poll_ui_queue(self):
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        self.after(20, self._poll_ui_queue)

    def _set_status(self, text, text_color):
        def update():
            self.status_label.configure(text=text, text_color=text_color)
        self._run_on_ui(update)

    def _log_diagnostic(self, message, *args):
        if not self._logger:
            return
        sanitized = tuple(sanitize_diagnostic(value) for value in args)
        self._logger.info(message, *sanitized)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _get_proxy(self):
        """Return the configured proxy URL, or None."""
        # Once the settings-bound entry exists, an empty value deliberately
        # means direct mode; do not resurrect a stale value from disk.
        if 'proxy_var' in self.__dict__:
            p = self.proxy_var.get().strip()
        else:
            p = self.__dict__.get('proxy', '').strip()
        return p if p else None

    def _format_diagnostic(self, info, prefix):
        self._log_diagnostic(
            '%s extractor=%s candidate=%s selected=%s', prefix,
            info.get('extractor_key') or info.get('extractor') or 'unknown',
            highest_video_summary(info), selected_format_summary(info),
        )

    @staticmethod
    def _is_http_403(error):
        text = str(error).lower()
        return any(marker in text for marker in (
            'http error 403', 'http 403', '403: forbidden', '403 forbidden',
            'server returned 403', 'status code 403'))

    def _build_opener(self, proxy=_PROXY_UNSET):
        """Build an opener from a plain-string proxy snapshot."""
        if proxy is _PROXY_UNSET:
            # Preserve the synchronous helper API while worker paths pass an
            # explicit value (including None for direct mode).
            proxy = self._get_proxy()
        if proxy:
            handler = urllib.request.ProxyHandler({
                'http': proxy, 'https': proxy, 'ftp': proxy,
            })
            return urllib.request.build_opener(handler)
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _ensure_download_state(self):
        """Initialize runtime state for tests that construct the app without __init__."""
        state = self.__dict__
        if '_cancel_event' not in state:
            self._cancel_event = threading.Event()
        if '_resource_lock' not in state:
            self._resource_lock = threading.Lock()
        for name in ('_active_ydls', '_active_processes', '_active_responses',
                     '_download_artifacts', '_protected_artifacts'):
            if name not in state:
                setattr(self, name, set())

    def _cancel_requested(self):
        self._ensure_download_state()
        return self._cancel_event.is_set() or self.__dict__.get('is_cancelled', False)

    def _raise_if_cancelled(self):
        if self._cancel_requested():
            raise RuntimeError('CANCELLED_BY_USER')

    @contextmanager
    def _active_youtube_dl(self, options):
        self._raise_if_cancelled()
        ydl = yt_dlp.YoutubeDL(options)
        with self._resource_lock:
            self._active_ydls.add(ydl)
        try:
            self._raise_if_cancelled()
            yield ydl
        finally:
            with self._resource_lock:
                self._active_ydls.discard(ydl)
            try:
                ydl.close()
            except Exception:
                pass

    def _open_download_response(self, opener, request, timeout=15):
        self._raise_if_cancelled()
        response = opener.open(request, timeout=timeout)
        with self._resource_lock:
            self._active_responses.add(response)
        if self._cancel_requested():
            self._release_download_response(response)
            raise RuntimeError('CANCELLED_BY_USER')
        return response

    def _release_download_response(self, response):
        self._ensure_download_state()
        with self._resource_lock:
            self._active_responses.discard(response)
        try:
            response.close()
        except Exception:
            pass

    def _run_cancellable_process(self, args, *, check=False, capture_output=False):
        self._raise_if_cancelled()
        pipe = subprocess.PIPE if capture_output else None
        process = subprocess.Popen(args, stdout=pipe, stderr=pipe)
        with self._resource_lock:
            self._active_processes.add(process)
            cancelled_during_start = self._cancel_requested()
        if cancelled_during_start:
            try:
                process.terminate()
            except Exception:
                pass
        try:
            stdout, stderr = process.communicate()
        finally:
            with self._resource_lock:
                self._active_processes.discard(process)
        self._raise_if_cancelled()
        result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result

    def _interrupt_active_download(self):
        self._ensure_download_state()
        with self._resource_lock:
            processes = tuple(self._active_processes)
            responses = tuple(self._active_responses)
            ydls = tuple(self._active_ydls)

        for process in processes:
            try:
                process.terminate()
            except Exception:
                pass
        for response in responses:
            try:
                response.close()
            except Exception:
                pass
        for ydl in ydls:
            try:
                ydl.close()
            except Exception:
                pass
        for process in processes:
            try:
                process.wait(timeout=0.75)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except Exception:
                    pass
            except Exception:
                pass

    def _track_artifact(self, *paths):
        self._ensure_download_state()
        valid_paths = [path for path in paths if isinstance(path, str) and path and path != '-']
        if not valid_paths:
            return
        self.cleanup_target = valid_paths[-1]
        with self._resource_lock:
            for path in valid_paths:
                normalized = os.path.abspath(path)
                self._download_artifacts.add(normalized)
                if not normalized.endswith('.part'):
                    self._download_artifacts.add(f'{normalized}.part')
                self._download_artifacts.add(f'{normalized}.ytdl')

    def _track_hook_artifacts(self, data):
        containers = [data]
        info = data.get('info_dict')
        if isinstance(info, dict):
            containers.append(info)
        for container in containers:
            self._track_artifact(*(container.get(key) for key in (
                'filename', 'tmpfilename', 'filepath', '_filename')))

    def _begin_download_transaction(self, output_path):
        """Protect files that existed before this download from cleanup."""
        self._ensure_download_state()
        protected = set()
        try:
            for entry in os.scandir(output_path):
                if entry.is_file(follow_symlinks=False) or entry.is_symlink():
                    protected.add(os.path.abspath(entry.path))
        except OSError:
            pass
        with self._resource_lock:
            self._download_artifacts.clear()
            self._protected_artifacts = protected

    def _cleanup_download_artifacts(self):
        self._ensure_download_state()
        with self._resource_lock:
            paths = tuple(self._download_artifacts)
            protected = set(self._protected_artifacts)
            self._download_artifacts.clear()
        for path in paths:
            if path in protected:
                continue
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.remove(path)
            except OSError:
                pass

    def _remove_artifact_if_unprotected(self, path):
        self._ensure_download_state()
        normalized = os.path.abspath(path)
        with self._resource_lock:
            is_protected = normalized in self._protected_artifacts
        if not is_protected and (os.path.isfile(normalized) or os.path.islink(normalized)):
            os.remove(normalized)

    def _retry_sleep(self, n=0, **_kwargs):
        """Use a short cancellable exponential backoff between retries.

        Immediate retries tend to hit the same overloaded CDN edge again.  A
        bounded delay gives the extractor or CDN time to rotate while keeping
        cancellation responsive.
        """
        self._raise_if_cancelled()
        try:
            attempt = max(0, int(n))
        except (TypeError, ValueError):
            attempt = 0
        delay = min(8.0, 0.5 * (2 ** attempt))
        # Waiting on the shared event lets cancellation interrupt the delay;
        # return zero because yt-dlp otherwise sleeps for the returned value
        # a second time.
        self._cancel_event.wait(delay)
        self._raise_if_cancelled()
        return 0

    @staticmethod
    def _is_transient_network_error(error):
        text = str(error).lower()
        if re.search(r'http error (?:408|409|425|429|5\d\d)\b', text):
            return True
        return any(marker in text for marker in (
            'connection refused', 'connection reset', 'connection aborted',
            'network is unreachable', 'no route to host', 'remote end closed',
            'remote disconnected', 'timed out', 'timeout', 'temporary failure',
            'name or service not known', 'nodename nor servname provided',
            'server disconnected', 'incomplete read', 'unexpected eof',
        ))

    def _probe_media(self, path):
        result = self._run_cancellable_process([
            get_ffprobe_path(), '-v', 'error',
            '-show_entries', 'format=format_name:stream=codec_type,codec_name',
            '-of', 'json', path,
        ], check=True, capture_output=True)
        output = result.stdout or b'{}'
        if isinstance(output, bytes):
            output = output.decode('utf-8', errors='replace')
        return json.loads(output)

    def _validate_video_output(self, path, expected_container):
        if not path or not os.path.isfile(path):
            raise RuntimeError(f'Final video output is missing: {path or "unknown"}')

        expected_container = expected_container.lower().lstrip('.')
        expected_extension = '.mov' if expected_container == 'mov' else f'.{expected_container}'
        if os.path.splitext(path)[1].lower() != expected_extension:
            raise RuntimeError(
                f'Final video extension mismatch: expected {expected_extension}, got {path}')

        probe = self._probe_media(path)
        format_names = set((probe.get('format') or {}).get('format_name', '').split(','))
        streams = probe.get('streams') or []
        stream_types = {stream.get('codec_type') for stream in streams}
        accepted_formats = {
            'mkv': {'matroska', 'webm'},
            'mp4': {'mov', 'mp4'},
            'mov': {'mov', 'mp4'},
        }[expected_container]
        if not format_names.intersection(accepted_formats):
            raise RuntimeError(
                f'Final video container mismatch: expected {expected_container}, '
                f'got {",".join(sorted(format_names)) or "unknown"}')
        if 'video' not in stream_types or 'audio' not in stream_types:
            raise RuntimeError(
                'Final video is incomplete: both video and audio streams are required')
        if expected_container == 'mov':
            video_codecs = {
                stream.get('codec_name') for stream in streams
                if stream.get('codec_type') == 'video'
            }
            if not any((codec or '').startswith('prores') for codec in video_codecs):
                raise RuntimeError('Final MOV does not contain a ProRes video stream')
        self._log_diagnostic(
            'validated output=%s container=%s streams=%s', path,
            expected_container, ','.join(sorted(stream_types)))

    def _ensure_mkv_output(self, base_filename):
        destination = f'{base_filename}.mkv'
        source = next((
            f'{base_filename}{ext}'
            for ext in ('.mp4', '.webm', '.flv', '.ts', '.m4v')
            if os.path.isfile(f'{base_filename}{ext}')
        ), None)
        if source is None and os.path.isfile(destination):
            return destination
        if source is None:
            raise RuntimeError('Downloaded media could not be located for MKV packaging')
        destination = self._next_available_path(destination)
        temporary = self._conversion_temp_path(destination)
        self._track_artifact(temporary)
        self._run_cancellable_process([
            get_ffmpeg_path(), '-y', '-i', source, '-c', 'copy', temporary,
        ], check=True, capture_output=True)
        self._track_artifact(destination)
        os.replace(temporary, destination)
        self._remove_artifact_if_unprotected(source)
        return destination

    @staticmethod
    def _conversion_temp_path(destination):
        """Keep the media extension on ffmpeg's temporary output path."""
        root, extension = os.path.splitext(destination)
        candidate = f'{root}.danload-tmp{extension}'
        return DownloaderApp._next_available_path(candidate)

    def _short_path(self, path):
        home = os.path.expanduser('~')
        return ('~' + path[len(home):]) if path.startswith(home) else path

    @staticmethod
    def _next_available_path(path):
        """Return a collision-free sibling path without touching ``path``.

        Partial-download sidecars count as collisions too; reusing one after
        an interrupted process could otherwise overwrite recoverable data.
        """
        def occupied(candidate):
            return any(os.path.exists(sibling) for sibling in (
                candidate, f'{candidate}.part', f'{candidate}.ytdl'))

        if not occupied(path):
            return path
        root, extension = os.path.splitext(path)
        index = 1
        while True:
            candidate = f'{root} ({index}){extension}'
            if not occupied(candidate):
                return candidate
            index += 1

    def center_window(self, width, height):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{width}x{height}+{(sw - width) // 2}+{(sh - height) // 2}")

    def _on_status_click(self, event):
        if self._last_error:
            self._show_error_detail(self._last_error)

    def _show_error_detail(self, full_error):
        d = ctk.CTkToplevel(self)
        d.title("错误详情" if self.lang == "zh" else "Error Detail")
        d.geometry("660x320")
        d.resizable(False, False)
        d.grab_set()
        ctk.CTkLabel(d, text="完整错误信息（可复制）" if self.lang == "zh" else "Full error (copyable)",
                     font=("Helvetica Neue", 13, "bold")).pack(pady=(12, 4))
        tb = ctk.CTkTextbox(d, width=630, height=210, font=("Courier", 12))
        tb.pack(padx=15)
        tb.insert("0.0", full_error)
        tb.configure(state="disabled")
        ctk.CTkButton(d, text="关闭" if self.lang == "zh" else "Close",
                      width=100, command=d.destroy).pack(pady=10)

    def _detect_original_audio_lang(self, info):
        """Detect the original audio language from yt-dlp format metadata.

        Examines audio-only format entries for ``language_preference`` —
        yt-dlp sets this to 10 for the original track and -1 for dubs.
        Returns a 2-char language code; falls back to ``'en'``.
        """
        formats = info.get('formats') or []
        audio_with_lang = [
            f for f in formats
            if f.get('acodec', 'none') != 'none'
            and f.get('vcodec', 'none') == 'none'
            and f.get('language')
        ]
        if audio_with_lang:
            original = max(audio_with_lang,
                           key=lambda f: f.get('language_preference', 0))
            lang = original['language'].lower()
            return lang[:2] if lang not in ('und', '') else 'en'
        # Fallback: top-level metadata (unreliable — often channel language)
        meta_lang = (info.get('language') or '').lower()
        if meta_lang and meta_lang not in ('und',):
            return meta_lang[:2]
        return 'en'

    def _remux_to_mp4(self, base_filename):
        """Remux the downloaded file to MP4 using ``-c copy``.

        Always merges to MKV during download, so this step converts the
        resulting MKV (or other container) to MP4. If the codec is
        incompatible with the MP4 container (e.g. FLAC audio), the
        remux fails gracefully and the original file is kept.

        Returns ``'mp4'`` on success, or the original extension (e.g.
        ``'mkv'``) if the remux was skipped or failed.
        """
        for ext in ['.mkv', '.webm', '.flv', '.ts', '.m4v', '.mp4']:
            src = f"{base_filename}{ext}"
            if not os.path.exists(src):
                continue
            if ext == '.mp4':
                self._last_remux_path = src
                return 'mp4'
            dst = f"{base_filename}.mp4"
            if os.path.exists(dst):
                # Never replace an existing output.  In normal downloads the
                # transaction marks old files as protected; using a sibling
                # name here also keeps direct helper calls non-destructive.
                dst = self._next_available_path(dst)
            temporary = None
            try:
                temporary = self._conversion_temp_path(dst)
                self._track_artifact(temporary)
                self._run_cancellable_process([
                    get_ffmpeg_path(), '-y', '-i', src,
                    '-c', 'copy', '-movflags', '+faststart', temporary
                ], check=True, capture_output=True)
                self._track_artifact(dst)
                os.replace(temporary, dst)
                self._remove_artifact_if_unprotected(src)
                self._last_remux_path = dst
                return 'mp4'
            except subprocess.CalledProcessError:
                if temporary and os.path.exists(temporary):
                    self._remove_artifact_if_unprotected(temporary)
                self._last_remux_path = src
                return ext.lstrip('.')
        self._last_remux_path = None
        return 'mkv'

    # ── File / folder pickers ────────────────────────────────────────────────

    def browse_cookie_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择 cookies.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            self.cookie_file_path.set(path)

    def browse_download_folder(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(
            title="选择下载文件夹" if self.lang == "zh" else "Choose Download Folder",
            initialdir=self.download_folder)
        if path:
            self.download_folder = path
            self.folder_val_label.configure(text=self._short_path(path))
            self._save_settings()

    def open_download_folder(self):
        os.makedirs(self.download_folder, exist_ok=True)
        try:
            if sys.platform == 'darwin':
                subprocess.run(["open", self.download_folder])
            elif os.name == 'nt':
                os.startfile(self.download_folder)
            else:
                subprocess.run(["xdg-open", self.download_folder])
        except Exception:
            pass

    # ── Cancel ──────────────────────────────────────────────────────────────

    def cancel_download(self):
        if self.download_btn.cget("state") == "disabled":
            self._ensure_download_state()
            self.is_cancelled = True
            self._cancel_event.set()
            msg = "⚠️ Cancelling..." if self.lang == "en" else "⚠️ 正在取消..."
            self.status_label.configure(text=msg, text_color=("#FF9500", "#FF9F0A"))
            self.cancel_btn.configure(state="disabled")
            threading.Thread(target=self._interrupt_active_download, daemon=True).start()

    # ── Progress hook (download thread) ─────────────────────────────────────

    def progress_hook(self, d):
        self._track_hook_artifacts(d)
        self._raise_if_cancelled()

        if d['status'] == 'downloading':
            try:
                pct = progress_fraction(d)
                stage = self._progress_stage
                overall = self._advance_progress(stage, pct)
                speed = d.get('_speed_str', '—')
                if stage == 'subtitle':
                    msg = (f"Subtitles {overall*100:.1f}%  ·  {speed}" if self.lang == "en"
                           else f"字幕下载 {overall*100:.1f}%  ·  {speed}")
                else:
                    msg = (f"Downloading {overall*100:.1f}%  ·  {speed}" if self.lang == "en"
                           else f"下载中 {overall*100:.1f}%  ·  {speed}")
                self._set_status(msg, ("#0071E3", "#0A84FF"))
            except Exception:
                pass

        elif d['status'] == 'finished':
            self._advance_progress(self._progress_stage, 1.0)
            msg = "Processing..." if self.lang == "en" else "处理中..."
            self._set_status(msg, ("#FF9500", "#FF9F0A"))

    def postprocessor_hook(self, data):
        self._track_hook_artifacts(data)
        self._raise_if_cancelled()

    # ── URL normalisation ───────────────────────────────────────────────────

    def is_telegram_url(self, url):
        host = urlparse(url).netloc.lower().removeprefix('www.')
        return host in ('t.me', 'telegram.me', 'web.telegram.org',
                        'webk.telegram.org', 'webz.telegram.org')

    def _telegram_public_post_url(self, url):
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix('www.')
        if host == 'telegram.me':
            host = 't.me'
        if host != 't.me':
            return None

        parts = [unquote(p) for p in parsed.path.split('/') if p]
        if len(parts) >= 3 and parts[0] == 's' and parts[2].isdigit():
            channel, msg_id = parts[1], parts[2]
        elif len(parts) >= 2 and parts[1].isdigit() and parts[0] not in ('c', 'joinchat'):
            channel, msg_id = parts[0], parts[1]
        else:
            return None

        if channel.startswith('+'):
            return None
        suffix = '?single' if 'single' in parsed.query else ''
        return f"https://t.me/{channel}/{msg_id}{suffix}"

    def normalize_url(self, url):
        from urllib.parse import parse_qs
        telegram_url = self._telegram_public_post_url(url)
        if telegram_url:
            return telegram_url
        # iesdouyin.com share links → douyin.com/video/{id}
        m = re.search(r'iesdouyin\.com/share/video/(\d+)', url)
        if m:
            return f"https://www.douyin.com/video/{m.group(1)}"
        m = re.match(r'(https?://(?:www\.)?douyin\.com)/jingxuan\?.*modal_id=(\d+)', url)
        if m:
            return f"{m.group(1)}/video/{m.group(2)}"
        if 'i.y.qq.com/v8/playsong.html' in url:
            params = parse_qs(urlparse(url).query)
            songmid = params.get('songmid', [None])[0]
            if songmid:
                return f"https://y.qq.com/n/ryqq/songDetail/{songmid}"
        url = re.sub(r'(y\.qq\.com/n/)ryqq_v2/', r'\1ryqq/', url)
        url = re.sub(r'\?.*$', '', url) if 'y.qq.com' in url else url
        return url

    def resolve_douyin_short_url(self, url, proxy=None):
        """Follow v.douyin.com redirect → full douyin.com/video/{id} URL."""
        if 'v.douyin.com' not in url:
            return url
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) '
                                       'AppleWebKit/605.1.15'})
            opener = self._build_opener(proxy)
            resp = self._open_download_response(opener, req, timeout=10)
            try:
                final = resp.url
            finally:
                self._release_download_response(resp)
            parsed = urlparse(final)
            if 'douyin.com/video/' in final:
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            return final
        except Exception:
            return url

    # ── Start download ───────────────────────────────────────────────────────

    def _build_request_config(self, include_subtitles):
        config = {
            'cookie_file': self.cookie_file_path.get().strip(),
            'use_browser_cookie': self.use_cookie_var.get(),
            'proxy': self._get_proxy(),
            'include_subtitles': bool(include_subtitles),
        }
        if include_subtitles:
            config.update({
                'subtitle_policy': self.subtitle_policy,
                'subtitle_format': self.subtitle_format_var.get().lower(),
            })
        return config

    def start_download_thread(self):
        raw = self.url_entry.get().strip()
        if not raw:
            self.status_label.configure(text=self.t("err_empty"),
                                        text_color=("#FF3B30", "#FF453A"))
            return
        match = re.search(r'https?://[^\s]+', raw)
        if not match:
            self.status_label.configure(text=self.t("err_invalid"),
                                        text_color=("#FF3B30", "#FF453A"))
            return

        url = self.normalize_url(match.group(0))
        if self.is_telegram_url(url) and not self._telegram_public_post_url(url):
            self.status_label.configure(text=self.t("err_telegram_unsupported"),
                                        text_color=("#FF3B30", "#FF453A"))
            return
        self.url_entry.delete(0, 'end')
        self.url_entry.insert(0, url)

        self._ensure_download_state()
        self.is_cancelled = False
        self._cancel_event.clear()
        self._begin_download_transaction(self.download_folder)
        self.cleanup_target = None
        download_type, original_container, include_subtitles = resolve_download_selection(
            self.option_var.get(), self.video_format_var.get(),
            self.include_subtitles_var.get())
        request_config = self._build_request_config(include_subtitles)
        self._last_url = url
        self._last_error = ""

        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self._start_progress_animation()

        msg = "🔍 Parsing URL..." if self.lang == "en" else "🔍 正在解析链接..."
        self.status_label.configure(text=msg, text_color=("#0071E3", "#0A84FF"))

        target = self.download_general_file if download_type == 'general_file' else self.download_media
        args = ((url, request_config.get('proxy')) if download_type == 'general_file'
                else (url, download_type, original_container, request_config))
        threading.Thread(target=target, args=args, daemon=True).start()

    def reset_ui_state(self):
        self._downloading = False
        self._ensure_download_state()
        with self._resource_lock:
            self._download_artifacts.clear()
            self._protected_artifacts.clear()
        def reset():
            if self._progress_target >= 1.0:
                self._progress_displayed = 1.0
                self.progress_bar.set(1.0)
            else:
                self._progress_target = 0.0
                self._progress_displayed = 0.0
                self.progress_bar.set(0)
            self.download_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            self.is_cancelled = False
            self._cancel_event.clear()
        self._run_on_ui(reset)

    # ── General file download ────────────────────────────────────────────────

    def download_general_file(self, url, proxy=None):
        output_path = self.download_folder
        os.makedirs(output_path, exist_ok=True)
        try:
            self._progress_stage = 'media'
            file_name = unquote(os.path.basename(urlparse(url).path)) or "Danload_File"
            if "." not in file_name:
                file_name = "Danload_File"
            filepath = self._next_available_path(os.path.join(output_path, file_name))
            # Never stream directly into a pre-existing destination.  A
            # cancelled or truncated response must not corrupt the user's
            # previous file; the final rename is atomic on the same volume.
            tmp_filepath = f'{filepath}.part'
            self._track_artifact(tmp_filepath)
            msg = "🚀 Connecting..." if self.lang == "en" else "🚀 正在建立连接..."
            self._set_status(text=msg, text_color=("#34C759", "#30D158"))

            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            opener = self._build_opener(proxy)
            resp = self._open_download_response(opener, req)
            try:
                out = open(tmp_filepath, 'wb')
                with out:
                    file_size = int(resp.info().get('Content-Length', -1))
                    downloaded = 0
                    while True:
                        self._raise_if_cancelled()
                        buf = resp.read(DOWNLOAD_CHUNK_SIZE)
                        if not buf:
                            break
                        downloaded += len(buf)
                        out.write(buf)
                        if file_size > 0:
                            pct = downloaded / file_size
                            overall = self._advance_progress('media', pct)
                            dl_mb, tot_mb = downloaded / 1048576, file_size / 1048576
                            msg = (f"Downloading {overall*100:.1f}%  ·  {dl_mb:.1f}/{tot_mb:.1f} MB"
                                   if self.lang == "en" else
                                   f"下载中 {overall*100:.1f}%  ·  {dl_mb:.1f}/{tot_mb:.1f} MB")
                            self._set_status(text=msg, text_color=("#0071E3", "#0A84FF"))
            finally:
                self._release_download_response(resp)

            self._raise_if_cancelled()
            self._track_artifact(filepath)
            os.replace(tmp_filepath, filepath)
            msg = "✅ File downloaded!" if self.lang == "en" else "✅ 文件下载完成！"
            self._advance_progress('complete', 1.0)
            self._set_status(text=msg, text_color=("#34C759", "#30D158"))
        except Exception as e:
            self.handle_error(
                RuntimeError('CANCELLED_BY_USER') if self._cancel_requested() else e)
        finally:
            self.reset_ui_state()

    # ── Media download ───────────────────────────────────────────────────────

    def _available_browsers(self):
        if sys.platform == 'darwin':
            paths = {
                'safari': '/Applications/Safari.app',
                'chrome': '/Applications/Google Chrome.app',
                'firefox': '/Applications/Firefox.app',
            }
            order = ('safari', 'chrome', 'firefox')
        elif os.name == 'nt':
            program_files = os.environ.get('ProgramFiles', r'C:\Program Files')
            program_files_x86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
            paths = {
                'chrome': os.path.join(program_files, r'Google\Chrome\Application\chrome.exe'),
                'firefox': os.path.join(program_files, r'Mozilla Firefox\firefox.exe'),
                'edge': os.path.join(program_files_x86, r'Microsoft\Edge\Application\msedge.exe'),
            }
            order = ('chrome', 'firefox', 'edge')
        else:
            paths = {'chrome': '/usr/bin/google-chrome', 'firefox': '/usr/bin/firefox'}
            order = ('chrome', 'firefox')
        return [browser for browser in order if os.path.exists(paths[browser])]

    def _download_attempts(self, request_config):
        cookie_file = request_config.get('cookie_file') or ''
        if cookie_file:
            if not os.path.isfile(cookie_file):
                raise FileNotFoundError(f'Cookie file not found: {cookie_file}')
            credentials = [('file', cookie_file)]
        elif request_config.get('use_browser_cookie'):
            browsers = self._available_browsers()
            if not browsers:
                raise RuntimeError('No supported browser was found for Cookie extraction')
            credentials = [('browser', browser) for browser in browsers]
        else:
            credentials = [('anonymous', None)]

        attempts = []
        for credential_type, credential_value in credentials:
            attempts.append((credential_type, credential_value, False))
            attempts.append((credential_type, credential_value, True))
        return attempts

    def _unique_media_output_template(self, options, metadata):
        """Choose a collision-free yt-dlp output template for one media item."""
        current = options.get('outtmpl')
        if not isinstance(current, str) or not isinstance(metadata, dict):
            return current
        if metadata.get('_type') in ('playlist', 'multi_video'):
            return current
        try:
            with yt_dlp.YoutubeDL(options) as probe:
                prepared = probe.prepare_filename(metadata)
        except Exception:
            return current
        root, _ = os.path.splitext(prepared)
        if not root:
            return current
        media_extensions = ('.mkv', '.mp4', '.webm', '.m4a', '.mp3', '.mov',
                            '.flv', '.ts', '.part', '.ytdl')
        if not any(os.path.exists(f'{root}{extension}') for extension in media_extensions):
            return current
        index = 1
        while any(os.path.exists(f'{root} ({index}){extension}')
                  for extension in media_extensions):
            index += 1
        unique_root = f'{root} ({index})'
        self._log_diagnostic('output collision; using %s', unique_root)
        return f'{unique_root}.%(ext)s'

    @staticmethod
    def _attempt_options(base_options, credential_type, credential_value, conservative):
        options = base_options.copy()
        if 'http_headers' in options:
            options['http_headers'] = options['http_headers'].copy()
        if credential_type == 'file':
            options['cookiefile'] = credential_value
        elif credential_type == 'browser':
            options['cookiesfrombrowser'] = (credential_value,)
        if conservative:
            options['concurrent_fragment_downloads'] = 1
            options['retries'] = 3
            options['fragment_retries'] = 3
            # A failed segmented transfer is more likely to be a CDN edge
            # problem; retry it with yt-dlp's native downloader instead of
            # immediately reopening many range connections.
            options.pop('external_downloader', None)
            options.pop('external_downloader_args', None)
        return options

    def _download_subtitles_only(self, url, options, metadata, request_config,
                                 show_completion=True):
        original_language = self._detect_original_audio_lang(metadata)
        languages = choose_subtitle_languages(
            metadata, original_language, request_config.get('subtitle_policy', 'original_english'))
        if not languages:
            raise RuntimeError(self.t('err_no_subtitles'))

        subtitle_format = request_config.get('subtitle_format', 'srt')
        if subtitle_format not in ('srt', 'vtt'):
            subtitle_format = 'srt'
        subtitle_options = options.copy()
        for key in ('format', 'merge_output_format', 'audio_multistreams'):
            subtitle_options.pop(key, None)
        subtitle_options.update({
            'skip_download': True,
            'writesubtitles': request_config.get('subtitle_policy') != 'automatic',
            'writeautomaticsub': True,
            'subtitleslangs': languages,
            'subtitlesformat': f'{subtitle_format}/best',
            'overwrites': False,
            'postprocessors': [{
                'key': 'FFmpegSubtitlesConvertor',
                'format': subtitle_format,
            }],
        })
        self._progress_stage = 'subtitle'
        self._set_status(
            'Downloading subtitles...' if self.lang == 'en' else '正在下载字幕...',
            ("#0071E3", "#0A84FF"))
        with self._active_youtube_dl(subtitle_options) as ydl:
            result = ydl.extract_info(url, download=True)
        self._raise_if_cancelled()
        self._advance_progress('subtitle_finalize', 1.0)
        self._log_diagnostic(
            'subtitles extractor=%s languages=%s format=%s manual=%s automatic=%s',
            result.get('extractor_key') or result.get('extractor') or 'unknown',
            ','.join(languages), subtitle_format,
            bool(metadata.get('subtitles')), bool(metadata.get('automatic_captions')))
        if show_completion:
            self._advance_progress('complete', 1.0)
            self._set_status(
                self.t('status_done_subtitles').format(
                    languages=', '.join(languages), format=subtitle_format.upper()),
                ("#34C759", "#30D158"))
        return languages, subtitle_format

    def _download_attached_subtitles(self, url, options, metadata,
                                     request_config, video_result):
        """Run the optional subtitle pass without hiding partial success."""
        try:
            languages, subtitle_format = self._download_subtitles_only(
                url, options, metadata, request_config, show_completion=False)
        except Exception as subtitle_error:
            if 'CANCELLED_BY_USER' in str(subtitle_error):
                raise
            self._last_error = sanitize_diagnostic(subtitle_error)
            self._log_diagnostic('subtitle attachment failed: %s', subtitle_error)
            self._advance_progress('complete', 1.0)
            self._set_status(
                self.t('status_partial_subtitles'),
                ("#FF9500", "#FF9F0A"))
            return False

        self._set_status(
            self.t('status_done_video_subtitles').format(
                video=video_result,
                languages=', '.join(languages),
                format=subtitle_format.upper()),
            ("#34C759", "#30D158"))
        return True

    def download_media(self, url, download_type, original_container=None, request_config=None):
        request_config = request_config or {}
        proxy = request_config.get('proxy')
        include_subtitles = bool(request_config.get('include_subtitles')) \
            and download_type in ('video_original', 'video_prores')
        output_path = self.download_folder
        os.makedirs(output_path, exist_ok=True)
        if original_container not in ('mkv', 'mp4'):
            original_container = ORIGINAL_CONTAINER_DEFAULT

        host = urlparse(url).netloc.lower().split(':', 1)[0].removeprefix('www.')
        is_douyin   = any(d in host for d in ['douyin.com', 'iesdouyin.com', 'tiktok.com'])
        is_telegram = self.is_telegram_url(url)
        is_bilibili = host == 'b23.tv' or host.endswith('.bilibili.com') or host == 'bilibili.com'

        # Resolve Douyin short links first
        if is_douyin and 'v.douyin.com' in url:
            self._set_status(
                text="🔗 正在解析抖音短链..." if self.lang == "zh" else "🔗 Resolving short URL...",
                text_color=("#6E6E73", "#8E8E93"))
            url = self.resolve_douyin_short_url(url, proxy)
            self._run_on_ui(lambda u=url: (self.url_entry.delete(0, 'end'),
                                           self.url_entry.insert(0, u)))

        # For Douyin, use native API download (no cookies needed)
        if is_douyin and not include_subtitles:
            self._set_status(
                text="🔄 正在解析抖音视频..." if self.lang == "zh" else "🔄 Fetching Douyin video...",
                text_color=("#FF9500", "#FF9F0A"))
            try:
                if self._try_douyin_native(
                        url, output_path, download_type, proxy=proxy):
                    self.reset_ui_state()
                    return
            except Exception as error:
                self.handle_error(
                    RuntimeError('CANCELLED_BY_USER')
                    if self._cancel_requested() else error)
                self.reset_ui_state()
                return
            # Native failed, fall through to yt-dlp as last resort
            self._set_status(
                text="🔄 备用方案下载中..." if self.lang == "zh" else "🔄 Trying fallback...",
                text_color=("#FF9500", "#FF9F0A"))

        if is_telegram:
            self._set_status(
                text="🔄 正在解析 Telegram 视频..." if self.lang == "zh" else "🔄 Fetching Telegram video...",
                text_color=("#FF9500", "#FF9F0A"))

        headers = {}
        if is_douyin:
            headers.update({
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15',
                'Referer': 'https://www.douyin.com/',
                'Origin': 'https://www.douyin.com',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'zh-CN,zh;q=0.9',
            })
        if is_telegram:
            headers.update({
                'Referer': 'https://t.me/',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            })
        if is_bilibili:
            # Bilibili CDN requests are checked against the web origin. Keep
            # these headers on both metadata and media requests to avoid 403s.
            headers.update({
                'Referer': url,
                'Origin': 'https://www.bilibili.com',
                'Accept': '*/*',
            })

        ydl_opts = {
            'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
            'noplaylist': bool(download_type == 'video_prores' or not is_telegram),
            'progress_hooks': [self.progress_hook],
            'postprocessor_hooks': [self.postprocessor_hook],
            'concurrent_fragment_downloads': 4,
            # A larger initial read buffer avoids spending the first part of
            # high-latency transfers growing yt-dlp's adaptive buffer.
            'buffersize': 1024 * 1024,
            'ffmpeg_location': get_ffmpeg_path(),
            # Existing media is never overwritten.  The output template is
            # made collision-free after metadata extraction below.
            'overwrites': False,
            'continuedl': True,
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': False,
            'socket_timeout': 15,
            'retry_sleep_functions': {
                kind: self._retry_sleep
                for kind in ('http', 'fragment', 'file_access', 'extractor')
            },
            'quiet': True,
            'no_warnings': False,
            'logger': YDLLogger(self),
            'js_runtimes': get_js_runtimes(),
        }
        aria2c = get_aria2c_path()
        if aria2c:
            # aria2c is only used for ordinary HTTP(S) streams.  yt-dlp still
            # handles manifests, fragments, cookies, merging and postprocess
            # steps, while aria2c can use multiple range connections for the
            # direct CDN streams that otherwise download serially.
            ydl_opts.update({
                'external_downloader': {'http': aria2c, 'https': aria2c},
                'external_downloader_args': {
                    'aria2c': [
                        '--file-allocation=none', '--summary-interval=0',
                        '--console-log-level=warn', '--allow-overwrite=true',
                        '-x8', '-s8', '--min-split-size=4M',
                    ],
                },
            })
            self._log_diagnostic('segmented downloader=aria2c path=%s', aria2c)
        if headers:
            ydl_opts['http_headers'] = headers
        proxy = proxy or ''
        # An empty string tells yt-dlp to bypass environment/system proxies.
        ydl_opts['proxy'] = proxy
        if is_douyin:
            ydl_opts.update({'sleep_interval': 1, 'max_sleep_interval': 3})

        if download_type == 'audio':
            ydl_opts.update({
                'format': media_format_selector(download_type),
                'postprocessors': [{'key': 'FFmpegExtractAudio',
                                    'preferredcodec': 'mp3', 'preferredquality': '320'}]
            })
        else:
            # Target container the user wants for original video
            target_container = (original_container if download_type == 'video_original'
                                else ORIGINAL_CONTAINER_DEFAULT)
            # Always merge to MKV first (universal codec compatibility),
            # then remux to MP4 afterward if requested. This avoids merge
            # failures when the source uses codecs that MP4 cannot hold
            # (e.g. B站 HEVC video + FLAC audio).
            ydl_opts.update({
                'format': media_format_selector(download_type),
                'merge_output_format': 'mkv',
            })
        COOKIE_ERR = [
            'cookie', 'fresh', 'login', 'sign check', 'sign in', 'not a bot',
            'confirm you', 'could not find', 'database', 'no such file',
            'permission denied', 'cookies from browser', 's_v_web_id',
            'keychain', 'decrypt',
        ]

        try:
            info, base_filename, last_err = None, None, None
            attempts = self._download_attempts(request_config)
            for attempt_index, (credential_type, credential_value, conservative) in enumerate(attempts):
                try:
                    self._raise_if_cancelled()
                    options = self._attempt_options(
                        ydl_opts, credential_type, credential_value, conservative)
                    self._log_diagnostic(
                        'attempt host=%s auth=%s route=%s conservative=%s yt-dlp=%s',
                        host, credential_type,
                        'configured-proxy' if proxy else 'explicit-direct',
                        conservative, yt_dlp.version.__version__)
                    self._set_status(
                        text="🌐 Connecting..." if self.lang == "en" else "🌐 正在连接服务器...",
                        text_color=("#0071E3", "#0A84FF"))

                    metadata_options = options.copy()
                    metadata_options.pop('progress_hooks', None)
                    metadata_options.pop('postprocessor_hooks', None)
                    metadata_options['skip_download'] = True
                    with self._active_youtube_dl(metadata_options) as ydl:
                        metadata = ydl.extract_info(url, download=False)
                    self._raise_if_cancelled()
                    self._advance_progress('parse', 1.0)
                    self._format_diagnostic(metadata, 'metadata')

                    if download_type != 'audio':
                        original_language = self._detect_original_audio_lang(metadata)
                        english_audio = any(
                            (fmt.get('language') or '').startswith('en')
                            and fmt.get('acodec', 'none') != 'none'
                            and fmt.get('vcodec', 'none') == 'none'
                            for fmt in (metadata.get('formats') or []))
                        if original_language != 'en' and english_audio:
                            options['format'] = (
                                f'bv*+ba[language={original_language}]+ba[language=en]'
                                '/bv*+ba/best')
                            options['audio_multistreams'] = True

                    options['outtmpl'] = self._unique_media_output_template(options, metadata)

                    self._progress_stage = 'media'
                    with self._active_youtube_dl(options) as ydl:
                        info = ydl.extract_info(url, download=True)
                        base_filename = os.path.splitext(ydl.prepare_filename(info))[0]
                    self._raise_if_cancelled()
                    self._advance_progress('media', 1.0)
                    self._format_diagnostic(info, 'downloaded')
                    break

                except Exception as e:
                    self._raise_if_cancelled()
                    auth_retry = self._is_http_403(e) or any(
                        word in str(e).lower() for word in COOKIE_ERR)
                    cdn_retry = is_bilibili and self._is_transient_network_error(e)
                    if (auth_retry or cdn_retry) and attempt_index + 1 < len(attempts):
                        last_err = e
                        self._log_diagnostic(
                            'attempt failed retryable=%s refresh_metadata=%s error=%s',
                            True, cdn_retry, e)
                        self._cleanup_download_artifacts()
                        if cdn_retry:
                            self._set_status(
                                self.t('status_retry_bilibili'),
                                ("#FF9500", "#FF9F0A"))
                        continue
                    raise

            if info is None:
                raise last_err or Exception("所有下载方案均无效")
            self._raise_if_cancelled()

            # ── MP4 remux (convert from MKV if user selected MP4) ───────────
            actual_container = ORIGINAL_CONTAINER_DEFAULT
            final_video_path = None
            if download_type == 'video_original' and target_container == 'mp4' \
                    and not self._cancel_requested():
                self._advance_progress('postprocess', 0.1)
                self._set_status(
                    text="📦 封装为 MP4..." if self.lang == "zh" else "📦 Remuxing to MP4...",
                    text_color=("#FF9500", "#FF9F0A"))
                actual_container = self._remux_to_mp4(base_filename)
                if actual_container == 'mp4':
                    final_video_path = getattr(
                        self, '_last_remux_path', f'{base_filename}.mp4')
                else:
                    final_video_path = self._ensure_mkv_output(base_filename)
                    actual_container = 'mkv'
                self._advance_progress('postprocess', 1.0)
            elif download_type == 'video_original':
                final_video_path = self._ensure_mkv_output(base_filename)

            # ── ProRes transcode ──────────────────────────────────────────────
            video_result = None
            if download_type == 'video_prores':
                orig = next(
                    (f"{base_filename}{ext}" for ext in ['.mp4', '.mkv', '.webm', '.flv', '.ts', '.m4v']
                     if os.path.exists(f"{base_filename}{ext}")), None)
                if orig is None:
                    raise RuntimeError('Downloaded media could not be located for ProRes conversion')
                self._advance_progress('postprocess', 0.1)
                self._set_status(
                    text="🎬 Transcoding to ProRes..." if self.lang == "en" else "🎬 正在转码 ProRes...",
                    text_color=("#FF9500", "#FF9F0A"))
                mov_path = f"{base_filename}.mov"
                mov_path = self._next_available_path(mov_path)
                temporary = self._conversion_temp_path(mov_path)
                self._track_artifact(temporary)
                self._run_cancellable_process([
                    get_ffmpeg_path(), '-y', '-i', orig,
                    '-c:v', get_prores_encoder(), '-profile:v', '2',
                    '-c:a', 'aac', '-b:a', '320k', '-map_metadata', '0',
                    temporary], check=True)
                self._track_artifact(mov_path)
                os.replace(temporary, mov_path)
                self._remove_artifact_if_unprotected(orig)
                final_video_path = mov_path
                self._advance_progress('postprocess', 1.0)
                self._set_status(
                    text="✅ ProRes ready! Drag into Final Cut Pro" if self.lang == "en"
                         else "✅ ProRes 转码完成！可拖入 Final Cut Pro",
                    text_color=("#34C759", "#30D158"))
                video_result = 'ProRes MOV'
            elif download_type == 'audio':
                self._set_status(
                    text="✅ Audio extracted as MP3" if self.lang == "en" else "✅ 音频提取完成（MP3）",
                    text_color=("#34C759", "#30D158"))
            elif is_telegram:
                video_result = actual_container.upper()
                self._set_status(
                    text="✅ Telegram video downloaded!" if self.lang == "en" else "✅ Telegram 视频下载完成！",
                    text_color=("#34C759", "#30D158"))
            else:
                video_result = actual_container.upper()
                if actual_container == 'mkv' and target_container == 'mp4':
                    self._set_status(
                        text=self.t("status_done_mkv_fallback"),
                        text_color=("#34C759", "#30D158"))
                else:
                    self._set_status(
                        text=self.t("status_done_original").format(
                            container=actual_container.upper()),
                        text_color=("#34C759", "#30D158"))

            if final_video_path:
                expected_container = 'mov' if download_type == 'video_prores' else actual_container
                self._validate_video_output(final_video_path, expected_container)

            if include_subtitles:
                self._raise_if_cancelled()
                if not self._download_attached_subtitles(
                        url, options, metadata, request_config, video_result):
                    return
            self._advance_progress('complete', 1.0)

        except Exception as e:
            if not self._cancel_requested():
                self._cleanup_download_artifacts()
            self.handle_error(
                RuntimeError('CANCELLED_BY_USER') if self._cancel_requested() else e)
        finally:
            self.reset_ui_state()

    # ── Native Douyin download (via iesdouyin SSR API, no cookies) ───────────

    def _extract_douyin_video_id(self, url):
        """Extract numeric video ID from various Douyin URL formats."""
        for pattern in [
            r'douyin\.com/video/(\d+)',
            r'iesdouyin\.com/share/video/(\d+)',
        ]:
            m = re.search(pattern, url)
            if m:
                return m.group(1)
        return None

    def _try_douyin_native(self, url, output_path, download_type, proxy=None):
        vid = self._extract_douyin_video_id(url)
        if not vid:
            return False
        try:
            api_url = f'https://www.iesdouyin.com/share/video/{vid}/'
            req = urllib.request.Request(api_url, headers={
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) '
                              'AppleWebKit/605.1.15 (KHTML, like Gecko) '
                              'Version/17.4 Mobile/15E148 Safari/604.1',
                'Referer': 'https://www.douyin.com/',
            })
            opener = self._build_opener(proxy)
            resp = self._open_download_response(opener, req, timeout=15)
            try:
                html = resp.read().decode('utf-8', errors='ignore')
            finally:
                self._release_download_response(resp)

            m = re.search(r'window\._ROUTER_DATA\s*=\s*({.*?})\s*</script>', html, re.DOTALL)
            if not m:
                return False
            import json
            data = json.loads(m.group(1))
            item = data['loaderData']['video_(id)/page']['videoInfoRes']['item_list'][0]
            title = re.sub(r'[\\/:*?"<>|]', '_', item.get('desc', vid).strip() or vid)
            # Trim overly long titles
            if len(title) > 120:
                title = title[:120]
            video_url = item['video']['play_addr']['url_list'][0]
            # Remove watermark: /playwm/ → /play/
            video_url = video_url.replace('/playwm/', '/play/')

            if download_type == 'audio':
                # Download video first, then extract audio with ffmpeg
                return self._douyin_download_and_convert(
                    video_url, output_path, title, audio_only=True, proxy=proxy)
            else:
                return self._douyin_download_and_convert(
                    video_url, output_path, title, audio_only=False,
                    prores=(download_type == 'video_prores'), proxy=proxy)
        except Exception as error:
            self._raise_if_cancelled()
            self._log_diagnostic('native Douyin download failed; falling back to yt-dlp: %s', error)
            self._cleanup_download_artifacts()
            return False

    def _douyin_download_and_convert(self, video_url, output_path, title,
                                     audio_only=False, prores=False, proxy=None):
        ext = '.mp4'
        filepath = self._next_available_path(os.path.join(output_path, f"{title}{ext}"))
        tmp_filepath = f'{filepath}.part'
        self._track_artifact(tmp_filepath)
        self._progress_stage = 'media'

        req = urllib.request.Request(video_url, headers={
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) '
                          'AppleWebKit/605.1.15',
            'Referer': 'https://www.douyin.com/',
        })
        opener = self._build_opener(proxy)
        resp = self._open_download_response(opener, req, timeout=15)
        try:
            file_size = int(resp.headers.get('Content-Length', -1))
            downloaded = 0
            with open(tmp_filepath, 'wb') as out:
                while True:
                    self._raise_if_cancelled()
                    buf = resp.read(DOWNLOAD_CHUNK_SIZE)
                    if not buf:
                        break
                    downloaded += len(buf)
                    out.write(buf)
                    if file_size > 0:
                        pct = downloaded / file_size
                        overall = self._advance_progress('media', pct)
                        dl_mb = downloaded / 1048576
                        tot_mb = file_size / 1048576
                        msg = (f"下载中 {overall*100:.1f}%  ·  {dl_mb:.1f}/{tot_mb:.1f} MB"
                               if self.lang == "zh" else
                               f"Downloading {overall*100:.1f}%  ·  {dl_mb:.1f}/{tot_mb:.1f} MB")
                        self._set_status(text=msg, text_color=("#0071E3", "#0A84FF"))
        finally:
            self._release_download_response(resp)

        self._raise_if_cancelled()
        source_path = tmp_filepath
        if audio_only:
            mp3_path = self._next_available_path(
                os.path.join(output_path, f"{title}.mp3"))
            temporary = self._conversion_temp_path(mp3_path)
            self._track_artifact(temporary)
            self._advance_progress('postprocess', 0.1)
            self._set_status(
                text="🎵 提取音频中..." if self.lang == "zh" else "🎵 Extracting audio...",
                text_color=("#FF9500", "#FF9F0A"))
            self._run_cancellable_process([
                get_ffmpeg_path(), '-y', '-i', source_path,
                '-vn', '-acodec', 'libmp3lame', '-q:a', '0', temporary
            ], check=True, capture_output=True)
            self._track_artifact(mp3_path)
            os.replace(temporary, mp3_path)
            self._remove_artifact_if_unprotected(source_path)
            msg = "✅ 音频提取完成（MP3）" if self.lang == "zh" else "✅ Audio extracted (MP3)"
        elif prores:
            mov_path = self._next_available_path(
                os.path.join(output_path, f"{title}.mov"))
            temporary = self._conversion_temp_path(mov_path)
            self._track_artifact(temporary)
            self._advance_progress('postprocess', 0.1)
            self._set_status(
                text="🎬 正在转码 ProRes..." if self.lang == "zh" else "🎬 Transcoding to ProRes...",
                text_color=("#FF9500", "#FF9F0A"))
            self._run_cancellable_process([
                get_ffmpeg_path(), '-y', '-i', source_path,
                '-c:v', get_prores_encoder(), '-profile:v', '2',
                '-c:a', 'aac', '-b:a', '320k', temporary
            ], check=True, capture_output=True)
            self._track_artifact(mov_path)
            os.replace(temporary, mov_path)
            self._remove_artifact_if_unprotected(source_path)
            msg = "✅ ProRes 转码完成！" if self.lang == "zh" else "✅ ProRes ready!"
        else:
            self._track_artifact(filepath)
            os.replace(source_path, filepath)
            msg = "✅ 抖音视频下载完成！" if self.lang == "zh" else "✅ Douyin video downloaded!"

        if not audio_only:
            self._validate_video_output(
                mov_path if prores else filepath,
                'mov' if prores else 'mp4')
        self._advance_progress('complete', 1.0)
        self._set_status(text=msg, text_color=("#34C759", "#30D158"))
        return True

    # ── Error handling ───────────────────────────────────────────────────────

    def handle_error(self, e):
        if "CANCELLED_BY_USER" in str(e):
            self._set_status(
                text="🚫 Cancelled, cleaning up..." if self.lang == "en" else "🚫 已取消，正在清理...",
                text_color=("#FF9500", "#FF9F0A"))
            self._cleanup_download_artifacts()
            self._set_status(
                text="🗑️ Cleaned up." if self.lang == "en" else "🗑️ 清理完成",
                text_color=("#FF9500", "#FF9F0A"))
        else:
            err_str = sanitize_diagnostic(e)
            last_url = getattr(self, '_last_url', '')
            self._last_error = err_str
            self._log_diagnostic('download failed: %s', e)
            if self.is_telegram_url(last_url):
                msg = ("❌ Telegram 下载失败：请确认链接是公开频道的视频消息（点击查看详情）"
                       if self.lang == "zh" else
                       "❌ Telegram download failed: use a public channel video post (click for details)")
                self._set_status(text=msg, text_color=("#FF3B30", "#FF453A"))
                return
            if self._is_http_403(err_str):
                summary = ("HTTP 403：服务器拒绝请求，请更新 Cookie 或设置代理"
                           if self.lang == "zh" else
                           "HTTP 403: request rejected; update cookies or set a proxy")
                hint = "（点击查看详情）" if self.lang == "zh" else " (click for details)"
                self._set_status(text=f"❌ {summary}{hint}",
                                 text_color=("#FF3B30", "#FF453A"))
                return
            if 'javascript runtime' in err_str.lower() or 'challenge solver' in err_str.lower():
                summary = ("YouTube 解析需要 Deno/EJS 运行环境"
                           if self.lang == "zh" else
                           "YouTube extraction requires the Deno/EJS runtime")
                hint = "（点击查看详情）" if self.lang == "zh" else " (click for details)"
                self._set_status(text=f"❌ {summary}{hint}",
                                 text_color=("#FF3B30", "#FF453A"))
                return
            summary = ' '.join(err_str.split())
            if len(summary) > 54:
                summary = f'{summary[:53].rstrip()}...'
            hint = "（点击查看详情）" if self.lang == "zh" else " (click for details)"
            self._set_status(text=f"❌ {summary}{hint}",
                             text_color=("#FF3B30", "#FF453A"))


if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()
