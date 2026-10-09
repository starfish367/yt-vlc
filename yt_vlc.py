#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yt-vlc: YouTube VLC Player (GTK3 Edition) v3.0.0
Phát video YouTube siêu nhẹ trên VLC Media Player.
Tối ưu hóa phần cứng cho chip Amlogic S905X (Armbian / Mali-450).
Hỗ trợ:
- Sửa lỗi nạp video trong kênh (Web + RSS + yt-dlp fallback)
- Tích hợp SponsorBlock (tự bỏ qua quảng cáo tài trợ khi xem và tải)
- Tích hợp DeArrow (tiêu đề và ảnh bìa sạch, chống giật tít câu view)
- Tự động cuộn vô tận để nạp thêm video (Infinite Scrolling)
- Tab Thịnh hành & Khám phá (Trending, Âm nhạc, Trò chơi, Tin tức)
- Tùy chọn chất lượng Video & Chỉ Audio trước khi mở, hỗ trợ TẢI VỀ
- Quản lý nhiều phiên người dùng (Profiles) & Chế độ Ẩn danh (Incognito)
- Theo dõi tiến trình xem (thanh màu đỏ tiến trình, tự mờ ảnh bìa khi xem xong)
- Loại bỏ hoàn toàn lỗi hiển thị mã hex icon (Tofu), dùng Native GTK Symbolic Icons
"""

import sys
import os
import json
import re
import time
import datetime
import threading
import subprocess
import shutil
import socket
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Pango

# --- Thư mục và file cấu hình ---
CONFIG_DIR = os.path.expanduser("~/.config/yt-vlc")
PROFILES_FILE = os.path.join(CONFIG_DIR, "profiles.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
CACHE_DIR = os.path.expanduser("~/.cache/yt-vlc")
THUMB_DIR = os.path.join(CACHE_DIR, "thumbs")
AVATAR_DIR = os.path.join(CACHE_DIR, "avatars")

# --- User-Agent presets ---
UA_PRESETS = {
    "Android TV (Khuyên dùng)":
        "Mozilla/5.0 (Linux; Android 10; SHIELD Android TV Build/PPR1.180610.011; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/73.0.3683.90 Safari/537.36",
    "Android Phone":
        "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
    "iPhone / iOS":
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Firefox Desktop (Linux)":
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Chrome Desktop":
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36",
    "Smart TV (Generic)":
        "Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/537.36 (KHTML, like Gecko) "
        "SamsungBrowser/2.1 Chrome/56.0.2924.0 TV Safari/537.36",
}

DEFAULT_SETTINGS = {
    "quality": "720",
    "caching": 3000,
    "player_client": "tv_embedded,android,mweb",
    "hw_accel": True,
    "max_results": 30,
    "dark_mode": True,
    "user_agent": "Android TV (Khuyên dùng)",
    "ask_quality": True,
    "sponsorblock": True,
    "dearrow": True,
    "auto_load_more": True,
    "download_dir": os.path.expanduser("~/Downloads"),
}

QUALITY_OPTIONS = [
    ("720", "720p HD – H.264 (Tối ưu phần cứng Mali-450)"),
    ("480", "480p – H.264 (Mượt mà nhẹ tải)"),
    ("360", "360p – H.264 (Tiết kiệm mạng)"),
    ("1080", "1080p Full HD – H.264"),
    ("audio", "Chỉ Audio (m4a / mp3)"),
    ("best", "Tốt nhất có thể"),
]

SORT_MODES = {
    "Mới nhất": "newest",
    "Cũ nhất": "oldest",
    "Tên A→Z": "title_asc",
    "Tên Z→A": "title_desc",
}

# In-memory storage for Incognito / Ẩn danh session
INCOGNITO_HISTORY = []
INCOGNITO_PROGRESS = {}
INCOGNITO_SUBS = []


# ==============================================================================
# QUẢN LÝ DỮ LIỆU & PHIÊN NGƯỜI DÙNG (PROFILES)
# ==============================================================================

def ensure_directories():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)
    os.makedirs(AVATAR_DIR, exist_ok=True)
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)
    if not os.path.exists(PROFILES_FILE):
        init_profiles = {
            "active": "Mặc định",
            "profiles": [
                {"name": "Mặc định", "is_incognito": False},
                {"name": "Ẩn danh", "is_incognito": True}
            ]
        }
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(init_profiles, f, ensure_ascii=False, indent=2)


def load_settings():
    ensure_directories()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            merged = DEFAULT_SETTINGS.copy()
            merged.update(data)
            return merged
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    ensure_directories()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def load_profiles_data():
    ensure_directories()
    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "active": "Mặc định",
            "profiles": [
                {"name": "Mặc định", "is_incognito": False},
                {"name": "Ẩn danh", "is_incognito": True}
            ]
        }


def save_profiles_data(pdata):
    ensure_directories()
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(pdata, f, ensure_ascii=False, indent=2)


def get_active_profile():
    pdata = load_profiles_data()
    active_name = pdata.get("active", "Mặc định")
    for p in pdata.get("profiles", []):
        if p.get("name") == active_name:
            return p.get("name"), bool(p.get("is_incognito"))
    return "Mặc định", False


def set_active_profile(name):
    pdata = load_profiles_data()
    # verify existence
    found = any(p.get("name") == name for p in pdata.get("profiles", []))
    if found:
        pdata["active"] = name
        save_profiles_data(pdata)


def create_profile(name, is_incognito=False):
    name = name.strip()
    if not name:
        return False
    pdata = load_profiles_data()
    if any(p.get("name") == name for p in pdata.get("profiles", [])):
        return False
    pdata.setdefault("profiles", []).append({
        "name": name,
        "is_incognito": is_incognito
    })
    save_profiles_data(pdata)
    return True


def delete_profile(name):
    if name in ["Mặc định", "Ẩn danh"]:
        return False
    pdata = load_profiles_data()
    pdata["profiles"] = [p for p in pdata.get("profiles", []) if p.get("name") != name]
    if pdata.get("active") == name:
        pdata["active"] = "Mặc định"
    save_profiles_data(pdata)
    return True


def _profile_to_suffix(pname):
    if pname == "Mặc định":
        return ""
    slug = re.sub(r'[^a-zA-Z0-9_-]', '_', pname)
    return f"_{slug}"


def get_subs_file():
    pname, is_incognito = get_active_profile()
    if is_incognito:
        return None
    suf = _profile_to_suffix(pname)
    return os.path.join(CONFIG_DIR, f"subscriptions{suf}.json")


def get_history_file():
    pname, is_incognito = get_active_profile()
    if is_incognito:
        return None
    suf = _profile_to_suffix(pname)
    return os.path.join(CONFIG_DIR, f"history{suf}.json")


def get_progress_file():
    pname, is_incognito = get_active_profile()
    if is_incognito:
        return None
    suf = _profile_to_suffix(pname)
    return os.path.join(CONFIG_DIR, f"progress{suf}.json")


def load_subs():
    ensure_directories()
    pname, is_incognito = get_active_profile()
    if is_incognito:
        return list(INCOGNITO_SUBS)
    sfile = get_subs_file()
    if not os.path.exists(sfile):
        # copy legacy or init
        legacy = os.path.join(CONFIG_DIR, "subscriptions.json")
        if os.path.exists(legacy) and sfile != legacy:
            try:
                shutil.copy(legacy, sfile)
            except Exception:
                pass
        else:
            return []
    try:
        with open(sfile, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_subs(subs):
    ensure_directories()
    pname, is_incognito = get_active_profile()
    if is_incognito:
        INCOGNITO_SUBS.clear()
        INCOGNITO_SUBS.extend(subs)
        return
    sfile = get_subs_file()
    with open(sfile, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)


def load_history():
    ensure_directories()
    pname, is_incognito = get_active_profile()
    if is_incognito:
        return list(INCOGNITO_HISTORY)
    hfile = get_history_file()
    if not os.path.exists(hfile):
        legacy = os.path.join(CONFIG_DIR, "history.json")
        if os.path.exists(legacy) and hfile != legacy:
            try:
                shutil.copy(legacy, hfile)
            except Exception:
                pass
        else:
            return []
    try:
        with open(hfile, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history):
    ensure_directories()
    pname, is_incognito = get_active_profile()
    if is_incognito:
        INCOGNITO_HISTORY.clear()
        INCOGNITO_HISTORY.extend(history[:100])
        return
    hfile = get_history_file()
    with open(hfile, "w", encoding="utf-8") as f:
        json.dump(history[:100], f, ensure_ascii=False, indent=2)


def add_to_history(video):
    history = load_history()
    history = [h for h in history if h.get("id") != video.get("id")]
    entry = {
        "id": video.get("id"),
        "title": video.get("title", "Video"),
        "channel": video.get("channel") or video.get("uploader", "YouTube"),
        "channel_id": video.get("channel_id"),
        "duration": video.get("duration", "--:--"),
        "watched_at": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    history.insert(0, entry)
    save_history(history)


def load_progress():
    ensure_directories()
    pname, is_incognito = get_active_profile()
    if is_incognito:
        return dict(INCOGNITO_PROGRESS)
    pfile = get_progress_file()
    if not os.path.exists(pfile):
        return {}
    try:
        with open(pfile, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_progress(progress_dict):
    ensure_directories()
    pname, is_incognito = get_active_profile()
    if is_incognito:
        INCOGNITO_PROGRESS.clear()
        INCOGNITO_PROGRESS.update(progress_dict)
        return
    pfile = get_progress_file()
    with open(pfile, "w", encoding="utf-8") as f:
        json.dump(progress_dict, f, ensure_ascii=False, indent=2)


def record_watch_progress(video_id, watched_seconds, total_seconds):
    if not video_id or (watched_seconds <= 0 and total_seconds <= 0):
        return
    prog = load_progress()
    completed = False
    if total_seconds > 0:
        if watched_seconds >= total_seconds * 0.88 or (total_seconds - watched_seconds <= 25):
            completed = True
    prog[video_id] = {
        "watched": int(watched_seconds),
        "total": int(total_seconds),
        "completed": completed,
        "updated_at": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    save_progress(prog)


def sort_videos(videos, mode="newest"):
    if mode == "newest":
        return sorted(videos, key=lambda x: x.get("published", ""), reverse=True)
    elif mode == "oldest":
        return sorted(videos, key=lambda x: x.get("published", ""), reverse=False)
    elif mode == "title_asc":
        return sorted(videos, key=lambda x: x.get("title", "").lower())
    elif mode == "title_desc":
        return sorted(videos, key=lambda x: x.get("title", "").lower(), reverse=True)
    return videos


# ==============================================================================
# SPONSORBLOCK & DEARROW APIs
# ==============================================================================

_sponsorblock_cache = {}
_dearrow_cache = {}


def fetch_sponsorblock_segments(video_id):
    if not video_id:
        return []
    if video_id in _sponsorblock_cache:
        return _sponsorblock_cache[video_id]
    categories = '["sponsor","intro","outro","selfpromo","interaction"]'
    url = f"https://sponsor.ajay.app/api/skipSegments?videoID={video_id}&categories={urllib.parse.quote(categories)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    segments = []
    try:
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode())
        for item in data:
            seg = item.get("segment")
            cat = item.get("category", "sponsor")
            if seg and len(seg) == 2:
                segments.append((float(seg[0]), float(seg[1]), cat))
    except Exception:
        pass
    _sponsorblock_cache[video_id] = segments
    return segments


def fetch_dearrow_info(video_id):
    if not video_id:
        return None
    if video_id in _dearrow_cache:
        return _dearrow_cache[video_id]
    url = f"https://sponsor.ajay.app/api/branding?videoID={video_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode())
        title = None
        for t in data.get("titles", []):
            if not t.get("original") and t.get("title"):
                title = t["title"]
                break
        thumb_time = None
        for th in data.get("thumbnails", []):
            if not th.get("original") and th.get("timestamp") is not None:
                thumb_time = th["timestamp"]
                break
        res = {"title": title, "timestamp": thumb_time}
        _dearrow_cache[video_id] = res
        return res
    except Exception:
        _dearrow_cache[video_id] = None
        return None


# ==============================================================================
# QUẢN LÝ THUMBNAILS & HÌNH ẢNH
# ==============================================================================

thumb_executor = ThreadPoolExecutor(max_workers=5)


def get_placeholder_pixbuf(width=160, height=90):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    pixbuf.fill(0x1e1e1eff)
    return pixbuf


def fetch_and_load_image(url_or_id, width=160, height=90, callback=None, is_avatar=False):
    if not url_or_id:
        if callback:
            GLib.idle_add(callback, get_placeholder_pixbuf(width, height))
        return

    # Direct URL
    if url_or_id.startswith("http://") or url_or_id.startswith("https://") or url_or_id.startswith("//"):
        img_url = "https:" + url_or_id if url_or_id.startswith("//") else url_or_id
        import hashlib
        h = hashlib.md5(img_url.encode("utf-8")).hexdigest()
        cache_dir = AVATAR_DIR if is_avatar else THUMB_DIR
        path = os.path.join(cache_dir, f"{h}.jpg")

        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width, height, False)
                if callback:
                    GLib.idle_add(callback, pb)
                return
            except Exception:
                pass

        try:
            req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = resp.read()
            if data and len(data) > 200:
                with open(path, "wb") as f:
                    f.write(data)
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width, height, False)
                if callback:
                    GLib.idle_add(callback, pb)
                return
        except Exception:
            pass

        if callback:
            GLib.idle_add(callback, get_placeholder_pixbuf(width, height))
        return

    # Video ID: check DeArrow first if enabled
    settings = load_settings()
    video_id = url_or_id
    if settings.get("dearrow", True):
        d_info = fetch_dearrow_info(video_id)
        if d_info and d_info.get("timestamp") is not None:
            dearrow_url = f"https://dearrow-thumb.ajay.app/api/v1/getThumbnail?videoID={video_id}&time={d_info['timestamp']}"
            fetch_and_load_image(dearrow_url, width, height, callback, is_avatar=False)
            return

    # Standard YouTube thumbnail
    path = os.path.join(THUMB_DIR, f"{video_id}.jpg")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width, height, False)
            if callback:
                GLib.idle_add(callback, pb)
            return
        except Exception:
            pass

    urls = [
        f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/default.jpg"
    ]
    downloaded = False
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
            if data and len(data) > 200:
                with open(path, "wb") as f:
                    f.write(data)
                downloaded = True
                break
        except Exception:
            continue

    if downloaded and os.path.exists(path):
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width, height, False)
            if callback:
                GLib.idle_add(callback, pb)
            return
        except Exception:
            pass

    if callback:
        GLib.idle_add(callback, get_placeholder_pixbuf(width, height))


def request_image_async(url_or_id, callback, width=160, height=90, is_avatar=False):
    thumb_executor.submit(fetch_and_load_image, url_or_id, width, height, callback, is_avatar)


def request_thumbnail_async(video_id, callback, width=160, height=90):
    request_image_async(video_id, callback, width, height, is_avatar=False)


# ==============================================================================
# HỖ TRỢ BIỂU TƯỢNG (ICONS) CHUẨN NATIVE GTK SYMBOLIC
# ==============================================================================

def create_tab_label(icon_name, text):
    """Tạo nhãn tab chứa biểu tượng GTK Native và text, chống lỗi vỡ font emoji."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    if icon_name:
        img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
        box.pack_start(img, False, False, 0)
    lbl = Gtk.Label(label=text)
    box.pack_start(lbl, False, False, 0)
    box.show_all()
    return box


