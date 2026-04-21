import customtkinter as ctk
import yt_dlp
import threading
import os
import sys
import re
import subprocess
import glob
import shutil
import urllib.request
import json
import webbrowser
from urllib.parse import urlparse, unquote
import time

APP_VERSION = "1.1.1"

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


def get_ffmpeg_path():
    if hasattr(sys, '_MEIPASS'):
        p = os.path.join(sys._MEIPASS, 'ffmpeg')
        if os.path.exists(p): return p
    main_dir = os.path.dirname(sys.executable)
    for rel in ('', os.path.join('..', 'Frameworks')):
        p = os.path.normpath(os.path.join(main_dir, rel, 'ffmpeg'))
        if os.path.exists(p): return p
    return '/opt/homebrew/bin/ffmpeg'


class DownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._last_error = ""
        self.lang = "zh"
        self.download_folder = DEFAULT_DOWNLOAD_PATH

        # Smooth progress state (main-thread animation)
        self._progress_target = 0.0
        self._progress_displayed = 0.0
        self._downloading = False

        self.i18n = {
            "zh": {
                "title": "Danload", "subtitle": "全能媒体提取引擎",
                "placeholder": "粘贴视频或文件链接...", "status_wait": "等待输入",
                "btn_start": "开始下载", "btn_cancel": "取消", "btn_open": "打开 Finder",
                "opt_orig": "原画视频", "opt_prores": "ProRes",
                "opt_audio": "纯音频", "opt_general": "文件下载",
                "opt_cookie": "使用浏览器 Cookie", "lang_switch": "EN",
                "err_empty": "请先粘贴链接", "err_invalid": "未检测到有效链接",
                "btn_browse": "选择", "label_folder": "保存位置",
                "update_title": "发现新版本",
                "update_msg": "Danload {ver} 已发布，当前版本 {cur}。\n\n更新内容：\n{notes}",
                "update_btn": "前往下载",
                "update_later": "稍后再说",
            },
            "en": {
                "title": "Danload", "subtitle": "Universal Media Extractor",
                "placeholder": "Paste video or file URL...", "status_wait": "Waiting for input",
                "btn_start": "Download", "btn_cancel": "Cancel", "btn_open": "Open Finder",
                "opt_orig": "Original", "opt_prores": "ProRes",
                "opt_audio": "Audio", "opt_general": "File",
                "opt_cookie": "Use Browser Cookie", "lang_switch": "中文",
                "err_empty": "Please paste a URL first", "err_invalid": "No valid URL detected",
                "btn_browse": "Browse", "label_folder": "Save to",
                "update_title": "New Version Available",
                "update_msg": "Danload {ver} is available (you have {cur}).\n\nWhat's new:\n{notes}",
                "update_btn": "Download",
                "update_later": "Later",
            }
        }

        self.title("Danload")
        self.center_window(720, 390)
        self.resizable(False, False)
        self.configure(fg_color=("#F5F5F7", "#1C1C1E"))

        self.cookie_file_path = ctk.StringVar(value="")
        self.use_cookie_var = ctk.BooleanVar(value=False)

        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.build_main_ui()
        self.main_frame.pack(fill="both", expand=True, padx=24, pady=14)

        threading.Thread(target=self.check_for_updates, daemon=True).start()

    def t(self, key):
        return self.i18n[self.lang][key]

    # ── Update check ─────────────────────────────────────────────────────────

    @staticmethod
    def _version_tuple(v):
        try:
            return tuple(int(x) for x in v.split('.'))
        except (ValueError, AttributeError):
            return (0,)

    def check_for_updates(self):
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/Danub3/Danload/releases/latest",
                headers={"User-Agent": "Danload/" + APP_VERSION}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = data.get("tag_name", "").lstrip("v")
            notes = data.get("body", "").strip()
            if latest and self._version_tuple(latest) > self._version_tuple(APP_VERSION):
                self.after(0, lambda: self._show_update_dialog(latest, notes))
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

        # Download Type
        self.option_var = ctk.StringVar(value="video_original")
        self.egg_container = ctk.CTkFrame(
            self.main_frame,
            fg_color=("#FFFFFF", "#2C2C2E"), corner_radius=10,
            border_width=1, border_color=("#D1D1D6", "#3A3A3C"))
        self.egg_container.pack(fill="x", pady=(8, 0))

        self.eggs = {}
        for val, key in [("video_original", "opt_orig"), ("video_prores", "opt_prores"),
                         ("audio", "opt_audio"), ("general_file", "opt_general")]:
            self._make_egg(val, key)
        self.select_egg("video_original")

        # Save Location
        folder_frame = ctk.CTkFrame(
            self.main_frame,
            fg_color=("#FFFFFF", "#2C2C2E"), corner_radius=10,
            border_width=1, border_color=("#D1D1D6", "#3A3A3C"))
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

        # Progress bar (thin, smooth)
        self.progress_bar = ctk.CTkProgressBar(
            self.main_frame, height=5, corner_radius=3,
            progress_color="#0071E3", fg_color=("#E5E5EA", "#3A3A3C"))
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(12, 4))

        # Status label (click for error detail)
        self.status_label = ctk.CTkLabel(
            self.main_frame, text=self.t("status_wait"),
            text_color=("#6E6E73", "#8E8E93"),
            font=("Helvetica Neue", 12),
            wraplength=660, justify="center")
        self.status_label.pack(pady=(0, 6))
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
        self.folder_key_label.configure(text=self.t("label_folder"))
        self.folder_btn.configure(text=self.t("btn_browse"))
        for val, btn in self.eggs.items():
            emoji = btn.cget("text").split(" ")[0]
            btn.configure(text=f"{emoji} {self.t(btn.text_key)}")
        if any(w in self.status_label.cget("text") for w in ["等待", "Waiting"]):
            self.status_label.configure(text=self.t("status_wait"))

    # ── Egg buttons ─────────────────────────────────────────────────────────

    def _make_egg(self, value, text_key):
        btn = ctk.CTkButton(
            self.egg_container, text=f"🥚 {self.t(text_key)}",
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

    # ── Smooth progress animation (main thread) ──────────────────────────────

    def _start_progress_animation(self):
        self._downloading = True
        self._progress_target = 0.0
        self._progress_displayed = 0.0
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

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _short_path(self, path):
        home = os.path.expanduser('~')
        return ('~' + path[len(home):]) if path.startswith(home) else path

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

    def _choose_subtitle_langs(self, info, orig_lang='en'):
        """Return subtitle language codes matching the audio track rule.

        * English original  → ``['en']``
        * Non-English original → ``[orig_lang, 'en']`` (no duplicates)
        """
        all_subs = set((info.get('subtitles') or {}).keys())
        all_auto = set((info.get('automatic_captions') or {}).keys())
        available = all_subs | all_auto

        picks = []

        # 1. Original language subtitle (only if non-English)
        if orig_lang != 'en':
            matches = sorted(
                [l for l in available if l.lower().startswith(orig_lang)], key=len)
            if matches:
                picks.append(matches[0])

        # 2. English subtitle (always)
        en_matches = sorted(
            [l for l in available if l.lower().startswith('en')], key=len)
        if en_matches:
            picks.append(en_matches[0])
        else:
            picks.append('en')

        return picks if picks else ['en']

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

    def open_download_folder(self):
        os.makedirs(self.download_folder, exist_ok=True)
        try:
            subprocess.run(["open", self.download_folder])
        except Exception:
            pass

    # ── Cancel ──────────────────────────────────────────────────────────────

    def cancel_download(self):
        if self.download_btn.cget("state") == "disabled":
            self.is_cancelled = True
            msg = "⚠️ Forcing termination..." if self.lang == "en" else "⚠️ 正在强行拦截数据流，请稍候..."
            self.status_label.configure(text=msg, text_color=("#FF9500", "#FF9F0A"))
            self.cancel_btn.configure(state="disabled")

    # ── Progress hook (download thread) ─────────────────────────────────────

    def progress_hook(self, d):
        if getattr(self, 'is_cancelled', False):
            if 'filename' in d:
                self.cleanup_target = d['filename']
            raise Exception("CANCELLED_BY_USER")

        if d['status'] == 'downloading':
            try:
                pct_str = d['_percent_str'].strip().replace('%', '')
                pct = float(re.sub(r'\x1b\[[0-9;]*m', '', pct_str)) / 100.0
                # Only advance forward — prevents backward-jump artifacts
                if pct > self._progress_target:
                    self._progress_target = pct
                speed = d.get('_speed_str', '—')
                msg = (f"Downloading {pct*100:.1f}%  ·  {speed}" if self.lang == "en"
                       else f"下载中 {pct*100:.1f}%  ·  {speed}")
                self.status_label.configure(text=msg, text_color=("#0071E3", "#0A84FF"))
            except Exception:
                pass

        elif d['status'] == 'finished':
            self._progress_target = 1.0   # snap to full on raw-download complete
            msg = "Processing..." if self.lang == "en" else "处理中..."
            self.status_label.configure(text=msg, text_color=("#FF9500", "#FF9F0A"))

    # ── URL normalisation ───────────────────────────────────────────────────

    def normalize_url(self, url):
        from urllib.parse import parse_qs
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

    def resolve_douyin_short_url(self, url):
        """Follow v.douyin.com redirect → full douyin.com/video/{id} URL."""
        if 'v.douyin.com' not in url:
            return url
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) '
                                       'AppleWebKit/605.1.15'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                final = resp.url
            parsed = urlparse(final)
            if 'douyin.com/video/' in final:
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            return final
        except Exception:
            return url

    # ── Start download ───────────────────────────────────────────────────────

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
        self.url_entry.delete(0, 'end')
        self.url_entry.insert(0, url)

        self.is_cancelled = False
        self.cleanup_target = None
        download_type = self.option_var.get()
        self._last_url = url
        self._last_download_type = download_type
        self._cookie_refresh_attempts = 0
        self._last_error = ""

        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self._start_progress_animation()

        msg = "🔍 Parsing URL..." if self.lang == "en" else "🔍 正在解析链接..."
        self.status_label.configure(text=msg, text_color=("#0071E3", "#0A84FF"))

        target = self.download_general_file if download_type == 'general_file' else self.download_media
        args = (url,) if download_type == 'general_file' else (url, download_type)
        threading.Thread(target=target, args=args, daemon=True).start()

    def reset_ui_state(self):
        self._downloading = False
        self._progress_target = 0.0
        self._progress_displayed = 0.0
        self.progress_bar.set(0)
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.is_cancelled = False

    # ── General file download ────────────────────────────────────────────────

    def download_general_file(self, url):
        output_path = self.download_folder
        os.makedirs(output_path, exist_ok=True)
        try:
            file_name = unquote(os.path.basename(urlparse(url).path)) or "Danload_File"
            if "." not in file_name:
                file_name = "Danload_File"
            filepath = os.path.join(output_path, file_name)
            self.cleanup_target = filepath
            msg = "🚀 Connecting..." if self.lang == "en" else "🚀 正在建立连接..."
            self.status_label.configure(text=msg, text_color=("#34C759", "#30D158"))

            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as resp, open(filepath, 'wb') as out:
                file_size = int(resp.info().get('Content-Length', -1))
                downloaded = 0
                while True:
                    if getattr(self, 'is_cancelled', False):
                        raise Exception("CANCELLED_BY_USER")
                    buf = resp.read(8192)
                    if not buf:
                        break
                    downloaded += len(buf)
                    out.write(buf)
                    if file_size > 0:
                        pct = downloaded / file_size
                        if pct > self._progress_target:
                            self._progress_target = pct
                        dl_mb, tot_mb = downloaded / 1048576, file_size / 1048576
                        msg = (f"Downloading {pct*100:.1f}%  ·  {dl_mb:.1f}/{tot_mb:.1f} MB"
                               if self.lang == "en" else
                               f"下载中 {pct*100:.1f}%  ·  {dl_mb:.1f}/{tot_mb:.1f} MB")
                        self.status_label.configure(text=msg, text_color=("#0071E3", "#0A84FF"))

            msg = "✅ File downloaded!" if self.lang == "en" else "✅ 文件下载完成！"
            self.status_label.configure(text=msg, text_color=("#34C759", "#30D158"))
        except Exception as e:
            self.handle_error(e)
        finally:
            self.reset_ui_state()

    # ── Media download ───────────────────────────────────────────────────────

    def download_media(self, url, download_type):
        output_path = self.download_folder
        os.makedirs(output_path, exist_ok=True)

        is_douyin   = any(d in url for d in ['douyin.com', 'v.douyin.com', 'iesdouyin.com', 'tiktok.com'])
        is_bilibili = any(d in url for d in ['bilibili.com', 'b23.tv'])
        is_youtube  = any(d in url for d in ['youtube.com', 'youtu.be', 'yt.be'])

        # Resolve Douyin short links first
        if is_douyin and 'v.douyin.com' in url:
            self.status_label.configure(
                text="🔗 正在解析抖音短链..." if self.lang == "zh" else "🔗 Resolving short URL...",
                text_color=("#6E6E73", "#8E8E93"))
            url = self.resolve_douyin_short_url(url)
            self.after(0, lambda u=url: (self.url_entry.delete(0, 'end'),
                                         self.url_entry.insert(0, u)))

        # For Douyin, use native API download (no cookies needed)
        if is_douyin:
            self.status_label.configure(
                text="🔄 正在解析抖音视频..." if self.lang == "zh" else "🔄 Fetching Douyin video...",
                text_color=("#FF9500", "#FF9F0A"))
            if self._try_douyin_native(url, output_path, download_type):
                return
            # Native failed, fall through to yt-dlp as last resort
            self.status_label.configure(
                text="🔄 备用方案下载中..." if self.lang == "zh" else "🔄 Trying fallback...",
                text_color=("#FF9500", "#FF9F0A"))

        headers = {
            'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/123.0.0.0 Safari/537.36'),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        if is_douyin:
            headers.update({
                'Referer': 'https://www.douyin.com/',
                'Origin': 'https://www.douyin.com',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'zh-CN,zh;q=0.9',
            })

        ydl_opts = {
            'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'progress_hooks': [self.progress_hook],
            'http_headers': headers,
            'concurrent_fragment_downloads': 16,
            'ffmpeg_location': get_ffmpeg_path(),
            'retries': 200,
            'fragment_retries': 200,
            'skip_unavailable_fragments': False,
            'socket_timeout': 120,
            'http_chunk_size': 10485760,
            'quiet': True,
            'no_warnings': True,
        }
        if is_douyin:
            ydl_opts.update({'sleep_interval': 1, 'max_sleep_interval': 3})

        _best_sort = ['lang', 'res', 'fps', 'vbr', 'abr', 'br']

        if download_type == 'audio':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'format_sort': ['abr', 'br'],
                'postprocessors': [{'key': 'FFmpegExtractAudio',
                                    'preferredcodec': 'mp3', 'preferredquality': '320'}]
            })
        else:
            ydl_opts.update({
                'format': 'bestvideo+bestaudio/best',
                'merge_output_format': 'mkv',
                'format_sort': _best_sort,
                'postprocessor_args': {'merger': ['-c', 'copy']},
            })

        BROWSER_PATHS = {
            'safari': '/Applications/Safari.app',
            'chrome': '/Applications/Google Chrome.app',
            'firefox': '/Applications/Firefox.app',
        }
        available_browsers = [b for b in ['safari', 'chrome', 'firefox']
                               if os.path.exists(BROWSER_PATHS[b])]

        COOKIE_ERR = [
            'cookie', 'fresh', 'login', 'sign check', 'sign in', 'not a bot',
            'confirm you', 'could not find', 'database', 'no such file',
            'permission denied', 'cookies from browser', 's_v_web_id',
            'keychain', 'decrypt',
        ]

        cookie_file = self.cookie_file_path.get().strip()
        attempts = []
        if cookie_file and os.path.exists(cookie_file):
            attempts.append(('file', cookie_file))
        if is_youtube or is_bilibili or is_douyin:
            for b in available_browsers:
                attempts.append(('browser', b))
            attempts.append(('browser', None))
        else:
            attempts.append(('browser', None))
            for b in available_browsers:
                attempts.append(('browser', b))

        try:
            info, base_filename, last_err = None, None, None
            orig_lang = 'en'
            lang_detected = False

            for attempt_type, attempt_val in attempts:
                try:
                    # Cookie setup
                    if attempt_type == 'file':
                        ydl_opts.pop('cookiesfrombrowser', None)
                        ydl_opts['cookiefile'] = attempt_val
                    else:
                        ydl_opts.pop('cookiefile', None)
                        if attempt_val:
                            ydl_opts['cookiesfrombrowser'] = (attempt_val,)
                        else:
                            ydl_opts.pop('cookiesfrombrowser', None)

                    self.status_label.configure(
                        text="🌐 Connecting..." if self.lang == "en" else "🌐 正在连接服务器...",
                        text_color=("#0071E3", "#0A84FF"))

                    # ── Phase 0: metadata → detect original audio language ────
                    if not lang_detected and download_type != 'audio':
                        try:
                            meta_opts = {k: v for k, v in ydl_opts.items()
                                         if k not in ('progress_hooks',)}
                            meta_opts['skip_download'] = True
                            with yt_dlp.YoutubeDL(meta_opts) as ydl:
                                meta = ydl.extract_info(url, download=False)
                            orig_lang = self._detect_original_audio_lang(meta)
                            # Non-English original + English dub available → two audio tracks
                            if orig_lang != 'en':
                                en_avail = any(
                                    (f.get('language') or '').startswith('en')
                                    and f.get('acodec', 'none') != 'none'
                                    and f.get('vcodec', 'none') == 'none'
                                    for f in (meta.get('formats') or []))
                                if en_avail:
                                    ydl_opts['format'] = (
                                        f'bv*+ba[language={orig_lang}]+ba[language=en]'
                                        f'/bv*+ba/best')
                                    ydl_opts['audio_multistreams'] = True
                            lang_detected = True
                        except Exception:
                            pass  # proceed with default format

                    # ── Phase 1: actual download ──────────────────────────────
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        base_filename = os.path.splitext(ydl.prepare_filename(info))[0]
                    break

                except Exception as e:
                    if any(w in str(e).lower() for w in COOKIE_ERR):
                        last_err = e
                        continue
                    raise

            # ── Phase 2: subtitle download (separate pass, silent failure) ────
            if info is not None and download_type not in ('audio', 'video_prores') \
                    and not getattr(self, 'is_cancelled', False):
                try:
                    if not lang_detected:
                        orig_lang = self._detect_original_audio_lang(info)
                    sub_langs = self._choose_subtitle_langs(info, orig_lang)
                    self.status_label.configure(
                        text="📄 正在下载字幕..." if self.lang == "zh" else "📄 Fetching subtitles...",
                        text_color=("#FF9500", "#FF9F0A"))
                    sub_opts = {k: v for k, v in ydl_opts.items()
                                if k not in ('concurrent_fragment_downloads', 'merge_output_format',
                                             'postprocessor_args', 'format_sort', 'format',
                                             'progress_hooks', 'audio_multistreams')}
                    sub_opts.update({
                        'skip_download': True,
                        'writesubtitles': True,
                        'writeautomaticsub': True,
                        'subtitleslangs': sub_langs,
                        'subtitlesformat': 'srt/vtt/best',
                        'quiet': True,
                        'no_warnings': True,
                    })
                    with yt_dlp.YoutubeDL(sub_opts) as ydl:
                        ydl.extract_info(url, download=True)
                except Exception:
                    pass  # subtitle failure never blocks the video

            if info is None:
                raise last_err or Exception("所有下载方案均无效")

            # ── ProRes transcode ──────────────────────────────────────────────
            if download_type == 'video_prores':
                orig = next(
                    (f"{base_filename}{ext}" for ext in ['.mp4', '.mkv', '.webm', '.flv', '.ts', '.m4v']
                     if os.path.exists(f"{base_filename}{ext}")), None)
                if orig:
                    self.status_label.configure(
                        text="🎬 Transcoding to ProRes..." if self.lang == "en" else "🎬 正在转码 ProRes...",
                        text_color=("#FF9500", "#FF9F0A"))
                    subprocess.run([
                        get_ffmpeg_path(), '-y', '-i', orig,
                        '-c:v', 'prores_videotoolbox', '-profile:v', '2',
                        '-c:a', 'aac', '-b:a', '320k', '-map_metadata', '0',
                        f"{base_filename}.mov"], check=True)
                    os.remove(orig)
                    self.status_label.configure(
                        text="✅ ProRes ready! Drag into Final Cut Pro" if self.lang == "en"
                             else "✅ ProRes 转码完成！可拖入 Final Cut Pro",
                        text_color=("#34C759", "#30D158"))
            elif download_type == 'audio':
                self.status_label.configure(
                    text="✅ Audio extracted as MP3" if self.lang == "en" else "✅ 音频提取完成（MP3）",
                    text_color=("#34C759", "#30D158"))
            else:
                self.status_label.configure(
                    text="✅ Done!" if self.lang == "en" else "✅ 下载完成！含字幕轨道（MKV）",
                    text_color=("#34C759", "#30D158"))

        except Exception as e:
            self.handle_error(e)
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

    def _try_douyin_native(self, url, output_path, download_type):
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
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode('utf-8', errors='ignore')

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
                    video_url, output_path, title, audio_only=True)
            else:
                return self._douyin_download_and_convert(
                    video_url, output_path, title, audio_only=False,
                    prores=(download_type == 'video_prores'))
        except Exception:
            return False

    def _douyin_download_and_convert(self, video_url, output_path, title,
                                     audio_only=False, prores=False):
        ext = '.mp4'
        filepath = os.path.join(output_path, f"{title}{ext}")
        self.cleanup_target = filepath

        req = urllib.request.Request(video_url, headers={
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) '
                          'AppleWebKit/605.1.15',
            'Referer': 'https://www.douyin.com/',
        })
        with urllib.request.urlopen(req, timeout=120) as resp:
            file_size = int(resp.headers.get('Content-Length', -1))
            downloaded = 0
            with open(filepath, 'wb') as out:
                while True:
                    if getattr(self, 'is_cancelled', False):
                        raise Exception("CANCELLED_BY_USER")
                    buf = resp.read(65536)
                    if not buf:
                        break
                    downloaded += len(buf)
                    out.write(buf)
                    if file_size > 0:
                        pct = downloaded / file_size
                        if pct > self._progress_target:
                            self._progress_target = pct
                        dl_mb = downloaded / 1048576
                        tot_mb = file_size / 1048576
                        msg = (f"下载中 {pct*100:.1f}%  ·  {dl_mb:.1f}/{tot_mb:.1f} MB"
                               if self.lang == "zh" else
                               f"Downloading {pct*100:.1f}%  ·  {dl_mb:.1f}/{tot_mb:.1f} MB")
                        self.status_label.configure(text=msg, text_color=("#0071E3", "#0A84FF"))

        if audio_only:
            mp3_path = os.path.join(output_path, f"{title}.mp3")
            self.status_label.configure(
                text="🎵 提取音频中..." if self.lang == "zh" else "🎵 Extracting audio...",
                text_color=("#FF9500", "#FF9F0A"))
            subprocess.run([
                get_ffmpeg_path(), '-y', '-i', filepath,
                '-vn', '-acodec', 'libmp3lame', '-q:a', '0', mp3_path
            ], check=True, capture_output=True)
            os.remove(filepath)
            msg = "✅ 音频提取完成（MP3）" if self.lang == "zh" else "✅ Audio extracted (MP3)"
        elif prores:
            mov_path = os.path.join(output_path, f"{title}.mov")
            self.status_label.configure(
                text="🎬 正在转码 ProRes..." if self.lang == "zh" else "🎬 Transcoding to ProRes...",
                text_color=("#FF9500", "#FF9F0A"))
            subprocess.run([
                get_ffmpeg_path(), '-y', '-i', filepath,
                '-c:v', 'prores_videotoolbox', '-profile:v', '2',
                '-c:a', 'aac', '-b:a', '320k', mov_path
            ], check=True, capture_output=True)
            os.remove(filepath)
            msg = "✅ ProRes 转码完成！" if self.lang == "zh" else "✅ ProRes ready!"
        else:
            msg = "✅ 抖音视频下载完成！" if self.lang == "zh" else "✅ Douyin video downloaded!"

        self._progress_target = 1.0
        self.status_label.configure(text=msg, text_color=("#34C759", "#30D158"))
        return True

    # ── you-get fallback (Douyin) ────────────────────────────────────────────

    def _try_you_get(self, url, output_path):
        bin_path = shutil.which('you-get')
        if not bin_path:
            return False
        try:
            VIDEO_EXTS = ('.mp4', '.flv', '.webm', '.mkv', '.m4v', '.ts')
            before = set(os.listdir(output_path)) if os.path.isdir(output_path) else set()
            r = subprocess.run(
                [bin_path, '-o', output_path, '--no-caption', url],
                capture_output=True, text=True, timeout=300)
            # Check if new video files appeared in output_path
            after = set(os.listdir(output_path)) if os.path.isdir(output_path) else set()
            new_files = after - before
            if any(f.endswith(VIDEO_EXTS) for f in new_files):
                return True
            # you-get sometimes ignores -o and writes to cwd instead
            cwd = os.getcwd()
            if cwd != output_path:
                cwd_before = set()  # can't diff, so scan for recent files
                for f in os.listdir(cwd):
                    if f.endswith(VIDEO_EXTS):
                        fp = os.path.join(cwd, f)
                        if os.path.getmtime(fp) > time.time() - 30:
                            os.makedirs(output_path, exist_ok=True)
                            shutil.move(fp, os.path.join(output_path, f))
                            return True
            return False
        except Exception:
            return False

    # ── Error handling ───────────────────────────────────────────────────────

    def handle_error(self, e):
        if "CANCELLED_BY_USER" in str(e):
            self.status_label.configure(
                text="🚫 Cancelled, cleaning up..." if self.lang == "en" else "🚫 已取消，正在清理...",
                text_color=("#FF9500", "#FF9F0A"))
            if hasattr(self, 'cleanup_target') and self.cleanup_target:
                base = os.path.splitext(self.cleanup_target)[0]
                for f in glob.glob(f"{base}*"):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            self.status_label.configure(
                text="🗑️ Cleaned up." if self.lang == "en" else "🗑️ 清理完成",
                text_color=("#FF9500", "#FF9F0A"))
        else:
            err_str = str(e)
            is_fresh = 'fresh' in err_str.lower() and 'cookie' in err_str.lower()
            last_url = getattr(self, '_last_url', '')
            is_douyin_url = any(d in last_url for d in ['douyin.com', 'v.douyin.com', 'iesdouyin.com', 'tiktok.com'])
            if is_fresh and is_douyin_url:
                # you-get already tried and failed; don't auto-refresh, just report
                self._last_error = err_str
                msg = ("❌ 抖音下载失败：you-get 和 yt-dlp 均无法获取此视频（点击查看详情）"
                       if self.lang == "zh" else
                       "❌ Douyin download failed: both you-get and yt-dlp failed (click for details)")
                self.status_label.configure(text=msg, text_color=("#FF3B30", "#FF453A"))
                return
            self._last_error = err_str
            summary = err_str.replace('\n', ' ')[:72]
            hint = "（点击查看详情）" if self.lang == "zh" else " (click for details)"
            self.status_label.configure(text=f"❌ {summary}...{hint}",
                                        text_color=("#FF3B30", "#FF453A"))

    def _auto_refresh_cookie_and_retry(self):
        import webbrowser
        self._cookie_refresh_attempts = getattr(self, '_cookie_refresh_attempts', 0) + 1
        if self._cookie_refresh_attempts > 2:
            self.status_label.configure(
                text=("❌ 自动刷新失败，请手动导出 cookies.txt（需含 s_v_web_id）" if self.lang == "zh"
                      else "❌ Auto-refresh failed. Export cookies.txt manually (needs s_v_web_id)."),
                text_color=("#FF3B30", "#FF453A"))
            return
        webbrowser.open('https://www.douyin.com')

        def _countdown():
            for i in range(12, 0, -1):
                msg = (f"🔄 已打开抖音刷新 Cookie，{i}s 后重试（第{self._cookie_refresh_attempts}次）"
                       if self.lang == "zh" else
                       f"🔄 Opened Douyin to refresh cookies... retrying in {i}s "
                       f"(attempt {self._cookie_refresh_attempts})")
                self.after(0, lambda m=msg: self.status_label.configure(
                    text=m, text_color=("#FF9500", "#FF9F0A")))
                time.sleep(1)
            self.after(0, self._retry_last_download)

        threading.Thread(target=_countdown, daemon=True).start()

    def _retry_last_download(self):
        url = getattr(self, '_last_url', None)
        dt  = getattr(self, '_last_download_type', None)
        if not url or not dt:
            return
        self.is_cancelled = False
        self.cleanup_target = None
        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self._start_progress_animation()
        threading.Thread(target=self.download_media, args=(url, dt), daemon=True).start()


if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()
