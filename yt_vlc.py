#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yt-vlc: YouTube VLC Player (GTK3 Edition) v2.5.0
Phát video YouTube siêu nhẹ trên VLC, hỗ trợ Kênh đăng ký, Lịch sử xem và Cài đặt.
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
SUBS_FILE = os.path.join(CONFIG_DIR, "subscriptions.json")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.json")
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
    "ask_quality": True,   # Hỏi chất lượng trước khi phát
}

# Các lựa chọn chất lượng để hiển thị khi phát
QUALITY_OPTIONS = [
    ("720", "720p HD – H.264 (Khuyên dùng)"),
    ("480", "480p – H.264"),
    ("360", "360p – H.264 (Tiết kiệm băng thông)"),
    ("1080", "1080p Full HD – H.264"),
    ("best", "Tốt nhất có thể"),
]

# --- Sort modes ---
SORT_MODES = {
    "Mới nhất": "newest",
    "Cũ nhất": "oldest",
    "Tên A→Z": "title_asc",
    "Tên Z→A": "title_desc",
}


def ensure_directories():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)
    os.makedirs(AVATAR_DIR, exist_ok=True)
    if not os.path.exists(SUBS_FILE):
        with open(SUBS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)


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


def load_subs():
    ensure_directories()
    try:
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_subs(subs):
    ensure_directories()
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)


def load_history():
    ensure_directories()
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history):
    ensure_directories()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
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


def sort_videos(videos, mode="newest"):
    """Sắp xếp danh sách video theo mode."""
    if mode == "newest":
        return sorted(videos, key=lambda x: x.get("published", ""), reverse=True)
    elif mode == "oldest":
        return sorted(videos, key=lambda x: x.get("published", ""), reverse=False)
    elif mode == "title_asc":
        return sorted(videos, key=lambda x: x.get("title", "").lower())
    elif mode == "title_desc":
        return sorted(videos, key=lambda x: x.get("title", "").lower(), reverse=True)
    return videos


# --- Quản lý Thumbnails & Avatar Kênh ---
thumb_executor = ThreadPoolExecutor(max_workers=4)


def get_placeholder_pixbuf(width=160, height=90):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    pixbuf.fill(0x222222ff)
    return pixbuf


def fetch_and_load_image(url_or_id, width=160, height=90, callback=None, is_avatar=False):
    """Tải và nạp ảnh bất đồng bộ (hỗ trợ cả thumbnail video lẫn avatar kênh)."""
    if not url_or_id:
        if callback:
            GLib.idle_add(callback, get_placeholder_pixbuf(width, height))
        return

    # Nếu là URL mạng (avatar kênh hoặc link trực tiếp)
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

    # Nếu là Video ID (11 ký tự YouTube)
    fetch_and_load_thumbnail(url_or_id, width, height, callback)


def fetch_and_load_thumbnail(video_id, width=160, height=90, callback=None):
    if not video_id:
        if callback:
            GLib.idle_add(callback, get_placeholder_pixbuf(width, height))
        return

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
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
    """Yêu cầu nạp ảnh trong thread nền và cập nhật giao diện qua GLib.idle_add."""
    thumb_executor.submit(fetch_and_load_image, url_or_id, width, height, callback, is_avatar)


def request_thumbnail_async(video_id, callback, width=160, height=90):
    request_image_async(video_id, callback, width, height, is_avatar=False)


# --- Trích xuất luồng & Phát qua VLC ---
def get_ua_string(settings):
    """Trả về chuỗi User-Agent từ cài đặt."""
    ua_key = settings.get("user_agent", "Android TV (Khuyên dùng)")
    return UA_PRESETS.get(ua_key, UA_PRESETS["Android TV (Khuyên dùng)"])


def extract_stream_url(video_id_or_url, quality="720", player_client="tv_embedded,android,mweb", ua_string=None):
    """Dùng yt-dlp trích xuất đường dẫn direct stream H.264."""
    target = video_id_or_url if video_id_or_url.startswith("http") else f"https://www.youtube.com/watch?v={video_id_or_url}"

    # Ưu tiên H.264 (avc1) – giải mã phần cứng trên Mali-450 / VPU S905X
    if quality in ["1080", "best"]:
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

    # Spoof User-Agent nếu có
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

    # Fallback: tv_embedded không bị rate limit
    try:
        cmd_fallback = [
            "yt-dlp",
            "--no-playlist",
            "--extractor-args", "youtube:player_client=tv_embedded",
            "-f", "best[acodec!=none]/best",
            "-g",
            target
        ]
        if ua_string:
            cmd_fallback.extend(["--add-headers", f"User-Agent:{ua_string}"])
        proc = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True, timeout=20, env=env)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("http")]
        if lines:
            return lines[0], None
    except Exception:
        pass

    return None, None