def create_icon_button(icon_name, label_text=None, tooltip=None, css_class=None):
    """Tạo nút bấm chứa icon symbolic và nhãn, hiển thị sắc nét trên mọi giao diện."""
    btn = Gtk.Button()
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.set_halign(Gtk.Align.CENTER)
    if icon_name:
        img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        box.pack_start(img, False, False, 0)
    if label_text:
        lbl = Gtk.Label(label=label_text)
        box.pack_start(lbl, False, False, 0)
    btn.add(box)
    if tooltip:
        btn.set_tooltip_text(tooltip)
    if css_class:
        btn.get_style_context().add_class(css_class)
    btn.show_all()
    return btn


# ==============================================================================
# TRÍCH XUẤT LUỒNG & PHÁT VIDEO / TẢI VỀ
# ==============================================================================

def get_ua_string(settings):
    ua_key = settings.get("user_agent", "Android TV (Khuyên dùng)")
    return UA_PRESETS.get(ua_key, UA_PRESETS["Android TV (Khuyên dùng)"])


def find_free_tcp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def extract_stream_url(video_id_or_url, quality="720", player_client="tv_embedded,android,mweb", ua_string=None):
    target = video_id_or_url if video_id_or_url.startswith("http") else f"https://www.youtube.com/watch?v={video_id_or_url}"

    # Luôn ép chuẩn video H.264 (avc1) để tận dụng VPU giải mã phần cứng của S905X
    if quality == "audio":
        format_spec = "bestaudio[ext=m4a]/bestaudio/best[acodec!=none]"
    elif quality in ["1080", "best"]:
        format_spec = (
            f"bestvideo[height<={quality}][vcodec^=avc1]+bestaudio[ext=m4a]/"
            f"best[height<={quality}][vcodec^=avc1][acodec!=none]/"
            f"best[height<={quality}][acodec!=none]/best"
        )
    else:
        format_spec = (
            f"bestvideo[height<={quality}][vcodec^=avc1]+bestaudio[ext=m4a]/"
            f"best[height<={quality}][vcodec^=avc1][acodec!=none]/"
            f"best[height<={quality}][ext=mp4][acodec!=none]/"
            f"best[acodec!=none]/best"
        )

    env = os.environ.copy()
    env["PATH"] = f"/home/a/.local/bin:{env.get('PATH', '')}"

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--extractor-args", f"youtube:player_client={player_client}",
        "-f", format_spec,
        "-g",
        target
    ]

    if ua_string:
        cmd.extend(["--add-headers", f"User-Agent:{ua_string}"])

    node_bin = shutil.which("node") or "/home/a/.local/bin/node"
    if os.path.exists(node_bin):
        cmd.extend(["--js-runtimes", f"node:{node_bin}"])

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True, timeout=30, env=env)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("http")]
        if len(lines) >= 2:
            return lines[0], lines[1]
        elif len(lines) == 1:
            return lines[0], None
    except Exception:
        pass

    # Fallback tv_embedded
    try:
        cmd_fb = [
            "yt-dlp",
            "--no-playlist",
            "--extractor-args", "youtube:player_client=tv_embedded",
            "-f", "best[acodec!=none]/best",
            "-g",
            target
        ]
        if ua_string:
            cmd_fb.extend(["--add-headers", f"User-Agent:{ua_string}"])
        proc = subprocess.run(cmd_fb, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True, timeout=20, env=env)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("http")]
        if lines:
            return lines[0], None
    except Exception:
        pass

    return None, None


def monitor_vlc_rc(port, video_id, segments, status_callback=None, on_playback_done=None):
    """Kết nối điều khiển từ xa VLC để tự bỏ qua quảng cáo SponsorBlock và ghi nhận tiến trình xem."""
    sock = None
    for _ in range(16):
        time.sleep(0.3)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.2)
            s.connect(('127.0.0.1', port))
            sock = s
            try:
                sock.recv(1024)
            except Exception:
                pass
            break
        except Exception:
            pass

    if not sock:
        return

    last_watched = 0
    total_length = 0
    skipped_indices = set()

    try:
        while True:
            time.sleep(0.8)
            # 1. Đo thời gian hiện tại
            try:
                sock.sendall(b"get_time\n")
                resp = sock.recv(256).decode("utf-8", errors="ignore")
                m = re.search(r"(\d+)", resp)
                if m:
                    cur_time = int(m.group(1))
                    if cur_time > 0:
                        last_watched = cur_time
                        # Kiểm tra phân đoạn SponsorBlock
                        if segments:
                            for idx, (s_start, s_end, cat) in enumerate(segments):
                                if idx not in skipped_indices and s_start <= cur_time < s_end:
                                    skip_target = int(s_end + 1)
                                    sock.sendall(f"seek {skip_target}\n".encode())
                                    skipped_indices.add(idx)
                                    dur = int(s_end - s_start)
                                    if status_callback:
                                        GLib.idle_add(
                                            status_callback,
                                            f"⏩ [SponsorBlock] Tự động bỏ qua đoạn tài trợ ({dur} giây)"
                                        )
                                    break
            except Exception:
                break

            # 2. Lấy tổng độ dài nếu chưa có
            if total_length <= 0:
                try:
                    sock.sendall(b"get_length\n")
                    resp_len = sock.recv(256).decode("utf-8", errors="ignore")
                    m_len = re.search(r"(\d+)", resp_len)
                    if m_len:
                        t_len = int(m_len.group(1))
                        if t_len > 0:
                            total_length = t_len
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
        if video_id and (last_watched > 0 or total_length > 0):
            record_watch_progress(video_id, last_watched, total_length)
        if on_playback_done:
            GLib.idle_add(on_playback_done, video_id)


def launch_vlc(video, settings, quality_override=None, status_callback=None, on_playback_done=None):
    def _run():
        vid_id = video.get("id")
        title = video.get("title", "YouTube Video")
        target_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else video.get("url")

        quality = quality_override or settings.get("quality", "720")
        ua_string = get_ua_string(settings)

        if status_callback:
            GLib.idle_add(status_callback, f"⏳ Đang kết nối luồng {quality}p: {title[:40]}...")

        video_url, audio_url = extract_stream_url(
            target_url,
            quality=quality,
            player_client=settings.get("player_client", "tv_embedded,android,mweb"),
            ua_string=ua_string
        )

        if not video_url:
            if status_callback:
                GLib.idle_add(status_callback, "❌ Không thể phát video. Vui lòng thử video khác!")
            return

        caching = settings.get("caching", 3000)
        rc_port = find_free_tcp_port()

        # SponsorBlock: Kiểm tra phân đoạn
        segments = []
        if settings.get("sponsorblock", True) and vid_id:
            segments = fetch_sponsorblock_segments(vid_id)

        vlc_cmd = [
            "vlc",
            video_url,
            f"--meta-title={title}",
            f"--file-caching={caching}",
            f"--network-caching={caching}",
            "--no-video-title-show",
            "--drop-late-frames",
            "--skip-frames",
            "--avcodec-skiploopfilter=3",
            "--extraintf=rc",
            f"--rc-host=127.0.0.1:{rc_port}",
            "--rc-fake-tty",
        ]

        # Bỏ qua ngay từ đầu nếu có intro/sponsor ở giây 0..2
        if segments and segments[0][0] <= 2.5:
            vlc_cmd.append(f"--start-time={int(segments[0][1])}")

        if audio_url:
            vlc_cmd.append(f"--input-slave={audio_url}")

        if not settings.get("hw_accel", True):
            vlc_cmd.extend(["--avcodec-hw=none", "--avcodec-skiploopfilter=4"])

        if status_callback:
            GLib.idle_add(status_callback, f"▶ Đang phát {quality}p trên VLC: {title[:40]}")

        add_to_history(video)

        # Thread giám sát VLC qua RC socket
        threading.Thread(
            target=monitor_vlc_rc,
            args=(rc_port, vid_id, segments, status_callback, on_playback_done),
            daemon=True
        ).start()

        try:
            subprocess.run(vlc_cmd)
        except Exception as e:
            if status_callback:
                GLib.idle_add(status_callback, f"Lỗi khởi động VLC: {e}")
        finally:
            if status_callback:
                GLib.idle_add(status_callback, "Sẵn sàng")

    threading.Thread(target=_run, daemon=True).start()


def download_media(video, quality="720", is_audio=False, download_dir=None, status_callback=None):
    """Tải video hoặc audio về máy bằng yt-dlp."""
    if not download_dir:
        download_dir = load_settings().get("download_dir", os.path.expanduser("~/Downloads"))
    os.makedirs(download_dir, exist_ok=True)

    vid_id = video.get("id")
    title = video.get("title", "Video")
    target_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else video.get("url")

    env = os.environ.copy()
    env["PATH"] = f"/home/a/.local/bin:{env.get('PATH', '')}"

    out_tmpl = os.path.join(download_dir, "%(title)s.%(ext)s")
    if is_audio:
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-x",
            "--audio-format", "mp3",
            "-o", out_tmpl,
            target_url
        ]
    else:
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", f"bestvideo[height<={quality}][vcodec^=avc1]+bestaudio[ext=m4a]/best[height<={quality}]/best",
            "-o", out_tmpl,
            target_url
        ]

    settings = load_settings()
    if settings.get("sponsorblock", True):
        cmd.extend(["--sponsorblock-remove", "sponsor,intro,outro,selfpromo,interaction"])

    def _worker():
        kind = "Audio MP3" if is_audio else f"Video {quality}p"
        if status_callback:
            GLib.idle_add(status_callback, f"⏳ Đang tải về [{kind}]: {title[:35]}...")
        try:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=env)
            if proc.returncode == 0:
                if status_callback:
                    GLib.idle_add(status_callback, f"✅ Đã tải xong: {title[:30]} vào {download_dir}")
            else:
                err_msg = proc.stderr.splitlines()[-1] if proc.stderr else "Lỗi không xác định"
                if status_callback:
                    GLib.idle_add(status_callback, f"❌ Tải thất bại: {err_msg[:60]}")
        except Exception as e:
            if status_callback:
                GLib.idle_add(status_callback, f"❌ Lỗi tải về: {e}")

    threading.Thread(target=_worker, daemon=True).start()


# ==============================================================================
# BỘ TÌM KIẾM, PHÂN GIẢI KÊNH & KHÁM PHÁ THỊNH HÀNH
# ==============================================================================

def resolve_channel(target):
    target = target.strip()
    channel_id = None

    if re.match(r"^UC[a-zA-Z0-9_-]{22}$", target):
        channel_id = target
    else:
        url = target if target.startswith("http") else f"https://www.youtube.com/{target if target.startswith('@') else '@' + target}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
            m = re.search(r"feeds/videos\.xml\?channel_id=(UC[a-zA-Z0-9_-]{22})", content)
            if m:
                channel_id = m.group(1)
            else:
                m2 = re.search(r"channel/(UC[a-zA-Z0-9_-]{22})", content)
                if m2:
                    channel_id = m2.group(1)
        except Exception:
            return None

    if not channel_id:
        return None

    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read())
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        title_elem = root.find("atom:title", ns)
        name = title_elem.text.strip() if title_elem is not None and title_elem.text else channel_id
        return {"id": channel_id, "name": name, "handle": target}
    except Exception:
        return {"id": channel_id, "name": channel_id, "handle": target}


