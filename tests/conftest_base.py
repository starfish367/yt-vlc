"""
conftest_base.py - Base fixtures, test constants, and helpers for yt-vlc E2E test suite.
"""
import os
import sys
import re
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

# Ensure yt-vlc project root is in sys.path
PROJECT_DIR = "/mnt/yt-vlc"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# Suppress GTK AT-SPI accessibility warnings
os.environ["NO_AT_BRIDGE"] = "1"

# Check if yt_vlc module can be imported
try:
    import yt_vlc
except Exception as e:
    yt_vlc = None

def get_yt_vlc_module():
    return yt_vlc

def make_sample_video(vid_id="test_vid_001", title="Test Track 1", duration="3:45", channel="Test Artist"):
    return {
        "id": vid_id,
        "title": title,
        "duration": duration,
        "channel": channel,
        "url": f"https://www.youtube.com/watch?v={vid_id}",
        "thumbnail": f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
    }

def make_sample_playlist(playlist_id="PL_test_123", title="Test Album Playlist", count=10):
    videos = []
    for i in range(1, count + 1):
        videos.append(make_sample_video(f"track_{i:02d}", f"Track #{i} - Song Title", "3:00", "Album Artist"))
    return {
        "id": playlist_id,
        "title": title,
        "item_count": count,
        "thumbnail": "https://i.ytimg.com/vi/track_01/hqdefault.jpg",
        "videos": videos
    }

COLOR_EMOJI_REGEX = re.compile(
    r"[\U0001F300-\U0001FAFF]"   # Symbols and Pictographs, Emoticons, Transport, Food, etc.
    r"|[\u2600-\u26FF]"           # Misc Symbols (except standard text bullets/checks)
    r"|[\u2300-\u23FF]"           # Misc Technical (play, pause, fast forward emoji)
    r"|[\u2700-\u27BF]"           # Dingbats (excluding standard checked marks: \u2713, \u2714)
)

ALLOWED_UNICODE_CHARS = {"\u2713", "\u2714", "\u2022"}  # ✓, ✔, •

def find_forbidden_emojis(text: str):
    """Returns list of forbidden color emoji characters found in text, ignoring allowed symbols."""
    matches = COLOR_EMOJI_REGEX.findall(text)
    return [c for c in matches if c not in ALLOWED_UNICODE_CHARS]


@contextmanager
def mock_vlc_execution(stream_url="https://googlevideo.com/playback", audio_url=None, is_live=False, captured_list=None, side_effect=None):
    """
    Standardized fixture for mocking launch_vlc execution without modifying production code.
    Mocks stream extraction, RC socket monitor, subprocess.Popen, and synchronous thread execution.
    """
    if captured_list is None:
        captured_list = []

    def _fake_popen(cmd, *args, **kwargs):
        if side_effect:
            if isinstance(side_effect, Exception) or (isinstance(side_effect, type) and issubclass(side_effect, Exception)):
                raise side_effect
            return side_effect(cmd, *args, **kwargs)
        captured_list.extend(cmd)
        m = MagicMock()
        m.wait.return_value = 0
        return m

    stream_res = (stream_url, audio_url, is_live)
    with patch("yt_vlc.extract_stream_url", return_value=stream_res), \
         patch("yt_vlc.monitor_vlc_rc"), \
         patch("subprocess.Popen", side_effect=_fake_popen) as mock_p, \
         patch("threading.Thread", lambda target, args=(), kwargs={}, daemon=True: MagicMock(start=lambda: target(*args, **kwargs))):
        yield captured_list