def launch_vlc(video, settings, quality_override=None, status_callback=None):
    def _run():
        vid_id = video.get("id")
        title = video.get("title", "YouTube Video")
        target_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else video.get("url")

        quality = quality_override or settings.get("quality", "720")
        ua_string = get_ua_string(settings)

        if status_callback:
            GLib.idle_add(status_callback, f"⏳ Đang tải luồng {quality}p: {title[:40]}...")

        video_url, audio_url = extract_stream_url(
            target_url,
            quality=quality,
            player_client=settings.get("player_client", "tv_embedded,android,mweb"),
            ua_string=ua_string
        )

        if not video_url:
            if status_callback:
                GLib.idle_add(status_callback,
                    "❌ Không thể phát video (bản quyền/độ tuổi hoặc mạng yếu). Vui lòng thử video khác!")
            return

        caching = settings.get("caching", 3000)

        vlc_cmd = [
            "vlc",
            video_url,
            f"--meta-title={title}",
            f"--file-caching={caching}",
            f"--network-caching={caching}",
            "--no-video-title-show",
            "--drop-late-frames",
            "--skip-frames",
        ]
        if audio_url:
            vlc_cmd.append(f"--input-slave={audio_url}")

        if settings.get("hw_accel", True):
            vlc_cmd.extend(["--avcodec-skiploopfilter=3"])
        else:
            vlc_cmd.extend(["--avcodec-hw=none", "--avcodec-skiploopfilter=4"])

        if status_callback:
            GLib.idle_add(status_callback, f"▶ Đang phát {quality}p trên VLC: {title[:40]}")

        add_to_history(video)

        try:
            subprocess.run(vlc_cmd)
        except Exception as e:
            if status_callback:
                GLib.idle_add(status_callback, f"Lỗi khởi động VLC: {e}")
        finally:
            if status_callback:
                GLib.idle_add(status_callback, "Sẵn sàng")

    threading.Thread(target=_run, daemon=True).start()


# --- Hộp thoại chọn chất lượng ---
class QualityDialog(Gtk.Dialog):
    def __init__(self, parent, video_title, current_quality="720"):
        super().__init__(title="Chọn chất lượng phát", transient_for=parent, modal=True)
        self.set_default_size(360, -1)
        self.add_buttons(
            "Phát ngay", Gtk.ResponseType.OK,
            "Huỷ", Gtk.ResponseType.CANCEL
        )
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(10)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        title_lbl = Gtk.Label()
        title_lbl.set_markup(f"<b>{GLib.markup_escape_text(video_title[:60])}</b>")
        title_lbl.set_line_wrap(True)
        title_lbl.set_xalign(0)
        box.pack_start(title_lbl, False, False, 0)

        lbl = Gtk.Label(label="Chọn độ phân giải:")
        lbl.set_xalign(0)
        box.pack_start(lbl, False, False, 0)

        self.combo = Gtk.ComboBoxText()
        for k, v in QUALITY_OPTIONS:
            self.combo.append(k, v)
        self.combo.set_active_id(current_quality)
        if self.combo.get_active_id() is None:
            self.combo.set_active(0)
        box.pack_start(self.combo, False, False, 0)

        box.show_all()

    def get_selected_quality(self):
        return self.combo.get_active_id() or "720"


# --- Bộ Tìm kiếm & Phân giải Kênh ---
def search_youtube_fast(query, limit=30):
    """Tìm kiếm YouTube siêu nhanh: trả về cả danh sách Kênh phù hợp và Video."""
    query = query.strip()
    if not query:
        return {"channels": [], "videos": []}

    channels = []
    videos = []
    existing_vid_ids = set()
    existing_chan_ids = set()

    # Nếu người dùng nhập thẳng handle (@kênh) hoặc link kênh, ưu tiên phân giải kênh
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
                    # 1. Trích xuất Kênh (channelRenderer)
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

                    # 2. Trích xuất Video (videoRenderer)
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

                    # 3. Trích xuất video trong kệ nhóm (shelfRenderer)
                    elif 'shelfRenderer' in item:
                        shelf_items = (item['shelfRenderer'].get('content', {}).get('verticalListRenderer', {}).get('items', []) or
                                       item['shelfRenderer'].get('content', {}).get('expandedShelfContentsRenderer', {}).get('items', []))
                        for s_it in shelf_items:
                            if 'videoRenderer' in s_it:
                                v = s_it['videoRenderer']
                                vid_id = v.get('videoId')
                                if vid_id and vid_id not in existing_vid_ids:
                                    title = ''.join(r.get('text', '') for r in v.get('title', {}).get('runs', []))
                                    dur = v.get('lengthText', {}).get('simpleText', '--:--')
                                    owner_runs = v.get('ownerText', {}).get('runs', [])
                                    uploader = ''.join(r.get('text', '') for r in owner_runs) or 'YouTube'
                                    cid = None
                                    if owner_runs and 'navigationEndpoint' in owner_runs[0]:
                                        cid = owner_runs[0]['navigationEndpoint'].get('browseEndpoint', {}).get('browseId')
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

    # Nếu số lượng video ít hơn yêu cầu, dùng yt-dlp fallback để bù thêm
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
                    title = parts[1].replace("\n", " ").replace("\r", "").strip()
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