def fetch_feed_for_channel(channel):
    """Trích xuất 15 video mới nhất từ RSS feed XML của kênh YouTube (<0.5 giây)."""
    channel_id = channel.get("id")
    if not channel_id:
        return []
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
    videos = []
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read())
        ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
        for entry in root.findall("atom:entry", ns):
            vid_id = entry.find("yt:videoId", ns)
            title = entry.find("atom:title", ns)
            pub = entry.find("atom:published", ns)
            if vid_id is not None and title is not None:
                videos.append({
                    "id": vid_id.text.strip(),
                    "title": title.text.replace("\n", " ").replace("\r", "").strip(),
                    "channel": channel.get("name") or channel.get("title", "Kênh"),
                    "uploader": channel.get("name") or channel.get("title", "Kênh"),
                    "channel_id": channel_id,
                    "duration": "--:--",
                    "published": pub.text[:10] if pub is not None and pub.text else ""
                })
    except Exception:
        pass
    return videos


def get_subscriptions_feed():
    """Tải feed video mới nhất từ tất cả các kênh người dùng đã đăng ký."""
    subs = load_subs()
    if not subs:
        return []
    videos = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = ex.map(fetch_feed_for_channel, subs)
        for vlist in results:
            if vlist:
                videos.extend(vlist)
    return sorted(videos, key=lambda x: x.get("published", ""), reverse=True)


def fetch_channel_videos_ytdlp(channel_id, limit=50):
    """Fallback nạp video kênh qua yt-dlp."""
    env = os.environ.copy()
    env["PATH"] = f"/home/a/.local/bin:{env.get('PATH', '')}"
    target = f"https://www.youtube.com/channel/{channel_id}/videos"
    cmd = [
        "yt-dlp",
        "--extractor-args", "youtube:player_client=tv_embedded",
        "--flat-playlist",
        "--playlist-end", str(limit),
        "--print", "%(id)s\t%(title)s\t%(uploader)s\t%(duration_string)s\t%(channel_id)s",
        target
    ]
    videos = []
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True, timeout=25, env=env)
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].strip():
                videos.append({
                    "id": parts[0].strip(),
                    "title": parts[1].replace("\n", " ").strip(),
                    "uploader": parts[2].strip() if len(parts) > 2 else "YouTube",
                    "channel": parts[2].strip() if len(parts) > 2 else "YouTube",
                    "channel_id": parts[4].strip() if len(parts) > 4 else channel_id,
                    "duration": parts[3].strip() if len(parts) > 3 else "--:--",
                    "type": "video"
                })
    except Exception:
        pass
    return videos


