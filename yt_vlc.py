#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yt-vlc: YouTube VLC Player (GTK3 Edition)
Phát video YouTube siêu nhẹ trên VLC, hỗ trợ Kênh đăng ký, Lịch sử xem và Cài đặt.
Mã nguồn mở: https://github.com/starfish367/yt-vlc
"""

import sys
import os
import json
import re
import time
import datetime
import threading
import subprocess
import urllib.request
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

DEFAULT_SETTINGS = {
    "quality": "720",
    "caching": 3000,
    "player_client": "ios,android,web",
    "hw_accel": True,
    "max_results": 20,
    "dark_mode": True
}

def ensure_directories():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)
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
    # Loại bỏ video trùng nếu đã có
    history = [h for h in history if h.get("id") != video.get("id")]
    entry = {
        "id": video.get("id"),
        "title": video.get("title", "Video"),
        "channel": video.get("channel") or video.get("uploader", "YouTube"),
        "duration": video.get("duration", "--:--"),
        "watched_at": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    history.insert(0, entry)
    save_history(history)

# --- Quản lý Thumbnails ---
thumb_executor = ThreadPoolExecutor(max_workers=8)

def get_placeholder_pixbuf(width=160, height=90):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    pixbuf.fill(0x222222ff)
    return pixbuf

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

    # Tải thumbnail từ YouTube
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

def request_thumbnail_async(video_id, callback, width=160, height=90):
    thumb_executor.submit(fetch_and_load_thumbnail, video_id, width, height, callback)

# --- Trích xuất luồng & Phát qua VLC ---
def extract_stream_url(video_id_or_url, quality="720", player_client="ios,android,web"):
    """Dùng yt-dlp trích xuất đường dẫn direct stream (GoogleVideo URL)"""
    target = video_id_or_url if video_id_or_url.startswith("http") else f"https://www.youtube.com/watch?v={video_id_or_url}"
    format_spec = f"best[height<={quality}][acodec!=none]/best[ext=mp4][acodec!=none]/best[acodec!=none]/best"
    
    env = os.environ.copy()
    env["PATH"] = f"/home/a/.local/bin:{env.get('PATH', '')}"

    cmd = [
        "yt-dlp",
        "--extractor-args", f"youtube:player_client={player_client}",
        "-f", format_spec,
        "-g",
        target
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15, env=env)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("http")]
        if lines:
            return lines[0]
    except Exception:
        pass
    return None

def launch_vlc(video, settings, status_callback=None):
    def _run():
        vid_id = video.get("id")
        title = video.get("title", "YouTube Video")
        target_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else video.get("url")

        if status_callback:
            GLib.idle_add(status_callback, f"⏳ Đang trích xuất luồng cho: {title[:40]}...")

        stream_url = extract_stream_url(
            target_url,
            quality=settings.get("quality", "720"),
            player_client=settings.get("player_client", "ios,android,web")
        )

        vlc_target = stream_url if stream_url else target_url
        caching = settings.get("caching", 3000)

        vlc_cmd = [
            "vlc",
            vlc_target,
            f"--meta-title={title}",
            f"--file-caching={caching}",
            f"--network-caching={caching}"
        ]
        if not settings.get("hw_accel", True):
            vlc_cmd.extend(["--avcodec-hw=none", "--avcodec-skiploopfilter=3"])

        if status_callback:
            GLib.idle_add(status_callback, f"▶ Đang phát trên VLC: {title[:40]}")

        # Thêm vào lịch sử xem
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

# --- Tìm kiếm & RSS Feed ---
def search_youtube(query, limit=20):
    if not query.strip():
        return []
    env = os.environ.copy()
    env["PATH"] = f"/home/a/.local/bin:{env.get('PATH', '')}"

    cmd = [
        "yt-dlp",
        "--extractor-args", "youtube:player_client=android",
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s\t%(uploader)s\t%(duration_string)s",
        f"ytsearch{limit}:{query}"
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=25, env=env)
        results = []
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                vid_id = parts[0].strip()
                title = parts[1].replace("\n", " ").replace("\r", "").strip()
                uploader = parts[2].replace("\n", " ").strip() if len(parts) > 2 else "YouTube"
                duration = parts[3].strip() if len(parts) > 3 else "--:--"
                results.append({
                    "id": vid_id,
                    "title": title,
                    "uploader": uploader,
                    "channel": uploader,
                    "duration": duration
                })
        return results
    except Exception:
        return []

def resolve_channel(target):
    target = target.strip()
    channel_id = None
    if re.match(r"^UC[a-zA-Z0-9_-]{22}$", target):
        channel_id = target
    elif "youtube.com/channel/" in target:
        m = re.search(r"channel/(UC[a-zA-Z0-9_-]{22})", target)
        if m:
            channel_id = m.group(1)
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
    channel_id = channel["id"]
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
                    "channel": channel.get("name", "Kênh"),
                    "uploader": channel.get("name", "Kênh"),
                    "duration": "Mới",
                    "published": pub.text[:10] if pub is not None and pub.text else ""
                })
    except Exception:
        pass
    return videos

def get_subscriptions_feed():
    subs = load_subs()
    if not subs:
        return []
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = ex.map(fetch_feed_for_channel, subs)
        all_videos = [v for res in results for v in res]
    all_videos.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_videos

# --- Widget Thẻ Video Hiện Đại (Video Card) ---
class VideoRow(Gtk.ListBoxRow):
    def __init__(self, video, on_play_callback):
        super().__init__()
        self.video = video
        self.on_play_callback = on_play_callback

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)

        # 1. Thumbnail to rõ (160x90)
        self.image = Gtk.Image.new_from_pixbuf(get_placeholder_pixbuf(160, 90))
        self.image.set_size_request(160, 90)
        hbox.pack_start(self.image, False, False, 0)
        request_thumbnail_async(video.get("id"), self._update_image, width=160, height=90)

        # 2. Thông tin Video
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
        chan_lbl = Gtk.Label(label=f"👤 {channel_name}")
        chan_lbl.set_xalign(0)
        info_box.pack_start(chan_lbl, False, False, 0)

        dur_text = video.get('duration') or video.get('published') or '--:--'
        dur_lbl = Gtk.Label(label=f"⏱ {dur_text}")
        dur_lbl.set_xalign(0)
        info_box.pack_start(dur_lbl, False, False, 0)

        if "watched_at" in video:
            hist_lbl = Gtk.Label(label=f"🕒 Xem lúc: {video['watched_at']}")
            hist_lbl.set_xalign(0)
            info_box.pack_start(hist_lbl, False, False, 0)

        vbox.pack_start(info_box, False, False, 0)
        hbox.pack_start(vbox, True, True, 0)

        # 3. Nút Phát
        play_btn = Gtk.Button(label="▶ Phát")
        play_btn.get_style_context().add_class("suggested-action")
        play_btn.set_valign(Gtk.Align.CENTER)
        play_btn.connect("clicked", lambda b: self.on_play_callback(self.video))
        hbox.pack_end(play_btn, False, False, 0)

        self.add(hbox)

    def _update_image(self, pixbuf):
        if self.image and pixbuf:
            self.image.set_from_pixbuf(pixbuf)

# --- Cửa sổ Chính Ứng Dụng ---
class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="YouTube VLC Player")
        self.set_default_size(1050, 700)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.settings = load_settings()
        if self.settings.get("dark_mode", True):
            Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)

        self._setup_css()

        # Layout chính
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(main_vbox)

        # HeaderBar hiện đại
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = "YouTube VLC Player"
        header.props.subtitle = "Giao diện nhẹ - Xem trực tiếp qua VLC"
        self.set_titlebar(header)

        # Notebook chứa các Tab
        self.notebook = Gtk.Notebook()
        main_vbox.pack_start(self.notebook, True, True, 0)

        # Khởi tạo các Tab
        self._init_search_tab()
        self._init_feed_tab()
        self._init_history_tab()
        self._init_subs_manager_tab()
        self._init_settings_tab()

        # Thanh trạng thái dưới cùng
        self.status_bar = Gtk.Statusbar()
        self.status_context = self.status_bar.get_context_id("status")
        main_vbox.pack_end(self.status_bar, False, False, 0)
        self.set_status("Sẵn sàng")

        # Tải danh sách Subscriptions feed ban đầu ở chế độ nền
        GLib.timeout_add(500, self.refresh_feed)

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
        launch_vlc(video, self.settings, status_callback=self.set_status)
        # Cập nhật lại tab lịch sử
        GLib.idle_add(self.reload_history)

    # 1. TAB TÌM KIẾM
    def _init_search_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)

        # Thanh tìm kiếm
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Nhập từ khóa tìm kiếm video YouTube hoặc link...")
        self.search_entry.connect("activate", lambda e: self.do_search())
        search_box.pack_start(self.search_entry, True, True, 0)

        btn_search = Gtk.Button(label="🔍 Tìm kiếm")
        btn_search.get_style_context().add_class("suggested-action")
        btn_search.connect("clicked", lambda b: self.do_search())
        search_box.pack_start(btn_search, False, False, 0)

        self.search_spinner = Gtk.Spinner()
        search_box.pack_start(self.search_spinner, False, False, 0)

        vbox.pack_start(search_box, False, False, 0)

        # Danh sách kết quả
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.search_list = Gtk.ListBox()
        self.search_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.search_list)
        vbox.pack_start(scroll, True, True, 0)

        self.notebook.append_page(vbox, Gtk.Label(label="🔍 Tìm kiếm"))

    def do_search(self):
        query = self.search_entry.get_text().strip()
        if not query:
            return
        
        # Nếu nhập trực tiếp link YouTube
        if "youtube.com/watch" in query or "youtu.be/" in query:
            vid = query.split("v=")[-1].split("&")[0] if "v=" in query else query.split("/")[-1].split("?")[0]
            self.play_video_action({"id": vid, "title": query, "channel": "Direct Link"})
            return

        self.search_spinner.start()
        self.set_status(f"Đang tìm kiếm: '{query}'...")
        
        # Xóa kết quả cũ
        for child in self.search_list.get_children():
            self.search_list.remove(child)

        def _search_thread():
            results = search_youtube(query, limit=self.settings.get("max_results", 20))
            GLib.idle_add(self._render_search_results, results)

        threading.Thread(target=_search_thread, daemon=True).start()

    def _render_search_results(self, results):
        self.search_spinner.stop()
        if not results:
            self.set_status("Không tìm thấy video nào.")
            lbl = Gtk.Label(label="❌ Không tìm thấy video nào khớp với từ khóa.")
            lbl.set_margin_top(30)
            self.search_list.add(lbl)
            self.search_list.show_all()
            return

        for r in results:
            row = VideoRow(r, self.play_video_action)
            self.search_list.add(row)

        self.search_list.show_all()
        self.set_status(f"Đã tìm thấy {len(results)} video.")

    # 2. TAB KÊNH ĐĂNG KÝ (SUBSCRIPTIONS FEED)
    def _init_feed_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl = Gtk.Label()
        lbl.set_markup("<b>Video mới nhất từ các kênh bạn theo dõi:</b>")
        top_bar.pack_start(lbl, False, False, 0)

        self.feed_spinner = Gtk.Spinner()
        top_bar.pack_start(self.feed_spinner, False, False, 0)

        btn_refresh = Gtk.Button(label="🔄 Làm mới Feed")
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
        if not videos:
            self.set_status("Chưa có video mới hoặc chưa đăng ký kênh nào.")
            lbl = Gtk.Label(label="Chưa có video mới. Hãy sang tab 'Quản lý kênh' để thêm kênh yêu thích!")
            lbl.set_margin_top(30)
            self.feed_list.add(lbl)
            self.feed_list.show_all()
            return

        for v in videos[:40]:
            row = VideoRow(v, self.play_video_action)
            self.feed_list.add(row)

        self.feed_list.show_all()
        self.set_status(f"Đã cập nhật {len(videos)} video từ kênh đăng ký.")

    # 3. TAB LỊCH SỬ XEM (WATCH HISTORY)
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
            row = VideoRow(h, self.play_video_action)
            self.history_list.add(row)

        self.history_list.show_all()

    def do_clear_history(self):
        clear_history = lambda: save_history([])
        clear_history()
        self.reload_history()
        self.set_status("Đã xóa toàn bộ lịch sử xem.")

    # 4. TAB QUẢN LÝ KÊNH (MANAGE SUBSCRIPTIONS)
    def _init_subs_manager_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        vbox.set_margin_top(16)
        vbox.set_margin_bottom(16)

        # Thêm kênh mới
        add_frame = Gtk.Frame(label="Đăng ký thêm kênh mới")
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_box.set_margin_start(10)
        add_box.set_margin_end(10)
        add_box.set_margin_top(10)
        add_box.set_margin_bottom(10)

        self.new_sub_entry = Gtk.Entry()
        self.new_sub_entry.set_placeholder_text("Nhập @handle (vd: @vunguyencoder) hoặc link kênh YouTube...")
        add_box.pack_start(self.new_sub_entry, True, True, 0)

        btn_add = Gtk.Button(label="➕ Đăng ký")
        btn_add.get_style_context().add_class("suggested-action")
        btn_add.connect("clicked", lambda b: self.do_add_channel())
        add_box.pack_start(btn_add, False, False, 0)

        add_frame.add(add_box)
        vbox.pack_start(add_frame, False, False, 0)

        # Danh sách kênh
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
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
            hbox.set_margin_start(10)
            hbox.set_margin_end(10)
            hbox.set_margin_top(8)
            hbox.set_margin_bottom(8)

            chan_info = Gtk.Label()
            chan_info.set_markup(f"<b>{GLib.markup_escape_text(s.get('name', 'Kênh'))}</b> ({s.get('handle', s.get('id'))})")
            chan_info.set_xalign(0)
            hbox.pack_start(chan_info, True, True, 0)

            btn_del = Gtk.Button(label="❌ Hủy theo dõi")
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

    # 5. TAB CÀI ĐẶT (SETTINGS)
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

        # 1. Chất lượng video
        lbl_q = Gtk.Label(label="Độ phân giải ưu tiên:", xalign=0)
        self.combo_quality = Gtk.ComboBoxText()
        qualities = [("720", "720p (Khuyên dùng - Cân bằng mượt mà)"),
                     ("1080", "1080p (Full HD)"),
                     ("480", "480p (Tiết kiệm băng thông)"),
                     ("360", "360p (Mạng rất yếu)"),
                     ("best", "Tốt nhất có thể (Best)")]
        for k, v in qualities:
            self.combo_quality.append(k, v)
        self.combo_quality.set_active_id(self.settings.get("quality", "720"))
        grid.attach(lbl_q, 0, 0, 1, 1)
        grid.attach(self.combo_quality, 1, 0, 1, 1)

        # 2. Bộ đệm VLC
        lbl_c = Gtk.Label(label="Bộ nhớ đệm VLC (Caching):", xalign=0)
        self.combo_cache = Gtk.ComboBoxText()
        caches = [("1000", "1000 ms (Mạng cáp quang siêu nhanh)"),
                  ("2000", "2000 ms (Mặc định)"),
                  ("3000", "3000 ms (Khuyên dùng - Chống giật lag)"),
                  ("5000", "5000 ms (Mạng không ổn định)")]
        for k, v in caches:
            self.combo_cache.append(k, v)
        self.combo_cache.set_active_id(str(self.settings.get("caching", 3000)))
        grid.attach(lbl_c, 0, 1, 1, 1)
        grid.attach(self.combo_cache, 1, 1, 1, 1)

        # 3. Tăng tốc phần cứng
        lbl_hw = Gtk.Label(label="Tăng tốc phần cứng (Hardware Accel):", xalign=0)
        self.switch_hw = Gtk.Switch()
        self.switch_hw.set_active(self.settings.get("hw_accel", True))
        grid.attach(lbl_hw, 0, 2, 1, 1)
        grid.attach(self.switch_hw, 1, 2, 1, 1)

        # 4. Giao diện tối
        lbl_dark = Gtk.Label(label="Giao diện tối (Dark Mode):", xalign=0)
        self.switch_dark = Gtk.Switch()
        self.switch_dark.set_active(self.settings.get("dark_mode", True))
        grid.attach(lbl_dark, 0, 3, 1, 1)
        grid.attach(self.switch_dark, 1, 3, 1, 1)

        # Nút lưu cấu hình
        btn_save = Gtk.Button(label="💾 Lưu cài đặt")
        btn_save.get_style_context().add_class("suggested-action")
        btn_save.connect("clicked", lambda b: self.do_save_settings())
        vbox.pack_start(btn_save, False, False, 0)

        # Quản lý bộ nhớ đệm
        cache_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_clean_cache = Gtk.Button(label="🧹 Dọn dẹp bộ nhớ đệm Thumbnail")
        btn_clean_cache.connect("clicked", lambda b: self.do_clean_cache())
        cache_box.pack_start(btn_clean_cache, False, False, 0)
        vbox.pack_start(cache_box, False, False, 10)

        # Thông tin bản quyền / GitHub
        about_lbl = Gtk.Label()
        about_lbl.set_markup(
            "<small>Dự án mã nguồn mở phát triển bởi <b>starfish367</b>\n"
            "Mã nguồn: <a href='https://github.com/starfish367/yt-vlc'>https://github.com/starfish367/yt-vlc</a>\n"
            "Phiên bản: 2.0.0 (GTK3 VLC Edition)</small>"
        )
        about_lbl.set_line_wrap(True)
        about_lbl.set_xalign(0)
        vbox.pack_end(about_lbl, False, False, 10)

        self.notebook.append_page(vbox, Gtk.Label(label="⚙️ Cài đặt"))

    def do_save_settings(self):
        self.settings["quality"] = self.combo_quality.get_active_id() or "720"
        self.settings["caching"] = int(self.combo_cache.get_active_id() or 3000)
        self.settings["hw_accel"] = self.switch_hw.get_active()
        self.settings["dark_mode"] = self.switch_dark.get_active()
        save_settings(self.settings)

        Gtk.Settings.get_default().set_property(
            "gtk-application-prefer-dark-theme", self.settings["dark_mode"]
        )
        self.set_status("✅ Đã lưu cài đặt thành công!")

    def do_clean_cache(self):
        count = 0
        if os.path.exists(THUMB_DIR):
            for f in os.listdir(THUMB_DIR):
                fp = os.path.join(THUMB_DIR, f)
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                        count += 1
                    except Exception:
                        pass
        self.set_status(f"🧹 Đã xóa {count} ảnh thumbnail trong cache.")

# --- Điểm khởi chạy chương trình ---
def main():
    ensure_directories()
    args = sys.argv[1:]

    # Nếu người dùng truyền link video trực tiếp từ terminal
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