def fetch_channel_videos_web(channel_id):
    """Trích xuất thông tin kênh và danh sách video trực tiếp từ web YouTube (nhanh & đầy đủ)."""
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

    # 1. Trích xuất metadata kênh (Header)
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

    # Canonical Channel ID nếu đầu vào là handle
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

    # 2. Trích xuất danh sách video từ tab Video
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


# --- Widget Thẻ Kênh (Hiển thị khi Tìm kiếm) ---
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

        # Avatar Kênh (64x64)
        self.avatar_img = Gtk.Image.new_from_pixbuf(get_placeholder_pixbuf(64, 64))
        self.avatar_img.set_size_request(64, 64)
        outer_box.pack_start(self.avatar_img, False, False, 0)
        if channel.get("avatar"):
            request_image_async(channel["avatar"], self._update_avatar, 64, 64, is_avatar=True)

        # Thông tin Kênh
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

        # Nút hành động
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_valign(Gtk.Align.CENTER)

        btn_view = Gtk.Button(label="📋 Xem video")
        btn_view.get_style_context().add_class("suggested-action")
        btn_view.set_tooltip_text(f"Xem các video của kênh {cname}")
        btn_view.connect("clicked", lambda b: self.on_view_channel_callback(
            self.channel.get("id"), cname
        ))
        btn_box.pack_start(btn_view, False, False, 0)

        self.btn_sub = Gtk.Button(label="✔️ Đã theo dõi" if self.is_subscribed else "➕ Theo dõi")
        self.btn_sub.set_tooltip_text("Bật/tắt theo dõi kênh này")
        if self.is_subscribed:
            self.btn_sub.get_style_context().add_class("suggested-action")
        self.btn_sub.connect("clicked", lambda b: self.on_toggle_sub_callback(self.channel, self.btn_sub))
        btn_box.pack_start(self.btn_sub, False, False, 0)

        outer_box.pack_end(btn_box, False, False, 0)
        self.add(outer_box)

    def _update_avatar(self, pixbuf):
        if self.avatar_img and pixbuf:
            self.avatar_img.set_from_pixbuf(pixbuf)


# --- Widget Thẻ Video ---
class VideoRow(Gtk.ListBoxRow):
    def __init__(self, video, on_play_callback, on_channel_click=None):
        super().__init__()
        self.video = video
        self.on_play_callback = on_play_callback
        self.on_channel_click = on_channel_click

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)

        # Thumbnail 16:9
        self.image = Gtk.Image.new_from_pixbuf(get_placeholder_pixbuf(160, 90))
        self.image.set_size_request(160, 90)
        hbox.pack_start(self.image, False, False, 0)
        request_thumbnail_async(video.get("id"), self._update_image, width=160, height=90)

        # Thông tin Video
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        vbox.set_valign(Gtk.Align.CENTER)

        title_lbl = Gtk.Label()
        title_lbl.set_markup(f"<b>{GLib.markup_escape_text(video.get('title', 'Video'))}</b>")
        title_lbl.set_line_wrap(True)
        title_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title_lbl.set_max_width_chars(60)
        title_lbl.set_xalign(0)
        vbox.pack_start(title_lbl, False, False, 0)

        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        channel_name = video.get('channel') or video.get('uploader') or 'YouTube'

        if on_channel_click:
            chan_btn = Gtk.Button()
            chan_btn.set_relief(Gtk.ReliefStyle.NONE)
            chan_lbl_inner = Gtk.Label()
            chan_lbl_inner.set_markup(
                f"<span foreground='#5e9cf6'>👤 <u>{GLib.markup_escape_text(channel_name)}</u></span>"
            )
            chan_btn.add(chan_lbl_inner)
            chan_btn.set_tooltip_text(f"Xem các video trong kênh {channel_name}")
            chan_btn.connect("clicked", lambda b: self._handle_channel_click(channel_name, video.get("channel_id")))
            chan_btn.get_style_context().add_class("flat")
            info_box.pack_start(chan_btn, False, False, 0)
        else:
            chan_lbl = Gtk.Label(label=f"👤 {channel_name}")
            chan_lbl.set_xalign(0)
            info_box.pack_start(chan_lbl, False, False, 0)

        dur_text = video.get('duration') or '--:--'
        dur_lbl = Gtk.Label(label=f"⏱ {dur_text}")
        dur_lbl.set_xalign(0)
        info_box.pack_start(dur_lbl, False, False, 0)

        if video.get("views"):
            views_lbl = Gtk.Label(label=f"👁 {video['views']}")
            views_lbl.set_xalign(0)
            info_box.pack_start(views_lbl, False, False, 0)

        if video.get("published"):
            pub_lbl = Gtk.Label(label=f"📅 {video['published']}")
            pub_lbl.set_xalign(0)
            info_box.pack_start(pub_lbl, False, False, 0)

        if "watched_at" in video:
            hist_lbl = Gtk.Label(label=f"🕒 Xem: {video['watched_at']}")
            hist_lbl.set_xalign(0)
            info_box.pack_start(hist_lbl, False, False, 0)

        vbox.pack_start(info_box, False, False, 0)
        hbox.pack_start(vbox, True, True, 0)

        # Nút Phát
        play_btn = Gtk.Button(label="▶ Phát")
        play_btn.get_style_context().add_class("suggested-action")
        play_btn.set_valign(Gtk.Align.CENTER)
        play_btn.connect("clicked", lambda b: self.on_play_callback(self.video))
        hbox.pack_end(play_btn, False, False, 0)

        self.add(hbox)

    def _handle_channel_click(self, channel_name, channel_id):
        if not self.on_channel_click:
            return
        if channel_id:
            self.on_channel_click(channel_id, channel_name)
        else:
            def _resolve():
                info = resolve_channel(channel_name)
                if info and info.get("id"):
                    GLib.idle_add(self.on_channel_click, info["id"], info.get("name", channel_name))
            threading.Thread(target=_resolve, daemon=True).start()

    def _update_image(self, pixbuf):
        if self.image and pixbuf:
            self.image.set_from_pixbuf(pixbuf)