def fetch_channel_videos_web(channel_id):
    """Trích xuất thông tin kênh và danh sách video trực tiếp từ web YouTube."""
    channel_id = channel_id.strip()
    if channel_id.startswith("http"):
        url = channel_id.rstrip("/") + "/videos"
    elif channel_id.startswith("@"):
        url = f"https://www.youtube.com/{channel_id}/videos"
    else:
        url = f"https://www.youtube.com/channel/{channel_id}/videos"

    req = urllib.request.Request(url, headers={
        "User-Agent": UA_PRESETS["Firefox Desktop (Linux)"],
        "Accept-Language": "vi,en;q=0.9"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    m = re.search(r"ytInitialData\s*=\s*({.+?});</script>", html) or \
        re.search(r"var ytInitialData\s*=\s*({.+?});", html)
    if not m:
        return None

    try:
        data = json.loads(m.group(1))
    except Exception:
        return None

    # Metadata kênh
    header = data.get("header", {})
    ph = header.get("pageHeaderRenderer", {})
    c4 = header.get("c4TabbedHeaderRenderer", {})
    title = ph.get("pageTitle") or c4.get("title") or ""

    avatar = None
    avatar_model = ph.get("content", {}).get("pageHeaderViewModel", {}).get(
        "image", {}).get("decoratedAvatarViewModel", {}).get("avatar", {}).get("avatarViewModel", {})
    if avatar_model:
        sources = avatar_model.get("image", {}).get("sources", [])
        if sources:
            avatar = sources[-1].get("url")
    if not avatar and c4:
        thumbs = c4.get("avatar", {}).get("thumbnails", [])
        if thumbs:
            avatar = thumbs[-1].get("url")
    if avatar and avatar.startswith("//"):
        avatar = "https:" + avatar

    meta_rows = ph.get("content", {}).get("pageHeaderViewModel", {}).get(
        "metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
    handle = ""
    subscribers = ""
    video_count = ""
    for r in meta_rows:
        for p in r.get("metadataParts", []):
            text = p.get("text", {}).get("content", "")
            if text.startswith("@"):
                handle = text
            elif "người đăng ký" in text or "subscriber" in text.lower():
                subscribers = text
            elif "video" in text.lower():
                video_count = text

    actual_cid = channel_id
    microformat = data.get("microformat", {}).get("microformatDataRenderer", {})
    canonical_url = microformat.get("urlCanonical", "")
    if "channel/" in canonical_url:
        actual_cid = canonical_url.split("channel/")[-1].split("/")[0]

    channel_meta = {
        "id": actual_cid,
        "title": title or channel_id,
        "name": title or channel_id,
        "avatar": avatar,
        "handle": handle,
        "subscribers": subscribers,
        "video_count": video_count,
        "verified": True
    }

    # Danh sách video
    videos = []
    tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    video_tab = None
    for t in tabs:
        tr = t.get("tabRenderer", {})
        if tr.get("selected") or tr.get("title") in ["Video", "Videos"]:
            video_tab = tr
            break
    if not video_tab and len(tabs) > 1:
        video_tab = tabs[1].get("tabRenderer", {})

    grid = video_tab.get("content", {}).get("richGridRenderer", {}) if video_tab else {}
    items = grid.get("contents", [])
    for it in items:
        vm = it.get("richItemRenderer", {}).get("content", {}).get("lockupViewModel")
        vr = it.get("richItemRenderer", {}).get("content", {}).get("videoRenderer")
        if vm:
            vid_id = vm.get("contentId")
            meta = vm.get("metadata", {}).get("lockupMetadataViewModel", {})
            vtitle = meta.get("title", {}).get("content", "")
            dur = "--:--"
            for ov in vm.get("contentImage", {}).get("thumbnailViewModel", {}).get("overlays", []):
                badges = ov.get("thumbnailBottomOverlayViewModel", {}).get("badges", [])
                for b in badges:
                    t = b.get("thumbnailBadgeViewModel", {}).get("text")
                    if t and (":" in t or t.isdigit()):
                        dur = t
                        break
            parts = []
            for r in meta.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", []):
                for p in r.get("metadataParts", []):
                    label = p.get("accessibilityLabel") or p.get("text", {}).get("content")
                    if label:
                        parts.append(label)
            views = parts[0] if len(parts) > 0 else ""
            pub = parts[1] if len(parts) > 1 else ""
            if vid_id and vtitle:
                videos.append({
                    "id": vid_id,
                    "title": vtitle,
                    "channel": title or channel_id,
                    "channel_id": actual_cid,
                    "uploader": title or channel_id,
                    "duration": dur,
                    "published": pub,
                    "views": views
                })
        elif vr:
            vid_id = vr.get("videoId")
            vtitle = "".join(r.get("text", "") for r in vr.get("title", {}).get("runs", []))
            dur = vr.get("lengthText", {}).get("simpleText", "--:--")
            pub = vr.get("publishedTimeText", {}).get("simpleText", "")
            views = vr.get("viewCountText", {}).get("simpleText", "")
            if vid_id and vtitle:
                videos.append({
                    "id": vid_id,
                    "title": vtitle,
                    "channel": title or channel_id,
                    "channel_id": actual_cid,
                    "uploader": title or channel_id,
                    "duration": dur,
                    "published": pub,
                    "views": views
                })

    return {"channel": channel_meta, "videos": videos}


def search_youtube_fast(query, limit=30):
    """Tìm kiếm YouTube siêu nhanh: trả về cả Kênh và Video."""
    query = query.strip()
    if not query:
        return {"channels": [], "videos": []}

    channels = []
    videos = []
    existing_vid_ids = set()
    existing_chan_ids = set()

    if query.startswith("@") or "youtube.com/@" in query or "youtube.com/channel/" in query:
        direct_chan = resolve_channel(query)
        if direct_chan and direct_chan.get("id"):
            channels.append(direct_chan)
            existing_chan_ids.add(direct_chan["id"])

    try:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={
            "User-Agent": UA_PRESETS["Firefox Desktop (Linux)"],
            "Accept-Language": "vi,en;q=0.9"
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r"ytInitialData\s*=\s*({.+?});</script>", html) or \
            re.search(r"var ytInitialData\s*=\s*({.+?});", html)
        if m:
            data = json.loads(m.group(1))
            contents = (data['contents']['twoColumnSearchResultsRenderer']
                        ['primaryContents']['sectionListRenderer']['contents'])
            for section in contents:
                for item in section.get('itemSectionRenderer', {}).get('contents', []):
                    if 'channelRenderer' in item:
                        cr = item['channelRenderer']
                        cid = cr.get('channelId')
                        if cid and cid not in existing_chan_ids:
                            title = cr.get('title', {}).get('simpleText') or ''.join(
                                r.get('text', '') for r in cr.get('title', {}).get('runs', [])
                            )
                            handle = cr.get('subscriberCountText', {}).get('simpleText', '')
                            if not handle or not handle.startswith('@'):
                                nav_url = cr.get('navigationEndpoint', {}).get(
                                    'browseEndpoint', {}).get('canonicalBaseUrl', '')
                                if nav_url.startswith('/@'):
                                    handle = nav_url[1:]
                            subs = cr.get('videoCountText', {}).get('simpleText') or cr.get(
                                'subscriberCountText', {}).get('simpleText', '')
                            desc = ''.join(r.get('text', '') for r in cr.get('descriptionSnippet', {}).get('runs', []))
                            thumbs = cr.get('thumbnail', {}).get('thumbnails', [])
                            avatar = thumbs[-1]['url'] if thumbs else None
                            if avatar and avatar.startswith('//'):
                                avatar = 'https:' + avatar
                            is_verified = bool(cr.get('ownerBadges'))

                            channels.append({
                                'id': cid,
                                'title': title or 'Kênh YouTube',
                                'name': title or 'Kênh YouTube',
                                'handle': handle,
                                'subscribers': subs,
                                'description': desc,
                                'avatar': avatar,
                                'verified': is_verified,
                                'type': 'channel'
                            })
                            existing_chan_ids.add(cid)

                    elif 'videoRenderer' in item:
                        v = item['videoRenderer']
                        vid_id = v.get('videoId')
                        if vid_id and vid_id not in existing_vid_ids:
                            title = ''.join(r.get('text', '') for r in v.get('title', {}).get('runs', []))
                            dur = v.get('lengthText', {}).get('simpleText', '--:--')
                            owner_runs = v.get('ownerText', {}).get('runs', [])
                            uploader = ''.join(r.get('text', '') for r in owner_runs) or 'YouTube'
                            cid = None
                            if owner_runs and 'navigationEndpoint' in owner_runs[0]:
                                cid = owner_runs[0]['navigationEndpoint'].get('browseEndpoint', {}).get('browseId')
                            if not cid:
                                cid = v.get('channelThumbnailSupportedRenderers', {}).get(
                                    'channelThumbnailWithLinkRenderer', {}).get(
                                    'navigationEndpoint', {}).get('browseEndpoint', {}).get('browseId')
                            pub = v.get('publishedTimeText', {}).get('simpleText', '')
                            views = v.get('viewCountText', {}).get('simpleText', '')

                            videos.append({
                                'id': vid_id,
                                'title': title,
                                'uploader': uploader,
                                'channel': uploader,
                                'channel_id': cid,
                                'duration': dur,
                                'published': pub,
                                'views': views,
                                'type': 'video'
                            })
                            existing_vid_ids.add(vid_id)
    except Exception:
        pass

    # yt-dlp fallback nếu thiếu video
    if len(videos) < limit:
        env = os.environ.copy()
        env["PATH"] = f"/home/a/.local/bin:{env.get('PATH', '')}"
        cmd = [
            "yt-dlp",
            "--extractor-args", "youtube:player_client=tv_embedded",
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s\t%(uploader)s\t%(duration_string)s\t%(channel_id)s",
            f"ytsearch{limit}:{query}"
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, timeout=25, env=env)
            for line in proc.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    vid_id = parts[0].strip()
                    if vid_id in existing_vid_ids:
                        continue
                    title = parts[1].replace("\n", " ").strip()
                    uploader = parts[2].replace("\n", " ").strip() if len(parts) > 2 else "YouTube"
                    duration = parts[3].strip() if len(parts) > 3 else "--:--"
                    cid = parts[4].strip() if len(parts) > 4 else None
                    videos.append({
                        "id": vid_id,
                        "title": title,
                        "uploader": uploader,
                        "channel": uploader,
                        "channel_id": cid,
                        "duration": duration,
                        "type": "video"
                    })
                    existing_vid_ids.add(vid_id)
        except Exception:
            pass

    return {"channels": channels, "videos": videos[:limit]}


def fetch_explore_videos(category="trending", limit=30):
    """Lấy danh sách video theo các danh mục khám phá (Thịnh hành, Âm nhạc, Trò chơi, Tin tức)."""
    category_queries = {
        "trending": "thịnh hành youtube việt nam",
        "music": "top bài hát việt nam mới nhất",
        "gaming": "game hot thịnh hành việt nam",
        "news": "tin tức giải trí mới nhất",
    }
    q = category_queries.get(category, "thịnh hành youtube việt nam")
    res = search_youtube_fast(q, limit=limit)
    return res.get("videos", [])


# ==============================================================================
# HỘP THOẠI & WIDGET GIAO DIỆN
# ==============================================================================

class QualityDialog(Gtk.Dialog):
    RESPONSE_DOWNLOAD = 1001

    def __init__(self, parent, video_title, current_quality="720"):
        super().__init__(title="Tùy chọn Phát & Tải về", transient_for=parent, modal=True)
        self.set_default_size(420, -1)

        btn_cancel = create_icon_button("window-close-symbolic", "Huỷ")
        btn_dl = create_icon_button("folder-download-symbolic", "Tải về")
        btn_play = create_icon_button("media-playback-start-symbolic", "Phát ngay", css_class="suggested-action")

        btn_play.set_can_default(True)
        self.add_action_widget(btn_cancel, Gtk.ResponseType.CANCEL)
        self.add_action_widget(btn_dl, self.RESPONSE_DOWNLOAD)
        self.add_action_widget(btn_play, Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(14)
        box.set_margin_bottom(14)

        title_lbl = Gtk.Label()
        title_lbl.set_markup(f"<b>{GLib.markup_escape_text(video_title[:70])}</b>")
        title_lbl.set_line_wrap(True)
        title_lbl.set_xalign(0)
        box.pack_start(title_lbl, False, False, 0)

        lbl = Gtk.Label(label="Chọn chất lượng video hoặc âm thanh:")
        lbl.set_xalign(0)
        box.pack_start(lbl, False, False, 0)

        self.combo = Gtk.ComboBoxText()
        for k, v in QUALITY_OPTIONS:
            self.combo.append(k, v)
        self.combo.set_active_id(current_quality)
        if self.combo.get_active_id() is None:
            self.combo.set_active(0)
        box.pack_start(self.combo, False, False, 0)

        info_lbl = Gtk.Label()
        info_lbl.set_markup(
            "<small><span foreground='#888888'>"
            "• Nhấn <b>Phát ngay</b> để xem mượt qua VLC.\n"
            "• Nhấn <b>Tải về</b> để lưu tệp MP4/MP3 vào máy.</span></small>"
        )
        info_lbl.set_xalign(0)
        box.pack_start(info_lbl, False, False, 0)

        self.show_all()

    def get_selected_quality(self):
        return self.combo.get_active_id() or "720"


class ProfileManagerDialog(Gtk.Dialog):
    """Hộp thoại quản lý phiên người dùng và chế độ Ẩn danh."""
    def __init__(self, parent, on_profile_changed_cb):
        super().__init__(title="Quản lý Người dùng & Phiên xem", transient_for=parent, modal=True)
        self.set_default_size(440, 380)
        self.on_profile_changed_cb = on_profile_changed_cb

        self.add_button("Đóng", Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_spacing(12)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(14)
        content.set_margin_bottom(14)

        lbl = Gtk.Label()
        lbl.set_markup("<b>Chọn hồ sơ người dùng hiện tại:</b>")
        lbl.set_xalign(0)
        content.pack_start(lbl, False, False, 0)

        # Danh sách hồ sơ
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(140)
        self.listbox = Gtk.ListBox()
        scroll.add(self.listbox)
        content.pack_start(scroll, True, True, 0)

        # Thêm người dùng mới
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.entry_name = Gtk.Entry()
        self.entry_name.set_placeholder_text("Nhập tên người dùng mới...")
        add_box.pack_start(self.entry_name, True, True, 0)

        btn_add = create_icon_button("list-add-symbolic", "Tạo", css_class="suggested-action")
        btn_add.connect("clicked", self._do_add_profile)
        add_box.pack_start(btn_add, False, False, 0)
        content.pack_start(add_box, False, False, 0)

        self._refresh_list()
        self.show_all()

    def _refresh_list(self):
        for c in self.listbox.get_children():
            self.listbox.remove(c)

        pdata = load_profiles_data()
        active = pdata.get("active", "Mặc định")

        for p in pdata.get("profiles", []):
            name = p.get("name")
            is_inc = p.get("is_incognito", False)
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            hbox.set_margin_start(8)
            hbox.set_margin_end(8)
            hbox.set_margin_top(6)
            hbox.set_margin_bottom(6)

            ic_name = "user-available-symbolic" if not is_inc else "avatar-default-symbolic"
            img = Gtk.Image.new_from_icon_name(ic_name, Gtk.IconSize.BUTTON)
            hbox.pack_start(img, False, False, 0)

            lbl_txt = f"<b>{GLib.markup_escape_text(name)}</b>"
            if is_inc:
                lbl_txt += " <span foreground='#f57c00'>(Ẩn danh – Không lưu lịch sử)</span>"
            if name == active:
                lbl_txt += " <span foreground='#3ea6ff'>[Đang dùng]</span>"

            lbl = Gtk.Label()
            lbl.set_markup(lbl_txt)
            lbl.set_xalign(0)
            hbox.pack_start(lbl, True, True, 0)

            if name != active:
                btn_sel = create_icon_button("object-select-symbolic", "Chọn")
                btn_sel.connect("clicked", lambda b, n=name: self._switch_to(n))
                hbox.pack_end(btn_sel, False, False, 0)

            if name not in ["Mặc định", "Ẩn danh"]:
                btn_del = create_icon_button("user-trash-symbolic", None, tooltip="Xóa người dùng")
                btn_del.connect("clicked", lambda b, n=name: self._delete(n))
                hbox.pack_end(btn_del, False, False, 0)

            row.add(hbox)
            self.listbox.add(row)

        self.listbox.show_all()

    def _switch_to(self, name):
        set_active_profile(name)
        self._refresh_list()
        if self.on_profile_changed_cb:
            self.on_profile_changed_cb()

    def _delete(self, name):
        delete_profile(name)
        self._refresh_list()
        if self.on_profile_changed_cb:
            self.on_profile_changed_cb()

    def _do_add_profile(self, widget):
        txt = self.entry_name.get_text().strip()
        if txt:
            if create_profile(txt):
                self.entry_name.set_text("")
                self._switch_to(txt)


class ChannelRow(Gtk.ListBoxRow):
    def __init__(self, channel, on_view_channel_callback, on_toggle_sub_callback, is_subscribed=False):
        super().__init__()
        self.channel = channel
        self.on_view_channel_callback = on_view_channel_callback
        self.on_toggle_sub_callback = on_toggle_sub_callback
        self.is_subscribed = is_subscribed

        outer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        outer_box.get_style_context().add_class("channel-card")
        outer_box.set_margin_start(8)
        outer_box.set_margin_end(8)
        outer_box.set_margin_top(6)
        outer_box.set_margin_bottom(6)

        self.avatar_img = Gtk.Image.new_from_pixbuf(get_placeholder_pixbuf(64, 64))
        self.avatar_img.set_size_request(64, 64)
        outer_box.pack_start(self.avatar_img, False, False, 0)
        if channel.get("avatar"):
            request_image_async(channel["avatar"], self._update_avatar, 64, 64, is_avatar=True)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_valign(Gtk.Align.CENTER)

        cname = channel.get("title") or channel.get("name") or "Kênh YouTube"
        title_lbl = Gtk.Label()
        badge = " <span foreground='#3ea6ff'>✔</span>" if channel.get("verified") else ""
        title_lbl.set_markup(f"<b><big>{GLib.markup_escape_text(cname)}</big></b>{badge}")
        title_lbl.set_xalign(0)
        vbox.pack_start(title_lbl, False, False, 0)

        meta_parts = []
        if channel.get("handle"):
            meta_parts.append(channel["handle"])
        if channel.get("subscribers"):
            meta_parts.append(channel["subscribers"])
        if channel.get("video_count"):
            meta_parts.append(channel["video_count"])

        if meta_parts:
            meta_lbl = Gtk.Label()
            meta_lbl.set_markup(f"<span foreground='#aaaaaa'>{' • '.join(meta_parts)}</span>")
            meta_lbl.set_xalign(0)
            vbox.pack_start(meta_lbl, False, False, 0)

        desc = channel.get("description", "").strip()
        if desc:
            desc_lbl = Gtk.Label()
            short_desc = desc[:130] + ("..." if len(desc) > 130 else "")
            desc_lbl.set_markup(f"<span foreground='#888888'>{GLib.markup_escape_text(short_desc)}</span>")
            desc_lbl.set_line_wrap(True)
            desc_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            desc_lbl.set_max_width_chars(65)
            desc_lbl.set_xalign(0)
            vbox.pack_start(desc_lbl, False, False, 0)

        outer_box.pack_start(vbox, True, True, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_valign(Gtk.Align.CENTER)

        btn_view = create_icon_button("video-display-symbolic", "Xem video", css_class="suggested-action")
        btn_view.set_tooltip_text(f"Xem danh sách video của kênh {cname}")
        btn_view.connect("clicked", lambda b: self.on_view_channel_callback(
            self.channel.get("id"), cname
        ))
        btn_box.pack_start(btn_view, False, False, 0)

        sub_label = "Đã theo dõi" if self.is_subscribed else "Theo dõi"
        sub_icon = "starred-symbolic" if self.is_subscribed else "list-add-symbolic"
        self.btn_sub = create_icon_button(sub_icon, sub_label)
        if self.is_subscribed:
            self.btn_sub.get_style_context().add_class("suggested-action")
        self.btn_sub.connect("clicked", lambda b: self.on_toggle_sub_callback(self.channel, self.btn_sub))
        btn_box.pack_start(self.btn_sub, False, False, 0)

        outer_box.pack_end(btn_box, False, False, 0)
        self.add(outer_box)

    def _update_avatar(self, pixbuf):
        if self.avatar_img and pixbuf:
            self.avatar_img.set_from_pixbuf(pixbuf)


class VideoRow(Gtk.ListBoxRow):
    """Widget thẻ Video: Hỗ trợ thanh màu đỏ tiến trình xem, mờ thumbnail khi xem hết, và Native GTK Icons."""
    def __init__(self, video, on_play_callback, on_channel_click=None, on_download_callback=None):
        super().__init__()
        self.video = video
        self.on_play_callback = on_play_callback
        self.on_channel_click = on_channel_click
        self.on_download_callback = on_download_callback

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)

        vid_id = video.get("id")

        # 1. Khung Thumbnail 16:9 với Gtk.Overlay
        self.overlay = Gtk.Overlay()
        self.image = Gtk.Image.new_from_pixbuf(get_placeholder_pixbuf(160, 90))
        self.image.set_size_request(160, 90)
        self.overlay.add(self.image)

        # Kiểm tra tiến trình đã xem
        prog_data = load_progress().get(vid_id, {})
        is_completed = prog_data.get("completed", False)
        watched_sec = prog_data.get("watched", 0)
        total_sec = prog_data.get("total", 0)

        if is_completed:
            # Xem xong: thumbnail hơi mờ mờ blur blur, thanh đỏ sẽ ẩn hết
            self.image.get_style_context().add_class("thumbnail-watched")
            badge_watched = Gtk.Label()
            badge_watched.set_markup("<span size='small' foreground='#ffffff' background='#1a1a1a'> <b>✓ ĐÃ XEM</b> </span>")
            badge_watched.set_halign(Gtk.Align.END)
            badge_watched.set_valign(Gtk.Align.START)
            badge_watched.set_margin_top(4)
            badge_watched.set_margin_end(4)
            self.overlay.add_overlay(badge_watched)
        elif watched_sec > 0 and total_sec > 0:
            # Đang xem dở: Hiện thanh màu đỏ tiến trình bên dưới thumbnail
            fraction = min(1.0, max(0.0, watched_sec / total_sec))
            pbar = Gtk.ProgressBar()
            pbar.set_fraction(fraction)
            pbar.get_style_context().add_class("video-progress-bar")
            pbar.set_halign(Gtk.Align.FILL)
            pbar.set_valign(Gtk.Align.END)
            self.overlay.add_overlay(pbar)

        # Huy hiệu thời lượng góc dưới thumbnail
        dur_text = video.get('duration') or '--:--'
        if dur_text and dur_text != '--:--' and not is_completed:
            dur_badge = Gtk.Label()
            dur_badge.set_markup(f"<span size='small' foreground='#ffffff' background='#1a1a1a'> <b>{dur_text}</b> </span>")
            dur_badge.set_halign(Gtk.Align.END)
            dur_badge.set_valign(Gtk.Align.END)
            dur_badge.set_margin_bottom(6)
            dur_badge.set_margin_end(6)
            self.overlay.add_overlay(dur_badge)

        hbox.pack_start(self.overlay, False, False, 0)
        request_thumbnail_async(vid_id, self._update_image, width=160, height=90)

        # 2. Thông tin Video
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        vbox.set_valign(Gtk.Align.CENTER)

        # DeArrow Title check
        display_title = video.get('title', 'Video')
        settings = load_settings()
        if settings.get("dearrow", True) and vid_id:
            d_info = fetch_dearrow_info(vid_id)
            if d_info and d_info.get("title"):
                display_title = d_info["title"]

        title_lbl = Gtk.Label()
        title_lbl.set_markup(f"<b>{GLib.markup_escape_text(display_title)}</b>")
        title_lbl.set_line_wrap(True)
        title_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title_lbl.set_max_width_chars(60)
        title_lbl.set_xalign(0)
        vbox.pack_start(title_lbl, False, False, 0)

        # Hàng thông tin chi tiết (không dùng Unicode emoji để tránh lỗi Tofu)
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        channel_name = video.get('channel') or video.get('uploader') or 'YouTube'

        if on_channel_click:
            chan_btn = Gtk.Button()
            chan_btn.set_relief(Gtk.ReliefStyle.NONE)
            chan_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            chan_icon = Gtk.Image.new_from_icon_name("avatar-default-symbolic", Gtk.IconSize.MENU)
            chan_box.pack_start(chan_icon, False, False, 0)
            chan_lbl = Gtk.Label()
            chan_lbl.set_markup(f"<span foreground='#5e9cf6'><u>{GLib.markup_escape_text(channel_name)}</u></span>")
            chan_box.pack_start(chan_lbl, False, False, 0)
            chan_btn.add(chan_box)
            chan_btn.set_tooltip_text(f"Xem các video trong kênh {channel_name}")
            chan_btn.connect("clicked", lambda b: self._handle_channel_click(channel_name, video.get("channel_id")))
            chan_btn.get_style_context().add_class("flat")
            info_box.pack_start(chan_btn, False, False, 0)
        else:
            chan_lbl = Gtk.Label(label=channel_name)
            chan_lbl.set_xalign(0)
            info_box.pack_start(chan_lbl, False, False, 0)

        # Metadata parts
        meta_items = []
        if video.get("views"):
            meta_items.append(video['views'])
        if video.get("published"):
            meta_items.append(video['published'])
        if "watched_at" in video:
            meta_items.append(f"Xem: {video['watched_at']}")

        if meta_items:
            m_lbl = Gtk.Label()
            m_lbl.set_markup(f"<span foreground='#aaaaaa'>• {' • '.join(meta_items)}</span>")
            m_lbl.set_xalign(0)
            info_box.pack_start(m_lbl, False, False, 0)

        vbox.pack_start(info_box, False, False, 0)
        hbox.pack_start(vbox, True, True, 0)

        # 3. Nút Thao tác (Phát & Tải về)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_valign(Gtk.Align.CENTER)

        if self.on_download_callback:
            dl_btn = create_icon_button("folder-download-symbolic", None, tooltip="Tải video hoặc audio về máy")
            dl_btn.connect("clicked", lambda b: self.on_download_callback(self.video))
            btn_box.pack_start(dl_btn, False, False, 0)

        play_btn = create_icon_button("media-playback-start-symbolic", "Phát", css_class="suggested-action")
        play_btn.connect("clicked", lambda b: self.on_play_callback(self.video))
        btn_box.pack_start(play_btn, False, False, 0)

        hbox.pack_end(btn_box, False, False, 0)
        self.add(hbox)

    def _handle_channel_click(self, channel_name, channel_id):
        if not self.on_channel_click:
            return
        if channel_id:
            self.on_channel_click(channel_id, channel_name)
        else:
            def _res():
                info = resolve_channel(channel_name)
                if info and info.get("id"):
                    GLib.idle_add(self.on_channel_click, info["id"], info.get("name", channel_name))
            threading.Thread(target=_res, daemon=True).start()

    def _update_image(self, pixbuf):
        if self.image and pixbuf:
            self.image.set_from_pixbuf(pixbuf)


# ==============================================================================
# CỬA SỔ XEM VIDEO TRONG KÊNH (CHANNEL VIDEOS DIALOG)
# ==============================================================================

class ChannelVideosDialog(Gtk.Dialog):
    def __init__(self, parent, channel_id, channel_name, settings, play_callback, on_subs_changed=None, download_callback=None):
        super().__init__(
            title=f"Kênh: {channel_name}",
            transient_for=parent,
            modal=True
        )
        self.set_default_size(960, 680)
        self.channel_id = channel_id
        self.channel_name = channel_name
        self.settings = settings
        self.play_callback = play_callback
        self.on_subs_changed = on_subs_changed
        self.download_callback = download_callback
        self.all_videos = []
        self.channel_meta = {}
        self.is_loading = False

        self.add_button("Đóng", Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_spacing(0)

        # 1. Header Banner thông tin Kênh
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        header_box.get_style_context().add_class("channel-card")
        header_box.set_margin_start(12)
        header_box.set_margin_end(12)
        header_box.set_margin_top(10)
        header_box.set_margin_bottom(6)

        self.chan_avatar = Gtk.Image.new_from_pixbuf(get_placeholder_pixbuf(64, 64))
        self.chan_avatar.set_size_request(64, 64)
        header_box.pack_start(self.chan_avatar, False, False, 0)

        info_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_vbox.set_valign(Gtk.Align.CENTER)

        self.chan_title_lbl = Gtk.Label()
        self.chan_title_lbl.set_markup(f"<b><big>{GLib.markup_escape_text(channel_name)}</big></b>")
        self.chan_title_lbl.set_xalign(0)
        info_vbox.pack_start(self.chan_title_lbl, False, False, 0)

        self.chan_meta_lbl = Gtk.Label()
        self.chan_meta_lbl.set_markup(f"<span foreground='#aaaaaa'>ID: {GLib.markup_escape_text(channel_id)}</span>")
        self.chan_meta_lbl.set_xalign(0)
        info_vbox.pack_start(self.chan_meta_lbl, False, False, 0)

        header_box.pack_start(info_vbox, True, True, 0)

        subs = load_subs()
        is_sub = any(s.get("id") == self.channel_id for s in subs)
        self.btn_chan_sub = create_icon_button(
            "starred-symbolic" if is_sub else "list-add-symbolic",
            "Đã theo dõi" if is_sub else "Theo dõi"
        )
        self.btn_chan_sub.set_valign(Gtk.Align.CENTER)
        if is_sub:
            self.btn_chan_sub.get_style_context().add_class("suggested-action")
        self.btn_chan_sub.connect("clicked", self._toggle_sub)
        header_box.pack_end(self.btn_chan_sub, False, False, 0)

        content.pack_start(header_box, False, False, 0)

        # 2. Thanh điều khiển Toolbar
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)

        self.filter_entry = Gtk.SearchEntry()
        self.filter_entry.set_placeholder_text("Lọc video trong kênh theo tiêu đề...")
        self.filter_entry.connect("search-changed", lambda e: self._redraw())
        toolbar.pack_start(self.filter_entry, True, True, 0)

        btn_refresh = create_icon_button("view-refresh-symbolic", "Tải lại", tooltip="Tải lại danh sách video từ kênh")
        btn_refresh.connect("clicked", lambda b: self._reload())
        toolbar.pack_start(btn_refresh, False, False, 0)

        self.chan_spinner = Gtk.Spinner()
        toolbar.pack_start(self.chan_spinner, False, False, 0)

        sort_lbl = Gtk.Label(label="Sắp xếp:")
        toolbar.pack_end(sort_lbl, False, False, 0)
        self.sort_combo = Gtk.ComboBoxText()
        for label in SORT_MODES:
            self.sort_combo.append_text(label)
        self.sort_combo.set_active(0)
        self.sort_combo.connect("changed", lambda c: self._redraw())
        toolbar.pack_end(self.sort_combo, False, False, 0)

        content.pack_start(toolbar, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        content.pack_start(sep, False, False, 0)

        # 3. Danh sách video & Infinite scroll
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.video_list = Gtk.ListBox()
        self.video_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.scroll.add(self.video_list)
        content.pack_start(self.scroll, True, True, 0)

        # Tự động cuộn nạp thêm video khi tới đáy trang
        vadjust = self.scroll.get_vadjustment()
        vadjust.connect("value-changed", self._on_scroll_changed)

        # 4. Trạng thái
        self.status_lbl = Gtk.Label(label="Đang tải danh sách video...")
        self.status_lbl.set_xalign(0)
        self.status_lbl.set_margin_start(12)
        self.status_lbl.set_margin_bottom(6)
        content.pack_start(self.status_lbl, False, False, 0)

        content.show_all()
        self._reload()

    def _on_scroll_changed(self, adj):
        if not self.settings.get("auto_load_more", True):
            return
        upper = adj.get_upper()
        page = adj.get_page_size()
        val = adj.get_value()
        if upper > page and val + page >= upper - 140:
            if not self.is_loading and len(self.all_videos) < 60:
                self._load_more_ytdlp()

    def _reload(self):
        self.is_loading = True
        self.chan_spinner.start()
        self.status_lbl.set_text("Đang kết nối và tải video từ kênh...")
        threading.Thread(target=self._load_videos_worker, daemon=True).start()

    def _load_videos_worker(self):
        try:
            # 1. Thử tải nhanh từ Web YouTube (đầy đủ metadata & 30 video)
            web_res = fetch_channel_videos_web(self.channel_id)
            if web_res and web_res.get("videos"):
                GLib.idle_add(self._apply_channel_meta, web_res.get("channel", {}))
                GLib.idle_add(self._render_videos, web_res["videos"], f"Web ({len(web_res['videos'])} video)")
                self.is_loading = False
                return
        except Exception:
            pass

        try:
            # 2. Thử nhanh từ RSS XML (<0.5s)
            channel_info = {"id": self.channel_id, "name": self.channel_name}
            rss_videos = fetch_feed_for_channel(channel_info)
            if rss_videos:
                GLib.idle_add(self._render_videos, rss_videos, f"RSS ({len(rss_videos)} video mới nhất)")
                self.is_loading = False
                return
        except Exception:
            pass

        try:
            # 3. Fallback bằng yt-dlp
            ytdlp_videos = fetch_channel_videos_ytdlp(self.channel_id, limit=50)
            if ytdlp_videos:
                GLib.idle_add(self._render_videos, ytdlp_videos, f"yt-dlp ({len(ytdlp_videos)} video)")
                self.is_loading = False
                return
        except Exception:
            pass

        self.is_loading = False
        GLib.idle_add(self._render_videos, [], "Không tìm thấy video")

    def _load_more_ytdlp(self):
        self.is_loading = True
        self.chan_spinner.start()
        self.status_lbl.set_text("Đang tự động tải thêm video...")

        def _worker():
            more = fetch_channel_videos_ytdlp(self.channel_id, limit=100)
            GLib.idle_add(self._append_videos, more)

        threading.Thread(target=_worker, daemon=True).start()

    def _append_videos(self, more_vids):
        self.is_loading = False
        self.chan_spinner.stop()
        existing = {v['id'] for v in self.all_videos}
        added = 0
        for v in more_vids:
            if v['id'] not in existing:
                self.all_videos.append(v)
                existing.add(v['id'])
                added += 1
        self._redraw()
        self.status_lbl.set_text(f"Đã tải thêm {added} video. Tổng cộng: {len(self.all_videos)} video.")

    def _apply_channel_meta(self, meta):
        if not meta:
            return
        self.channel_meta = meta
        cname = meta.get("title") or self.channel_name
        self.channel_name = cname
        badge = " <span foreground='#3ea6ff'>✔</span>" if meta.get("verified") else ""
        self.chan_title_lbl.set_markup(f"<b><big>{GLib.markup_escape_text(cname)}</big></b>{badge}")

        parts = []
        if meta.get("handle"):
            parts.append(meta["handle"])
        if meta.get("subscribers"):
            parts.append(meta["subscribers"])
        if meta.get("video_count"):
            parts.append(meta["video_count"])
        if parts:
            self.chan_meta_lbl.set_markup(f"<span foreground='#aaaaaa'>{' • '.join(parts)}</span>")

        if meta.get("avatar"):
            request_image_async(meta["avatar"], self._update_avatar, 64, 64, is_avatar=True)

    def _update_avatar(self, pb):
        if self.chan_avatar and pb:
            self.chan_avatar.set_from_pixbuf(pb)

    def _toggle_sub(self, widget):
        subs = load_subs()
        existing = [s for s in subs if s.get("id") == self.channel_id]
        if existing:
            subs = [s for s in subs if s.get("id") != self.channel_id]
            save_subs(subs)
            self.btn_chan_sub.set_label("Theo dõi")
            self.btn_chan_sub.get_style_context().remove_class("suggested-action")
            self.status_lbl.set_text(f"Đã hủy theo dõi kênh: {self.channel_name}")
        else:
            subs.append({
                "id": self.channel_id,
                "name": self.channel_name,
                "handle": self.channel_meta.get("handle", ""),
                "avatar": self.channel_meta.get("avatar", "")
            })
            save_subs(subs)
            self.btn_chan_sub.set_label("Đã theo dõi")
            self.btn_chan_sub.get_style_context().add_class("suggested-action")
            self.status_lbl.set_text(f"Đã theo dõi kênh: {self.channel_name}")
        if self.on_subs_changed:
            self.on_subs_changed()

    def _render_videos(self, videos, source_label):
        self.chan_spinner.stop()
        self.all_videos = list(videos)
        if not videos:
            self.status_lbl.set_text("Kênh chưa có video nào hoặc không tải được.")
            self._redraw()
            return
        self.status_lbl.set_text(f"{len(videos)} video – nguồn: {source_label}")
        self._redraw()

    def _redraw(self):
        for child in self.video_list.get_children():
            self.video_list.remove(child)

        kw = self.filter_entry.get_text().strip().lower()
        if kw:
            videos = [v for v in self.all_videos if kw in v.get("title", "").lower()]
        else:
            videos = list(self.all_videos)

        mode_label = self.sort_combo.get_active_text() or "Mới nhất"
        mode = SORT_MODES.get(mode_label, "newest")
        sorted_v = sort_videos(videos, mode)

        if not sorted_v:
            lbl = Gtk.Label(label="Không có video nào khớp với bộ lọc." if kw else "Chưa có video nào.")
            lbl.set_margin_top(20)
            self.video_list.add(lbl)
        else:
            for v in sorted_v:
                row = VideoRow(v, self.play_callback, on_download_callback=self.download_callback)
                self.video_list.add(row)

        self.video_list.show_all()


# ==============================================================================
# CỬA SỔ CHÍNH (MAIN WINDOW)
# ==============================================================================

class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="YouTube VLC Player")
        self.set_default_size(1100, 740)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.settings = load_settings()
        if self.settings.get("dark_mode", True):
            Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)

        self._setup_icon()
        self._setup_css()

        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(main_vbox)

        # 1. HeaderBar với Quản lý Hồ sơ & Trạng thái Ẩn danh
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = "YouTube VLC Player"
        header.props.subtitle = "Phát video nhẹ qua VLC Media Player"

        if self.app_icon_pixbuf is not None:
            try:
                icon_img = Gtk.Image.new_from_pixbuf(self.app_icon_pixbuf)
                icon_img.set_margin_start(6)
                header.pack_start(icon_img)
            except Exception:
                pass

        # Nút chuyển đổi / quản lý hồ sơ người dùng
        self.btn_profile = Gtk.Button()
        self.btn_profile.connect("clicked", lambda b: self.open_profile_dialog())
        header.pack_end(self.btn_profile)
        self._update_profile_button_label()

        self.set_titlebar(header)

        # 2. Notebook chứa các Tab
        self.notebook = Gtk.Notebook()
        main_vbox.pack_start(self.notebook, True, True, 0)

        # Trạng thái dữ liệu
        self.current_search_query = ""
        self.current_search_channels = []
        self.current_search_results = []
        self.is_search_loading_more = False

        self.current_explore_category = "trending"
        self.current_explore_videos = []
        self.is_explore_loading_more = False

        self.current_feed_videos = []
        self.feed_sort_mode = "newest"

        # Khởi tạo các Tab
        self._init_search_tab()
        self._init_explore_tab()
        self._init_feed_tab()
        self._init_history_tab()
        self._init_subs_manager_tab()
        self._init_settings_tab()

        # 3. Thanh trạng thái StatusBar
        self.status_bar = Gtk.Statusbar()
        self.status_context = self.status_bar.get_context_id("status")
        main_vbox.pack_end(self.status_bar, False, False, 0)
        self.set_status("Sẵn sàng")

        GLib.timeout_add(500, self.refresh_feed)

    def _setup_icon(self):
        self.app_icon_pixbuf = None
        icon_candidates = [
            os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/yt-vlc.png"),
            os.path.expanduser("~/.local/share/pixmaps/yt-vlc.png"),
            os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps/yt-vlc.svg"),
            os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets", "yt-vlc.png"),
            os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets", "yt-vlc.svg"),
        ]
        for ic in icon_candidates:
            if os.path.exists(ic):
                try:
                    self.set_icon_from_file(ic)
                    self.app_icon_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(ic, 24, 24, True)
                    break
                except Exception:
                    continue

    def _setup_css(self):
        css_provider = Gtk.CssProvider()
        css = b"""
        list row {
            padding: 4px;
            border-bottom: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 6px;
            margin: 2px 6px;
        }
        list row:hover {
            background-color: rgba(255, 255, 255, 0.08);
        }
        .suggested-action {
            padding: 6px 14px;
            font-weight: bold;
        }
        .flat {
            border: none;
            background: none;
            padding: 0px 4px;
        }
        .channel-card {
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
            padding: 8px 12px;
            margin: 4px 6px;
        }
        .section-header {
            padding: 8px 12px;
            color: #3ea6ff;
        }
        .thumbnail-watched {
            opacity: 0.35;
        }
        .video-progress-bar progress {
            background-color: #ff0000;
            min-height: 4px;
            border-radius: 0px;
        }
        .video-progress-bar trough {
            background-color: rgba(255, 255, 255, 0.3);
            min-height: 4px;
            border-radius: 0px;
        }
        """
        css_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def set_status(self, text):
        self.status_bar.pop(self.status_context)
        self.status_bar.push(self.status_context, text)

    def _update_profile_button_label(self):
        pname, is_inc = get_active_profile()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        ic_name = "avatar-default-symbolic" if is_inc else "user-available-symbolic"
        img = Gtk.Image.new_from_icon_name(ic_name, Gtk.IconSize.BUTTON)
        lbl = Gtk.Label(label=f"{pname} (Ẩn danh)" if is_inc else pname)
        box.pack_start(img, False, False, 0)
        box.pack_start(lbl, False, False, 0)
        for c in self.btn_profile.get_children():
            self.btn_profile.remove(c)
        self.btn_profile.add(box)
        self.btn_profile.show_all()

    def open_profile_dialog(self):
        dlg = ProfileManagerDialog(self, on_profile_changed_cb=self.reload_all_profile_data)
        dlg.run()
        dlg.destroy()

    def reload_all_profile_data(self):
        self._update_profile_button_label()
        self.reload_subs_list()
        self.reload_history()
        self.refresh_feed()
        self.set_status("Đã chuyển đổi người dùng thành công.")

    def play_video_action(self, video):
        """Phát video – hỏi chất lượng trước nếu bật tùy chọn ask_quality."""
        if self.settings.get("ask_quality", True):
            dlg = QualityDialog(self, video.get("title", "Video"),
                                current_quality=self.settings.get("quality", "720"))
            response = dlg.run()
            quality = dlg.get_selected_quality()
            dlg.destroy()

            if response == QualityDialog.RESPONSE_DOWNLOAD:
                is_audio = (quality == "audio")
                self.download_video_action(video, quality=quality, is_audio=is_audio)
                return
            elif response != Gtk.ResponseType.OK:
                return
        else:
            quality = self.settings.get("quality", "720")

        launch_vlc(
            video, self.settings, quality_override=quality,
            status_callback=self.set_status,
            on_playback_done=lambda vid: self._on_playback_completed(vid)
        )
        GLib.idle_add(self.reload_history)

    def _on_playback_completed(self, vid_id):
        self.reload_history()
        # Redraw visible lists to immediately show updated watch progress
        self._redraw_search_list()
        self._redraw_feed_list()
        self._redraw_explore_list()

    def download_video_action(self, video, quality="720", is_audio=False):
        """Kích hoạt tải video hoặc audio."""
        download_media(video, quality=quality, is_audio=is_audio,
                       download_dir=self.settings.get("download_dir"),
                       status_callback=self.set_status)

    def open_channel_videos(self, channel_id, channel_name):
        """Mở cửa sổ xem video trong kênh."""
        dlg = ChannelVideosDialog(
            self, channel_id, channel_name,
            self.settings, self.play_video_action,
            on_subs_changed=self.reload_subs_list,
            download_callback=lambda v: self.download_video_action(v, self.settings.get("quality", "720"))
        )
        dlg.run()
        dlg.destroy()

    def toggle_channel_sub(self, channel, btn):
        """Đăng ký hoặc hủy theo dõi kênh từ thẻ kênh."""
        subs = load_subs()
        chan_id = channel.get("id")
        chan_name = channel.get("title") or channel.get("name") or chan_id
        existing = [s for s in subs if s.get("id") == chan_id]
        if existing:
            subs = [s for s in subs if s.get("id") != chan_id]
            save_subs(subs)
            btn.set_label("Theo dõi")
            btn.get_style_context().remove_class("suggested-action")
            self.set_status(f"Đã hủy theo dõi kênh: {chan_name}")
        else:
            subs.append({
                "id": chan_id,
                "name": chan_name,
                "handle": channel.get("handle", ""),
                "avatar": channel.get("avatar", "")
            })
            save_subs(subs)
            btn.set_label("Đã theo dõi")
            btn.get_style_context().add_class("suggested-action")
            self.set_status(f"Đã theo dõi kênh: {chan_name}")
        self.reload_subs_list()

    # ===================== 1. TAB TÌM KIẾM =====================
    def _init_search_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)

        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Nhập từ khóa, @kênh hoặc link YouTube...")
        self.search_entry.connect("activate", lambda e: self.do_search())
        search_box.pack_start(self.search_entry, True, True, 0)

        btn_search = create_icon_button("edit-find-symbolic", "Tìm kiếm", css_class="suggested-action")
        btn_search.connect("clicked", lambda b: self.do_search())
        search_box.pack_start(btn_search, False, False, 0)

        sort_lbl = Gtk.Label(label="Sắp xếp:")
        search_box.pack_start(sort_lbl, False, False, 0)
        self.search_sort_combo = Gtk.ComboBoxText()
        for label in SORT_MODES:
            self.search_sort_combo.append_text(label)
        self.search_sort_combo.set_active(0)
        self.search_sort_combo.connect("changed", lambda c: self._resort_search())
        search_box.pack_start(self.search_sort_combo, False, False, 0)

        self.search_spinner = Gtk.Spinner()
        search_box.pack_start(self.search_spinner, False, False, 0)
        vbox.pack_start(search_box, False, False, 0)

        self.search_scroll = Gtk.ScrolledWindow()
        self.search_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.search_list = Gtk.ListBox()
        self.search_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.search_scroll.add(self.search_list)
        vbox.pack_start(self.search_scroll, True, True, 0)

        # Infinite Scroll cho kết quả tìm kiếm
        adj = self.search_scroll.get_vadjustment()
        adj.connect("value-changed", self._on_search_scroll_changed)

        self.load_more_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.load_more_box.set_halign(Gtk.Align.CENTER)
        self.btn_load_more = create_icon_button("go-down-symbolic", "Tải thêm video")
        self.btn_load_more.connect("clicked", lambda b: self.load_more_search())
        self.load_more_box.pack_start(self.btn_load_more, False, False, 0)
        self.load_more_spinner = Gtk.Spinner()
        self.load_more_box.pack_start(self.load_more_spinner, False, False, 0)
        self.load_more_box.set_no_show_all(True)
        vbox.pack_end(self.load_more_box, False, False, 4)

        self.notebook.append_page(vbox, create_tab_label("edit-find-symbolic", "Tìm kiếm"))

    def _on_search_scroll_changed(self, adj):
        if not self.settings.get("auto_load_more", True):
            return
        upper = adj.get_upper()
        page = adj.get_page_size()
        val = adj.get_value()
        if upper > page and val + page >= upper - 140:
            if not self.is_search_loading_more and self.current_search_results:
                self.load_more_search()

    def do_search(self):
        query = self.search_entry.get_text().strip()
        if not query:
            return

        if "youtube.com/watch" in query or "youtu.be/" in query:
            vid = query.split("v=")[-1].split("&")[0] if "v=" in query else query.split("/")[-1].split("?")[0]
            self.play_video_action({"id": vid, "title": query, "channel": "Direct Link"})
            return

        self.current_search_query = query
        self.current_search_channels = []
        self.current_search_results = []
        self.load_more_box.hide()
        self.search_spinner.start()
        self.set_status(f"Đang tìm kiếm: '{query}'...")

        for child in self.search_list.get_children():
            self.search_list.remove(child)

        limit = self.settings.get("max_results", 30)

        def _search_thread():
            results = search_youtube_fast(query, limit=limit)
            GLib.idle_add(self._render_search_results, results)

        threading.Thread(target=_search_thread, daemon=True).start()

    def _render_search_results(self, search_data):
        self.search_spinner.stop()
        if isinstance(search_data, dict):
            self.current_search_channels = search_data.get("channels", [])
            self.current_search_results = search_data.get("videos", [])
        else:
            self.current_search_channels = []
            self.current_search_results = list(search_data)

        if not self.current_search_channels and not self.current_search_results:
            self.set_status("Không tìm thấy kết quả nào.")
            lbl = Gtk.Label(label="Không tìm thấy kênh hoặc video nào khớp với từ khóa.")
            lbl.set_margin_top(30)
            self.search_list.add(lbl)
            self.search_list.show_all()
            self.load_more_box.hide()
            return

        self._redraw_search_list()
        if self.current_search_results:
            self.load_more_box.show_all()
        else:
            self.load_more_box.hide()

        status_parts = []
        if self.current_search_channels:
            status_parts.append(f"{len(self.current_search_channels)} kênh")
        if self.current_search_results:
            status_parts.append(f"{len(self.current_search_results)} video")
        self.set_status(f"Đã tìm thấy: {', '.join(status_parts)}.")

    def _redraw_search_list(self):
        for child in self.search_list.get_children():
            self.search_list.remove(child)

        subs = load_subs()
        sub_ids = {s.get("id") for s in subs}

        if self.current_search_channels:
            lbl_chan = Gtk.Label()
            lbl_chan.set_markup("<b>KÊNH PHÙ HỢP:</b>")
            lbl_chan.set_xalign(0)
            lbl_chan.get_style_context().add_class("section-header")
            self.search_list.add(lbl_chan)

            for c in self.current_search_channels:
                is_sub = c.get("id") in sub_ids
                row = ChannelRow(c, self.open_channel_videos, self.toggle_channel_sub, is_sub)
                self.search_list.add(row)

        if self.current_search_results:
            if self.current_search_channels:
                lbl_vid = Gtk.Label()
                lbl_vid.set_markup("<b>VIDEO KẾT QUẢ:</b>")
                lbl_vid.set_xalign(0)
                lbl_vid.get_style_context().add_class("section-header")
                self.search_list.add(lbl_vid)

            mode_label = self.search_sort_combo.get_active_text() or "Mới nhất"
            mode = SORT_MODES.get(mode_label, "newest")
            sorted_results = sort_videos(self.current_search_results, mode)
            for r in sorted_results:
                row = VideoRow(
                    r, self.play_video_action,
                    on_channel_click=self.open_channel_videos,
                    on_download_callback=lambda v: self.download_video_action(v, self.settings.get("quality", "720"))
                )
                self.search_list.add(row)

        self.search_list.show_all()

    def _resort_search(self):
        if self.current_search_results or self.current_search_channels:
            self._redraw_search_list()

    def load_more_search(self):
        if not self.current_search_query or self.is_search_loading_more:
            return
        self.is_search_loading_more = True
        self.load_more_spinner.start()
        self.btn_load_more.set_sensitive(False)
        self.set_status(f"Đang tự động tải thêm kết quả...")

        current_count = len(self.current_search_results)
        fetch_limit = current_count + self.settings.get("max_results", 30)

        def _more_thread():
            results = search_youtube_fast(self.current_search_query, limit=fetch_limit)
            GLib.idle_add(self._append_more_results, results)

        threading.Thread(target=_more_thread, daemon=True).start()

    def _append_more_results(self, new_data):
        self.is_search_loading_more = False
        self.load_more_spinner.stop()
        self.btn_load_more.set_sensitive(True)

        new_videos = new_data.get("videos", []) if isinstance(new_data, dict) else new_data
        existing_ids = {r['id'] for r in self.current_search_results}
        added_count = 0
        for r in new_videos:
            if r['id'] not in existing_ids:
                self.current_search_results.append(r)
                existing_ids.add(r['id'])
                added_count += 1

        self._redraw_search_list()
        if added_count > 0:
            self.set_status(f"Đã tải thêm {added_count} video. Tổng: {len(self.current_search_results)} video.")
        else:
            self.set_status(f"Đã hết video cho từ khóa này. Tổng: {len(self.current_search_results)} video.")

    # ===================== 2. TAB THỊNH HÀNH & KHÁM PHÁ =====================
    def _init_explore_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl = Gtk.Label()
        lbl.set_markup("<b>Khám phá YouTube:</b>")
        top_bar.pack_start(lbl, False, False, 0)

        # Bộ chọn danh mục: Thịnh hành, Âm nhạc, Trò chơi, Tin tức
        self.explore_cat_combo = Gtk.ComboBoxText()
        self.explore_cat_combo.append("trending", "Thịnh hành chung")
        self.explore_cat_combo.append("music", "Âm nhạc (Music)")
        self.explore_cat_combo.append("gaming", "Trò chơi (Gaming)")
        self.explore_cat_combo.append("news", "Tin tức & Giải trí")
        self.explore_cat_combo.set_active_id("trending")
        self.explore_cat_combo.connect("changed", lambda c: self.refresh_explore())
        top_bar.pack_start(self.explore_cat_combo, False, False, 0)

        btn_refresh = create_icon_button("view-refresh-symbolic", "Làm mới")
        btn_refresh.connect("clicked", lambda b: self.refresh_explore())
        top_bar.pack_start(btn_refresh, False, False, 0)

        self.explore_spinner = Gtk.Spinner()
        top_bar.pack_start(self.explore_spinner, False, False, 0)

        vbox.pack_start(top_bar, False, False, 0)

        self.explore_scroll = Gtk.ScrolledWindow()
        self.explore_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.explore_list = Gtk.ListBox()
        self.explore_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.explore_scroll.add(self.explore_list)
        vbox.pack_start(self.explore_scroll, True, True, 0)

        # Infinite Scroll cho tab thịnh hành
        adj = self.explore_scroll.get_vadjustment()
        adj.connect("value-changed", self._on_explore_scroll_changed)

        self.notebook.append_page(vbox, create_tab_label("applications-multimedia-symbolic", "Thịnh hành"))
        GLib.timeout_add(1000, self.refresh_explore)

    def _on_explore_scroll_changed(self, adj):
        if not self.settings.get("auto_load_more", True):
            return
        upper = adj.get_upper()
        page = adj.get_page_size()
        val = adj.get_value()
        if upper > page and val + page >= upper - 140:
            if not self.is_explore_loading_more and len(self.current_explore_videos) < 80:
                self.load_more_explore()

    def refresh_explore(self):
        self.explore_spinner.start()
        cat_id = self.explore_cat_combo.get_active_id() or "trending"
        self.current_explore_category = cat_id
        cat_name = self.explore_cat_combo.get_active_text()
        self.set_status(f"Đang tải nội dung {cat_name}...")

        def _thread():
            vids = fetch_explore_videos(cat_id, limit=self.settings.get("max_results", 30))
            GLib.idle_add(self._render_explore, vids)

        threading.Thread(target=_thread, daemon=True).start()

    def _render_explore(self, videos):
        self.explore_spinner.stop()
        self.current_explore_videos = list(videos)
        self._redraw_explore_list()
        self.set_status(f"Đã cập nhật {len(videos)} video trong mục {self.explore_cat_combo.get_active_text()}.")

    def _redraw_explore_list(self):
        for child in self.explore_list.get_children():
            self.explore_list.remove(child)
        if not self.current_explore_videos:
            lbl = Gtk.Label(label="Chưa có dữ liệu cho danh mục này.")
            lbl.set_margin_top(30)
            self.explore_list.add(lbl)
        else:
            for v in self.current_explore_videos:
                row = VideoRow(
                    v, self.play_video_action,
                    on_channel_click=self.open_channel_videos,
                    on_download_callback=lambda vid: self.download_video_action(vid, self.settings.get("quality", "720"))
                )
                self.explore_list.add(row)
        self.explore_list.show_all()

    def load_more_explore(self):
        if self.is_explore_loading_more:
            return
        self.is_explore_loading_more = True
        self.explore_spinner.start()
        fetch_limit = len(self.current_explore_videos) + self.settings.get("max_results", 30)

        def _thread():
            more = fetch_explore_videos(self.current_explore_category, limit=fetch_limit)
            GLib.idle_add(self._append_more_explore, more)

        threading.Thread(target=_thread, daemon=True).start()

    def _append_more_explore(self, new_vids):
        self.is_explore_loading_more = False
        self.explore_spinner.stop()
        existing = {v['id'] for v in self.current_explore_videos}
        added = 0
        for v in new_vids:
            if v['id'] not in existing:
                self.current_explore_videos.append(v)
                existing.add(v['id'])
                added += 1
        self._redraw_explore_list()
        if added > 0:
            self.set_status(f"Đã tải thêm {added} video khám phá.")

    # ===================== 3. TAB KÊNH ĐĂNG KÝ =====================
    def _init_feed_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl = Gtk.Label()
        lbl.set_markup("<b>Video mới nhất từ các kênh theo dõi:</b>")
        top_bar.pack_start(lbl, False, False, 0)

        self.feed_spinner = Gtk.Spinner()
        top_bar.pack_start(self.feed_spinner, False, False, 0)

        sort_lbl = Gtk.Label(label="Sắp xếp:")
        top_bar.pack_end(sort_lbl, False, False, 0)

        self.feed_sort_combo = Gtk.ComboBoxText()
        for label in SORT_MODES:
            self.feed_sort_combo.append_text(label)
        self.feed_sort_combo.set_active(0)
        self.feed_sort_combo.connect("changed", lambda c: self._resort_feed())
        top_bar.pack_end(self.feed_sort_combo, False, False, 0)

        btn_refresh = create_icon_button("view-refresh-symbolic", "Làm mới")
        btn_refresh.connect("clicked", lambda b: self.refresh_feed())
        top_bar.pack_end(btn_refresh, False, False, 0)

        vbox.pack_start(top_bar, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.feed_list = Gtk.ListBox()
        self.feed_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.feed_list)
        vbox.pack_start(scroll, True, True, 0)

        self.notebook.append_page(vbox, create_tab_label("starred-symbolic", "Kênh đăng ký"))

    def refresh_feed(self):
        self.feed_spinner.start()
        self.set_status("Đang lấy video mới từ các kênh theo dõi...")

        for child in self.feed_list.get_children():
            self.feed_list.remove(child)

        def _feed_thread():
            videos = get_subscriptions_feed()
            GLib.idle_add(self._render_feed, videos)

        threading.Thread(target=_feed_thread, daemon=True).start()

    def _render_feed(self, videos):
        self.feed_spinner.stop()
        self.current_feed_videos = list(videos)
        if not videos:
            self.set_status("Chưa có video mới hoặc chưa đăng ký kênh nào.")
            lbl = Gtk.Label(label="Chưa có video mới. Hãy sang tab 'Quản lý kênh' để thêm kênh!")
            lbl.set_margin_top(30)
            self.feed_list.add(lbl)
            self.feed_list.show_all()
            return
        self._redraw_feed_list()
        self.set_status(f"Đã cập nhật {len(videos)} video từ kênh đăng ký.")

    def _redraw_feed_list(self):
        for child in self.feed_list.get_children():
            self.feed_list.remove(child)
        mode_label = self.feed_sort_combo.get_active_text() or "Mới nhất"
        mode = SORT_MODES.get(mode_label, "newest")
        sorted_videos = sort_videos(self.current_feed_videos, mode)
        for v in sorted_videos[:60]:
            row = VideoRow(
                v, self.play_video_action,
                on_channel_click=self.open_channel_videos,
                on_download_callback=lambda vid: self.download_video_action(vid, self.settings.get("quality", "720"))
            )
            self.feed_list.add(row)
        self.feed_list.show_all()

    def _resort_feed(self):
        if self.current_feed_videos:
            self._redraw_feed_list()

    # ===================== 4. TAB LỊCH SỬ =====================
    def _init_history_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl = Gtk.Label()
        lbl.set_markup("<b>Danh sách video bạn đã xem:</b>")
        top_bar.pack_start(lbl, False, False, 0)

        btn_clear = create_icon_button("user-trash-symbolic", "Xóa lịch sử")
        btn_clear.connect("clicked", lambda b: self.do_clear_history())
        top_bar.pack_end(btn_clear, False, False, 0)

        vbox.pack_start(top_bar, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.history_list)
        vbox.pack_start(scroll, True, True, 0)

        self.notebook.append_page(vbox, create_tab_label("document-open-recent-symbolic", "Lịch sử xem"))
        self.reload_history()

    def reload_history(self):
        for child in self.history_list.get_children():
            self.history_list.remove(child)
        history = load_history()
        if not history:
            lbl = Gtk.Label(label="Lịch sử xem đang trống.")
            lbl.set_margin_top(30)
            self.history_list.add(lbl)
            self.history_list.show_all()
            return
        for h in history:
            row = VideoRow(
                h, self.play_video_action,
                on_channel_click=self.open_channel_videos,
                on_download_callback=lambda vid: self.download_video_action(vid, self.settings.get("quality", "720"))
            )
            self.history_list.add(row)
        self.history_list.show_all()

    def do_clear_history(self):
        save_history([])
        self.reload_history()
        self.set_status("Đã xóa toàn bộ lịch sử xem.")

    # ===================== 5. TAB QUẢN LÝ KÊNH =====================
    def _init_subs_manager_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        vbox.set_margin_top(16)
        vbox.set_margin_bottom(16)

        add_frame = Gtk.Frame(label="Đăng ký thêm kênh mới")
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_box.set_margin_start(10)
        add_box.set_margin_end(10)
        add_box.set_margin_top(10)
        add_box.set_margin_bottom(10)

        self.new_sub_entry = Gtk.Entry()
        self.new_sub_entry.set_placeholder_text("Nhập @handle hoặc link kênh YouTube...")
        self.new_sub_entry.connect("activate", lambda e: self.do_add_channel())
        add_box.pack_start(self.new_sub_entry, True, True, 0)

        btn_add = create_icon_button("list-add-symbolic", "Đăng ký", css_class="suggested-action")
        btn_add.connect("clicked", lambda b: self.do_add_channel())
        add_box.pack_start(btn_add, False, False, 0)

        add_frame.add(add_box)
        vbox.pack_start(add_frame, False, False, 0)

        list_lbl = Gtk.Label()
        list_lbl.set_markup("<b>Các kênh đang theo dõi:</b>")
        list_lbl.set_xalign(0)
        vbox.pack_start(list_lbl, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        self.subs_listbox = Gtk.ListBox()
        self.subs_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.subs_listbox)
        vbox.pack_start(scroll, True, True, 0)

        self.notebook.append_page(vbox, create_tab_label("contact-new-symbolic", "Quản lý kênh"))
        self.reload_subs_list()

    def reload_subs_list(self):
        for child in self.subs_listbox.get_children():
            self.subs_listbox.remove(child)
        subs = load_subs()
        if not subs:
            lbl = Gtk.Label(label="Chưa đăng ký kênh nào.")
            lbl.set_margin_top(20)
            self.subs_listbox.add(lbl)
            self.subs_listbox.show_all()
            return

        for s in subs:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            hbox.set_margin_start(10)
            hbox.set_margin_end(10)
            hbox.set_margin_top(8)
            hbox.set_margin_bottom(8)

            avatar_img = Gtk.Image.new_from_pixbuf(get_placeholder_pixbuf(44, 44))
            avatar_img.set_size_request(44, 44)
            hbox.pack_start(avatar_img, False, False, 0)
            if s.get("avatar"):
                request_image_async(
                    s["avatar"],
                    lambda pb, img=avatar_img: img.set_from_pixbuf(pb) if pb else None,
                    44, 44, is_avatar=True
                )

            chan_info = Gtk.Label()
            c_name = s.get("name") or s.get("title") or "Kênh"
            chan_info.set_markup(
                f"<b>{GLib.markup_escape_text(c_name)}</b> "
                f"<span foreground='#888888'>({s.get('handle', s.get('id'))})</span>"
            )
            chan_info.set_xalign(0)
            hbox.pack_start(chan_info, True, True, 0)

            btn_view = create_icon_button("video-display-symbolic", "Xem video", css_class="suggested-action")
            btn_view.set_tooltip_text(f"Xem danh sách video của kênh {c_name}")
            btn_view.connect("clicked", lambda b, c=s: self.open_channel_videos(c["id"], c.get("name") or c.get("title") or c["id"]))
            hbox.pack_end(btn_view, False, False, 0)

            btn_del = create_icon_button("user-trash-symbolic", "Hủy theo dõi")
            btn_del.set_tooltip_text("Hủy theo dõi kênh này")
            btn_del.connect("clicked", lambda b, c_id=s['id']: self.do_remove_channel(c_id))
            hbox.pack_end(btn_del, False, False, 0)

            row.add(hbox)
            self.subs_listbox.add(row)

        self.subs_listbox.show_all()

    def do_add_channel(self):
        target = self.new_sub_entry.get_text().strip()
        if not target:
            return
        self.set_status("Đang tìm thông tin kênh...")

        def _add_thread():
            info = resolve_channel(target)
            if not info:
                GLib.idle_add(self.set_status, "❌ Không tìm thấy kênh YouTube này!")
                return
            subs = load_subs()
            if any(s["id"] == info["id"] for s in subs):
                GLib.idle_add(self.set_status, f"Kênh '{info['name']}' đã có trong danh sách.")
                return
            subs.append(info)
            save_subs(subs)
            GLib.idle_add(self._after_add_channel, info["name"])

        threading.Thread(target=_add_thread, daemon=True).start()

    def _after_add_channel(self, name):
        self.new_sub_entry.set_text("")
        self.reload_subs_list()
        self.set_status(f"Đã thêm kênh: {name}")
        self.refresh_feed()

    def do_remove_channel(self, chan_id):
        subs = load_subs()
        subs = [s for s in subs if s["id"] != chan_id]
        save_subs(subs)
        self.reload_subs_list()
        self.set_status("Đã hủy theo dõi kênh.")
        self.refresh_feed()

    # ===================== 6. TAB CÀI ĐẶT =====================
    def _init_settings_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)

        grid = Gtk.Grid()
        grid.set_column_spacing(20)
        grid.set_row_spacing(14)
        vbox.pack_start(grid, False, False, 0)

        row_i = 0

        # 1. Chất lượng mặc định
        lbl_q = Gtk.Label(label="Độ phân giải mặc định:", xalign=0)
        self.combo_quality = Gtk.ComboBoxText()
        for k, v in QUALITY_OPTIONS:
            self.combo_quality.append(k, v)
        self.combo_quality.set_active_id(self.settings.get("quality", "720"))
        grid.attach(lbl_q, 0, row_i, 1, 1)
        grid.attach(self.combo_quality, 1, row_i, 1, 1)
        row_i += 1

        # 2. Hỏi chất lượng trước khi phát
        lbl_ask = Gtk.Label(label="Hỏi chất lượng trước khi phát:", xalign=0)
        self.switch_ask_quality = Gtk.Switch()
        self.switch_ask_quality.set_halign(Gtk.Align.START)
        self.switch_ask_quality.set_valign(Gtk.Align.CENTER)
        self.switch_ask_quality.set_active(self.settings.get("ask_quality", True))
        grid.attach(lbl_ask, 0, row_i, 1, 1)
        grid.attach(self.switch_ask_quality, 1, row_i, 1, 1)
        row_i += 1

        # 3. SponsorBlock
        lbl_sb = Gtk.Label(label="SponsorBlock (Tự bỏ qua quảng cáo tài trợ):", xalign=0)
        self.switch_sponsorblock = Gtk.Switch()
        self.switch_sponsorblock.set_halign(Gtk.Align.START)
        self.switch_sponsorblock.set_valign(Gtk.Align.CENTER)
        self.switch_sponsorblock.set_active(self.settings.get("sponsorblock", True))
        grid.attach(lbl_sb, 0, row_i, 1, 1)
        grid.attach(self.switch_sponsorblock, 1, row_i, 1, 1)
        row_i += 1

        # 4. DeArrow
        lbl_da = Gtk.Label(label="DeArrow (Tiêu đề & ảnh bìa sạch, chống câu view):", xalign=0)
        self.switch_dearrow = Gtk.Switch()
        self.switch_dearrow.set_halign(Gtk.Align.START)
        self.switch_dearrow.set_valign(Gtk.Align.CENTER)
        self.switch_dearrow.set_active(self.settings.get("dearrow", True))
        grid.attach(lbl_da, 0, row_i, 1, 1)
        grid.attach(self.switch_dearrow, 1, row_i, 1, 1)
        row_i += 1

        # 5. Tự động cuộn nạp thêm video (Infinite Scrolling)
        lbl_inf = Gtk.Label(label="Tự động nạp thêm video khi cuộn xuống:", xalign=0)
        self.switch_auto_load = Gtk.Switch()
        self.switch_auto_load.set_halign(Gtk.Align.START)
        self.switch_auto_load.set_valign(Gtk.Align.CENTER)
        self.switch_auto_load.set_active(self.settings.get("auto_load_more", True))
        grid.attach(lbl_inf, 0, row_i, 1, 1)
        grid.attach(self.switch_auto_load, 1, row_i, 1, 1)
        row_i += 1

        # 6. Thư mục tải về
        lbl_dl = Gtk.Label(label="Thư mục lưu video & audio tải về:", xalign=0)
        self.entry_dl_dir = Gtk.Entry()
        self.entry_dl_dir.set_text(self.settings.get("download_dir", os.path.expanduser("~/Downloads")))
        grid.attach(lbl_dl, 0, row_i, 1, 1)
        grid.attach(self.entry_dl_dir, 1, row_i, 1, 1)
        row_i += 1

        # 7. Bộ đệm VLC
        lbl_c = Gtk.Label(label="Bộ nhớ đệm VLC (Caching):", xalign=0)
        self.combo_cache = Gtk.ComboBoxText()
        caches = [("1000", "1000 ms (Mạng cáp quang nhanh)"),
                  ("2000", "2000 ms"),
                  ("3000", "3000 ms (Khuyên dùng)"),
                  ("5000", "5000 ms (Mạng không ổn định)")]
        for k, v in caches:
            self.combo_cache.append(k, v)
        self.combo_cache.set_active_id(str(self.settings.get("caching", 3000)))
        grid.attach(lbl_c, 0, row_i, 1, 1)
        grid.attach(self.combo_cache, 1, row_i, 1, 1)
        row_i += 1

        # 8. Player client (yt-dlp extractor)
        lbl_pc = Gtk.Label(label="yt-dlp Player Client:", xalign=0)
        self.combo_player_client = Gtk.ComboBoxText()
        pc_options = [
            ("tv_embedded,android,mweb", "tv_embedded + android + mweb (Khuyên dùng – chống 429)"),
            ("tv_embedded", "tv_embedded (TV – ổn định nhất)"),
            ("android,mweb", "android + mweb"),
            ("ios,android,web", "ios + android + web (Cũ)"),
            ("android", "android"),
        ]
        for k, v in pc_options:
            self.combo_player_client.append(k, v)
        self.combo_player_client.set_active_id(
            self.settings.get("player_client", "tv_embedded,android,mweb"))
        if self.combo_player_client.get_active_id() is None:
            self.combo_player_client.set_active(0)
        grid.attach(lbl_pc, 0, row_i, 1, 1)
        grid.attach(self.combo_player_client, 1, row_i, 1, 1)
        row_i += 1

        # 9. Spoof User-Agent
        lbl_ua = Gtk.Label(label="Spoof User-Agent:", xalign=0)
        self.combo_ua = Gtk.ComboBoxText()
        for ua_name in UA_PRESETS:
            self.combo_ua.append_text(ua_name)
        current_ua = self.settings.get("user_agent", "Android TV (Khuyên dùng)")
        ua_keys = list(UA_PRESETS.keys())
        idx = ua_keys.index(current_ua) if current_ua in ua_keys else 0
        self.combo_ua.set_active(idx)
        grid.attach(lbl_ua, 0, row_i, 1, 1)
        grid.attach(self.combo_ua, 1, row_i, 1, 1)
        row_i += 1

        # 10. Số lượng video tìm kiếm
        lbl_res = Gtk.Label(label="Số video tải mỗi lần tìm kiếm:", xalign=0)
        self.combo_max_res = Gtk.ComboBoxText()
        for k, v in [("20", "20 video"), ("30", "30 video (Khuyên dùng)"),
                     ("50", "50 video"), ("80", "80 video")]:
            self.combo_max_res.append(k, v)
        self.combo_max_res.set_active_id(str(self.settings.get("max_results", 30)))
        grid.attach(lbl_res, 0, row_i, 1, 1)
        grid.attach(self.combo_max_res, 1, row_i, 1, 1)
        row_i += 1

        # 11. Tăng tốc phần cứng
        lbl_hw = Gtk.Label(label="Tăng tốc phần cứng (HW Accel):", xalign=0)
        self.switch_hw = Gtk.Switch()
        self.switch_hw.set_halign(Gtk.Align.START)
        self.switch_hw.set_valign(Gtk.Align.CENTER)
        self.switch_hw.set_active(self.settings.get("hw_accel", True))
        grid.attach(lbl_hw, 0, row_i, 1, 1)
        grid.attach(self.switch_hw, 1, row_i, 1, 1)
        row_i += 1

        # 12. Giao diện tối
        lbl_dark = Gtk.Label(label="Giao diện tối (Dark Mode):", xalign=0)
        self.switch_dark = Gtk.Switch()
        self.switch_dark.set_halign(Gtk.Align.START)
        self.switch_dark.set_valign(Gtk.Align.CENTER)
        self.switch_dark.set_active(self.settings.get("dark_mode", True))
        grid.attach(lbl_dark, 0, row_i, 1, 1)
        grid.attach(self.switch_dark, 1, row_i, 1, 1)
        row_i += 1

        # Nút lưu & Thao tác
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_save = create_icon_button("document-save-symbolic", "Lưu cài đặt", css_class="suggested-action")
        btn_save.connect("clicked", lambda b: self.do_save_settings())
        btn_box.pack_start(btn_save, False, False, 0)

        btn_prof = create_icon_button("user-available-symbolic", "Quản lý Người dùng")
        btn_prof.connect("clicked", lambda b: self.open_profile_dialog())
        btn_box.pack_start(btn_prof, False, False, 0)

        btn_clean_cache = create_icon_button("edit-clear-symbolic", "Dọn cache ảnh")
        btn_clean_cache.connect("clicked", lambda b: self.do_clean_cache())
        btn_box.pack_start(btn_clean_cache, False, False, 0)

        vbox.pack_start(btn_box, False, False, 0)

        about_lbl = Gtk.Label()
        about_lbl.set_markup(
            "<small>Dự án mã nguồn mở phát triển bởi <b>starfish367</b>\n"
            "Phiên bản: 3.0.0 (GTK3 VLC Edition – Tối ưu Armbian S905X)</small>"
        )
        about_lbl.set_line_wrap(True)
        about_lbl.set_xalign(0)
        vbox.pack_end(about_lbl, False, False, 10)

        self.notebook.append_page(vbox, create_tab_label("preferences-system-symbolic", "Cài đặt"))

    def do_save_settings(self):
        self.settings["quality"] = self.combo_quality.get_active_id() or "720"
        self.settings["ask_quality"] = self.switch_ask_quality.get_active()
        self.settings["sponsorblock"] = self.switch_sponsorblock.get_active()
        self.settings["dearrow"] = self.switch_dearrow.get_active()
        self.settings["auto_load_more"] = self.switch_auto_load.get_active()
        self.settings["download_dir"] = self.entry_dl_dir.get_text().strip() or os.path.expanduser("~/Downloads")
        self.settings["caching"] = int(self.combo_cache.get_active_id() or 3000)
        self.settings["player_client"] = self.combo_player_client.get_active_id() or "tv_embedded,android,mweb"
        self.settings["user_agent"] = self.combo_ua.get_active_text() or "Android TV (Khuyên dùng)"
        self.settings["max_results"] = int(self.combo_max_res.get_active_id() or 30)
        self.settings["hw_accel"] = self.switch_hw.get_active()
        self.settings["dark_mode"] = self.switch_dark.get_active()
        save_settings(self.settings)
        Gtk.Settings.get_default().set_property(
            "gtk-application-prefer-dark-theme", self.settings["dark_mode"]
        )
        self.set_status("Đã lưu cài đặt thành công!")

    def do_clean_cache(self):
        count = 0
        for cdir in [THUMB_DIR, AVATAR_DIR]:
            if os.path.exists(cdir):
                for f in os.listdir(cdir):
                    fp = os.path.join(cdir, f)
                    if os.path.isfile(fp):
                        try:
                            os.remove(fp)
                            count += 1
                        except Exception:
                            pass
        self.set_status(f"Đã xóa {count} tệp ảnh trong bộ nhớ đệm cache.")


# ==============================================================================
# ĐIỂM KHỞI CHẠY (ENTRY POINT)
# ==============================================================================

def main():
    ensure_directories()
    args = sys.argv[1:]

    if args and not args[0].startswith("-"):
        target = args[0]
        settings = load_settings()
        vid = target.split("v=")[-1].split("&")[0] if "v=" in target else target.split("/")[-1].split("?")[0]
        launch_vlc({"id": vid, "title": target, "channel": "Direct"}, settings)
        return

    win = MainWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