# --- Cửa sổ Chính Ứng Dụng ---
class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="YouTube VLC Player")
        self.set_default_size(1080, 720)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.settings = load_settings()
        if self.settings.get("dark_mode", True):
            Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)

        self._setup_icon()
        self._setup_css()

        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(main_vbox)

        # HeaderBar
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = "YouTube VLC Player"
        header.props.subtitle = "Phát video nhẹ qua VLC Media Player"

        # Icon trên header – chỉ thêm nếu load thành công
        if self.app_icon_pixbuf is not None:
            try:
                icon_img = Gtk.Image.new_from_pixbuf(self.app_icon_pixbuf)
                icon_img.set_margin_start(6)
                header.pack_start(icon_img)
            except Exception:
                pass

        self.set_titlebar(header)

        # Notebook chứa các Tab
        self.notebook = Gtk.Notebook()
        main_vbox.pack_start(self.notebook, True, True, 0)

        # Biến trạng thái
        self.current_search_query = ""
        self.current_search_channels = []
        self.current_search_results = []
        self.current_feed_videos = []
        self.feed_sort_mode = "newest"

        # Khởi tạo các Tab
        self._init_search_tab()
        self._init_feed_tab()
        self._init_history_tab()
        self._init_subs_manager_tab()
        self._init_settings_tab()

        # Thanh trạng thái
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
            padding: 6px 16px;
            font-weight: bold;
        }
        .load-more-btn {
            padding: 10px 20px;
            font-size: 14px;
            margin: 12px;
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
        .channel-card:hover {
            background-color: rgba(255, 255, 255, 0.09);
            border-color: rgba(94, 156, 246, 0.5);
        }
        .section-header {
            font-size: 13px;
            font-weight: bold;
            color: #88a4e8;
            padding: 6px 10px;
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

    def play_video_action(self, video):
        """Phát video – hỏi chất lượng trước nếu bật tùy chọn ask_quality."""
        if self.settings.get("ask_quality", True):
            dlg = QualityDialog(self, video.get("title", "Video"),
                                current_quality=self.settings.get("quality", "720"))
            response = dlg.run()
            quality = dlg.get_selected_quality()
            dlg.destroy()
            if response != Gtk.ResponseType.OK:
                return
        else:
            quality = self.settings.get("quality", "720")

        launch_vlc(video, self.settings, quality_override=quality,
                   status_callback=self.set_status)
        GLib.idle_add(self.reload_history)

    def open_channel_videos(self, channel_id, channel_name):
        """Mở cửa sổ xem video trong kênh."""
        dlg = ChannelVideosDialog(self, channel_id, channel_name,
                                  self.settings, self.play_video_action,
                                  on_subs_changed=self.reload_subs_list)
        dlg.run()
        dlg.destroy()

    def toggle_channel_sub(self, channel, btn):
        """Đăng ký hoặc hủy đăng ký kênh từ thẻ kênh."""
        subs = load_subs()
        chan_id = channel.get("id")
        chan_name = channel.get("title") or channel.get("name") or chan_id
        existing = [s for s in subs if s.get("id") == chan_id]
        if existing:
            subs = [s for s in subs if s.get("id") != chan_id]
            save_subs(subs)
            btn.set_label("➕ Theo dõi")
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
            btn.set_label("✔️ Đã theo dõi")
            btn.get_style_context().add_class("suggested-action")
            self.set_status(f"🎉 Đã theo dõi kênh: {chan_name}")
        self.reload_subs_list()

    # ===================== 1. TAB TÌM KIẾM =====================
    def _init_search_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)

        # Thanh tìm kiếm
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Nhập từ khóa, @kênh hoặc link YouTube...")
        self.search_entry.connect("activate", lambda e: self.do_search())
        search_box.pack_start(self.search_entry, True, True, 0)

        btn_search = Gtk.Button(label="🔍 Tìm kiếm")
        btn_search.get_style_context().add_class("suggested-action")
        btn_search.connect("clicked", lambda b: self.do_search())
        search_box.pack_start(btn_search, False, False, 0)

        # Sort cho tìm kiếm
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

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.search_list = Gtk.ListBox()
        self.search_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.search_list)
        vbox.pack_start(scroll, True, True, 0)

        self.load_more_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.load_more_box.set_halign(Gtk.Align.CENTER)
        self.btn_load_more = Gtk.Button(label="⬇️ Tải thêm video")
        self.btn_load_more.get_style_context().add_class("load-more-btn")
        self.btn_load_more.connect("clicked", lambda b: self.load_more_search())
        self.load_more_box.pack_start(self.btn_load_more, False, False, 0)
        self.load_more_spinner = Gtk.Spinner()
        self.load_more_box.pack_start(self.load_more_spinner, False, False, 0)
        self.load_more_box.set_no_show_all(True)
        vbox.pack_end(self.load_more_box, False, False, 4)

        self.notebook.append_page(vbox, Gtk.Label(label="🔍 Tìm kiếm"))

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
            lbl = Gtk.Label(label="❌ Không tìm thấy kênh hoặc video nào khớp với từ khóa.")
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

        # 1. Hiển thị Kênh phù hợp ở đầu danh sách tìm kiếm
        if self.current_search_channels:
            lbl_chan = Gtk.Label()
            lbl_chan.set_markup("<b>📺 KÊNH PHÙ HỢP:</b>")
            lbl_chan.set_xalign(0)
            lbl_chan.get_style_context().add_class("section-header")
            self.search_list.add(lbl_chan)

            for c in self.current_search_channels:
                is_sub = c.get("id") in sub_ids
                row = ChannelRow(c, self.open_channel_videos, self.toggle_channel_sub, is_sub)
                self.search_list.add(row)

        # 2. Hiển thị Danh sách Video
        if self.current_search_results:
            if self.current_search_channels:
                lbl_vid = Gtk.Label()
                lbl_vid.set_markup("<b>🎬 VIDEO KẾT QUẢ:</b>")
                lbl_vid.set_xalign(0)
                lbl_vid.get_style_context().add_class("section-header")
                self.search_list.add(lbl_vid)

            mode_label = self.search_sort_combo.get_active_text() or "Mới nhất"
            mode = SORT_MODES.get(mode_label, "newest")
            sorted_results = sort_videos(self.current_search_results, mode)
            for r in sorted_results:
                row = VideoRow(r, self.play_video_action,
                               on_channel_click=self.open_channel_videos)
                self.search_list.add(row)

        self.search_list.show_all()

    def _resort_search(self):
        if self.current_search_results or self.current_search_channels:
            self._redraw_search_list()

    def load_more_search(self):
        if not self.current_search_query:
            return
        self.load_more_spinner.start()
        self.btn_load_more.set_sensitive(False)
        self.set_status(f"Đang tải thêm kết quả cho '{self.current_search_query}'...")

        current_count = len(self.current_search_results)
        fetch_limit = current_count + self.settings.get("max_results", 30)

        def _more_thread():
            results = search_youtube_fast(self.current_search_query, limit=fetch_limit)
            GLib.idle_add(self._append_more_results, results)

        threading.Thread(target=_more_thread, daemon=True).start()

    def _append_more_results(self, new_data):
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
            self.set_status(f"Không còn video mới. Tổng: {len(self.current_search_results)} video.")

    # ===================== 2. TAB KÊNH ĐĂNG KÝ =====================
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

        # Sort cho feed
        sort_lbl = Gtk.Label(label="Sắp xếp:")
        top_bar.pack_end(sort_lbl, False, False, 0)

        self.feed_sort_combo = Gtk.ComboBoxText()
        for label in SORT_MODES:
            self.feed_sort_combo.append_text(label)
        self.feed_sort_combo.set_active(0)
        self.feed_sort_combo.connect("changed", lambda c: self._resort_feed())
        top_bar.pack_end(self.feed_sort_combo, False, False, 0)

        btn_refresh = Gtk.Button(label="🔄 Làm mới")
        btn_refresh.connect("clicked", lambda b: self.refresh_feed())
        top_bar.pack_end(btn_refresh, False, False, 0)

        vbox.pack_start(top_bar, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.feed_list = Gtk.ListBox()
        self.feed_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.feed_list)
        vbox.pack_start(scroll, True, True, 0)

        self.notebook.append_page(vbox, Gtk.Label(label="📺 Kênh đăng ký"))

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
        for v in sorted_videos[:50]:
            row = VideoRow(v, self.play_video_action,
                           on_channel_click=self.open_channel_videos)
            self.feed_list.add(row)
        self.feed_list.show_all()

    def _resort_feed(self):
        if self.current_feed_videos:
            self._redraw_feed_list()

    # ===================== 3. TAB LỊCH SỬ =====================
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

        btn_clear = Gtk.Button(label="🗑 Xóa lịch sử")
        btn_clear.connect("clicked", lambda b: self.do_clear_history())
        top_bar.pack_end(btn_clear, False, False, 0)

        vbox.pack_start(top_bar, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.history_list)
        vbox.pack_start(scroll, True, True, 0)

        self.notebook.append_page(vbox, Gtk.Label(label="🕒 Lịch sử xem"))
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
            row = VideoRow(h, self.play_video_action, on_channel_click=self.open_channel_videos)
            self.history_list.add(row)
        self.history_list.show_all()

    def do_clear_history(self):
        save_history([])
        self.reload_history()
        self.set_status("Đã xóa toàn bộ lịch sử xem.")

    # ===================== 4. TAB QUẢN LÝ KÊNH =====================
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

        btn_add = Gtk.Button(label="➕ Đăng ký")
        btn_add.get_style_context().add_class("suggested-action")
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

        self.notebook.append_page(vbox, Gtk.Label(label="➕ Quản lý kênh"))
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

            # Avatar kênh nhỏ (44x44)
            avatar_img = Gtk.Image.new_from_pixbuf(get_placeholder_pixbuf(44, 44))
            avatar_img.set_size_request(44, 44)
            hbox.pack_start(avatar_img, False, False, 0)
            if s.get("avatar"):
                request_image_async(s["avatar"], lambda pb, img=avatar_img: img.set_from_pixbuf(pb) if pb else None, 44, 44, is_avatar=True)

            chan_info = Gtk.Label()
            c_name = s.get("name") or s.get("title") or "Kênh"
            chan_info.set_markup(
                f"<b>{GLib.markup_escape_text(c_name)}</b> "
                f"<span foreground='#888888'>({s.get('handle', s.get('id'))})</span>"
            )
            chan_info.set_xalign(0)
            hbox.pack_start(chan_info, True, True, 0)

            # Nút xem video trong kênh
            btn_view = Gtk.Button(label="📋 Xem video")
            btn_view.get_style_context().add_class("suggested-action")
            btn_view.set_tooltip_text(f"Xem danh sách video của kênh {c_name}")
            btn_view.connect("clicked", lambda b, c=s: self.open_channel_videos(c["id"], c.get("name") or c.get("title") or c["id"]))
            hbox.pack_end(btn_view, False, False, 0)

            btn_del = Gtk.Button(label="❌ Hủy theo dõi")
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
        self.set_status(f"✅ Đã thêm kênh: {name}")
        self.refresh_feed()

    def do_remove_channel(self, chan_id):
        subs = load_subs()
        subs = [s for s in subs if s["id"] != chan_id]
        save_subs(subs)
        self.reload_subs_list()
        self.set_status("Đã hủy theo dõi kênh.")
        self.refresh_feed()

    # ===================== 5. TAB CÀI ĐẶT =====================
    def _init_settings_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)

        grid = Gtk.Grid()
        grid.set_column_spacing(20)
        grid.set_row_spacing(16)
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

        # 3. Bộ đệm VLC
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

        # 4. Player client (yt-dlp extractor)
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

        # 5. Spoof User-Agent
        lbl_ua = Gtk.Label(label="Spoof User-Agent:", xalign=0)
        self.combo_ua = Gtk.ComboBoxText()
        for ua_name in UA_PRESETS:
            self.combo_ua.append_text(ua_name)
        current_ua = self.settings.get("user_agent", "Android TV (Khuyên dùng)")
        # set active
        ua_keys = list(UA_PRESETS.keys())
        idx = ua_keys.index(current_ua) if current_ua in ua_keys else 0
        self.combo_ua.set_active(idx)
        grid.attach(lbl_ua, 0, row_i, 1, 1)
        grid.attach(self.combo_ua, 1, row_i, 1, 1)
        row_i += 1

        # 6. Số lượng video tìm kiếm
        lbl_res = Gtk.Label(label="Số video tải mỗi lần tìm kiếm:", xalign=0)
        self.combo_max_res = Gtk.ComboBoxText()
        for k, v in [("20", "20 video"), ("30", "30 video (Khuyên dùng)"),
                     ("50", "50 video"), ("80", "80 video")]:
            self.combo_max_res.append(k, v)
        self.combo_max_res.set_active_id(str(self.settings.get("max_results", 30)))
        grid.attach(lbl_res, 0, row_i, 1, 1)
        grid.attach(self.combo_max_res, 1, row_i, 1, 1)
        row_i += 1

        # 7. Tăng tốc phần cứng
        lbl_hw = Gtk.Label(label="Tăng tốc phần cứng (HW Accel):", xalign=0)
        self.switch_hw = Gtk.Switch()
        self.switch_hw.set_halign(Gtk.Align.START)
        self.switch_hw.set_valign(Gtk.Align.CENTER)
        self.switch_hw.set_active(self.settings.get("hw_accel", True))
        grid.attach(lbl_hw, 0, row_i, 1, 1)
        grid.attach(self.switch_hw, 1, row_i, 1, 1)
        row_i += 1

        # 8. Giao diện tối
        lbl_dark = Gtk.Label(label="Giao diện tối (Dark Mode):", xalign=0)
        self.switch_dark = Gtk.Switch()
        self.switch_dark.set_halign(Gtk.Align.START)
        self.switch_dark.set_valign(Gtk.Align.CENTER)
        self.switch_dark.set_active(self.settings.get("dark_mode", True))
        grid.attach(lbl_dark, 0, row_i, 1, 1)
        grid.attach(self.switch_dark, 1, row_i, 1, 1)
        row_i += 1

        # Thông tin tối ưu hóa Armbian
        armbian_frame = Gtk.Frame(label="Tối ưu hóa hệ thống")
        armbian_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        armbian_box.set_margin_start(10)
        armbian_box.set_margin_end(10)
        armbian_box.set_margin_top(8)
        armbian_box.set_margin_bottom(8)
        armbian_lbl = Gtk.Label()
        armbian_lbl.set_markup(
            "⚡ <b>Phát hiện:</b> Armbian Linux (Amlogic S905X / ARM64)\n"
            "✅ Đã bật tối ưu H.264 (AVC) giải mã phần cứng, chống quá tải CPU.\n"
            "✅ Spoof User-Agent giúp bypass giới hạn API YouTube."
        )
        armbian_lbl.set_xalign(0)
        armbian_box.pack_start(armbian_lbl, False, False, 0)
        armbian_frame.add(armbian_box)
        vbox.pack_start(armbian_frame, False, False, 0)

        # Nút lưu
        btn_save = Gtk.Button(label="💾 Lưu cài đặt")
        btn_save.get_style_context().add_class("suggested-action")
        btn_save.connect("clicked", lambda b: self.do_save_settings())
        vbox.pack_start(btn_save, False, False, 0)

        # Dọn cache
        cache_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_clean_cache = Gtk.Button(label="🧹 Dọn dẹp cache Thumbnail")
        btn_clean_cache.connect("clicked", lambda b: self.do_clean_cache())
        cache_box.pack_start(btn_clean_cache, False, False, 0)
        vbox.pack_start(cache_box, False, False, 10)

        about_lbl = Gtk.Label()
        about_lbl.set_markup(
            "<small>Dự án mã nguồn mở phát triển bởi <b>starfish367</b>\n"
            "Phiên bản: 2.5.0 (GTK3 VLC Edition)</small>"
        )
        about_lbl.set_line_wrap(True)
        about_lbl.set_xalign(0)
        vbox.pack_end(about_lbl, False, False, 10)

        self.notebook.append_page(vbox, Gtk.Label(label="⚙️ Cài đặt"))

    def do_save_settings(self):
        self.settings["quality"] = self.combo_quality.get_active_id() or "720"
        self.settings["ask_quality"] = self.switch_ask_quality.get_active()
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
        self.set_status("✅ Đã lưu cài đặt thành công!")

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
        self.set_status(f"🧹 Đã xóa {count} tệp ảnh trong bộ nhớ đệm cache.")


# --- Cửa sổ xem Video trong Kênh ---
class ChannelVideosDialog(Gtk.Dialog):
    def __init__(self, parent, channel_id, channel_name, settings, play_callback, on_subs_changed=None):
        super().__init__(
            title=f"📺 Kênh: {channel_name}",
            transient_for=parent,
            modal=True
        )
        self.set_default_size(950, 680)
        self.channel_id = channel_id
        self.channel_name = channel_name
        self.settings = settings
        self.play_callback = play_callback
        self.on_subs_changed = on_subs_changed
        self.all_videos = []
        self.channel_meta = {}

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

        # Avatar Kênh
        self.chan_avatar = Gtk.Image.new_from_pixbuf(get_placeholder_pixbuf(64, 64))
        self.chan_avatar.set_size_request(64, 64)
        header_box.pack_start(self.chan_avatar, False, False, 0)

        # Tiêu đề & Thông số
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

        # Nút Theo dõi trên Header
        subs = load_subs()
        is_sub = any(s.get("id") == self.channel_id for s in subs)
        self.btn_chan_sub = Gtk.Button(label="✔️ Đã theo dõi" if is_sub else "➕ Theo dõi")
        self.btn_chan_sub.set_valign(Gtk.Align.CENTER)
        if is_sub:
            self.btn_chan_sub.get_style_context().add_class("suggested-action")
        self.btn_chan_sub.connect("clicked", self._toggle_sub)
        header_box.pack_end(self.btn_chan_sub, False, False, 0)

        content.pack_start(header_box, False, False, 0)

        # 2. Thanh điều khiển Toolbar (Lọc, Sắp xếp, Làm mới)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)

        # Ô lọc video trong kênh
        self.filter_entry = Gtk.SearchEntry()
        self.filter_entry.set_placeholder_text("🔍 Lọc video trong kênh theo tiêu đề...")
        self.filter_entry.connect("search-changed", lambda e: self._on_filter_changed())
        toolbar.pack_start(self.filter_entry, True, True, 0)

        # Nút làm mới
        btn_refresh = Gtk.Button(label="🔄 Tải lại")
        btn_refresh.set_tooltip_text("Tải lại danh sách video từ kênh")
        btn_refresh.connect("clicked", lambda b: self._reload())
        toolbar.pack_start(btn_refresh, False, False, 0)

        self.chan_spinner = Gtk.Spinner()
        toolbar.pack_start(self.chan_spinner, False, False, 0)

        # Sắp xếp
        sort_lbl = Gtk.Label(label="Sắp xếp:")
        toolbar.pack_end(sort_lbl, False, False, 0)
        self.sort_combo = Gtk.ComboBoxText()
        for label in SORT_MODES:
            self.sort_combo.append_text(label)
        self.sort_combo.set_active(0)
        self.sort_combo.connect("changed", lambda c: self._resort())
        toolbar.pack_end(self.sort_combo, False, False, 0)

        content.pack_start(toolbar, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        content.pack_start(sep, False, False, 0)

        # 3. Danh sách video
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.video_list = Gtk.ListBox()
        self.video_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.video_list)
        content.pack_start(scroll, True, True, 0)

        # 4. Trạng thái
        self.status_lbl = Gtk.Label(label="Đang tải danh sách video...")
        self.status_lbl.set_xalign(0)
        self.status_lbl.set_margin_start(12)
        self.status_lbl.set_margin_bottom(6)
        content.pack_start(self.status_lbl, False, False, 0)

        content.show_all()

        # Bắt đầu tải video
        self._reload()

    def _reload(self):
        self.chan_spinner.start()
        self.status_lbl.set_text("Đang kết nối và tải video từ kênh...")
        threading.Thread(target=self._load_videos_worker, daemon=True).start()

    def _load_videos_worker(self):
        # 1. Tải nhanh từ RSS feed (<0.5s) để hiển thị 15 video mới nhất trước
        channel_info = {"id": self.channel_id, "name": self.channel_name}
        rss_videos = fetch_feed_for_channel(channel_info)
        if rss_videos:
            GLib.idle_add(self._render_videos, rss_videos, "RSS (15 video mới nhất)")

        # 2. Tải trực tiếp qua web YouTube (30+ video kèm thời lượng, lượt xem & avatar kênh)
        web_res = fetch_channel_videos_web(self.channel_id)
        if web_res and web_res.get("videos"):
            GLib.idle_add(self._apply_channel_meta, web_res.get("channel", {}))
            GLib.idle_add(self._render_videos, web_res["videos"], f"Web ({len(web_res['videos'])} video)")
            return

        # 3. Fallback bằng yt-dlp nếu không lấy được qua web
        ytdlp_videos = fetch_channel_videos_ytdlp(self.channel_id, limit=50)
        if ytdlp_videos:
            GLib.idle_add(self._render_videos, ytdlp_videos, f"yt-dlp ({len(ytdlp_videos)} video)")
        elif not rss_videos:
            GLib.idle_add(self._render_videos, [], "Không tìm thấy video")

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
            self.btn_chan_sub.set_label("➕ Theo dõi")
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
            self.btn_chan_sub.set_label("✔️ Đã theo dõi")
            self.btn_chan_sub.get_style_context().add_class("suggested-action")
            self.status_lbl.set_text(f"🎉 Đã theo dõi kênh: {self.channel_name}")
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

    def _on_filter_changed(self):
        self._redraw()

    def _resort(self):
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
                row = VideoRow(v, self.play_callback)
                self.video_list.add(row)

        self.video_list.show_all()


# --- Điểm khởi chạy ---
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
